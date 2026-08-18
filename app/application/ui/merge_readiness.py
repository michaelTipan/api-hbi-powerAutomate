"""Readiness de Merge (solo lectura): histórico + listado de ASIENTOS.

No adquiere mutex, no escribe control, no une PDFs ni sube manifiestos.
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from io import BytesIO
from typing import Any, Protocol

from openpyxl import load_workbook

from app.application.job_manager import get_job_manager
from app.application.services.colombia_time import now_colombia_iso
from app.application.services.historical_application_rows import (
    group_rows_by_id_pago,
    read_validated_abono_rows,
    read_validated_payment_rows,
)
from app.application.services.merge_group_validation import (
    credit_hint_from_pdf_filename,
    validate_merge_group_completeness,
)
from app.application.services.review_schema import ExtractRole
from app.application.ui.merge_capabilities import control_indicates_already_merged
from app.application.use_cases.merge_composite_validado_pdfs import (
    _classify_asiento_pdf_names,
    _pdf_names_in_children,
    _ruta_asientos_from_cell,
    normalize_sharepoint_path,
)
from app.application.use_cases.payment_validation_process_control import (
    ProcessControlSnapshot,
)
from app.application.use_cases.send_validar_extractos_notification import (
    _collect_pdf_paths_from_ruta_cell,
    _list_drive_folder_children,
)
from app.application.use_cases.validate_payment_report import _graph_download_by_path
from app.application.sharepoint_resolution import resolve_sharepoint_from_env

logger = logging.getLogger(__name__)

_MSG_ALREADY = "Los asientos contables de este proceso ya fueron consolidados."
_MSG_INCOMPLETE = "Aún faltan documentos contables para uno o más créditos."
_MSG_INCOMPLETE_MISMATCH = (
    "Hay PDF en ASIENTOS cuyo nombre no coincide con el crédito."
)
_MSG_INCOMPLETE_MIXED = (
    "Faltan asientos contables o hay nombres de PDF que no coinciden con el crédito."
)
_MSG_UNKNOWN = (
    "No se pudo verificar si los asientos contables están completos. "
    "Actualice e intente nuevamente."
)
_MSG_READY = "Los asientos contables están listos para consolidar."
_NEXT_LOAD = (
    "Cargue o corrija los archivos pendientes y verifique los asientos contables."
)
_NEXT_RETRY = "Actualice el detalle del proceso e intente nuevamente."
_NEXT_MERGE = "Puede generar el PDF consolidado desde la UI."
_NEXT_DONE = "Consulte los PDFs consolidados y continúe con amortización cuando corresponda."


def _incomplete_user_message(missing_items: list[dict[str, Any]]) -> str:
    """Mensaje corto según el tipo de faltante (detalle va en missing_items)."""
    codes = {str(item.get("error_code") or "").strip() for item in missing_items}
    has_mismatch = "asiento_contable_credit_mismatch" in codes
    has_absence = bool(
        codes
        & {
            "asiento_contable_not_found",
            "missing_ruta_asientos_contables",
            "document_missing",
            "extract_routes_missing",
            "ASIENTO_ASSIGNMENT_AMBIGUOUS",
            "ASIENTO_ASSIGNMENT_NO_MATCH",
            "ASIENTO_ASSIGNMENT_PARSE_FAILED",
            "ASIENTO_ASSIGNMENT_COMPLEXITY_LIMIT",
        }
    )
    if has_mismatch and has_absence:
        return _MSG_INCOMPLETE_MIXED
    if has_mismatch:
        return _MSG_INCOMPLETE_MISMATCH
    return _MSG_INCOMPLETE


class GraphLike(Protocol):
    async def get(self, *a: Any, **k: Any) -> Any: ...
    async def get_bytes(self, *a: Any, **k: Any) -> Any: ...


@dataclass
class MergeReadiness:
    status: str  # ready|incomplete|unknown|already_merged
    expected_groups: int = 0
    ready_groups: int = 0
    missing_groups: int = 0
    missing_items: list[dict[str, Any]] = field(default_factory=list)
    folder_links: list[dict[str, Any]] = field(default_factory=list)
    checked_at: str = ""
    user_message: str = ""
    next_action: str = ""


def _now() -> str:
    return now_colombia_iso()


def _result(
    status: str,
    *,
    expected: int = 0,
    ready: int = 0,
    missing_items: list[dict[str, Any]] | None = None,
    folder_links: list[dict[str, Any]] | None = None,
    user_message: str,
    next_action: str,
) -> MergeReadiness:
    missing_groups = max(0, expected - ready)
    return MergeReadiness(
        status=status,
        expected_groups=expected,
        ready_groups=ready,
        missing_groups=missing_groups,
        missing_items=list(missing_items or []),
        folder_links=list(folder_links or []),
        checked_at=_now(),
        user_message=user_message,
        next_action=next_action,
    )


def collect_asientos_folder_links(
    all_groups: list[tuple[str, str, list[dict[str, Any]]]],
) -> list[dict[str, Any]]:
    """Una entrada por carpeta ASIENTOS requerida (dedupe por path normalizado).

    Alineado con lo que Finalize provisionó en histórico: cada crédito/ruta del
    lote PAGO+ABONO debe aparecer aunque Graph falle al listar hijos.
    Mismo crédito / misma ruta → un solo link.
    """
    folder_links: list[dict[str, Any]] = []
    seen: set[str] = set()
    for _id_pago, _tipo, rows in all_groups:
        for row in rows:
            credit_digits = str(row.get("credito_digits") or "").strip()
            asientos_dir = _ruta_asientos_from_cell(row.get("ruta_asientos_cell"))
            if not asientos_dir:
                continue
            key = normalize_sharepoint_path(asientos_dir)
            if key in seen:
                continue
            seen.add(key)
            folder_links.append(
                {
                    "rel": "asientos",
                    "path": asientos_dir,
                    "credito": credit_digits,
                    "label": "Carpeta ASIENTOS",
                }
            )
    return folder_links


def _observed_pdfs_from_children(children: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Metadata ligera de PDFs en el nivel de la carpeta (sin descargar contenido)."""
    out: list[dict[str, Any]] = []
    for child in children:
        if not isinstance(child, dict):
            continue
        # Graph marca archivos con clave ``file`` (puede ser {}).
        if "folder" in child or "file" not in child:
            continue
        name = str(child.get("name") or "").strip()
        if not name or not name.lower().endswith(".pdf") or name.startswith("~$"):
            continue
        size_raw = child.get("size")
        size = int(size_raw) if isinstance(size_raw, int) else None
        out.append(
            {
                "name": name,
                "size": size,
                "etag": str(child.get("eTag") or child.get("etag") or "").strip() or None,
                "last_modified": str(child.get("lastModifiedDateTime") or "").strip()
                or None,
            }
        )
    return out


async def _attach_observed_pdfs(
    graph: GraphLike,
    site_id: str,
    drive_id: str,
    folder_links: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Lista ASIENTOS por carpeta y adjunta observed_pdfs (informativo; no cambia status)."""
    enriched: list[dict[str, Any]] = []
    for fl in folder_links:
        row = dict(fl)
        path = str(row.get("path") or "").strip()
        if not path:
            enriched.append(row)
            continue
        try:
            children = await _list_drive_folder_children(graph, site_id, drive_id, path)
            row["observed_pdfs"] = _observed_pdfs_from_children(children)
            row["list_ok"] = True
        except Exception:
            logger.info(
                "merge_readiness: list asientos (already_merged) falló path=%s",
                path,
                exc_info=True,
            )
            row["observed_pdfs"] = []
            row["list_ok"] = False
        enriched.append(row)
    return enriched


async def _load_historico_groups(
    graph: GraphLike,
    historico: str,
) -> tuple[str, str, list[tuple[str, str, list[dict[str, Any]]]]] | None:
    """Descarga histórico y agrupa filas PAGO/ABONO. None si no hay grupos."""
    ctx = await resolve_sharepoint_from_env(graph)
    site_id = str(ctx["site_id"])
    drive_id = str(ctx["drive_id"])
    hist_bytes = await _graph_download_by_path(graph, site_id, drive_id, historico)
    estado = (
        os.getenv("GRAPH_VALIDAR_EXTRACTO_ESTADO_CONTAINS") or "VALIDAR"
    ).strip() or "VALIDAR"
    wb = load_workbook(filename=BytesIO(hist_bytes), data_only=True)
    try:
        payment_rows = read_validated_payment_rows(wb, legacy_estado_token=estado)
        abono_rows = read_validated_abono_rows(wb)
        payment_groups = group_rows_by_id_pago(payment_rows)
        abono_groups = group_rows_by_id_pago(abono_rows)
    finally:
        wb.close()

    all_groups: list[tuple[str, str, list[dict[str, Any]]]] = []
    for id_pago, rows in payment_groups.items():
        all_groups.append((str(id_pago), "PAGO", list(rows)))
    for id_pago, rows in abono_groups.items():
        all_groups.append((str(id_pago), "ABONO", list(rows)))
    if not all_groups:
        return None
    return site_id, drive_id, all_groups


async def assess_merge_readiness(
    graph: GraphLike,
    snap: ProcessControlSnapshot,
    bank_code: str,
) -> MergeReadiness:
    """Evalúa si hay asientos contables suficientes para consolidar (solo lectura)."""
    pk = (snap.process_key or "").strip()
    already_merged = control_indicates_already_merged(snap) or (
        bool(pk) and get_job_manager().has_completed_merge(pk)
    )

    historico = (snap.historical_file_path or "").strip().strip("/")
    email_pdf = (snap.email_pdf_path or "").strip().strip("/")
    if not historico or not email_pdf:
        if already_merged:
            return _result(
                "already_merged",
                user_message=_MSG_ALREADY,
                next_action=_NEXT_DONE,
            )
        return _result(
            "incomplete",
            user_message=_MSG_INCOMPLETE,
            next_action=_NEXT_LOAD,
        )

    try:
        loaded = await _load_historico_groups(graph, historico)
        if loaded is None:
            if already_merged:
                return _result(
                    "already_merged",
                    user_message=_MSG_ALREADY,
                    next_action=_NEXT_DONE,
                )
            return _result(
                "incomplete",
                user_message=_MSG_INCOMPLETE,
                next_action=_NEXT_LOAD,
            )

        site_id, drive_id, all_groups = loaded
        # Carpetas primero: no depender del listado Graph ni de grupos incompletos.
        folder_links = collect_asientos_folder_links(all_groups)

        # already_merged: conservar status, pero devolver folder_links + listado
        # ligero (nombre/size/etag/fecha) para recovery UX. No cambia gates.
        if already_merged:
            folder_links = await _attach_observed_pdfs(
                graph, site_id, drive_id, folder_links
            )
            expected = len(all_groups)
            return _result(
                "already_merged",
                expected=expected,
                ready=expected,
                missing_items=[],
                folder_links=folder_links,
                user_message=_MSG_ALREADY,
                next_action=_NEXT_DONE,
            )

        ready = 0
        missing_items: list[dict[str, Any]] = []
        list_failed = False

        for id_pago, tipo, rows in all_groups:
            credit_items: list[dict[str, Any]] = []
            pre_skips: list[str] = []
            for row in rows:
                credit_digits = str(row.get("credito_digits") or "").strip()
                asientos_dir = _ruta_asientos_from_cell(row.get("ruta_asientos_cell"))
                if not asientos_dir:
                    pre_skips.append(
                        f"missing_ruta_asientos_contables credito={credit_digits}"
                    )
                    continue
                try:
                    children = await _list_drive_folder_children(
                        graph, site_id, drive_id, asientos_dir
                    )
                except Exception:
                    logger.info(
                        "merge_readiness: list asientos falló path=%s",
                        asientos_dir,
                        exc_info=True,
                    )
                    list_failed = True
                    pre_skips.append(
                        f"asientos_list_failed credito={credit_digits}"
                    )
                    continue
                names = _pdf_names_in_children(children)
                valid_names, rejected = _classify_asiento_pdf_names(
                    names, credit_digits
                )
                if not valid_names:
                    # Misma distinción que el job de merge (_pick_single_asiento_pdf):
                    # PDF presente pero sin dígitos del crédito → mismatch; carpeta
                    # vacía o sin PDF usable → not_found.
                    if rejected:
                        first_rejected = rejected[0]
                        hint = credit_hint_from_pdf_filename(
                            first_rejected, credit_digits
                        )
                        # Tokens sin espacios (parser de skip lines).
                        safe_name = first_rejected.replace(" ", "_")
                        skip = (
                            f"asiento_contable_credit_mismatch credito={credit_digits}"
                            f" asiento_pdf_found={safe_name}"
                        )
                        if hint:
                            skip = f"{skip} found_credit={hint}"
                        pre_skips.append(skip)
                    else:
                        pre_skips.append(
                            f"asiento_contable_not_found credito={credit_digits}"
                        )
                    continue

                row_include_extract = bool(
                    row.get(
                        "include_extract_in_composite",
                        row.get("requiere_extracto"),
                    )
                )
                row_rol = str(row.get("rol_extracto") or ExtractRole.CIERRE_CUOTA).strip().upper()
                if (
                    tipo == "PAGO"
                    and row_include_extract
                    and row_rol
                    in (
                        ExtractRole.CIERRE_CUOTA,
                        ExtractRole.REFERENCIA_MORA,
                        ExtractRole.REFERENCIA_SALDO,
                    )
                ):
                    extract_paths: list[str] = []
                    for p in await _collect_pdf_paths_from_ruta_cell(
                        graph, site_id, drive_id, row.get("ruta_cell")
                    ):
                        extract_paths.append(p)
                    if not extract_paths:
                        pre_skips.append(
                            f"extract_routes_missing credito={credit_digits}"
                        )
                        continue

                credit_items.append(
                    {
                        "credito": credit_digits,
                        "asiento_pdf_paths": [
                            f"{asientos_dir}/{n}".replace("//", "/")
                            for n in valid_names
                        ],
                    }
                )

            validation = validate_merge_group_completeness(
                id_pago=id_pago,
                tipo_aplicacion=tipo,
                group_rows=rows,
                credit_items=credit_items,
                pre_skips=pre_skips,
            )
            if validation.is_complete:
                ready += 1
            else:
                for item in validation.missing_inputs:
                    missing_items.append(
                        {
                            "id_pago": id_pago,
                            "tipo_aplicacion": tipo,
                            **dict(item),
                        }
                    )

        expected = len(all_groups)
        if list_failed:
            return _result(
                "unknown",
                expected=expected,
                ready=ready,
                missing_items=missing_items,
                folder_links=folder_links,
                user_message=_MSG_UNKNOWN,
                next_action=_NEXT_RETRY,
            )
        if ready >= expected and expected > 0 and not missing_items:
            return _result(
                "ready",
                expected=expected,
                ready=ready,
                missing_items=[],
                folder_links=folder_links,
                user_message=_MSG_READY,
                next_action=_NEXT_MERGE,
            )
        return _result(
            "incomplete",
            expected=expected,
            ready=ready,
            missing_items=missing_items,
            folder_links=folder_links,
            user_message=_incomplete_user_message(missing_items),
            next_action=_NEXT_LOAD,
        )
    except Exception:
        logger.info(
            "merge_readiness: fallo Graph/histórico bank=%s",
            bank_code,
            exc_info=True,
        )
        if already_merged:
            return _result(
                "already_merged",
                user_message=_MSG_ALREADY,
                next_action=_NEXT_DONE,
            )
        return _result(
            "unknown",
            user_message=_MSG_UNKNOWN,
            next_action=_NEXT_RETRY,
        )
