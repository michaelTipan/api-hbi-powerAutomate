"""Orquestación compartida de cola Generate (Power Automate + UI).

Única implementación de lock → job queued → background → use case → finish.
Los routers solo adaptan HTTP; no duplican cableado.
"""
from __future__ import annotations

import asyncio
import logging
import uuid
from dataclasses import dataclass
from datetime import date
from time import perf_counter
from typing import Any, Protocol

from fastapi import BackgroundTasks

from app.application.config.payment_validation_settings import validate_bank_code
from app.application.job_manager import JobManager, get_job_manager
from app.application.services.colombia_time import now_colombia_iso, today_colombia_iso
from app.application.services.execution_log_hooks import (
    infer_terminal_status_from_result,
    try_bootstrap_generate_execution_log,
    try_persist_execution_ids_to_control,
    try_record_step_event,
)
from app.application.use_cases.payment_validation_generate import generate_payment_validation

logger = logging.getLogger(__name__)


class GraphLike(Protocol):
    async def get(self, *a: Any, **k: Any) -> Any: ...
    async def get_bytes(self, *a: Any, **k: Any) -> Any: ...
    async def put_bytes(self, *a: Any, **k: Any) -> Any: ...


class GenerateQueueBusyError(Exception):
    """Lock Generate/Finalize ocupado."""


class GenerateQueueValidationError(Exception):
    """bank_code o process_date inválidos."""

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


@dataclass(frozen=True)
class GenerateQueueAccepted:
    job_id: str
    bank_code: str
    status: str = "queued"


def _utc_now_iso() -> str:
    return now_colombia_iso()


class GenerateQueueService:
    """Cola Generate compartida. Usa el JobManager singleton de PA."""

    def __init__(self, job_manager: JobManager | None = None) -> None:
        self._jm = job_manager if job_manager is not None else get_job_manager()

    @property
    def job_manager(self) -> JobManager:
        return self._jm

    async def enqueue(
        self,
        *,
        graph: GraphLike,
        background_tasks: BackgroundTasks,
        bank_code: str,
        process_date: date | None = None,
        trigger_source: str = "power_automate",
        requested_by: str | None = None,
        ui_request_id: str | None = None,
        force_regenerate: bool = False,
    ) -> GenerateQueueAccepted:
        if not self._jm.try_start_generate():
            raise GenerateQueueBusyError(
                "Ya existe un proceso generate o finalize activo. Consulta /jobs/{job_id}."
            )

        try:
            validate_bank_code(bank_code)
        except ValueError as exc:
            self._jm.finish_generate()
            raise GenerateQueueValidationError(
                "bank_code inválido. Use banco_bogota o banco_bancolombia."
            ) from exc

        resolved_date = process_date or today_colombia_iso()
        if isinstance(resolved_date, str):
            try:
                resolved_date = date.fromisoformat(resolved_date)
            except ValueError as exc:
                self._jm.finish_generate()
                raise GenerateQueueValidationError(
                    "process_date inválido. Usar formato YYYY-MM-DD."
                ) from exc

        job_id = str(uuid.uuid4())
        initial: dict[str, Any] = {
            "job_id": job_id,
            "type": "generate",
            "status": "queued",
            "bank_code": bank_code,
            "queued_at": _utc_now_iso(),
            "updated_at": _utc_now_iso(),
            "trigger_source": trigger_source,
        }
        if requested_by:
            initial["requested_by"] = requested_by
        if ui_request_id:
            initial["ui_request_id"] = ui_request_id
        if force_regenerate:
            initial["force_regenerate"] = True

        await self._jm.set_job(job_id, initial)

        try:
            boot = await try_bootstrap_generate_execution_log(
                graph,
                bank_code=bank_code,
                process_date=resolved_date,
                job_id=job_id,
            )
        except Exception:
            logger.exception(
                "generate_queue: bootstrap execution_log best-effort falló job=%s",
                job_id,
            )
            boot = {}

        execution_id = (boot or {}).get("execution_id") or None
        execution_log_path = (boot or {}).get("execution_log_path") or None
        if boot:
            try:
                await self._jm.set_job(
                    job_id,
                    {
                        "execution_id": execution_id or "",
                        "execution_log_path": execution_log_path or "",
                        "execution_log_status": (boot or {}).get("execution_log_status")
                        or "",
                    },
                )
            except Exception:
                logger.exception(
                    "generate_queue: no se pudo persistir meta execution_log job=%s",
                    job_id,
                )

        background_tasks.add_task(
            self._run_generate_job,
            job_id,
            graph,
            resolved_date,
            bank_code,
            execution_id,
            execution_log_path,
            trigger_source,
            requested_by,
            ui_request_id,
            force_regenerate,
        )
        logger.info(
            "job %s: generate encolado trigger=%s by=%s",
            job_id,
            trigger_source,
            requested_by or "",
        )
        return GenerateQueueAccepted(job_id=job_id, bank_code=bank_code, status="queued")

    async def _job_heartbeat_loop(self, job_id: str, interval_s: float = 30.0) -> None:
        while True:
            await asyncio.sleep(interval_s)
            try:
                await self._jm.set_job(
                    job_id,
                    {"updated_at": _utc_now_iso(), "heartbeat_at": _utc_now_iso()},
                )
            except Exception:
                logger.exception("job %s: heartbeat falló", job_id)

    async def _run_generate_job(
        self,
        job_id: str,
        graph: GraphLike,
        process_date: date,
        bank_code: str,
        execution_id: str | None = None,
        execution_log_path: str | None = None,
        trigger_source: str = "power_automate",
        requested_by: str | None = None,
        ui_request_id: str | None = None,
        force_regenerate: bool = False,
    ) -> None:
        await self._jm.set_job(
            job_id,
            {
                "status": "running",
                "started_at": _utc_now_iso(),
                "updated_at": _utc_now_iso(),
                "execution_id": execution_id or "",
                "execution_log_path": execution_log_path or "",
                "trigger_source": trigger_source,
                **({"requested_by": requested_by} if requested_by else {}),
                **({"ui_request_id": ui_request_id} if ui_request_id else {}),
            },
        )
        logger.info("job %s: generate_payment_validation iniciado", job_id)
        started = perf_counter()
        heartbeat = asyncio.create_task(self._job_heartbeat_loop(job_id))
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
                graph,
                process_date,
                bank_code=bank_code,
                job_id=job_id,
                force_regenerate=force_regenerate,
            )
            elapsed_ms = round((perf_counter() - started) * 1000, 2)
            if execution_id and active_log_path:
                await try_persist_execution_ids_to_control(
                    graph,
                    bank_code=bank_code,
                    execution_id=execution_id,
                    execution_log_path=active_log_path,
                )
            terminal = infer_terminal_status_from_result(
                result if isinstance(result, dict) else None
            )
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
                    "trigger_source": trigger_source,
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
                "trigger_source": trigger_source,
            }
            if requested_by:
                enriched_result["requested_by"] = requested_by
            if ui_request_id:
                enriched_result["ui_request_id"] = ui_request_id
            if log_meta.get("execution_id"):
                enriched_result["execution_id"] = log_meta.get("execution_id")
                enriched_result["execution_log_path"] = log_meta.get("execution_log_path")
                enriched_result["execution_log_status"] = log_meta.get(
                    "execution_log_status"
                )
            await self._jm.set_job(
                job_id,
                {
                    "status": "completed",
                    "finished_at": _utc_now_iso(),
                    "updated_at": _utc_now_iso(),
                    "result": enriched_result,
                },
            )
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
            await self._jm.set_job(
                job_id,
                {
                    "status": "failed",
                    "finished_at": _utc_now_iso(),
                    "updated_at": _utc_now_iso(),
                    "error": {"type": type(exc).__name__, "message": str(exc)},
                    "trigger_source": trigger_source,
                    **({"requested_by": requested_by} if requested_by else {}),
                    **({"ui_request_id": ui_request_id} if ui_request_id else {}),
                },
            )
            logger.error(
                "job %s: falló con %s: %s", job_id, type(exc).__name__, exc
            )
        finally:
            heartbeat.cancel()
            try:
                await heartbeat
            except asyncio.CancelledError:
                pass
            self._jm.finish_generate()


_default_service: GenerateQueueService | None = None


def get_generate_queue_service() -> GenerateQueueService:
    """Singleton del servicio de cola (comparte JobManager con PA)."""
    global _default_service
    if _default_service is None:
        _default_service = GenerateQueueService(get_job_manager())
    return _default_service


def reset_generate_queue_service_for_tests() -> None:
    global _default_service
    _default_service = None
