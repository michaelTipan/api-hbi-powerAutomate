"""Orquestación compartida de cola Finalize (Power Automate + UI).

Única implementación de lock → job queued → background → use case → finish.
Los routers solo adaptan HTTP; no duplican cableado.
Corrige el uso de ``infer_terminal_status_from_result`` (import válido).
"""
from __future__ import annotations

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
    try_record_step_event,
)
from app.application.use_cases.payment_validation_finalize import finalize_payment_validation

logger = logging.getLogger(__name__)


class GraphLike(Protocol):
    async def get(self, *a: Any, **k: Any) -> Any: ...
    async def get_bytes(self, *a: Any, **k: Any) -> Any: ...
    async def put_bytes(self, *a: Any, **k: Any) -> Any: ...


class FinalizeQueueBusyError(Exception):
    """Lock Generate/Finalize ocupado."""


class FinalizeQueueValidationError(Exception):
    """bank_code o process_date inválidos."""

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


@dataclass(frozen=True)
class FinalizeQueueAccepted:
    job_id: str
    bank_code: str | None
    process_key: str | None = None
    status: str = "queued"


def _utc_now_iso() -> str:
    return now_colombia_iso()


class FinalizeQueueService:
    """Cola Finalize compartida. Usa el JobManager singleton de PA/Generate."""

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
        bank_code: str | None = None,
        validation_file: str | None = None,
        validation_file_path: str | None = None,
        process_date: date | str | None = None,
        process_key: str | None = None,
        trigger_source: str = "power_automate",
        requested_by: str | None = None,
        ui_request_id: str | None = None,
    ) -> FinalizeQueueAccepted:
        if not self._jm.try_start_finalize():
            raise FinalizeQueueBusyError(
                "Ya existe un proceso generate o finalize activo. Consulta /jobs/{job_id}."
            )

        lock_held = True
        try:
            resolved_bank: str | None = None
            if bank_code is not None and str(bank_code).strip():
                try:
                    validate_bank_code(str(bank_code).strip())
                except ValueError as exc:
                    self._jm.finish_finalize()
                    lock_held = False
                    raise FinalizeQueueValidationError(
                        "bank_code inválido. Use banco_bogota o banco_bancolombia."
                    ) from exc
                resolved_bank = str(bank_code).strip()

            resolved_date: date
            if process_date is None:
                resolved_date = date.fromisoformat(today_colombia_iso())
            elif isinstance(process_date, date):
                resolved_date = process_date
            else:
                try:
                    resolved_date = date.fromisoformat(str(process_date).strip())
                except ValueError as exc:
                    self._jm.finish_finalize()
                    lock_held = False
                    raise FinalizeQueueValidationError(
                        "process_date inválido. Usar formato YYYY-MM-DD."
                    ) from exc

            job_id = str(uuid.uuid4())
            initial: dict[str, Any] = {
                "job_id": job_id,
                "type": "finalize",
                "status": "queued",
                "queued_at": _utc_now_iso(),
                "updated_at": _utc_now_iso(),
                "trigger_source": trigger_source,
            }
            if resolved_bank:
                initial["bank_code"] = resolved_bank
            if process_key:
                initial["process_key"] = process_key
            if requested_by:
                initial["requested_by"] = requested_by
            if ui_request_id:
                initial["ui_request_id"] = ui_request_id

            await self._jm.set_job(job_id, initial)

            background_tasks.add_task(
                self._run_finalize_job,
                job_id,
                graph,
                validation_file,
                validation_file_path,
                resolved_date,
                resolved_bank,
                trigger_source,
                requested_by,
                ui_request_id,
            )
            # El lock queda hasta finally del runner; no liberar aquí.
            lock_held = False
            logger.info(
                "job %s: finalize encolado trigger=%s by=%s",
                job_id,
                trigger_source,
                requested_by or "",
            )
            return FinalizeQueueAccepted(
                job_id=job_id,
                bank_code=resolved_bank,
                process_key=process_key,
                status="queued",
            )
        except (FinalizeQueueBusyError, FinalizeQueueValidationError):
            raise
        except Exception:
            if lock_held:
                self._jm.finish_finalize()
            raise

    async def _run_finalize_job(
        self,
        job_id: str,
        graph: GraphLike,
        validation_file: str | None,
        validation_file_path: str | None,
        process_date: date,
        bank_code: str | None,
        trigger_source: str = "power_automate",
        requested_by: str | None = None,
        ui_request_id: str | None = None,
    ) -> None:
        await self._jm.set_job(
            job_id,
            {
                "status": "running",
                "started_at": _utc_now_iso(),
                "updated_at": _utc_now_iso(),
                "trigger_source": trigger_source,
                **({"requested_by": requested_by} if requested_by else {}),
                **({"ui_request_id": ui_request_id} if ui_request_id else {}),
            },
        )
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
            terminal = infer_terminal_status_from_result(
                result if isinstance(result, dict) else None
            )
            await try_record_step_event(
                graph,
                step="FINALIZE",
                status=terminal,
                job_id=job_id,
                bank_code=bank_code or (result or {}).get("bank_code"),
                metrics={
                    "elapsed_ms": elapsed_ms,
                    "trigger_source": trigger_source,
                },
            )
            enriched: dict[str, Any] = {
                **(result if isinstance(result, dict) else {"value": result}),
                "elapsed_ms": elapsed_ms,
                "trigger_source": trigger_source,
            }
            if requested_by:
                enriched["requested_by"] = requested_by
            if ui_request_id:
                enriched["ui_request_id"] = ui_request_id
            await self._jm.set_job(
                job_id,
                {
                    "status": "completed",
                    "finished_at": _utc_now_iso(),
                    "updated_at": _utc_now_iso(),
                    "result": enriched,
                },
            )
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
            self._jm.finish_finalize()


_default_service: FinalizeQueueService | None = None


def get_finalize_queue_service() -> FinalizeQueueService:
    """Singleton del servicio de cola (comparte JobManager con PA/Generate)."""
    global _default_service
    if _default_service is None:
        _default_service = FinalizeQueueService(get_job_manager())
    return _default_service


def reset_finalize_queue_service_for_tests() -> None:
    global _default_service
    _default_service = None
