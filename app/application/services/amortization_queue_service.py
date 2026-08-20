"""Orquestación compartida de cola Amortization (Power Automate + UI).

Única implementación de lock → job queued → background → use case → finish.
Los routers solo adaptan HTTP; no duplican runners ni hacen HTTP interno a /graph.

Tres entradas, un solo mutex (`try_claim_amortization_for_process` /
`finish_amortization`, compartido con Generate/Finalize/Notify/Merge):

- ``enqueue_process_ui``: UI, un solo job visible (``amortization_process``).
  Prepara una vez (`prepare_amortization_application`); si ``can_apply=false``
  termina en ``requires_correction`` sin ninguna escritura; si ``can_apply=true``
  ejecuta el plan ya validado (`execute_amortization_from_prepared`).
- ``enqueue_dry_run_pa``: PA, contrato histórico (`amortization_dry_run`).
- ``enqueue_apply_pa``: PA, contrato histórico (`amortization_apply`).
"""
from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from time import perf_counter
from typing import Any, Protocol

from fastapi import BackgroundTasks

from app.application.job_manager import JobManager, get_job_manager
from app.application.services.colombia_time import now_colombia_iso
from app.application.services.execution_log_hooks import (
    infer_terminal_status_from_result,
    try_record_step_event,
)
from app.application.use_cases.amortization_application_plan import (
    prepare_amortization_application,
)
from app.application.use_cases.amortization_fill_apply import (
    execute_amortization_from_prepared,
    run_amortization_fill_apply,
)
from app.application.use_cases.amortization_fill_dry_run import (
    run_amortization_fill_dry_run,
)
from app.application.ui.amortization_attempt import (
    build_last_amortization_attempt_snapshot,
    persist_last_amortization_attempt,
)
from app.domain.exceptions import GraphConfigError

logger = logging.getLogger(__name__)


class GraphLike(Protocol):
    async def get(self, *a: Any, **k: Any) -> Any: ...
    async def get_bytes(self, *a: Any, **k: Any) -> Any: ...
    async def put_bytes(self, *a: Any, **k: Any) -> Any: ...
    async def post_json(self, *a: Any, **k: Any) -> Any: ...
    async def delete(self, *a: Any, **k: Any) -> Any: ...


class AmortizationQueueBusyError(Exception):
    """Lock Generate/Finalize/Notify/Merge/Amortization ocupado."""


class AmortizationAlreadyAppliedError(Exception):
    """ProcessKey ya tiene Amortization aplicada por completo (evidencia JobManager).

    Sin job nuevo (uso UI: el operador no debe poder reintentar un proceso ya cerrado).
    """

    def __init__(self, process_key: str, prior_job_id: str | None = None) -> None:
        self.process_key = process_key
        self.prior_job_id = prior_job_id
        super().__init__(
            "La amortización de este proceso ya fue aplicada anteriormente."
            + (f" process_key={process_key}" if process_key else "")
        )


@dataclass(frozen=True)
class AmortizationQueueAccepted:
    job_id: str
    bank_code: str | None
    process_key: str | None = None
    status: str = "queued"
    reused_prior: bool = False


def _utc_now_iso() -> str:
    return now_colombia_iso()


class AmortizationQueueService:
    """Cola Amortization compartida. Usa el JobManager singleton de PA/UI."""

    def __init__(self, job_manager: JobManager | None = None) -> None:
        self._jm = job_manager if job_manager is not None else get_job_manager()

    @property
    def job_manager(self) -> JobManager:
        return self._jm

    def _accepted_from_prior(
        self,
        process_key: str | None,
        bank_code: str | None,
    ) -> AmortizationQueueAccepted:
        """Reutiliza job Amortization exitoso previo (PA 202 compatible; sin lock)."""
        prior = self._jm.find_successful_amortization_by_process_key(
            (process_key or "").strip()
        )
        prior_id = ""
        prior_status = "queued"
        if prior is not None:
            prior_id = str(prior.get("job_id") or "") or ""
            st = str(prior.get("status") or "").strip().lower()
            if st:
                prior_status = st
        return AmortizationQueueAccepted(
            job_id=prior_id,
            bank_code=bank_code,
            process_key=process_key,
            status=prior_status,
            reused_prior=True,
        )

    def _raise_already_applied(self, process_key: str) -> None:
        prior = self._jm.find_successful_amortization_by_process_key(process_key)
        prior_id = None
        if prior is not None:
            prior_id = str(prior.get("job_id") or "") or None
        raise AmortizationAlreadyAppliedError(process_key, prior_job_id=prior_id)

    async def _persist_attempt_from_result(
        self,
        graph: GraphLike,
        *,
        site_id: str,
        drive_id: str,
        bank_code: str | None,
        job_id: str,
        result: dict[str, Any] | None,
        outcome: str | None = None,
        clear_on_success: bool = False,
    ) -> None:
        bank = str(bank_code or "").strip()
        if not bank or not site_id or not drive_id:
            return
        if clear_on_success or outcome in {"applied", "already_applied"}:
            await persist_last_amortization_attempt(
                graph,
                site_id=site_id,
                drive_id=drive_id,
                bank_code=bank,
                attempt=None,
            )
            return
        if not isinstance(result, dict):
            return
        attempt = build_last_amortization_attempt_snapshot(
            result, attempt_id=job_id, outcome=outcome
        )
        await persist_last_amortization_attempt(
            graph,
            site_id=site_id,
            drive_id=drive_id,
            bank_code=bank,
            attempt=attempt,
        )

    # ------------------------------------------------------------------
    # UI: un solo job visible (validar → aplicar).
    # ------------------------------------------------------------------

    async def enqueue_process_ui(
        self,
        *,
        graph: GraphLike,
        background_tasks: BackgroundTasks,
        bank_code: str | None = None,
        process_key: str | None = None,
        trigger_source: str = "web_ui",
        requested_by: str | None = None,
        ui_request_id: str | None = None,
    ) -> AmortizationQueueAccepted:
        # Atómico: busy vs already_applied vs claim (no 202 si ya hubo éxito).
        claim = self._jm.try_claim_amortization_for_process(process_key)
        if claim == "busy":
            raise AmortizationQueueBusyError(
                "Ya existe un proceso generate, finalize, notify, merge o amortización "
                "activo. Consulta /jobs/{job_id}."
            )
        if claim == "already_applied":
            self._raise_already_applied((process_key or "").strip())

        lock_held = True
        try:
            job_id = str(uuid.uuid4())
            initial: dict[str, Any] = {
                "job_id": job_id,
                "type": "amortization_process",
                "status": "queued",
                "queued_at": _utc_now_iso(),
                "created_at": _utc_now_iso(),
                "updated_at": _utc_now_iso(),
                "started_at": None,
                "finished_at": None,
                "result": None,
                "error": None,
                "trigger_source": trigger_source,
                "request": {"bank_code": bank_code, "process_key": process_key},
            }
            if bank_code:
                initial["bank_code"] = bank_code
            if process_key:
                initial["process_key"] = process_key
            if requested_by:
                initial["requested_by"] = requested_by
            if ui_request_id:
                initial["ui_request_id"] = ui_request_id

            await self._jm.set_job(job_id, initial)

            background_tasks.add_task(
                self._run_process_ui_job,
                job_id,
                graph,
                bank_code,
                process_key,
                trigger_source,
                requested_by,
                ui_request_id,
            )
            lock_held = False
            logger.info(
                "job %s: amortization_process encolado trigger=%s by=%s",
                job_id,
                trigger_source,
                requested_by or "",
            )
            return AmortizationQueueAccepted(
                job_id=job_id,
                bank_code=bank_code,
                process_key=process_key,
                status="queued",
            )
        except (AmortizationQueueBusyError, AmortizationAlreadyAppliedError):
            raise
        except Exception:
            if lock_held:
                self._jm.finish_amortization()
            raise

    async def _run_process_ui_job(
        self,
        job_id: str,
        graph: GraphLike,
        bank_code: str | None,
        process_key: str | None,
        trigger_source: str = "web_ui",
        requested_by: str | None = None,
        ui_request_id: str | None = None,
    ) -> None:
        await self._jm.set_job(
            job_id,
            {
                "type": "amortization_process",
                "status": "running",
                "started_at": _utc_now_iso(),
                "updated_at": _utc_now_iso(),
                "progress": {"phase": "validating"},
                "trigger_source": trigger_source,
                **({"process_key": process_key} if process_key else {}),
                **({"bank_code": bank_code} if bank_code else {}),
                **({"requested_by": requested_by} if requested_by else {}),
                **({"ui_request_id": ui_request_id} if ui_request_id else {}),
            },
        )
        logger.info("job %s: amortization_process iniciado", job_id)
        started_ts = perf_counter()
        await try_record_step_event(
            graph,
            step="AMORTIZATION",
            status="STARTED",
            job_id=job_id,
            bank_code=bank_code,
            process_key=process_key,
        )
        plan = None
        plan_site_id = ""
        plan_drive_id = ""
        plan_bank: str | None = bank_code
        try:
            # Preparación canónica única: sin este paso no hay ninguna escritura
            # posterior (execute_amortization_from_prepared exige un plan válido).
            plan = await prepare_amortization_application(
                graph,
                bank_code=bank_code,
                job_id=job_id,
                update_process_control=False,
            )
            pk_final = (plan.resolved_process_key or process_key or "").strip() or None
            bank_final = plan.resolved_bank_code or bank_code
            plan_site_id = plan.site_id
            plan_drive_id = plan.drive_id
            plan_bank = bank_final

            await self._jm.set_job(
                job_id,
                {
                    "updated_at": _utc_now_iso(),
                    "can_apply": bool(plan.can_apply),
                    "validation_result": (
                        plan.dry_run
                        if plan.dry_run is not None
                        else (plan.rejection_result or plan.already_applied_result)
                    ),
                    **({"process_key": pk_final} if pk_final else {}),
                    **({"bank_code": bank_final} if bank_final else {}),
                },
            )

            if plan.already_applied_result is not None:
                elapsed_ms = round((perf_counter() - started_ts) * 1000, 2)
                result = dict(plan.already_applied_result)
                result.setdefault("outcome", "already_applied")
                result["elapsed_ms"] = elapsed_ms
                terminal = infer_terminal_status_from_result(result)
                await try_record_step_event(
                    graph,
                    step="AMORTIZATION",
                    status=terminal,
                    job_id=job_id,
                    bank_code=bank_final,
                    process_key=pk_final,
                    metrics={"elapsed_ms": elapsed_ms, "trigger_source": trigger_source},
                )
                await self._jm.set_job(
                    job_id,
                    {
                        "status": "completed",
                        "finished_at": _utc_now_iso(),
                        "updated_at": _utc_now_iso(),
                        "elapsed_ms": elapsed_ms,
                        "result": result,
                        "error": None,
                        **({"process_key": pk_final} if pk_final else {}),
                        **({"bank_code": bank_final} if bank_final else {}),
                    },
                )
                logger.info(
                    "job %s: amortization_process completado (already_applied)", job_id
                )
                await self._persist_attempt_from_result(
                    graph,
                    site_id=plan.site_id,
                    drive_id=plan.drive_id,
                    bank_code=bank_final,
                    job_id=job_id,
                    result=None,
                    clear_on_success=True,
                )
                return

            if not plan.can_apply:
                # Rechazo de la preparación: NUNCA se llama apply/execute desde aquí.
                # Cero escrituras, cero cambio de EstadoProceso (a diferencia del
                # camino PA con update_control_on_reject=True).
                elapsed_ms = round((perf_counter() - started_ts) * 1000, 2)
                from app.application.ui.amortization_operational_issues import (
                    enrich_operational_issue_web_urls,
                )

                result = await enrich_operational_issue_web_urls(
                    graph,
                    plan.site_id,
                    plan.drive_id,
                    dict(plan.rejection_result or {}),
                )
                result["can_apply"] = False
                result.setdefault("outcome", "requires_correction")
                result["elapsed_ms"] = elapsed_ms
                await try_record_step_event(
                    graph,
                    step="AMORTIZATION",
                    status="BLOCKED",
                    job_id=job_id,
                    bank_code=bank_final,
                    process_key=pk_final,
                    metrics={"elapsed_ms": elapsed_ms, "trigger_source": trigger_source},
                    error={
                        "error_code": str(
                            result.get("error_code") or "REQUIRES_CORRECTION"
                        ),
                        "technical_message": str(
                            result.get("message") or result.get("user_message") or ""
                        )[:4000],
                    },
                )
                await self._jm.set_job(
                    job_id,
                    {
                        "status": "completed",
                        "finished_at": _utc_now_iso(),
                        "updated_at": _utc_now_iso(),
                        "elapsed_ms": elapsed_ms,
                        "result": result,
                        "error": None,
                        **({"process_key": pk_final} if pk_final else {}),
                        **({"bank_code": bank_final} if bank_final else {}),
                    },
                )
                logger.info(
                    "job %s: amortization_process completado (requires_correction)",
                    job_id,
                )
                await self._persist_attempt_from_result(
                    graph,
                    site_id=plan.site_id,
                    drive_id=plan.drive_id,
                    bank_code=bank_final,
                    job_id=job_id,
                    result=result,
                    outcome="requires_correction",
                )
                return

            # can_apply=True: aplica el MISMO plan ya validado (sin re-dry-run).
            await self._jm.set_job(
                job_id,
                {"updated_at": _utc_now_iso(), "progress": {"phase": "applying"}},
            )
            await try_record_step_event(
                graph,
                step="APPLY",
                status="STARTED",
                job_id=job_id,
                bank_code=bank_final,
                process_key=pk_final,
            )
            apply_result = await execute_amortization_from_prepared(
                graph, plan, job_id=job_id
            )
            elapsed_ms = round((perf_counter() - started_ts) * 1000, 2)
            apply_result["elapsed_ms"] = elapsed_ms
            outcome = str(apply_result.get("outcome") or "").strip().lower()
            terminal = infer_terminal_status_from_result(apply_result)
            apply_bank = apply_result.get("bank_code") or bank_final
            apply_pk = (
                apply_result.get("process_key") or pk_final or ""
            ).strip() or None
            await try_record_step_event(
                graph,
                step="APPLY",
                status=terminal,
                job_id=job_id,
                bank_code=apply_bank,
                process_key=apply_pk,
                metrics={
                    "elapsed_ms": elapsed_ms,
                    "trigger_source": trigger_source,
                    "tables_uploaded_count": apply_result.get("tables_uploaded_count"),
                },
            )
            await self._jm.set_job(
                job_id,
                {
                    "status": "completed",
                    "finished_at": _utc_now_iso(),
                    "updated_at": _utc_now_iso(),
                    "elapsed_ms": elapsed_ms,
                    "result": apply_result,
                    "error": None,
                    **({"process_key": apply_pk} if apply_pk else {}),
                    **({"bank_code": apply_bank} if apply_bank else {}),
                },
            )
            logger.info(
                "job %s: amortization_process completado outcome=%s", job_id, outcome
            )
            if outcome in {"applied", "already_applied"}:
                await self._persist_attempt_from_result(
                    graph,
                    site_id=plan_site_id,
                    drive_id=plan_drive_id,
                    bank_code=str(apply_bank or bank_final or ""),
                    job_id=job_id,
                    result=apply_result,
                    outcome=outcome,
                    clear_on_success=True,
                )
            elif outcome in {"requires_correction", "failed", "partial"}:
                from app.application.ui.amortization_operational_issues import (
                    enrich_operational_issue_web_urls,
                )

                enriched = await enrich_operational_issue_web_urls(
                    graph,
                    plan_site_id,
                    plan_drive_id,
                    dict(apply_result),
                )
                await self._jm.set_job(
                    job_id,
                    {
                        "result": enriched,
                        "updated_at": _utc_now_iso(),
                    },
                )
                await self._persist_attempt_from_result(
                    graph,
                    site_id=plan_site_id,
                    drive_id=plan_drive_id,
                    bank_code=str(apply_bank or bank_final or ""),
                    job_id=job_id,
                    result=enriched,
                    outcome=outcome,
                )
        except Exception as exc:
            await try_record_step_event(
                graph,
                step="AMORTIZATION",
                status="FAILED",
                job_id=job_id,
                bank_code=bank_code,
                process_key=process_key,
                error={
                    "error_code": type(exc).__name__,
                    "exception_type": type(exc).__name__,
                    "technical_message": str(exc)[:4000],
                },
            )
            msg = str(exc)
            code = msg.split("|", 1)[0].strip() if "|" in msg else type(exc).__name__
            await self._jm.set_job(
                job_id,
                {
                    "status": "failed",
                    "finished_at": _utc_now_iso(),
                    "updated_at": _utc_now_iso(),
                    "result": None,
                    "error": {"type": type(exc).__name__, "message": msg, "error_code": code},
                    "trigger_source": trigger_source,
                    **({"process_key": process_key} if process_key else {}),
                    **({"requested_by": requested_by} if requested_by else {}),
                    **({"ui_request_id": ui_request_id} if ui_request_id else {}),
                },
            )
            logger.exception("job %s: amortization_process falló: %s", job_id, exc)
            site_id = plan_site_id or (plan.site_id if plan is not None else "")
            drive_id = plan_drive_id or (plan.drive_id if plan is not None else "")
            bank_persist = plan_bank or (
                plan.resolved_bank_code if plan is not None else None
            )
            if site_id and drive_id and bank_persist:
                from app.application.ui.amortization_operational_issues import (
                    attach_operational_issues_to_amortization_result,
                )

                fail_result = attach_operational_issues_to_amortization_result(
                    {
                        "outcome": "failed",
                        "error_code": code,
                        "user_message": msg,
                        "next_action": (
                            "Revise el estado del proceso e intente de nuevo. "
                            "Si el problema continúa, contacte a soporte."
                        ),
                    }
                )
                await self._persist_attempt_from_result(
                    graph,
                    site_id=site_id,
                    drive_id=drive_id,
                    bank_code=bank_persist,
                    job_id=job_id,
                    result=fail_result,
                    outcome="failed",
                )
        finally:
            self._jm.finish_amortization()

    # ------------------------------------------------------------------
    # PA: dry-run (contrato histórico, dos endpoints separados).
    # ------------------------------------------------------------------

    async def enqueue_dry_run_pa(
        self,
        *,
        graph: GraphLike,
        background_tasks: BackgroundTasks,
        report_date_iso: str | None = None,
        merge_manifest_path: str | None = None,
        historical_file_path: str | None = None,
        bank_code: str | None = None,
        process_key: str | None = None,
        trigger_source: str = "power_automate",
    ) -> AmortizationQueueAccepted:
        # Mutex de amortización: serializa dry-run contra Apply/Generate/.../Merge.
        # El dry-run nunca cuenta como "already_applied" evidencia (tipo de job
        # distinto en JobManager._is_amortization_apply_job_type).
        claim = self._jm.try_claim_amortization_for_process(process_key)
        if claim == "busy":
            raise AmortizationQueueBusyError(
                "Ya existe un proceso generate, finalize, notify, merge o amortización "
                "activo. Consulta /jobs/{job_id}."
            )
        if claim == "already_applied":
            return self._accepted_from_prior(process_key, bank_code)

        lock_held = True
        try:
            job_id = str(uuid.uuid4())
            initial: dict[str, Any] = {
                "job_id": job_id,
                "type": "amortization_dry_run",
                "status": "queued",
                "queued_at": _utc_now_iso(),
                "created_at": _utc_now_iso(),
                "updated_at": _utc_now_iso(),
                "started_at": None,
                "finished_at": None,
                "result": None,
                "error": None,
                "trigger_source": trigger_source,
                "request": {
                    "report_date_iso": report_date_iso,
                    "merge_manifest_path": merge_manifest_path,
                    "historical_file_path": historical_file_path,
                    "bank_code": bank_code,
                },
            }
            if bank_code:
                initial["bank_code"] = bank_code
            if process_key:
                initial["process_key"] = process_key

            await self._jm.set_job(job_id, initial)

            background_tasks.add_task(
                self._run_dry_run_pa_job,
                job_id,
                graph,
                report_date_iso,
                merge_manifest_path,
                historical_file_path,
                bank_code,
                trigger_source,
            )
            lock_held = False
            logger.info("job %s: amortization_dry_run encolado", job_id)
            return AmortizationQueueAccepted(
                job_id=job_id,
                bank_code=bank_code,
                process_key=process_key,
                status="queued",
            )
        except AmortizationQueueBusyError:
            raise
        except Exception:
            if lock_held:
                self._jm.finish_amortization()
            raise

    async def _run_dry_run_pa_job(
        self,
        job_id: str,
        graph: GraphLike,
        report_date_iso: str | None,
        merge_manifest_path: str | None,
        historical_file_path: str | None,
        bank_code: str | None,
        trigger_source: str = "power_automate",
    ) -> None:
        await self._jm.set_job(
            job_id,
            {
                "status": "running",
                "started_at": _utc_now_iso(),
                "updated_at": _utc_now_iso(),
                "trigger_source": trigger_source,
            },
        )
        logger.info("job %s: amortization_dry_run iniciado", job_id)
        started_ts = perf_counter()
        await try_record_step_event(
            graph, step="DRY_RUN", status="STARTED", job_id=job_id, bank_code=bank_code
        )
        try:
            # update_process_control=True: contrato histórico PA (LastStepStatus).
            result = await run_amortization_fill_dry_run(
                graph,
                report_date_iso=report_date_iso,
                merge_manifest_path=merge_manifest_path,
                historical_file_path=historical_file_path,
                bank_code=bank_code,
                job_id=job_id,
                update_process_control=True,
            )
            elapsed_ms = round((perf_counter() - started_ts) * 1000, 2)
            terminal = infer_terminal_status_from_result(
                result if isinstance(result, dict) else None
            )
            if isinstance(result, dict) and result.get("can_apply") is False:
                terminal = "BLOCKED"
            await try_record_step_event(
                graph,
                step="DRY_RUN",
                status=terminal,
                job_id=job_id,
                bank_code=bank_code,
                metrics={"elapsed_ms": elapsed_ms, "trigger_source": trigger_source},
            )
            await self._jm.set_job(
                job_id,
                {
                    "status": "completed",
                    "finished_at": _utc_now_iso(),
                    "updated_at": _utc_now_iso(),
                    "result": {**result, "elapsed_ms": elapsed_ms},
                    "error": None,
                },
            )
            logger.info(
                "job %s: amortization_dry_run completado en %.2fms", job_id, elapsed_ms
            )
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
            await self._jm.set_job(
                job_id,
                {
                    "status": "failed",
                    "finished_at": _utc_now_iso(),
                    "updated_at": _utc_now_iso(),
                    "result": None,
                    "error": {"type": "ValueError", "message": msg, "error_code": code},
                },
            )
            logger.warning(
                "job %s: amortization_dry_run falló (validación): %s", job_id, msg
            )
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
            await self._jm.set_job(
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
            await self._jm.set_job(
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
        finally:
            self._jm.finish_amortization()

    # ------------------------------------------------------------------
    # PA: apply (contrato histórico).
    # ------------------------------------------------------------------

    async def enqueue_apply_pa(
        self,
        *,
        graph: GraphLike,
        background_tasks: BackgroundTasks,
        report_date_iso: str | None = None,
        merge_manifest_path: str | None = None,
        historical_file_path: str | None = None,
        bank_code: str | None = None,
        process_key: str | None = None,
        trigger_source: str = "power_automate",
    ) -> AmortizationQueueAccepted:
        claim = self._jm.try_claim_amortization_for_process(process_key)
        if claim == "busy":
            raise AmortizationQueueBusyError(
                "Ya existe un proceso generate, finalize, notify, merge o amortización "
                "activo. Consulta /jobs/{job_id}."
            )
        if claim == "already_applied":
            # PA no debe fallar con 409 en un reintento tras éxito: reusa el job
            # previo (mismo criterio que MergeQueueService para PA).
            return self._accepted_from_prior(process_key, bank_code)

        lock_held = True
        try:
            job_id = str(uuid.uuid4())
            initial: dict[str, Any] = {
                "job_id": job_id,
                "type": "amortization_apply",
                "status": "queued",
                "queued_at": _utc_now_iso(),
                "created_at": _utc_now_iso(),
                "updated_at": _utc_now_iso(),
                "started_at": None,
                "finished_at": None,
                "result": None,
                "error": None,
                "trigger_source": trigger_source,
                "request": {
                    "report_date_iso": report_date_iso,
                    "merge_manifest_path": merge_manifest_path,
                    "historical_file_path": historical_file_path,
                    "bank_code": bank_code,
                },
            }
            if bank_code:
                initial["bank_code"] = bank_code
            if process_key:
                initial["process_key"] = process_key

            await self._jm.set_job(job_id, initial)

            background_tasks.add_task(
                self._run_apply_pa_job,
                job_id,
                graph,
                report_date_iso,
                merge_manifest_path,
                historical_file_path,
                bank_code,
                trigger_source,
            )
            lock_held = False
            logger.info("job %s: amortization_apply encolado", job_id)
            return AmortizationQueueAccepted(
                job_id=job_id,
                bank_code=bank_code,
                process_key=process_key,
                status="queued",
            )
        except AmortizationQueueBusyError:
            raise
        except Exception:
            if lock_held:
                self._jm.finish_amortization()
            raise

    async def _run_apply_pa_job(
        self,
        job_id: str,
        graph: GraphLike,
        report_date_iso: str | None,
        merge_manifest_path: str | None,
        historical_file_path: str | None,
        bank_code: str | None,
        trigger_source: str = "power_automate",
    ) -> None:
        await self._jm.set_job(
            job_id,
            {
                "status": "running",
                "started_at": _utc_now_iso(),
                "updated_at": _utc_now_iso(),
                "trigger_source": trigger_source,
            },
        )
        logger.info("job %s: amortization_apply iniciado", job_id)
        started_ts = perf_counter()
        await try_record_step_event(
            graph, step="APPLY", status="STARTED", job_id=job_id, bank_code=bank_code
        )
        try:
            # Sin prevalidated_plan: prepara internamente una sola vez (contrato PA).
            result = await run_amortization_fill_apply(
                graph,
                report_date_iso=report_date_iso,
                merge_manifest_path=merge_manifest_path,
                historical_file_path=historical_file_path,
                bank_code=bank_code,
                job_id=job_id,
            )
            elapsed_ms = round((perf_counter() - started_ts) * 1000, 2)
            terminal = infer_terminal_status_from_result(
                result if isinstance(result, dict) else None
            )
            await try_record_step_event(
                graph,
                step="APPLY",
                status=terminal,
                job_id=job_id,
                bank_code=bank_code,
                metrics={"elapsed_ms": elapsed_ms, "trigger_source": trigger_source},
            )
            await self._jm.set_job(
                job_id,
                {
                    "status": "completed",
                    "finished_at": _utc_now_iso(),
                    "updated_at": _utc_now_iso(),
                    "result": {**result, "elapsed_ms": elapsed_ms},
                    "error": None,
                },
            )
            logger.info(
                "job %s: amortization_apply completado en %.2fms", job_id, elapsed_ms
            )
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
            await self._jm.set_job(
                job_id,
                {
                    "status": "failed",
                    "finished_at": _utc_now_iso(),
                    "updated_at": _utc_now_iso(),
                    "result": None,
                    "error": {"type": "ValueError", "message": msg, "error_code": code},
                },
            )
            logger.warning("job %s: amortization_apply falló (validación): %s", job_id, msg)
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
            await self._jm.set_job(
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
            logger.error("job %s: amortization_apply config: %s", job_id, exc)
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
            await self._jm.set_job(
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
        finally:
            self._jm.finish_amortization()


_default_service: AmortizationQueueService | None = None


def get_amortization_queue_service() -> AmortizationQueueService:
    """Singleton del servicio de cola (comparte JobManager con PA/UI)."""
    global _default_service
    if _default_service is None:
        _default_service = AmortizationQueueService(get_job_manager())
    return _default_service


def reset_amortization_queue_service_for_tests() -> None:
    global _default_service
    _default_service = None
