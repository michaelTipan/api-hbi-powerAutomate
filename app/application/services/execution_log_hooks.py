"""
Ganchos de bitácora para runners HTTP. Todo es best-effort y flag-gated.

No modifica EstadoProceso, IsActive, ProcessKey ni claves de idempotencia:
solo escribe ExecutionId / ExecutionLogPath (columnas aditivas de auditoría).
"""

from __future__ import annotations

import logging
from datetime import date
from typing import Any

from app.application.config.payment_validation_settings import (
    execution_run_log_enabled,
    resolve_execution_run_logs_folder_path,
)
from app.application.services.execution_run_log import (
    initialize_execution_log,
    new_execution_id,
    record_execution_event,
    should_reuse_execution_id,
)
from app.application.sharepoint_resolution import (
    require_operations_site_config,
    resolve_sharepoint_from_env,
    resolve_sharepoint_path,
)
from app.application.use_cases.payment_validation_process_control import (
    read_process_control_snapshot,
    update_process_control_row2,
)
from app.domain.ports.graph import GraphApiPort

logger = logging.getLogger(__name__)


async def _ops_site_drive(graph: GraphApiPort) -> tuple[str, str] | None:
    try:
        require_operations_site_config()
        try:
            resolved = await resolve_sharepoint_from_env(graph)
        except Exception:
            import os

            site_search = os.getenv("GRAPH_SHAREPOINT_SITE_SEARCH", "").strip()
            drive_name = os.getenv("GRAPH_SHAREPOINT_DRIVE_NAME", "").strip()
            resolved = await resolve_sharepoint_path(
                graph, site_search, drive_name, resolve_execution_run_logs_folder_path()
            )
        site_id = str(resolved.get("site_id") or "")
        drive_id = str(resolved.get("drive_id") or "")
        if site_id and drive_id:
            return site_id, drive_id
    except Exception as exc:
        logger.warning("execution_log: no se resolvió sitio Operaciones: %s", exc)
    return None


async def try_bootstrap_generate_execution_log(
    graph: GraphApiPort,
    *,
    bank_code: str,
    process_date: date,
    job_id: str,
) -> dict[str, str]:
    """
    Si el flag está activo: reserva ``execution_id`` (nuevo o reutilizado), crea el
    JSON inicial del intento GENERATE y persiste ExecutionId/ExecutionLogPath en
    control de inmediato (aunque el job falle después).

    Si está apagado: dict vacío (sin efectos sobre el flujo financiero).
    """
    if not execution_run_log_enabled():
        return {}
    site_drive = await _ops_site_drive(graph)
    if site_drive is None:
        return {}
    site_id, drive_id = site_drive

    execution_id = new_execution_id()
    reused = False
    try:
        snap = await read_process_control_snapshot(
            graph, site_id, drive_id, bank_code=bank_code
        )
        if should_reuse_execution_id(
            existing_execution_id=snap.execution_id,
            is_active=snap.is_active,
            estado_proceso=snap.estado_proceso,
        ):
            execution_id = snap.execution_id.strip()
            reused = True
    except Exception as exc:
        logger.warning(
            "execution_log: no se pudo leer control para reutilizar execution_id: %s",
            exc,
        )

    init = await initialize_execution_log(
        graph,
        site_id,
        drive_id,
        execution_id=execution_id,
        bank_code=bank_code,
        process_date=process_date,
        job_id=job_id,
    )
    out = {
        "execution_id": str(init.get("execution_id") or execution_id),
        "execution_log_path": str(init.get("execution_log_path") or ""),
        "execution_log_status": str(init.get("execution_log_status") or ""),
        "execution_id_reused": "true" if reused else "false",
    }
    # Persistencia temprana: solo columnas de auditoría (no toca estado de proceso).
    if out["execution_id"]:
        await try_persist_execution_ids_to_control(
            graph,
            bank_code=bank_code,
            execution_id=out["execution_id"],
            execution_log_path=out["execution_log_path"],
        )
    return out


async def try_persist_execution_ids_to_control(
    graph: GraphApiPort,
    *,
    bank_code: str,
    execution_id: str,
    execution_log_path: str,
) -> None:
    """Escribe únicamente ExecutionId / ExecutionLogPath en la fila 2 del control."""
    if not execution_run_log_enabled() or not execution_id:
        return
    site_drive = await _ops_site_drive(graph)
    if site_drive is None:
        return
    site_id, drive_id = site_drive
    try:
        await update_process_control_row2(
            graph,
            site_id,
            drive_id,
            bank_code=bank_code,
            updates={
                "ExecutionId": execution_id,
                "ExecutionLogPath": execution_log_path,
            },
        )
    except Exception as exc:
        logger.warning(
            "execution_log: no se pudo escribir ExecutionId en control bank=%s: %s",
            bank_code,
            exc,
        )


async def try_record_step_event(
    graph: GraphApiPort,
    *,
    step: str,
    status: str,
    job_id: str | None = None,
    bank_code: str | None = None,
    execution_id: str | None = None,
    execution_log_path: str | None = None,
    error: dict[str, Any] | None = None,
    metrics: dict[str, Any] | None = None,
    artifacts: list[dict[str, Any]] | None = None,
    process_id: str | None = None,
    process_key: str | None = None,
    attempt: int = 1,
) -> dict[str, Any]:
    if not execution_run_log_enabled():
        return {"execution_log_status": "DISABLED"}

    eid = (execution_id or "").strip()
    elp = (execution_log_path or "").strip().strip("/")

    site_drive = await _ops_site_drive(graph)
    if site_drive is None:
        return {"execution_log_status": "SKIPPED_NO_SITE"}
    site_id, drive_id = site_drive

    if (not eid or not elp) and bank_code:
        try:
            snap = await read_process_control_snapshot(
                graph, site_id, drive_id, bank_code=bank_code
            )
            eid = eid or (snap.execution_id or "").strip()
            elp = elp or (snap.execution_log_path or "").strip().strip("/")
        except Exception as exc:
            logger.warning(
                "execution_log: no se leyó control para correlacionar step=%s: %s",
                step,
                exc,
            )

    if not eid:
        return {"execution_log_status": "SKIPPED_NO_PATH"}

    meta = await record_execution_event(
        graph,
        site_id,
        drive_id,
        execution_id=eid,
        execution_log_path=elp,
        step=step,
        status=status,
        job_id=job_id,
        attempt=attempt,
        error=error,
        metrics=metrics,
        artifacts=artifacts,
        process_id=process_id,
        process_key=process_key,
        bank_code=bank_code,
    )

    # Actualizar solo la ruta del último archivo de bitácora (auditoría).
    new_path = str(meta.get("execution_log_path") or "").strip()
    if bank_code and eid and new_path and meta.get("execution_log_status") == "OK":
        await try_persist_execution_ids_to_control(
            graph,
            bank_code=bank_code,
            execution_id=eid,
            execution_log_path=new_path,
        )
    return meta


def infer_terminal_status_from_result(result: dict[str, Any] | None) -> str:
    if not isinstance(result, dict):
        return "SUCCEEDED"
    status = str(result.get("status") or "").strip().lower()
    if status in ("already_generated", "already_merged", "already_applied", "already_notified"):
        return "SKIPPED_IDEMPOTENT"
    if status in ("partial", "completed_with_warnings"):
        return "PARTIAL" if status == "partial" else "COMPLETED_WITH_WARNINGS"
    if status in ("blocked",):
        return "BLOCKED"
    if result.get("error") or result.get("errors"):
        if status in ("ok", "success", "completed", ""):
            return "SUCCEEDED"
    return "SUCCEEDED"
