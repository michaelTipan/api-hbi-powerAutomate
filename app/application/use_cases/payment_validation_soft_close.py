"""
Cerrar sin amortizar: soft-close en fase de amortización (post-CONSOLIDADO).

Libera el banco para un Generate nuevo sin borrar histórico, PDFs de correo
ni el consolidado, y sin fingir AMORTIZACION_APLICADA. Los asientos usados en
el consolidado se mueven a PROCESADOS (mismo mecanismo que post-Apply),
best-effort. Estado terminal: CERRADO_SIN_AMORTIZAR.
No aplica durante Merge (PENDIENTE_ASIENTOS / MERGE_PARCIAL / ERROR_MERGE).
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any

from app.application.config.payment_validation_settings import (
    get_payment_validation_paths,
    resolve_bank_display_name,
    validate_bank_code,
)
from app.application.services.accounting_pdf_processed_move import (
    empty_accounting_pdf_move_summary,
    process_used_accounting_pdfs_after_soft_close,
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
from app.application.use_cases.setup_merge_control_workbook import (
    process_date_from_process_key,
)
from app.application.use_cases.validate_payment_report import _graph_download_by_path
from app.domain.ports.graph import GraphApiPort

logger = logging.getLogger(__name__)

# Fase amortización: ya consolidó (o falló/parcial al aplicar). No en Merge.
SOFT_CLOSE_ALLOWED_STATES = frozenset(
    {
        "CONSOLIDADO",
        "AMORTIZACION_PARCIAL",
        "ERROR_APPLY",
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
        # closed_for_new_lote e IsActive=false). Asientos usados → PROCESADOS
        # (best-effort, fuera de este update).
        "ApplyIdempotencyKey": "",
        "ApplyJobId": "",
        "LastCompletedStep": "SOFT_CLOSE",
        "LastStepStatus": "COMPLETED",
        "LastStepErrorCode": "",
        "LastErrorUserMessage": reason or _DEFAULT_CLOSE_MESSAGE,
        "LastErrorNextAction": (
            "Proceso cerrado sin amortizar. Los asientos usados en el consolidado "
            "se movieron a Procesados en la carpeta ASIENTOS de cada crédito "
            "(si el movimiento falló, revise SharePoint). Puede iniciar una "
            "validación nueva para este banco."
        ),
        "LastUpdatedAtProceso": now_iso,
    }


async def _move_used_asientos_best_effort(
    client: GraphApiPort,
    *,
    site_id: str,
    drive_id: str,
    bank_code: str,
    merge_manifest_path: str,
    process_key: str,
) -> dict[str, Any]:
    """Carga el merge manifest y mueve asientos usados; nunca bloquea el cierre."""
    summary = empty_accounting_pdf_move_summary()
    manifest_rel = (merge_manifest_path or "").strip().strip("/")
    if not manifest_rel:
        logger.info(
            "soft_close: sin MergeManifestPath; no hay asientos que mover bank=%s",
            bank_code,
        )
        return summary

    process_date = process_date_from_process_key(process_key)
    fallback_date = process_date.isoformat() if process_date else ""

    try:
        raw = await _graph_download_by_path(client, site_id, drive_id, manifest_rel)
        manifest = json.loads(raw.decode("utf-8"))
        if not isinstance(manifest, dict):
            raise ValueError("merge_manifest_not_object")
    except Exception:
        logger.warning(
            "soft_close: no se pudo leer merge manifest %s (best-effort)",
            manifest_rel,
            exc_info=True,
        )
        return summary

    try:
        summary = await process_used_accounting_pdfs_after_soft_close(
            client,
            site_id,
            drive_id,
            manifest=manifest,
            bank_code=bank_code,
            fallback_payment_date_iso=fallback_date,
        )
    except Exception:
        logger.warning(
            "soft_close: movimiento de asientos falló (best-effort) bank=%s",
            bank_code,
            exc_info=True,
        )
        return empty_accounting_pdf_move_summary()

    if summary.get("accounting_pdfs_move_errors_count") or summary.get(
        "accounting_pdfs_move_warnings_count"
    ):
        logger.warning(
            "soft_close: asientos move summary bank=%s moved=%s already=%s "
            "warnings=%s errors=%s",
            bank_code,
            summary.get("accounting_pdfs_moved_count"),
            summary.get("accounting_pdfs_already_moved_count"),
            summary.get("accounting_pdfs_move_warnings_count"),
            summary.get("accounting_pdfs_move_errors_count"),
        )
    else:
        logger.info(
            "soft_close: asientos movidos a PROCESADOS bank=%s count=%s",
            bank_code,
            summary.get("accounting_pdfs_moved_count"),
        )
    return summary


async def soft_close_payment_validation(
    client: GraphApiPort,
    *,
    bank_code: str,
    process_key: str,
    reason: str | None = None,
    job_id: str | None = None,
) -> dict[str, Any]:
    """
    Soft-close: CERRADO_SIN_AMORTIZAR + IsActive=false + archivo best-effort
    + mover asientos usados del consolidado a PROCESADOS (best-effort).

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
            **empty_accounting_pdf_move_summary(),
        }

    if expected_key and snap_key and expected_key != snap_key:
        raise ValueError(f"process_key_mismatch|{expected_key}|{snap_key}")
    if not snap_key:
        raise ValueError("process_key_mismatch|" + expected_key + "|")

    if estado not in SOFT_CLOSE_ALLOWED_STATES:
        raise ValueError(f"soft_close_not_allowed|{estado or 'VACIO'}|{snap_key}")

    pdf_move_summary = await _move_used_asientos_best_effort(
        client,
        site_id=site_id,
        drive_id=drive_id,
        bank_code=bank_code,
        merge_manifest_path=snap.merge_manifest_path,
        process_key=snap_key,
    )

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
        "soft_close: bank=%s estado_antes=%s process_key=%s archive=%s moved=%s",
        bank_code,
        estado,
        snap_key,
        archive_path or "(none)",
        pdf_move_summary.get("accounting_pdfs_moved_count"),
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
        **pdf_move_summary,
    }
