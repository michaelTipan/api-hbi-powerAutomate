"""
Cerrar sin amortizar: soft-close de un lote en fase tardía (post-Merge / amort).

Libera el banco para un Generate nuevo sin borrar histórico, PDFs ni asientos,
y sin fingir AMORTIZACION_APLICADA. Estado terminal: CERRADO_SIN_AMORTIZAR.
"""

from __future__ import annotations

import logging
import os
from typing import Any

from app.application.config.payment_validation_settings import (
    get_payment_validation_paths,
    resolve_bank_display_name,
    validate_bank_code,
)
from app.application.sharepoint_resolution import (
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

# Fase tardía: ya hay (o hubo) trabajo post-revisión; no abortar pre-Finalize aquí.
SOFT_CLOSE_ALLOWED_STATES = frozenset(
    {
        "CONSOLIDADO",
        "AMORTIZACION_PARCIAL",
        "ERROR_APPLY",
        "MERGE_PARCIAL",
        "PENDIENTE_ASIENTOS",
        "ERROR_MERGE",
    }
)

SOFT_CLOSE_ESTADO = "CERRADO_SIN_AMORTIZAR"
_REASON_MAX_LEN = 280
_DEFAULT_CLOSE_MESSAGE = "Cerrado sin amortizar."


def normalize_soft_close_reason(reason: str | None) -> str:
    """Motivo opcional; si viene, se recorta y valida longitud máxima."""
    text = " ".join((reason or "").strip().split())
    if len(text) > _REASON_MAX_LEN:
        raise ValueError(f"soft_close_reason_too_long|{_REASON_MAX_LEN}")
    return text


def _build_soft_close_updates(*, reason: str, job_id: str | None) -> dict[str, Any]:
    """Marca terminal libre; conserva rutas de histórico/PDF/manifiesto."""
    _ = job_id
    now_iso = utc_now_iso()
    return {
        "EstadoProceso": SOFT_CLOSE_ESTADO,
        "IsActive": "false",
        # No borrar artefactos: HistoricalFilePath / EmailPdfPath / MergeManifestPath
        # quedan. ValidationFilePath se conserva para auditoría (Generate usa
        # closed_for_new_lote e IsActive=false).
        "ApplyIdempotencyKey": "",
        "ApplyJobId": "",
        "LastCompletedStep": "SOFT_CLOSE",
        "LastStepStatus": "COMPLETED",
        "LastStepErrorCode": "",
        "LastErrorUserMessage": reason or _DEFAULT_CLOSE_MESSAGE,
        "LastErrorNextAction": (
            "Proceso cerrado sin amortizar. Puede iniciar una validación nueva "
            "para este banco. Los archivos ya generados se conservan."
        ),
        "LastUpdatedAtProceso": now_iso,
    }


async def soft_close_payment_validation(
    client: GraphApiPort,
    *,
    bank_code: str,
    process_key: str,
    reason: str | None = None,
    job_id: str | None = None,
) -> dict[str, Any]:
    """
    Soft-close: CERRADO_SIN_AMORTIZAR + IsActive=false + archivo best-effort.

    Parameters
    ----------
    bank_code:
        banco_bogota | banco_bancolombia (obligatorio en UI).
    process_key:
        Debe coincidir con el ProcessKey del control.
    reason:
        Motivo opcional (se guarda en control/archivo si viene; vacío OK).
    """
    bank_code = (bank_code or "").strip()
    validate_bank_code(bank_code)
    expected_key = (process_key or "").strip()
    if not expected_key:
        raise ValueError("process_key_required")
    reason_norm = normalize_soft_close_reason(reason)

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

    bank_name = resolve_bank_display_name(bank_code)
    process_control_file_path = resolve_process_control_path_for_bank(bank_code).strip().strip("/")

    snap = await read_process_control_snapshot(client, site_id, drive_id, bank_code=bank_code)
    estado = (snap.estado_proceso or "").strip()
    snap_key = (snap.process_key or "").strip()

    if estado == SOFT_CLOSE_ESTADO and not snap.is_active:
        return {
            "status": "ok",
            "already_closed": True,
            "bank_code": bank_code,
            "bank_name": bank_name,
            "process_key": snap_key or expected_key,
            "process_control_file_path": process_control_file_path,
            "process_control_estado": SOFT_CLOSE_ESTADO,
            "process_control_updated": False,
            "process_archive_path": None,
            "reason": reason_norm,
            "artifacts_deleted": False,
        }

    if expected_key and snap_key and expected_key != snap_key:
        raise ValueError(f"process_key_mismatch|{expected_key}|{snap_key}")
    if not snap_key:
        raise ValueError("process_key_mismatch|" + expected_key + "|")

    if estado not in SOFT_CLOSE_ALLOWED_STATES:
        raise ValueError(f"soft_close_not_allowed|{estado or 'VACIO'}|{snap_key}")

    # Archivar antes de marcar el control (mismo patrón que Apply).
    archive_path: str | None = None
    try:
        from app.application.ui.process_archive import try_archive_process_snapshot

        archive_path = await try_archive_process_snapshot(
            client,
            site_id,
            drive_id,
            snap,
            archive_reason=f"closed_without_amortization|{reason_norm}",
            control_estado_proceso=SOFT_CLOSE_ESTADO,
        )
    except Exception:
        logger.warning(
            "soft_close: archivo de proceso falló (best-effort) bank=%s",
            bank_code,
            exc_info=True,
        )

    updates = _build_soft_close_updates(reason=reason_norm, job_id=job_id)
    await update_process_control_row2(
        client, site_id, drive_id, bank_code=bank_code, updates=updates
    )

    logger.info(
        "soft_close: bank=%s estado_antes=%s process_key=%s archive=%s",
        bank_code,
        estado,
        snap_key,
        archive_path or "(none)",
    )

    return {
        "status": "ok",
        "already_closed": False,
        "bank_code": bank_code,
        "bank_name": bank_name,
        "process_key": snap_key,
        "process_key_before": snap_key,
        "estado_antes": estado,
        "process_control_file_path": process_control_file_path,
        "process_control_estado": SOFT_CLOSE_ESTADO,
        "process_control_updated": True,
        "process_archive_path": archive_path,
        "reason": reason_norm,
        "artifacts_deleted": False,
    }
