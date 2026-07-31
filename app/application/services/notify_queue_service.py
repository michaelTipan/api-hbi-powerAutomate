"""Orquestación compartida de cola Notify (Power Automate + UI).

Única implementación de lock → job queued → background → use case → finish.
Los routers solo adaptan HTTP; no duplican runners ni hacen HTTP interno a /graph.
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
from app.application.use_cases.send_validar_extractos_notification import (
    ValidarExtractosNotifyResult,
    record_notify_failure_on_control,
    send_validar_extractos_notification_email,
)

logger = logging.getLogger(__name__)


class GraphLike(Protocol):
    async def get(self, *a: Any, **k: Any) -> Any: ...
    async def get_bytes(self, *a: Any, **k: Any) -> Any: ...
    async def put_bytes(self, *a: Any, **k: Any) -> Any: ...
    async def post_json(self, *a: Any, **k: Any) -> Any: ...


class NotifyQueueBusyError(Exception):
    """Lock Generate/Finalize/Notify ocupado."""


@dataclass(frozen=True)
class NotifyQueueAccepted:
    job_id: str
    bank_code: str | None
    process_key: str | None = None
    status: str = "queued"


def _utc_now_iso() -> str:
    return now_colombia_iso()


def _result_to_dict(result: ValidarExtractosNotifyResult) -> dict[str, Any]:
    return {
        "status": "ok",
        "message": "Ejecutado con éxito",
        "report_date": result.report_date,
        "historical_file_path": result.historical_file_path,
        "historical_file_source": result.historical_file_source,
        "historico_excel_path": result.historico_excel_path,
        "rows_included": result.rows_included,
        "subject": result.subject,
        "attachments_count": result.attachments_count,
        "email_pdf_path": result.email_pdf_path,
        "email_pdf_error": result.email_pdf_error,
        "graph_sendmail_http_status": result.graph_sendmail_http_status,
        "mail_sender": result.mail_sender,
        "mail_to": result.mail_to,
        "merge_control_updated": result.merge_control_updated,
        "merge_control_file_path": result.merge_control_file_path,
        "merge_control_status": result.merge_control_status,
        "merge_control_warning": result.merge_control_warning,
        "merge_control_error_code": result.merge_control_error_code,
        "bank_code": result.bank_code,
        "bank_name": result.bank_name,
        "bank_email_label": result.bank_email_label,
        "bank_code_source": result.bank_code_source,
        "process_key": result.process_key,
        "process_control_file_path": result.process_control_file_path,
        "process_control_estado": result.process_control_estado,
        "payment_groups_included": result.payment_groups_included,
        "abono_groups_included": result.abono_groups_included,
        "abono_credit_rows_included": result.abono_credit_rows_included,
        "extracts_attached_count": result.extracts_attached_count,
        "extracts_not_required_count": result.extracts_not_required_count,
        "movement_groups_included": result.movement_groups_included,
    }


class NotifyQueueService:
    """Cola Notify compartida. Usa el JobManager singleton de PA/Generate/Finalize."""

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
        historical_file_path: str | None = None,
        bank_code: str | None = None,
        to_override: str | None = None,
        cc_override: str | None = None,
        process_key: str | None = None,
        trigger_source: str = "power_automate",
        requested_by: str | None = None,
        ui_request_id: str | None = None,
    ) -> NotifyQueueAccepted:
        if not self._jm.try_start_notify():
            raise NotifyQueueBusyError(
                "Ya existe un proceso generate, finalize o notify activo. "
                "Consulta /jobs/{job_id}."
            )

        lock_held = True
        try:
            job_id = str(uuid.uuid4())
            initial: dict[str, Any] = {
                "job_id": job_id,
                "type": "notify_validar_extractos",
                "status": "queued",
                "queued_at": _utc_now_iso(),
                "created_at": _utc_now_iso(),
                "updated_at": _utc_now_iso(),
                "started_at": None,
                "finished_at": None,
                "result": None,
                "error": None,
                "trigger_source": trigger_source,
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
                self._run_notify_job,
                job_id,
                graph,
                historical_file_path,
                bank_code,
                to_override,
                cc_override,
                trigger_source,
                requested_by,
                ui_request_id,
            )
            lock_held = False
            logger.info(
                "job %s: notify encolado trigger=%s by=%s",
                job_id,
                trigger_source,
                requested_by or "",
            )
            return NotifyQueueAccepted(
                job_id=job_id,
                bank_code=bank_code,
                process_key=process_key,
                status="queued",
            )
        except NotifyQueueBusyError:
            raise
        except Exception:
            if lock_held:
                self._jm.finish_notify()
            raise

    async def _run_notify_job(
        self,
        job_id: str,
        graph: GraphLike,
        historical_file_path: str | None,
        bank_code: str | None,
        to_override: str | None,
        cc_override: str | None,
        trigger_source: str = "power_automate",
        requested_by: str | None = None,
        ui_request_id: str | None = None,
    ) -> None:
        await self._jm.set_job(
            job_id,
            {
                "type": "notify_validar_extractos",
                "status": "running",
                "started_at": _utc_now_iso(),
                "updated_at": _utc_now_iso(),
                "trigger_source": trigger_source,
                **({"requested_by": requested_by} if requested_by else {}),
                **({"ui_request_id": ui_request_id} if ui_request_id else {}),
            },
        )
        logger.info("job %s: notify_validar_extractos iniciado", job_id)
        started_ts = perf_counter()
        await try_record_step_event(
            graph,
            step="NOTIFY",
            status="STARTED",
            job_id=job_id,
            bank_code=bank_code,
        )
        try:
            result = await send_validar_extractos_notification_email(
                graph,
                historical_file_path=historical_file_path,
                bank_code=bank_code,
                job_id=job_id,
                to_override=to_override,
                cc_override=cc_override,
            )
            elapsed_ms = round((perf_counter() - started_ts) * 1000, 2)
            result_dict = _result_to_dict(result)
            result_dict["elapsed_ms"] = elapsed_ms
            result_dict["trigger_source"] = trigger_source
            if requested_by:
                result_dict["requested_by"] = requested_by
            if ui_request_id:
                result_dict["ui_request_id"] = ui_request_id

            terminal = infer_terminal_status_from_result(result_dict)
            await try_record_step_event(
                graph,
                step="NOTIFY",
                status=terminal,
                job_id=job_id,
                bank_code=result.bank_code or bank_code,
                process_key=result.process_key,
                metrics={
                    "elapsed_ms": elapsed_ms,
                    "rows_included": result.rows_included,
                    "trigger_source": trigger_source,
                },
                artifacts=[
                    {
                        "role": "EMAIL_PDF",
                        "path": result.email_pdf_path or "",
                        "file_name": "",
                        "action": "CREATED",
                        "status": "SUCCEEDED",
                    }
                ]
                if result.email_pdf_path and terminal != "SKIPPED_IDEMPOTENT"
                else None,
            )
            await self._jm.set_job(
                job_id,
                {
                    "status": "completed",
                    "finished_at": _utc_now_iso(),
                    "updated_at": _utc_now_iso(),
                    "elapsed_ms": elapsed_ms,
                    "result": result_dict,
                    "error": None,
                },
            )
            logger.info("job %s: notify_validar_extractos completado", job_id)
        except Exception as exc:
            await try_record_step_event(
                graph,
                step="NOTIFY",
                status="FAILED",
                job_id=job_id,
                bank_code=bank_code,
                error={
                    "error_code": type(exc).__name__,
                    "exception_type": type(exc).__name__,
                    "technical_message": str(exc)[:4000],
                },
            )
            await record_notify_failure_on_control(
                graph,
                bank_code=bank_code,
                exc=exc,
                job_id=job_id,
            )
            msg = str(exc)
            code = msg.split("|", 1)[0].strip() if "|" in msg else msg.strip()
            await self._jm.set_job(
                job_id,
                {
                    "status": "failed",
                    "finished_at": _utc_now_iso(),
                    "updated_at": _utc_now_iso(),
                    "result": None,
                    "error": {
                        "type": type(exc).__name__,
                        "message": msg,
                        "error_code": code,
                    },
                    "trigger_source": trigger_source,
                    **({"requested_by": requested_by} if requested_by else {}),
                    **({"ui_request_id": ui_request_id} if ui_request_id else {}),
                },
            )
            logger.exception("job %s: notify_validar_extractos falló: %s", job_id, exc)
        finally:
            self._jm.finish_notify()


_default_service: NotifyQueueService | None = None


def get_notify_queue_service() -> NotifyQueueService:
    """Singleton del servicio de cola (comparte JobManager con PA/UI)."""
    global _default_service
    if _default_service is None:
        _default_service = NotifyQueueService(get_job_manager())
    return _default_service


def reset_notify_queue_service_for_tests() -> None:
    global _default_service
    _default_service = None
