"""
Cancelar / resetear un proceso de validación de pagos activo (pre-Finalize).

Aditivo: no altera Generate/Finalize. Solo deja el control del banco en estado
idle (VACIO / IsActive=false) cuando el lote sigue en revisión, para que la
secretaría pueda volver a lanzar Generate sin editar el Excel protegido.

``bank_code`` es opcional: si falta, se auto-detecta el único banco con proceso
cancelable (REVISION_CREADA / ERROR_GENERATE + IsActive). Si hay dos → error.
"""

from __future__ import annotations

import logging
import os
from typing import Any

import httpx

from app.application.config.payment_validation_settings import (
    BANK_CODE_BANCOLOMBIA,
    BANK_CODE_BOGOTA,
    get_payment_validation_paths,
    resolve_bank_display_name,
    validate_bank_code,
)
from app.application.sharepoint_resolution import (
    encode_graph_drive_path,
    require_operations_site_config,
    resolve_sharepoint_path,
)
from app.application.use_cases.payment_validation_process_control import (
    read_process_control_snapshot,
    resolve_process_control_path_for_bank,
    update_process_control_row2,
    utc_now_iso,
)
from app.domain.ports.graph import GraphApiPort

logger = logging.getLogger(__name__)

# Solo pre-Finalize: no cancelar lotes ya cerrados o en merge/amortización.
_CANCEL_ALLOWED_STATES = frozenset({"REVISION_CREADA", "ERROR_GENERATE"})


async def _delete_review_file_best_effort(
    graph: GraphApiPort,
    site_id: str,
    drive_id: str,
    validation_file_path: str,
) -> dict[str, Any]:
    """Elimina el Excel de revisión si existe. 404 = OK (ya ausente)."""
    rel = (validation_file_path or "").strip().strip("/")
    if not rel:
        return {"deleted": False, "reason": "empty_path"}
    endpoint = f"/sites/{site_id}/drives/{drive_id}/root:/{encode_graph_drive_path(rel)}:"
    try:
        await graph.delete(endpoint)
        logger.info("cancel: Excel de revisión eliminado path=%s", rel)
        return {"deleted": True, "path": rel}
    except httpx.HTTPStatusError as exc:
        code = exc.response.status_code if exc.response is not None else 0
        if code == 404:
            return {"deleted": False, "reason": "already_absent", "path": rel}
        logger.warning(
            "cancel: no se pudo eliminar Excel de revisión path=%s http=%s",
            rel,
            code,
        )
        return {
            "deleted": False,
            "reason": "http_error",
            "path": rel,
            "http_status": code,
            "error": str(exc)[:300],
        }
    except Exception as exc:
        logger.warning("cancel: error eliminando Excel de revisión path=%s: %s", rel, exc)
        return {
            "deleted": False,
            "reason": "error",
            "path": rel,
            "error": str(exc)[:300],
        }


def _build_idle_control_updates(*, job_id: str | None) -> dict[str, Any]:
    """Valores idle alineados con setup (VACIO / IsActive=false), preservando Bank*."""
    _ = job_id  # reservado: el job_id queda en el JobManager / respuesta HTTP
    now_iso = utc_now_iso()
    return {
        "EstadoProceso": "VACIO",
        "IsActive": "false",
        "ProcessKey": "",
        "ProcessDate": "",
        "ProcessId": "",
        "ValidationFilePath": "",
        "HistoricalFilePath": "",
        "SecretaryFilePath": "",
        "EmailPdfPath": "",
        "MergeManifestPath": "",
        "GenerateIdempotencyKey": "",
        "FinalizeIdempotencyKey": "",
        "NotifyIdempotencyKey": "",
        "MergeIdempotencyKey": "",
        "ApplyIdempotencyKey": "",
        "GenerateJobId": "",
        "FinalizeJobId": "",
        "NotifyJobId": "",
        "MergeJobId": "",
        "ApplyJobId": "",
        "LastStepErrorCode": "",
        "LastErrorUserMessage": "",
        "LastErrorNextAction": "",
        "MergeOutputCount": 0,
        "MergeSkippedCount": 0,
        "ExecutionId": "",
        "ExecutionLogPath": "",
        "LastCompletedStep": "CANCEL",
        "LastStepStatus": "COMPLETED",
        "LastUpdatedAtProceso": now_iso,
    }


def _is_cancelable_snapshot(snap: Any) -> bool:
    estado = (snap.estado_proceso or "").strip()
    return bool(snap.is_active and estado in _CANCEL_ALLOWED_STATES)


async def _auto_detect_cancelable_banks(
    client: GraphApiPort,
    site_id: str,
    drive_id: str,
) -> list[str]:
    """Bancos con proceso cancelable (REVISION_CREADA/ERROR_GENERATE + IsActive)."""
    candidates: list[str] = []
    for bc in (BANK_CODE_BOGOTA, BANK_CODE_BANCOLOMBIA):
        snap = await read_process_control_snapshot(client, site_id, drive_id, bank_code=bc)
        if _is_cancelable_snapshot(snap):
            candidates.append(bc)
    return candidates


async def cancel_active_payment_validation(
    client: GraphApiPort,
    *,
    bank_code: str | None = None,
    process_key: str | None = None,
    job_id: str | None = None,
) -> dict[str, Any]:
    """
    Resetea el control del banco a VACIO si el lote está en revisión.

    Parameters
    ----------
    bank_code:
        Opcional (banco_bogota | banco_bancolombia). Si falta, auto-detecta
        el único banco con proceso cancelable.
    process_key:
        Opcional. Si se envía, debe coincidir con el ProcessKey del control.
    job_id:
        Opcional. Se registra en auditoría del control.
    """
    bank_code_raw = (bank_code or "").strip() or None
    bank_code_source = "body" if bank_code_raw else "auto_detected"
    ready_banks_detected: list[str] = []

    paths = get_payment_validation_paths()
    review_path = paths.review
    if not review_path:
        raise ValueError("missing_sharepoint_folder")

    require_operations_site_config()
    site_search = (os.getenv("GRAPH_SHAREPOINT_SITE_SEARCH") or "").strip()
    drive_name = (os.getenv("GRAPH_SHAREPOINT_DRIVE_NAME") or "").strip()
    review_info = await resolve_sharepoint_path(client, site_search, drive_name, review_path)
    site_id = review_info["site_id"]
    drive_id = review_info["drive_id"]

    if bank_code_raw:
        validate_bank_code(bank_code_raw)
        bank_code = bank_code_raw
    else:
        candidates = await _auto_detect_cancelable_banks(client, site_id, drive_id)
        ready_banks_detected = list(candidates)
        if len(candidates) > 1:
            raise ValueError("MULTIPLE_READY_PROCESSES|" + ",".join(candidates))
        if not candidates:
            # Ningún banco cancelable: éxito idempotente (botón Cancel sin proceso).
            return {
                "status": "ok",
                "already_cancelled": True,
                "bank_code": "",
                "bank_name": "",
                "bank_code_source": bank_code_source,
                "ready_banks_detected": [],
                "process_key_before": "",
                "process_key_cleared": "",
                "process_control_file_path": "",
                "process_control_estado": "VACIO",
                "process_control_updated": False,
                "review_file_cleanup": {"deleted": False, "reason": "already_idle"},
                "validation_file_path_before": "",
            }
        bank_code = candidates[0]
        bank_code_source = "auto_detected"

    bank_name = resolve_bank_display_name(bank_code)
    process_control_file_path = resolve_process_control_path_for_bank(bank_code).strip().strip("/")

    snap = await read_process_control_snapshot(client, site_id, drive_id, bank_code=bank_code)
    estado = (snap.estado_proceso or "").strip()
    snap_key = (snap.process_key or "").strip()
    expected_key = (process_key or "").strip()

    fully_idle = estado == "VACIO" and not snap.is_active and not snap_key
    if fully_idle:
        return {
            "status": "ok",
            "already_cancelled": True,
            "bank_code": bank_code,
            "bank_name": bank_name,
            "bank_code_source": bank_code_source,
            "ready_banks_detected": ready_banks_detected,
            "process_key_before": "",
            "process_key_cleared": "",
            "process_control_file_path": process_control_file_path,
            "process_control_estado": "VACIO",
            "process_control_updated": False,
            "review_file_cleanup": {"deleted": False, "reason": "already_idle"},
            "validation_file_path_before": "",
        }

    if expected_key and snap_key and expected_key != snap_key:
        raise ValueError(f"process_key_mismatch|{expected_key}|{snap_key}")

    if estado not in _CANCEL_ALLOWED_STATES:
        raise ValueError(f"cancel_not_allowed|{estado or 'VACIO'}|{snap_key}")

    validation_path = (snap.validation_file_path or "").strip()
    review_cleanup = await _delete_review_file_best_effort(
        client, site_id, drive_id, validation_path
    )

    updates = _build_idle_control_updates(job_id=job_id)
    await update_process_control_row2(
        client, site_id, drive_id, bank_code=bank_code, updates=updates
    )

    logger.info(
        "cancel: proceso reseteado bank=%s source=%s estado_antes=%s process_key=%s",
        bank_code,
        bank_code_source,
        estado,
        snap_key,
    )

    return {
        "status": "ok",
        "already_cancelled": False,
        "bank_code": bank_code,
        "bank_name": bank_name,
        "bank_code_source": bank_code_source,
        "ready_banks_detected": ready_banks_detected,
        "process_key_before": snap_key,
        "process_key_cleared": snap_key,
        "process_control_file_path": process_control_file_path,
        "process_control_estado": "VACIO",
        "process_control_updated": True,
        "estado_antes": estado,
        "review_file_cleanup": review_cleanup,
        "validation_file_path_before": validation_path,
    }
