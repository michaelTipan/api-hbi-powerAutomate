import logging
import asyncio
from datetime import date, datetime
from time import perf_counter
from typing import Any

from fastapi import APIRouter, BackgroundTasks, HTTPException
from pydantic import BaseModel, Field, field_validator

from app.adapters.primary.http.deps import GraphClientDep
from app.application.job_status_enrichment import enrich_job_for_http_response
from app.application.job_manager import JobManager
from app.application.services.colombia_time import now_colombia_iso, today_colombia_iso
from app.application.use_cases.payment_validation_generate import generate_payment_validation
from app.application.use_cases.payment_validation_finalize import finalize_payment_validation
from app.application.use_cases.setup_ibr_workbook import (
    IbrWorkbookSetupError,
    setup_ibr_workbook,
)
from app.application.use_cases.setup_payment_followup_workbooks import (
    PaymentFollowupSetupError,
    setup_payment_followup_workbooks,
)
from app.application.use_cases.setup_merge_control_workbook import (
    MergeControlSetupError,
    setup_merge_control_workbook,
)
from app.application.config.payment_validation_settings import validate_bank_code
from app.application.services.execution_log_hooks import (
    infer_terminal_status_from_result,
    try_bootstrap_generate_execution_log,
    try_persist_execution_ids_to_control,
    try_record_step_event,
)
from app.application.use_cases.amortization_fill_apply import run_amortization_fill_apply
from app.application.use_cases.amortization_fill_dry_run import run_amortization_fill_dry_run
from app.domain.exceptions import GraphConfigError

router = APIRouter(prefix="/graph/sharepoint/payment-validation", tags=["payment-validation"])
logger = logging.getLogger(__name__)


def _utc_now_iso() -> str:
    """Marca de tiempo de jobs (America/Bogota). Nombre histórico conservado."""
    return now_colombia_iso()


# ─── Request Bodies ──────────────────────────────────────────────────────────

class GenerateRequest(BaseModel):
    bank_code: str = Field(..., min_length=1, description="banco_bogota | banco_bancolombia")
    process_date: str | None = None
    source_file_path: str | None = None
    force: bool = False

    @field_validator("bank_code")
    @classmethod
    def _bank_code_not_blank(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("bank_code es obligatorio")
        return stripped

class FinalizeRequest(BaseModel):
    validation_file: str | None = None
    validation_file_path: str | None = None
    process_date: str | None = None
    bank_code: str | None = None


class PaymentFollowupSetupRequest(BaseModel):
    force_recreate: bool = False


class IbrWorkbookSetupRequest(BaseModel):
    force_recreate: bool = False


class AmortizationDryRunRequest(BaseModel):
    report_date_iso: str | None = None
    merge_manifest_path: str | None = None
    historical_file_path: str | None = None
    bank_code: str | None = None


# ─── Background Tasks ─────────────────────────────────────────────────────────

async def _run_generate_job(
    job_id: str,
    graph: GraphClientDep,
    process_date: date,
    bank_code: str,
    execution_id: str | None = None,
    execution_log_path: str | None = None,
) -> None:
    jm = JobManager()
    await jm.set_job(job_id, {
        "status": "running",
        "started_at": _utc_now_iso(),
        "updated_at": _utc_now_iso(),
        "execution_id": execution_id or "",
        "execution_log_path": execution_log_path or "",
    })
    logger.info("job %s: generate_payment_validation iniciado", job_id)
    started = perf_counter()
    started_meta = await try_record_step_event(
        graph,
        step="GENERATE",
        status="STARTED",
        job_id=job_id,
        bank_code=bank_code,
        execution_id=execution_id,
        execution_log_path=execution_log_path,
    )
    active_log_path = (
        str(started_meta.get("execution_log_path") or "").strip()
        or (execution_log_path or "")
    )
    try:
        result = await generate_payment_validation(
            graph, process_date, bank_code=bank_code, job_id=job_id
        )
        elapsed_ms = round((perf_counter() - started) * 1000, 2)
        # Refuerzo post-éxito: mismas columnas de auditoría (no altera estado de proceso).
        if execution_id and active_log_path:
            await try_persist_execution_ids_to_control(
                graph,
                bank_code=bank_code,
                execution_id=execution_id,
                execution_log_path=active_log_path,
            )
        terminal = infer_terminal_status_from_result(result if isinstance(result, dict) else None)
        log_meta = await try_record_step_event(
            graph,
            step="GENERATE",
            status=terminal,
            job_id=job_id,
            bank_code=bank_code,
            execution_id=execution_id,
            execution_log_path=active_log_path,
            process_id=str((result or {}).get("process_id") or "") or None,
            process_key=str((result or {}).get("process_key") or "") or None,
            metrics={
                "elapsed_ms": elapsed_ms,
                "status": str((result or {}).get("status") or ""),
            },
            artifacts=[
                {
                    "role": "VALIDATION_FILE",
                    "path": str((result or {}).get("validation_file_path") or ""),
                    "file_name": "",
                    "action": "CREATED",
                    "status": "SUCCEEDED",
                }
            ]
            if (result or {}).get("validation_file_path")
            else None,
        )
        enriched_result = {
            **(result if isinstance(result, dict) else {"value": result}),
            "process_date": process_date.isoformat(),
            "elapsed_ms": elapsed_ms,
        }
        if log_meta.get("execution_id"):
            enriched_result["execution_id"] = log_meta.get("execution_id")
            enriched_result["execution_log_path"] = log_meta.get("execution_log_path")
            enriched_result["execution_log_status"] = log_meta.get("execution_log_status")
        await jm.set_job(job_id, {
            "status": "completed",
            "finished_at": _utc_now_iso(),
            "updated_at": _utc_now_iso(),
            "result": enriched_result,
        })
        logger.info("job %s: completado en %.2fms", job_id, elapsed_ms)
    except Exception as exc:
        await try_record_step_event(
            graph,
            step="GENERATE",
            status="FAILED",
            job_id=job_id,
            bank_code=bank_code,
            execution_id=execution_id,
            execution_log_path=active_log_path,
            error={
                "error_code": type(exc).__name__,
                "exception_type": type(exc).__name__,
                "technical_message": str(exc)[:4000],
            },
        )
        await jm.set_job(job_id, {
            "status": "failed",
            "finished_at": _utc_now_iso(),
            "updated_at": _utc_now_iso(),
            "error": {"type": type(exc).__name__, "message": str(exc)},
        })
        logger.error("job %s: falló con %s: %s", job_id, type(exc).__name__, exc)
    finally:
        jm.finish_generate()


async def _run_finalize_job(
    job_id: str,
    graph: GraphClientDep,
    validation_file: str | None,
    validation_file_path: str | None,
    process_date: date,
    bank_code: str | None,
) -> None:
    jm = JobManager()
    await jm.set_job(job_id, {
        "status": "running",
        "started_at": _utc_now_iso(),
        "updated_at": _utc_now_iso(),
    })
    logger.info("job %s: finalize_payment_validation iniciado", job_id)
    started = perf_counter()
    await try_record_step_event(
        graph,
        step="FINALIZE",
        status="STARTED",
        job_id=job_id,
        bank_code=bank_code,
    )
    try:
        result = await finalize_payment_validation(
            graph,
            validation_file=validation_file,
            validation_file_path=validation_file_path,
            process_date=process_date,
            bank_code=bank_code,
            job_id=job_id,
        )
        elapsed_ms = round((perf_counter() - started) * 1000, 2)
        terminal = infer_terminal_status_from_result(result if isinstance(result, dict) else None)
        await try_record_step_event(
            graph,
            step="FINALIZE",
            status=terminal,
            job_id=job_id,
            bank_code=bank_code or (result or {}).get("bank_code"),
            metrics={"elapsed_ms": elapsed_ms},
        )
        await jm.set_job(job_id, {
            "status": "completed",
            "finished_at": _utc_now_iso(),
            "updated_at": _utc_now_iso(),
            "result": {**result, "elapsed_ms": elapsed_ms},
        })
        logger.info("job %s: completado en %.2fms", job_id, elapsed_ms)
    except Exception as exc:
        await try_record_step_event(
            graph,
            step="FINALIZE",
            status="FAILED",
            job_id=job_id,
            bank_code=bank_code,
            error={
                "error_code": type(exc).__name__,
                "exception_type": type(exc).__name__,
                "technical_message": str(exc)[:4000],
            },
        )
        await jm.set_job(job_id, {
            "status": "failed",
            "finished_at": _utc_now_iso(),
            "updated_at": _utc_now_iso(),
            "error": {"type": type(exc).__name__, "message": str(exc)},
        })
        logger.error("job %s: falló con %s: %s", job_id, type(exc).__name__, exc)
    finally:
        jm.finish_finalize()


async def _run_amortization_dry_run_job(
    job_id: str,
    graph: GraphClientDep,
    *,
    report_date_iso: str | None,
    merge_manifest_path: str | None,
    historical_file_path: str | None,
    bank_code: str | None,
) -> None:
    jm = JobManager()
    await jm.set_job(
        job_id,
        {
            "status": "running",
            "started_at": _utc_now_iso(),
            "updated_at": _utc_now_iso(),
        },
    )
    logger.info("job %s: amortization_dry_run iniciado", job_id)
    started = perf_counter()
    await try_record_step_event(
        graph, step="DRY_RUN", status="STARTED", job_id=job_id, bank_code=bank_code
    )
    try:
        result = await run_amortization_fill_dry_run(
            graph,
            report_date_iso=report_date_iso,
            merge_manifest_path=merge_manifest_path,
            historical_file_path=historical_file_path,
            bank_code=bank_code,
            job_id=job_id,
        )
        elapsed_ms = round((perf_counter() - started) * 1000, 2)
        terminal = infer_terminal_status_from_result(result if isinstance(result, dict) else None)
        if isinstance(result, dict) and result.get("can_apply") is False:
            terminal = "BLOCKED"
        await try_record_step_event(
            graph,
            step="DRY_RUN",
            status=terminal,
            job_id=job_id,
            bank_code=bank_code,
            metrics={"elapsed_ms": elapsed_ms},
        )
        await jm.set_job(
            job_id,
            {
                "status": "completed",
                "finished_at": _utc_now_iso(),
                "updated_at": _utc_now_iso(),
                "result": {**result, "elapsed_ms": elapsed_ms},
                "error": None,
            },
        )
        logger.info("job %s: amortization_dry_run completado en %.2fms", job_id, elapsed_ms)
    except ValueError as exc:
        msg = str(exc)
        code = msg.split("|", 1)[0].strip() if "|" in msg else msg.strip()
        await try_record_step_event(
            graph,
            step="DRY_RUN",
            status="FAILED",
            job_id=job_id,
            bank_code=bank_code,
            error={
                "error_code": code,
                "exception_type": "ValueError",
                "technical_message": msg[:4000],
            },
        )
        await jm.set_job(
            job_id,
            {
                "status": "failed",
                "finished_at": _utc_now_iso(),
                "updated_at": _utc_now_iso(),
                "result": None,
                "error": {
                    "type": "ValueError",
                    "message": msg,
                    "error_code": code,
                },
            },
        )
        logger.warning("job %s: amortization_dry_run falló (validación): %s", job_id, msg)
    except GraphConfigError as exc:
        await try_record_step_event(
            graph,
            step="DRY_RUN",
            status="FAILED",
            job_id=job_id,
            bank_code=bank_code,
            error={
                "error_code": "graph_config_error",
                "exception_type": "GraphConfigError",
                "technical_message": str(exc)[:4000],
            },
        )
        await jm.set_job(
            job_id,
            {
                "status": "failed",
                "finished_at": _utc_now_iso(),
                "updated_at": _utc_now_iso(),
                "result": None,
                "error": {
                    "type": "GraphConfigError",
                    "message": str(exc),
                    "error_code": "graph_config_error",
                },
            },
        )
        logger.error("job %s: amortization_dry_run config: %s", job_id, exc)
    except Exception as exc:
        await try_record_step_event(
            graph,
            step="DRY_RUN",
            status="FAILED",
            job_id=job_id,
            bank_code=bank_code,
            error={
                "error_code": type(exc).__name__,
                "exception_type": type(exc).__name__,
                "technical_message": str(exc)[:4000],
            },
        )
        await jm.set_job(
            job_id,
            {
                "status": "failed",
                "finished_at": _utc_now_iso(),
                "updated_at": _utc_now_iso(),
                "result": None,
                "error": {"type": type(exc).__name__, "message": str(exc)},
            },
        )
        logger.exception("job %s: amortization_dry_run falló: %s", job_id, exc)


async def _run_amortization_apply_job(
    job_id: str,
    graph: GraphClientDep,
    *,
    report_date_iso: str | None,
    merge_manifest_path: str | None,
    historical_file_path: str | None,
    bank_code: str | None,
) -> None:
    jm = JobManager()
    await jm.set_job(
        job_id,
        {
            "status": "running",
            "started_at": _utc_now_iso(),
            "updated_at": _utc_now_iso(),
        },
    )
    logger.info("job %s: amortization_apply iniciado", job_id)
    started = perf_counter()
    await try_record_step_event(
        graph, step="APPLY", status="STARTED", job_id=job_id, bank_code=bank_code
    )
    try:
        result = await run_amortization_fill_apply(
            graph,
            report_date_iso=report_date_iso,
            merge_manifest_path=merge_manifest_path,
            historical_file_path=historical_file_path,
            bank_code=bank_code,
            job_id=job_id,
        )
        elapsed_ms = round((perf_counter() - started) * 1000, 2)
        terminal = infer_terminal_status_from_result(result if isinstance(result, dict) else None)
        await try_record_step_event(
            graph,
            step="APPLY",
            status=terminal,
            job_id=job_id,
            bank_code=bank_code,
            metrics={"elapsed_ms": elapsed_ms},
        )
        await jm.set_job(
            job_id,
            {
                "status": "completed",
                "finished_at": _utc_now_iso(),
                "updated_at": _utc_now_iso(),
                "result": {**result, "elapsed_ms": elapsed_ms},
                "error": None,
            },
        )
        logger.info("job %s: amortization_apply completado en %.2fms", job_id, elapsed_ms)
    except ValueError as exc:
        msg = str(exc)
        code = msg.split("|", 1)[0].strip() if "|" in msg else msg.strip()
        await try_record_step_event(
            graph,
            step="APPLY",
            status="FAILED",
            job_id=job_id,
            bank_code=bank_code,
            error={
                "error_code": code,
                "exception_type": "ValueError",
                "technical_message": msg[:4000],
            },
        )
        await jm.set_job(
            job_id,
            {
                "status": "failed",
                "finished_at": _utc_now_iso(),
                "updated_at": _utc_now_iso(),
                "result": None,
                "error": {
                    "type": "ValueError",
                    "message": msg,
                    "error_code": code,
                },
            },
        )
    except GraphConfigError as exc:
        await try_record_step_event(
            graph,
            step="APPLY",
            status="FAILED",
            job_id=job_id,
            bank_code=bank_code,
            error={
                "error_code": "graph_config_error",
                "exception_type": "GraphConfigError",
                "technical_message": str(exc)[:4000],
            },
        )
        await jm.set_job(
            job_id,
            {
                "status": "failed",
                "finished_at": _utc_now_iso(),
                "updated_at": _utc_now_iso(),
                "result": None,
                "error": {
                    "type": "GraphConfigError",
                    "message": str(exc),
                    "error_code": "graph_config_error",
                },
            },
        )
    except Exception as exc:
        await try_record_step_event(
            graph,
            step="APPLY",
            status="FAILED",
            job_id=job_id,
            bank_code=bank_code,
            error={
                "error_code": type(exc).__name__,
                "exception_type": type(exc).__name__,
                "technical_message": str(exc)[:4000],
            },
        )
        await jm.set_job(
            job_id,
            {
                "status": "failed",
                "finished_at": _utc_now_iso(),
                "updated_at": _utc_now_iso(),
                "result": None,
                "error": {"type": type(exc).__name__, "message": str(exc)},
            },
        )
        logger.exception("job %s: amortization_apply falló: %s", job_id, exc)


# ─── Endpoints ────────────────────────────────────────────────────────────────

@router.post("/generate/queue", status_code=202)
async def queue_generate(
    graph: GraphClientDep,
    background_tasks: BackgroundTasks,
    body: GenerateRequest,
) -> dict[str, Any]:
    """
    Encola la generación del Excel de revisión de pagos.
    Power Automate debe llamar este endpoint con bank_code obligatorio
    y luego consultar /jobs/{job_id}.
    """
    jm = JobManager()
    if not jm.try_start_generate():
        raise HTTPException(
            status_code=409,
            detail="Ya existe un proceso generate o finalize activo. Consulta /jobs/{job_id}."
        )

    try:
        validate_bank_code(body.bank_code)
    except ValueError:
        jm.finish_generate()
        raise HTTPException(
            status_code=422,
            detail="bank_code inválido. Use banco_bogota o banco_bancolombia.",
        )

    try:
        pd_str = body.process_date or today_colombia_iso()
        process_date = date.fromisoformat(pd_str)
    except ValueError:
        jm.finish_generate()
        raise HTTPException(status_code=422, detail="process_date inválido. Usar formato YYYY-MM-DD.")

    # Crear el job en estado queued
    import uuid
    job_id = str(uuid.uuid4())
    await jm.set_job(job_id, {
        "job_id": job_id,
        "type": "generate",
        "status": "queued",
        "queued_at": _utc_now_iso(),
        "updated_at": _utc_now_iso(),
    })

    boot = await try_bootstrap_generate_execution_log(
        graph, bank_code=body.bank_code, process_date=process_date, job_id=job_id
    )
    execution_id = boot.get("execution_id") or None
    execution_log_path = boot.get("execution_log_path") or None
    if boot:
        await jm.set_job(job_id, {
            "execution_id": execution_id or "",
            "execution_log_path": execution_log_path or "",
            "execution_log_status": boot.get("execution_log_status") or "",
        })

    background_tasks.add_task(
        _run_generate_job,
        job_id,
        graph,
        process_date,
        body.bank_code,
        execution_id,
        execution_log_path,
    )
    logger.info("job %s: generate encolado", job_id)

    return {"job_id": job_id, "status": "queued"}


@router.post("/finalize/queue", status_code=202)
async def queue_finalize(
    graph: GraphClientDep,
    background_tasks: BackgroundTasks,
    body: FinalizeRequest = None,
) -> dict[str, Any]:
    """
    Encola la finalización del flujo de validación de pagos.
    Power Automate debe llamar este endpoint después de que la secretaria
    complete el Excel de revisión.

    Flujo productivo: Generate → Finalize (control por banco). El endpoint antiguo
    `validate-payment-report` fue retirado; use estos endpoints.
    """
    jm = JobManager()
    if not jm.try_start_finalize():
        raise HTTPException(
            status_code=409,
            detail="Ya existe un proceso generate o finalize activo. Consulta /jobs/{job_id}."
        )

    body = body or FinalizeRequest()
    validation_file = body.validation_file or None
    validation_file_path = body.validation_file_path or None
    bank_code = body.bank_code or None

    try:
        pd_str = body.process_date or today_colombia_iso()
        process_date = date.fromisoformat(pd_str)
    except ValueError:
        jm.finish_finalize()
        raise HTTPException(status_code=422, detail="process_date inválido. Usar formato YYYY-MM-DD.")

    import uuid
    job_id = str(uuid.uuid4())
    await jm.set_job(job_id, {
        "job_id": job_id,
        "type": "finalize",
        "status": "queued",
        "queued_at": _utc_now_iso(),
        "updated_at": _utc_now_iso(),
    })

    background_tasks.add_task(
        _run_finalize_job,
        job_id,
        graph,
        validation_file,
        validation_file_path,
        process_date,
        bank_code,
    )
    logger.info("job %s: finalize encolado", job_id)

    return {"job_id": job_id, "status": "queued"}


@router.post("/amortization/dry-run/queue", status_code=202)
async def queue_amortization_dry_run(
    graph: GraphClientDep,
    background_tasks: BackgroundTasks,
    body: AmortizationDryRunRequest | None = None,
) -> dict[str, Any]:
    """
    Encola análisis preliminar de amortización (dry-run) contra SharePoint.
    Sin body resuelve insumos desde el control oficial por banco (auto-detección; Merge escribe MergeManifestPath).
    Consulte ``GET /jobs/{job_id}`` para el resultado.
    """
    payload = body or AmortizationDryRunRequest()
    manifest_path = (payload.merge_manifest_path or "").strip() or None
    report_date = (payload.report_date_iso or "").strip() or None
    historical_path = (payload.historical_file_path or "").strip() or None
    bank_code = (payload.bank_code or "").strip() or None

    if report_date:
        try:
            date.fromisoformat(report_date)
        except ValueError as exc:
            raise HTTPException(
                status_code=422,
                detail={
                    "error_code": "invalid_report_date_iso",
                    "user_message": "report_date_iso no es una fecha válida.",
                    "next_action": "Use formato YYYY-MM-DD, por ejemplo 2026-05-15.",
                },
            ) from exc

    import uuid

    job_id = str(uuid.uuid4())
    jm = JobManager()
    await jm.set_job(
        job_id,
        {
            "job_id": job_id,
            "type": "amortization_dry_run",
            "status": "queued",
            "queued_at": _utc_now_iso(),
            "updated_at": _utc_now_iso(),
            "request": {
                "report_date_iso": report_date,
                "merge_manifest_path": manifest_path,
                "historical_file_path": historical_path,
                "bank_code": bank_code,
            },
        },
    )

    background_tasks.add_task(
        _run_amortization_dry_run_job,
        job_id,
        graph,
        report_date_iso=report_date,
        merge_manifest_path=manifest_path,
        historical_file_path=historical_path,
        bank_code=bank_code,
    )
    logger.info("job %s: amortization_dry_run encolado", job_id)

    return {"job_id": job_id, "status": "queued"}


@router.post("/amortization/apply/queue", status_code=202)
async def queue_amortization_apply(
    graph: GraphClientDep,
    background_tasks: BackgroundTasks,
    body: AmortizationDryRunRequest | None = None,
) -> dict[str, Any]:
    """
    Encola apply real de amortización (preflight dry-run + escritura en SharePoint).
    Sin body resuelve insumos desde el control oficial por banco (auto-detección).
    Consulte ``GET /jobs/{job_id}``.
    """
    payload = body or AmortizationDryRunRequest()
    manifest_path = (payload.merge_manifest_path or "").strip() or None
    report_date = (payload.report_date_iso or "").strip() or None
    historical_path = (payload.historical_file_path or "").strip() or None
    bank_code = (payload.bank_code or "").strip() or None

    if report_date:
        try:
            date.fromisoformat(report_date)
        except ValueError as exc:
            raise HTTPException(
                status_code=422,
                detail={"error_code": "invalid_report_date_iso"},
            ) from exc

    import uuid

    job_id = str(uuid.uuid4())
    jm = JobManager()
    await jm.set_job(
        job_id,
        {
            "job_id": job_id,
            "type": "amortization_apply",
            "status": "queued",
            "queued_at": _utc_now_iso(),
            "updated_at": _utc_now_iso(),
            "request": {
                "report_date_iso": report_date,
                "merge_manifest_path": manifest_path,
                "historical_file_path": historical_path,
                "bank_code": bank_code,
            },
        },
    )

    background_tasks.add_task(
        _run_amortization_apply_job,
        job_id,
        graph,
        report_date_iso=report_date,
        merge_manifest_path=manifest_path,
        historical_file_path=historical_path,
        bank_code=bank_code,
    )
    logger.info("job %s: amortization_apply encolado", job_id)

    return {"job_id": job_id, "status": "queued"}


@router.get("/jobs/{job_id}")
async def get_job_status(job_id: str) -> dict[str, Any]:
    """
    Consulta el estado de un job de payment-validation.
    Devuelve 404 si el job no existe.
    """
    jm = JobManager()
    job = jm.get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail=f"Job {job_id!r} no encontrado.")
    return enrich_job_for_http_response(job)


@router.post("/setup/merge-control-workbook")
async def post_setup_merge_control_workbook(graph: GraphClientDep) -> dict[str, Any]:
    """
    Crea o repara de forma idempotente los Excel de control del proceso en la carpeta de control.

  Oficiales (por banco, preparados para generate → finalize → notify → merge → apply):

  * ``control_proceso_validacion_pagos_banco_bogota.xlsx``
  * ``control_proceso_validacion_pagos_banco_bancolombia.xlsx``

  Crea o repara solo ``control_proceso_validacion_pagos_banco_bogota.xlsx`` y
  ``control_proceso_validacion_pagos_banco_bancolombia.xlsx`` en la carpeta de control.
  El flujo productivo Generate/Finalize/Notify/Merge/dry-run/apply ya usa estos controles
  para encadenamiento, trazabilidad e idempotencia.
    """
    try:
        return await setup_merge_control_workbook(graph)
    except MergeControlSetupError as exc:
        raise HTTPException(
            status_code=exc.http_status,
            detail={
                "user_message": exc.user_message,
                "next_action": exc.next_action,
                "technical_message": exc.technical_message,
            },
        ) from exc
    except GraphConfigError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.post("/setup/payment-followup-workbooks")
async def post_setup_payment_followup_workbooks(
    graph: GraphClientDep,
    body: PaymentFollowupSetupRequest | None = None,
) -> dict[str, Any]:
    """
    Crea la bandeja operativa ``pagos_adelantados.xlsx`` (hojas Pendientes + Historico).
    Por defecto no sobrescribe; ``force_recreate`` reemplaza.
    """
    payload = body or PaymentFollowupSetupRequest()
    try:
        return await setup_payment_followup_workbooks(
            graph,
            force_recreate=payload.force_recreate,
        )
    except PaymentFollowupSetupError as exc:
        raise HTTPException(
            status_code=exc.http_status,
            detail={
                "user_message": exc.user_message,
                "next_action": exc.next_action,
                "technical_message": exc.technical_message,
            },
        ) from exc
    except GraphConfigError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.post("/setup/ibr-workbook")
async def post_setup_ibr_workbook(
    graph: GraphClientDep,
    body: IbrWorkbookSetupRequest | None = None,
) -> dict[str, Any]:
    """
    Crea o repara idempotentemente ``IBR_DIARIO.xlsx`` (hoja IBR: Inicio, Fin, Valor).
    Encabezados bloqueados; filas de datos editables. ``force_recreate`` reemplaza el archivo.
    """
    payload = body or IbrWorkbookSetupRequest()
    try:
        return await setup_ibr_workbook(graph, force_recreate=payload.force_recreate)
    except IbrWorkbookSetupError as exc:
        raise HTTPException(
            status_code=exc.http_status,
            detail={
                "user_message": exc.user_message,
                "next_action": exc.next_action,
                "technical_message": exc.technical_message,
            },
        ) from exc
    except GraphConfigError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
