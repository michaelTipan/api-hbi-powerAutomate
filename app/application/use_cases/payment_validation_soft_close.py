"""
Cerrar sin amortizar: soft-close en fase de amortización (post-CONSOLIDADO).

Libera el banco para un Generate nuevo sin borrar histórico, PDFs de correo
ni el consolidado, y sin fingir AMORTIZACION_APLICADA. Los asientos usados en
el consolidado se mueven a PROCESADOS (archivo al cierre; no mid-apply),
best-effort. El Excel de trabajo en la carpeta de revisión se elimina
(best-effort): el respaldo operativo ya está en HistoricalFilePath desde
Finalize. Estado terminal: CERRADO_SIN_AMORTIZAR o
CERRADO_AMORTIZACION_INCOMPLETA (si ya hubo escrituras de apply).
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
    read_process_control_record,
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
SOFT_CLOSE_PARTIAL_ESTADO = "CERRADO_AMORTIZACION_INCOMPLETA"
SOFT_CLOSE_TERMINAL_STATES = frozenset(
    {SOFT_CLOSE_ESTADO, SOFT_CLOSE_PARTIAL_ESTADO}
)
_REASON_MAX_LEN = 280
_DEFAULT_CLOSE_MESSAGE = "Cerrado sin amortizar."
_DEFAULT_PARTIAL_CLOSE_MESSAGE = (
    "Cerrado con amortización incompleta: tablas ya aplicadas no se revierten."
)


def normalize_soft_close_reason(reason: str | None) -> str:
    """Motivo opcional; si viene, se recorta y valida longitud máxima."""
    text = " ".join((reason or "").strip().split())
    if len(text) > _REASON_MAX_LEN:
        raise ValueError(f"soft_close_reason_too_long|{_REASON_MAX_LEN}")
    return text


def soft_close_had_amortization_writes(
    *,
    estado: str,
    process_key: str | None,
    apply_idempotency_key: str | None,
) -> bool:
    """True si el cierre no puede venderse como «sin amortizar»."""
    e = (estado or "").strip().upper()
    key = (process_key or "").strip()
    apply_key = (apply_idempotency_key or "").strip()
    if e == "AMORTIZACION_PARCIAL":
        return True
    if key and apply_key and key == apply_key:
        return True
    return False


def _normalize_table_link_dicts(raw: Any) -> list[dict[str, str]]:
    if not isinstance(raw, list):
        return []
    out: list[dict[str, str]] = []
    seen: set[str] = set()
    for item in raw:
        if not isinstance(item, dict):
            continue
        path = str(item.get("path") or item.get("tabla_amortizacion_path") or "").strip().strip("/")
        file_url = str(item.get("file_url") or item.get("web_url") or "").strip()
        label = str(item.get("label") or "").strip()
        key = path or file_url
        if not key or key in seen:
            continue
        seen.add(key)
        row: dict[str, str] = {}
        if label:
            row["label"] = label
        if path:
            row["path"] = path
        if file_url:
            row["file_url"] = file_url
        if row.get("path") or row.get("file_url"):
            if "label" not in row:
                row["label"] = path.rsplit("/", 1)[-1] if path else "Tabla de amortización"
            out.append(row)
    return out


def _table_paths_from_apply_result(result: dict[str, Any]) -> list[str]:
    paths: list[str] = []
    seen: set[str] = set()
    for raw in result.get("tables_uploaded") or []:
        norm = str(raw or "").strip().strip("/")
        if norm and norm not in seen:
            seen.add(norm)
            paths.append(norm)
    for link in _normalize_table_link_dicts(result.get("tables_updated_links")):
        path = str(link.get("path") or "").strip().strip("/")
        if path and path not in seen:
            seen.add(path)
            paths.append(path)
    return paths


def _latest_apply_job_for_process(
    *,
    process_key: str,
    apply_job_id: str | None,
) -> dict[str, Any] | None:
    """Best-effort: job Apply/amortization del proceso (links de tablas escritas)."""
    try:
        from app.application.job_manager import JobManager, get_job_manager

        jm = get_job_manager()
    except Exception:
        logger.warning("soft_close: JobManager no disponible para links", exc_info=True)
        return None

    want_id = (apply_job_id or "").strip()
    if want_id:
        try:
            job = jm.get_job(want_id)
        except Exception:
            job = None
        if isinstance(job, dict) and JobManager._is_amortization_apply_job_type(job):
            return job

    key = (process_key or "").strip()
    if not key:
        return None
    try:
        jobs = jm.list_jobs_by_process_key(key)
    except Exception:
        logger.warning(
            "soft_close: no se pudieron listar jobs del process_key",
            exc_info=True,
        )
        return None
    for job in reversed(jobs):
        if not isinstance(job, dict):
            continue
        if not JobManager._is_amortization_apply_job_type(job):
            continue
        status = str(job.get("status") or "").strip().lower()
        if status not in {"completed", "failed"}:
            continue
        result = job.get("result")
        if isinstance(result, dict) and (
            result.get("tables_updated_links") or result.get("tables_uploaded")
        ):
            return job
    return None


async def _resolve_soft_close_amortization_table_links(
    client: GraphApiPort,
    *,
    site_id: str,
    drive_id: str,
    process_key: str,
    apply_job_id: str | None,
) -> list[dict[str, str]]:
    """Rehidrata links de tablas ya escritas (best-effort; nunca bloquea el cierre)."""
    try:
        job = _latest_apply_job_for_process(
            process_key=process_key,
            apply_job_id=apply_job_id,
        )
        if not job:
            return []
        result = job.get("result") if isinstance(job.get("result"), dict) else {}
        existing = _normalize_table_link_dicts(result.get("tables_updated_links"))
        if existing:
            return existing
        paths = _table_paths_from_apply_result(result if isinstance(result, dict) else {})
        if not paths:
            return []
        from app.application.use_cases.amortization_fill_apply import (
            _build_tables_updated_links,
        )

        built = await _build_tables_updated_links(client, site_id, drive_id, paths)
        return _normalize_table_link_dicts(built)
    except Exception:
        logger.warning(
            "soft_close: no se pudieron resolver links de tablas aplicadas",
            exc_info=True,
        )
        return []


def _build_soft_close_updates(
    *,
    reason: str,
    job_id: str | None,
    terminal_estado: str,
    had_amort_writes: bool,
) -> dict[str, Any]:
    """Marca terminal libre; conserva rutas de histórico/PDF/manifiesto."""
    _ = job_id
    now_iso = utc_now_iso()
    if had_amort_writes:
        default_msg = _DEFAULT_PARTIAL_CLOSE_MESSAGE
        next_action = (
            "Proceso cerrado con amortización incompleta. Las tablas ya aplicadas "
            "no se revierten. Los asientos usados en el consolidado se movieron a "
            "Procesados en la carpeta ASIENTOS de cada crédito (si el movimiento "
            "falló, revise SharePoint). Puede iniciar una validación nueva para "
            "este banco."
        )
    else:
        default_msg = _DEFAULT_CLOSE_MESSAGE
        next_action = (
            "Proceso cerrado sin amortizar. Los asientos usados en el consolidado "
            "se movieron a Procesados en la carpeta ASIENTOS de cada crédito "
            "(si el movimiento falló, revise SharePoint). Puede iniciar una "
            "validación nueva para este banco."
        )
    return {
        "EstadoProceso": terminal_estado,
        "IsActive": "false",
        # Conserva histórico/PDF/manifiesto. ValidationFilePath se limpia: el
        # Excel de trabajo ya no vive en la carpeta de revisión (purga aparte).
        "ValidationFilePath": "",
        "ApplyIdempotencyKey": "",
        "ApplyJobId": "",
        "LastCompletedStep": "SOFT_CLOSE",
        "LastStepStatus": "COMPLETED",
        "LastStepErrorCode": "",
        "LastErrorUserMessage": reason or default_msg,
        "LastErrorNextAction": next_action,
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
    exclude_paths: set[str] | None = None,
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
            exclude_paths=exclude_paths,
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


async def _load_decisions_registry_best_effort(
    client: GraphApiPort, *, site_id: str, drive_id: str, snap: Any
) -> dict[str, Any] | None:
    """Registro de decisiones del proceso; el cierre nunca se bloquea si no se lee."""
    path = (getattr(snap, "decisions_registry_path", "") or "").strip()
    if not path:
        return None
    from app.application.services.amortization_decisions import load_registry_for_process

    try:
        return await load_registry_for_process(
            client,
            site_id,
            drive_id,
            registry_path=path,
            process_key=(snap.process_key or "").strip(),
        )
    except Exception:
        logger.warning("soft_close: registro de decisiones no legible %s", path, exc_info=True)
        return None


async def _move_unused_asientos_best_effort(
    client: GraphApiPort, *, site_id: str, drive_id: str, unused: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    from app.application.services.accounting_pdf_processed_move import (
        move_unused_asiento_to_no_usados,
    )

    moves: list[dict[str, Any]] = []
    for entry in unused:
        try:
            rec = await move_unused_asiento_to_no_usados(
                client,
                site_id,
                drive_id,
                asiento_pdf_path=str(entry.get("path") or ""),
                credito=str(entry.get("credito_carpeta") or ""),
            )
            row = rec.as_dict()
        except Exception as exc:
            row = {"source_path": str(entry.get("path") or ""), "status": "error", "reason": str(exc)[:300]}
        row["nota"] = str(entry.get("nota") or "")
        moves.append(row)
    return moves


async def _record_closure_best_effort(
    client: GraphApiPort,
    *,
    site_id: str,
    drive_id: str,
    snap: Any,
    registry: dict[str, Any] | None,
    terminal_estado: str,
    unused_moves: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Guarda en el registro qué créditos quedaron sin amortizar (nunca bloquea el cierre)."""
    if registry is None:
        return []
    from app.application.services.amortization_decisions import (
        active_exclusions,
        mutate_registry,
        record_closure,
    )

    creditos: list[dict[str, Any]] = []
    for entry in active_exclusions(registry):
        clientes = entry.get("clientes") or {}
        tablas = entry.get("tablas") or {}
        for tok in entry.get("credits") or []:
            creditos.append(
                {
                    "credito": str(tok),
                    "cliente": str(clientes.get(tok) or ""),
                    "motivo": str(entry.get("motivo") or ""),
                    "motivo_codigo": str(entry.get("motivo_codigo") or ""),
                    "nota": str(entry.get("nota") or ""),
                    "tabla_amortizacion_path": str(tablas.get(tok) or ""),
                }
            )
    try:
        await mutate_registry(
            client,
            site_id,
            drive_id,
            path=snap.decisions_registry_path,
            process_key=(snap.process_key or "").strip(),
            bank_code=str(registry.get("bank_code") or getattr(snap, "bank_code", "") or ""),
            report_date_iso=str(registry.get("report_date_iso") or ""),
            mutate=lambda reg: (
                record_closure(
                    reg,
                    estado=terminal_estado,
                    creditos_sin_amortizar=creditos,
                    asiento_moves=unused_moves,
                ),
                None,
            ),
        )
    except Exception:
        logger.warning("soft_close: no se pudo registrar el cierre en decisiones", exc_info=True)
    return creditos


async def _purge_review_folder_best_effort(
    client: GraphApiPort,
    *,
    site_id: str,
    drive_id: str,
    review_path: str,
    path_encoded: str,
) -> list[str]:
    """Quita Excels sueltos de la carpeta de revisión para no bloquear el siguiente Generate."""
    from app.application.use_cases.payment_validation_generate import (
        _purge_review_folder_loose_files,
    )

    try:
        review_children = await client.get(
            f"/sites/{site_id}/drives/{drive_id}/root:/{path_encoded}:/children"
        )
    except Exception:
        logger.warning(
            "soft_close: no se pudo listar carpeta de revisión",
            exc_info=True,
        )
        return []
    valid_children = [
        item
        for item in (review_children.get("value", []) if isinstance(review_children, dict) else [])
        if not str(item.get("name") or "").startswith("~$")
    ]
    if not valid_children:
        return []
    try:
        return await _purge_review_folder_loose_files(
            client,
            site_id=site_id,
            drive_id=drive_id,
            review_folder_path=review_path,
            children=valid_children,
        )
    except Exception:
        logger.warning(
            "soft_close: no se pudo purgar carpeta de revisión",
            exc_info=True,
        )
        return []


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

    record = await read_process_control_record(
        client, site_id, drive_id, bank_code=bank_code
    )
    snap = record.snapshot
    estado = (snap.estado_proceso or "").strip()
    snap_key = (snap.process_key or "").strip()
    apply_job_id = str(record.cells.get("ApplyJobId") or "").strip() or None

    if estado in SOFT_CLOSE_TERMINAL_STATES and not snap.is_active:
        return {
            "status": "ok",
            "already_closed": True,
            "bank_code": bank_code,
            "bank_name": bank_name,
            "process_key": snap_key or expected_key,
            "process_control_file_path": process_control_file_path,
            "process_control_estado": estado or SOFT_CLOSE_ESTADO,
            "process_control_updated": False,
            "process_archive_path": None,
            "reason": reason_norm,
            "artifacts_deleted": False,
            "tables_updated_links": [],
            **empty_accounting_pdf_move_summary(),
        }

    if expected_key and snap_key and expected_key != snap_key:
        raise ValueError(f"process_key_mismatch|{expected_key}|{snap_key}")
    if not snap_key:
        raise ValueError("process_key_mismatch|" + expected_key + "|")

    if estado not in SOFT_CLOSE_ALLOWED_STATES:
        raise ValueError(f"soft_close_not_allowed|{estado or 'VACIO'}|{snap_key}")

    had_amort_writes = soft_close_had_amortization_writes(
        estado=estado,
        process_key=snap_key,
        apply_idempotency_key=snap.apply_idempotency_key,
    )
    terminal_estado = (
        SOFT_CLOSE_PARTIAL_ESTADO if had_amort_writes else SOFT_CLOSE_ESTADO
    )
    archive_reason_prefix = (
        "closed_incomplete_amortization"
        if had_amort_writes
        else "closed_without_amortization"
    )

    registry = await _load_decisions_registry_best_effort(
        client, site_id=site_id, drive_id=drive_id, snap=snap
    )
    from app.application.services.amortization_decisions import unused_asientos

    unused = unused_asientos(registry)
    pdf_move_summary = await _move_used_asientos_best_effort(
        client,
        site_id=site_id,
        drive_id=drive_id,
        bank_code=bank_code,
        merge_manifest_path=snap.merge_manifest_path,
        process_key=snap_key,
        exclude_paths={str(a.get("path") or "") for a in unused},
    )
    unused_moves = await _move_unused_asientos_best_effort(
        client, site_id=site_id, drive_id=drive_id, unused=unused
    )
    creditos_sin_amortizar = await _record_closure_best_effort(
        client,
        site_id=site_id,
        drive_id=drive_id,
        snap=snap,
        registry=registry,
        terminal_estado=terminal_estado,
        unused_moves=unused_moves,
    )

    if not (snap.historical_file_path or "").strip():
        logger.warning(
            "soft_close: HistoricalFilePath vacío al cerrar; igual se purga revisión bank=%s",
            bank_code,
        )
    purged_review = await _purge_review_folder_best_effort(
        client,
        site_id=site_id,
        drive_id=drive_id,
        review_path=review_path,
        path_encoded=review_info["path_encoded"],
    )

    # Resolver links de tablas escritas ANTES de archivar (paridad con Apply OK).
    tables_updated_links: list[dict[str, str]] = []
    if had_amort_writes:
        tables_updated_links = await _resolve_soft_close_amortization_table_links(
            client,
            site_id=site_id,
            drive_id=drive_id,
            process_key=snap_key,
            apply_job_id=apply_job_id,
        )

    # Archivar antes de marcar el control (mismo patrón que Apply).
    archive_path: str | None = None
    try:
        from app.application.ui.document_catalog import (
            amortization_group_from_apply_result,
            serialize_document_groups,
        )
        from app.application.ui.process_archive import try_archive_process_snapshot

        archive_groups = []
        if tables_updated_links:
            amort_group = amortization_group_from_apply_result(
                {"tables_updated_links": tables_updated_links}
            )
            if amort_group is not None:
                archive_groups.append(amort_group)

        archive_path = await try_archive_process_snapshot(
            client,
            site_id,
            drive_id,
            snap,
            archive_reason=f"{archive_reason_prefix}|{reason_norm}",
            control_estado_proceso=terminal_estado,
            document_groups=serialize_document_groups(archive_groups) or None,
        )
    except Exception:
        logger.warning(
            "soft_close: archivo de proceso falló (best-effort) bank=%s",
            bank_code,
            exc_info=True,
        )

    updates = _build_soft_close_updates(
        reason=reason_norm,
        job_id=job_id,
        terminal_estado=terminal_estado,
        had_amort_writes=had_amort_writes,
    )
    await update_process_control_row2(
        client, site_id, drive_id, bank_code=bank_code, updates=updates
    )

    logger.info(
        "soft_close: bank=%s estado_antes=%s terminal=%s process_key=%s archive=%s moved=%s links=%s",
        bank_code,
        estado,
        terminal_estado,
        snap_key,
        archive_path or "(none)",
        pdf_move_summary.get("accounting_pdfs_moved_count"),
        len(tables_updated_links),
    )

    return {
        "status": "ok",
        "already_closed": False,
        "bank_code": bank_code,
        "bank_name": bank_name,
        "process_key": snap_key,
        "process_key_before": snap_key,
        "estado_antes": estado,
        "had_amortization_writes": had_amort_writes,
        "process_control_file_path": process_control_file_path,
        "process_control_estado": terminal_estado,
        "process_control_updated": True,
        "process_archive_path": archive_path,
        "reason": reason_norm,
        "artifacts_deleted": False,
        "review_files_purged": purged_review,
        "tables_updated_links": tables_updated_links,
        "creditos_sin_amortizar": creditos_sin_amortizar,
        "asientos_no_usados_moves": unused_moves,
        **pdf_move_summary,
    }
