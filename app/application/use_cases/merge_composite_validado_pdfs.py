"""
Por cada ID Pago con filas Validar Pago=SI en Aplicacion_Pagos (histórico schema v4),
descarga y concatena PDFs: primero el PDF del correo (ruta exacta en el archivo de
control), luego por cada crédito asiento(+extracto según política documental).

Un consolidado por ID Pago. El nombre usa Fecha banco + tokens del tipo confirmado
(APLICACION MULTIPLE si hay tipos distintos). Observación/sugerencia nunca en el nombre.

El histórico y el PDF del correo se leen desde el control oficial
por banco (``payment_validation_process_control``, fila 2), salvo overrides en el body.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import unicodedata
from dataclasses import dataclass
from datetime import date
from io import BytesIO
from typing import Any

import httpx
from openpyxl import load_workbook
from pypdf import PdfReader, PdfWriter

from app.application.config.payment_validation_settings import (
    BANK_CODE_BANCOLOMBIA,
    BANK_CODE_BOGOTA,
    resolve_bank_display_name,
    resolve_bank_email_label,
    resolve_bank_report_path,
    resolve_logs_folder_path,
    resolve_merge_output_folder_path,
)
from app.application.services.asiento_lote_assignment import (
    ASIENTO_ASSIGNMENT_AMBIGUOUS,
    ASIENTO_ASSIGNMENT_COMPLEXITY_LIMIT,
    ASIENTO_ASSIGNMENT_NO_MATCH,
    ASIENTO_ASSIGNMENT_PARSE_FAILED,
    AsientoCandidate,
    CandidateParseFailure,
    IdPagoTarget,
    assign_asientos_unique,
)
from app.application.services.accounting_pdf_parser import (
    AccountingParseError,
    PdfTextNotExtractableError,
    extract_text_from_pdf,
    parse_accounting_text,
)
from app.application.services.colombia_time import today_colombia_iso
from app.application.services.accounting_destination import (
    AccountingDestinationError,
    AccountingDestinationResolver,
)
from app.application.services.historical_application_rows import (
    _coerce_historical_date,
    group_rows_by_id_pago,
    read_validated_application_rows,
)
from app.application.services.merge_group_validation import (
    MANIFEST_STATUS_COMPLETE,
    MANIFEST_STATUS_PARTIAL,
    MERGE_GROUP_COMPLETE,
    complete_output_manifest_dict,
    credit_items_cover_expected_creditos,
    credit_items_have_single_asiento_each,
    group_can_reuse_existing_pdf,
    incomplete_group_record,
    validate_merge_group_completeness,
)
from app.application.services.merge_manifest_gate import assess_manifest_completeness
from app.application.services.review_schema import (
    ExtractRole,
    TipoAplicacion,
    merge_name_token_for_tipos,
    policy_fields_for_manifest,
    resolve_manifest_policy,
)
from app.application.sharepoint_resolution import (
    accounting_site_is_configured,
    encode_graph_drive_path,
    resolve_accounting_context,
    resolve_sharepoint_from_env,
    resolve_sharepoint_path,
)
from app.application.use_cases.send_validar_extractos_notification import (
    _collect_pdf_paths_from_ruta_cell,
    _excel_cell_display,
    _list_drive_folder_children,
    _parse_bank_report_table_and_min_date,
    _process_date_from_process_key,
    _sanitize_pdf_filename_component,
)
from app.application.use_cases.validate_payment_report import (
    _graph_download_by_path,
    _graph_get_item_metadata_by_path,
)
from app.domain.ports.graph import GraphApiPort

logger = logging.getLogger(__name__)


# Estados desde los que Unir PDFs puede ejecutarse o reintentarse sin parámetros extra.
# El flujo de Power Automate llama siempre la misma URL, así que un intento que quedó
# incompleto o con error debe poder repetirse con solo volver a llamar el endpoint.
MERGE_RUNNABLE_STATES: frozenset[str] = frozenset(
    {
        "PENDIENTE_ASIENTOS",  # correo enviado: primer intento
        "MERGE_PARCIAL",  # quedaron grupos sin soporte completo
        "ERROR_MERGE",  # intento anterior falló
        "CONSOLIDANDO",  # intento anterior quedó a medias (reinicio del servicio)
        "CONSOLIDADO",  # repetición: la idempotencia devuelve el resultado previo
    }
)


async def _auto_detect_bank_ready_for_merge(
    graph: GraphApiPort, site_id: str, drive_id: str
) -> tuple[str | None, list[str]]:
    """
    Auto-detección Phase 4: el banco es candidato a Merge cuando su control está activo,
    tiene HistoricalFilePath y EmailPdfPath, y su EstadoProceso permite ejecutar o
    reintentar (ver MERGE_RUNNABLE_STATES).
    """
    from app.application.use_cases.payment_validation_process_control import (
        read_process_control_snapshot,
    )

    ready: list[str] = []
    for bc in (BANK_CODE_BOGOTA, BANK_CODE_BANCOLOMBIA):
        snap = await read_process_control_snapshot(graph, site_id, drive_id, bank_code=bc)
        if (
            (snap.estado_proceso or "").strip() in MERGE_RUNNABLE_STATES
            and snap.is_active
            and (snap.historical_file_path or "").strip()
            and (snap.email_pdf_path or "").strip()
        ):
            ready.append(bc)
    if len(ready) == 1:
        return ready[0], ready
    return None, ready


def _merge_pdf_bytes(parts: list[bytes]) -> bytes:
    writer = PdfWriter()
    for chunk in parts:
        if not chunk:
            continue
        reader = PdfReader(BytesIO(chunk))
        for page in reader.pages:
            writer.add_page(page)
    out = BytesIO()
    writer.write(out)
    return out.getvalue()


def _parent_dir(rel_file: str) -> str:
    rel_file = rel_file.strip().strip("/").replace("\\", "/")
    if "/" not in rel_file:
        raise ValueError(f"Ruta de PDF sin carpeta padre: {rel_file!r}")
    return rel_file.rsplit("/", 1)[0]


def _ruta_asientos_from_cell(cell: Any) -> str:
    if cell is None:
        return ""
    return _excel_cell_display(cell).strip().replace("\\", "/").strip("/")


_IGNORED_ASIENTO_SUBFOLDER_NAMES = frozenset({"PROCESADOS", "PROCESADO"})


def normalize_sharepoint_path(path: str) -> str:
    """Clave de deduplicación: sin espacios extremos, barras unificadas, casefold."""
    return str(path or "").strip().strip("/").replace("\\", "/").casefold()


def unique_paths_preserve_order(paths: list[str]) -> list[str]:
    """Deduplica por path normalizado; conserva la primera aparición y el casing original."""
    seen: set[str] = set()
    out: list[str] = []
    for raw in paths:
        canonical = str(raw or "").strip().strip("/").replace("\\", "/")
        if not canonical:
            continue
        key = normalize_sharepoint_path(canonical)
        if key in seen:
            continue
        seen.add(key)
        out.append(canonical)
    return out


def _pdf_names_in_children(children: list[dict[str, Any]]) -> list[str]:
    """PDF en el nivel actual de la carpeta; ignora subcarpetas (p. ej. PROCESADOS)."""
    out: list[str] = []
    for it in children:
        if "folder" in it:
            folder_name = str(it.get("name", "")).strip().casefold()
            if folder_name in _IGNORED_ASIENTO_SUBFOLDER_NAMES:
                continue
            continue
        if "file" not in it:
            continue
        name = str(it.get("name", "")).strip()
        if name.lower().endswith(".pdf") and not name.startswith("~$"):
            out.append(name)
    return sorted(out)


def _filename_contains_credit_isolated(filename: str, credit_digits: str) -> bool:
    """Evita que el crédito 264 coincida con 1264 o 2640 (límites de dígitos)."""
    if not credit_digits:
        return False
    stem = filename.rsplit(".", 1)[0] if "." in filename else filename
    return (
        re.search(rf"(?<!\d){re.escape(credit_digits)}(?!\d)", stem, flags=re.IGNORECASE) is not None
    )


def _merge_skip_line(
    id_pago: str,
    reason: str,
    *,
    cliente: str = "",
    credito_label: str = "",
    credit_number_expected: str = "",
    asiento_pdf_found: str = "",
    asiento_folder_path: str = "",
    extracto_path: str = "",
    names_seen: str = "",
    tipo_aplicacion: str = "",
    requiere_extracto: str = "",
    creditos_seleccionados: str = "",
) -> str:
    def nz(x: str) -> str:
        return x if (x or "").strip() else "-"

    return (
        f"id_pago={id_pago} | reason={reason} | cliente={nz(cliente)} | credito={nz(credito_label)} | "
        f"credit_number_expected={nz(credit_number_expected)} | "
        f"asiento_pdf_found={nz(asiento_pdf_found)} | asiento_folder_path={nz(asiento_folder_path)} | "
        f"extracto_path={nz(extracto_path)} | names_seen={nz(names_seen)} | "
        f"tipo_aplicacion={nz(tipo_aplicacion)} | requiere_extracto={nz(requiere_extracto)} | "
        f"creditos_seleccionados={nz(creditos_seleccionados)}"
    )


_FULLWIDTH_NUMBER_SIGN = "\uff03"

_CREDIT_FOLDER_STATUS_SUFFIXES = (
    "TERMINADO",
    "FINALIZADO",
    "CANCELADO",
    "PAGADO",
    "LIQUIDADO",
    "VIGENTE",
    "REPUESTOS",
)

_CREDIT_FOLDER_SUFFIX_PATTERN = "|".join(
    re.escape(s.casefold()) for s in _CREDIT_FOLDER_STATUS_SUFFIXES
)


def _normalize_folder_sharp(s: str) -> str:
    return s.replace(_FULLWIDTH_NUMBER_SIGN, "#")


def _fold_folder_segment(seg: str) -> str:
    raw = _normalize_folder_sharp(str(seg).strip())
    raw = unicodedata.normalize("NFC", raw)
    nfkd = unicodedata.normalize("NFD", raw)
    return "".join(c for c in nfkd if unicodedata.category(c) != "Mn").strip().casefold()


def _looks_like_credit_folder_name(folded: str) -> bool:
    if not folded:
        return False
    if folded.startswith("credito") or folded.startswith("obligacion"):
        return True
    return bool(re.search(r"credito\s*#?\s*\d+", folded))


def _credit_number_from_folder_segment(seg: str) -> str:
    """
    Extrae dígitos de crédito desde el nombre de carpeta (CREDITO / CRÉDITO + # opcional + número).
    Acepta sufijos operativos (TERMINADO, FINALIZADO, etc.), formas sin '#',
    y prefijos ordinales (p. ej. «2 CREDITO #37 VIGENTE» → 37).
    """
    if not seg or not str(seg).strip():
        return ""
    folded = _fold_folder_segment(seg)
    if not _looks_like_credit_folder_name(folded):
        return ""
    # Buscar «credito [#] N» en cualquier posición (carpetas con prefijo de índice).
    m = re.search(r"credito\s*#?\s*(\d+)", folded)
    if m:
        return m.group(1)
    m_plain = re.search(r"obligacion\s*#?\s*(\d+)", folded)
    if m_plain:
        return m_plain.group(1)
    return ""


def _credit_number_from_extract_parent(ep: str) -> str:
    """Crédito del directorio padre inmediato del PDF de extracto (carpeta CREDITO # n)."""
    try:
        parent = _parent_dir(ep)
    except ValueError:
        return ""
    parts = [p for p in parent.replace("\\", "/").split("/") if str(p).strip()]
    if not parts:
        return ""
    return _credit_number_from_folder_segment(parts[-1])


def _resolve_credit_digits_for_extract(extract_path: str, row_credito_digits: str) -> str:
    """Carpeta del extracto primero; si falla, columna Crédito de la fila del histórico."""
    d = _credit_number_from_extract_parent(extract_path)
    if d:
        return d
    row = str(row_credito_digits or "").strip()
    if row:
        return row
    return _credit_number_from_path_scan(extract_path)


@dataclass(frozen=True)
class _OutputTarget:
    """Sitio, biblioteca y carpeta donde se guarda el PDF consolidado de un grupo."""

    site_id: str
    drive_id: str
    folder: str


def _accounting_date_for_group(fecha_banco: str, fallback: date) -> date:
    """Fecha bancaria del grupo; si no es interpretable, la fecha del reporte."""
    raw = (fecha_banco or "").strip()
    if raw:
        try:
            return date.fromisoformat(raw[:10])
        except ValueError:
            logger.warning(
                "merge_composite_validado: fecha_banco %r no interpretable; se usa %s.",
                raw,
                fallback.isoformat(),
            )
    return fallback


async def _resolve_output_target(
    *,
    accounting_resolver: AccountingDestinationResolver | None,
    accounting_context: dict[str, str] | None,
    operations_site_id: str,
    operations_drive_id: str,
    operations_folder: str,
    fecha_banco: str,
    fallback_date: date,
    bank_code: str,
) -> _OutputTarget:
    """
    Destino del consolidado. Sin sitio de Contabilidad configurado se conserva el
    comportamiento histórico: escribir en la carpeta de asientos de Operaciones.
    """
    if accounting_resolver is None or accounting_context is None:
        return _OutputTarget(operations_site_id, operations_drive_id, operations_folder)

    group_date = _accounting_date_for_group(fecha_banco, fallback_date)
    folder = await accounting_resolver.resolve_folder(group_date, bank_code)
    return _OutputTarget(
        accounting_context["site_id"], accounting_context["drive_id"], folder
    )


async def _drive_item_exists(
    graph: GraphApiPort, site_id: str, drive_id: str, rel_path: str
) -> bool:
    enc = encode_graph_drive_path(rel_path.strip().strip("/"))
    try:
        await graph.get_bytes(f"/sites/{site_id}/drives/{drive_id}/root:/{enc}:/content")
        return True
    except httpx.HTTPStatusError as exc:
        if exc.response is not None and exc.response.status_code == 404:
            return False
        raise


def _row_application_policy(
    row: dict[str, Any],
    *,
    default_canonical: str,
) -> Any:
    return resolve_manifest_policy(row, default_canonical=default_canonical)


def _mora_reference_amount_from_row(row: dict[str, Any]) -> float | None:
    for key in ("mora_reference_amount", "valor_extracto", "otros_valores", "intereses_mora"):
        raw = row.get(key)
        if raw is None or str(raw).strip() == "":
            continue
        if isinstance(raw, (int, float)):
            return float(raw)
        try:
            return float(str(raw).replace(",", "."))
        except ValueError:
            continue
    return None


def _finalize_credit_item(
    credit_digits: str,
    asiento_paths: list[str],
    extract_paths: list[str],
    *,
    warnings: list[str] | None = None,
    tipo_aplicacion: str = TipoAplicacion.PAGO.value,
    ruta_tabla_amortizacion: str = "",
    ruta_unidad_credito: str = "",
    ruta_asientos_contables: str = "",
    policy: Any | None = None,
    mora_reference_amount: float | None = None,
) -> dict[str, Any]:
    asientos = unique_paths_preserve_order(asiento_paths)
    extractos = unique_paths_preserve_order(extract_paths)
    w = list(warnings or [])
    if len(extractos) > 1:
        w.append("MULTIPLE_EXTRACTS_FOR_CREDIT")
    resolved_policy = policy
    if resolved_policy is None:
        resolved_policy = resolve_manifest_policy(
            {"tipo_aplicacion": tipo_aplicacion},
            default_canonical=tipo_aplicacion,
        )
    item: dict[str, Any] = {
        "credito": credit_digits,
        "tipo_aplicacion": resolved_policy.tipo_aplicacion_canonica,
        **policy_fields_for_manifest(resolved_policy),
        "ruta_tabla_amortizacion": ruta_tabla_amortizacion,
        "ruta_unidad_credito": ruta_unidad_credito,
        "ruta_asientos_contables": ruta_asientos_contables,
        "asiento_pdf_paths": asientos,
        "extracto_pdf_paths": extractos,
        "extracto_pdf_path": extractos[0] if extractos else "",
        "warnings": w,
    }
    if mora_reference_amount is not None:
        item["mora_reference_amount"] = mora_reference_amount
    return item



async def _list_procesados_pdf_names(
    graph: GraphApiPort,
    site_id: str,
    drive_id: str,
    asientos_dir_ep: str,
) -> set[str]:
    """Nombres de PDF ya en PROCESADOS (no reasignar)."""
    folder = f"{asientos_dir_ep.rstrip('/')}/PROCESADOS"
    try:
        children = await _list_drive_folder_children(graph, site_id, drive_id, folder)
    except Exception:
        return set()
    return {n.casefold() for n in _pdf_names_in_children(children)}


def _child_file_tags(children: list[dict[str, Any]], name: str) -> tuple[str, str]:
    want = str(name or "").strip().casefold()
    for it in children:
        if str(it.get("name") or "").strip().casefold() != want:
            continue
        return (
            str(it.get("eTag") or it.get("etag") or ""),
            str(it.get("cTag") or it.get("ctag") or ""),
        )
    return "", ""


async def _prevalidate_id_pago_group(
    graph: GraphApiPort,
    site_id: str,
    drive_id: str,
    id_pago: str,
    rows: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[str]]:
    """
    Valida filas del ID Pago y devuelve credit_items (un bloque por crédito) y líneas skipped.
    """
    credit_accum: dict[str, dict[str, Any]] = {}
    skip_lines: list[str] = []

    for row in rows:
        cliente = str(row.get("cliente") or "").strip()
        credito_label = str(row.get("credito_label") or "").strip()
        row_cred = str(row.get("credito_digits") or "").strip()
        row_include_extract = bool(
            row.get(
                "include_extract_in_composite",
                row.get("requiere_extracto", True),
            )
        )
        row_rol = str(row.get("rol_extracto") or ExtractRole.CIERRE_CUOTA).strip().upper()
        tipo_visible = str(row.get("tipo_aplicacion_original") or TipoAplicacion.PAGO.value).strip()

        extract_paths: list[str] = []
        if row_include_extract and row_rol in (
            ExtractRole.CIERRE_CUOTA,
            ExtractRole.REFERENCIA_MORA,
            ExtractRole.REFERENCIA_SALDO,
        ):
            ruta_cell = row.get("ruta_cell")
            for p in await _collect_pdf_paths_from_ruta_cell(graph, site_id, drive_id, ruta_cell):
                extract_paths.append(p.strip().strip("/").replace("\\", "/"))
            extract_paths = unique_paths_preserve_order(extract_paths)

        if row_include_extract and not extract_paths:
            skip_lines.append(
                _merge_skip_line(
                    id_pago,
                    "extract_routes_missing",
                    cliente=cliente,
                    credito_label=credito_label,
                    credit_number_expected=row_cred or "-",
                    extracto_path="-",
                    tipo_aplicacion=tipo_visible,
                    requiere_extracto="SI",
                )
            )
            continue

        credit_digits = row_cred
        if extract_paths:
            credit_digits = row_cred or _resolve_credit_digits_for_extract(extract_paths[0], "")
            if not credit_digits:
                credit_digits = _resolve_credit_digits_for_extract(extract_paths[0], row_cred)
        if not credit_digits:
            skip_lines.append(
                _merge_skip_line(
                    id_pago,
                    "credit_number_not_resolved",
                    cliente=cliente,
                    credito_label=credito_label,
                    extracto_path=extract_paths[0] if extract_paths else "-",
                )
            )
            continue

        asientos_dir_ep = _ruta_asientos_from_cell(row.get("ruta_asientos_cell"))
        if not asientos_dir_ep:
            skip_lines.append(
                _merge_skip_line(
                    id_pago,
                    "missing_ruta_asientos_contables",
                    cliente=cliente,
                    credito_label=credito_label,
                    credit_number_expected=credit_digits,
                    extracto_path=extract_paths[0] if extract_paths else "-",
                )
            )
            continue

        try:
            asiento_children = await _list_drive_folder_children(
                graph, site_id, drive_id, asientos_dir_ep
            )
        except Exception as exc:
            skip_lines.append(
                _merge_skip_line(
                    id_pago,
                    "asiento_folder_list_failed",
                    cliente=cliente,
                    credito_label=credito_label,
                    credit_number_expected=credit_digits,
                    asiento_folder_path=asientos_dir_ep,
                    extracto_path=extract_paths[0] if extract_paths else "-",
                    names_seen=str(exc)[:800],
                )
            )
            continue

        names = _pdf_names_in_children(asiento_children)
        valid_names, rejected_names = _classify_asiento_pdf_names(names, credit_digits)
        processed = await _list_procesados_pdf_names(
            graph, site_id, drive_id, asientos_dir_ep
        )
        valid_names = [n for n in valid_names if n.casefold() not in processed]
        for rej in rejected_names:
            skip_lines.append(
                _merge_skip_line(
                    id_pago,
                    "asiento_contable_credit_mismatch",
                    cliente=cliente,
                    credito_label=credito_label,
                    credit_number_expected=credit_digits,
                    asiento_pdf_found=rej,
                    asiento_folder_path=asientos_dir_ep,
                    extracto_path=extract_paths[0],
                    names_seen=", ".join(names) if names else "-",
                )
            )
        if not valid_names:
            skip_lines.append(
                _merge_skip_line(
                    id_pago,
                    "asiento_contable_not_found",
                    cliente=cliente,
                    credito_label=credito_label,
                    credit_number_expected=credit_digits,
                    asiento_folder_path=asientos_dir_ep,
                    extracto_path=extract_paths[0],
                    names_seen=", ".join(names) if names else "-",
                )
            )
            continue

        policy = _row_application_policy(row, default_canonical=TipoAplicacion.PAGO.value)
        bucket = credit_accum.setdefault(
            credit_digits,
            {
                "asiento_pdf_paths": [],
                "extracto_pdf_paths": [],
                "warnings": [],
                "policy": policy,
            },
        )
        # Un PDF por archivo; la asignación lote↔ID Pago se resuelve por monto (no por filename).
        for asiento_name in valid_names:
            asiento_rel = f"{asientos_dir_ep}/{asiento_name}".replace("//", "/")
            if asiento_rel not in bucket["asiento_pdf_paths"]:
                bucket["asiento_pdf_paths"].append(asiento_rel)
                bucket.setdefault("asiento_children", asiento_children)
        bucket["extracto_pdf_paths"].extend(extract_paths)

    credit_items: list[dict[str, Any]] = []
    for credit_digits in sorted(credit_accum.keys(), key=lambda x: (len(x), x)):
        raw = credit_accum[credit_digits]
        item = _finalize_credit_item(
            credit_digits,
            raw["asiento_pdf_paths"],
            raw["extracto_pdf_paths"],
            warnings=raw.get("warnings"),
            policy=raw.get("policy"),
        )
        policy = raw.get("policy")
        needs_extract = True
        if policy is not None:
            needs_extract = bool(
                getattr(policy, "include_extract_in_composite", None)
                if getattr(policy, "include_extract_in_composite", None) is not None
                else getattr(policy, "requiere_extracto", True)
            )
        if not item["asiento_pdf_paths"] or (needs_extract and not item["extracto_pdf_paths"]):
            skip_lines.append(
                _merge_skip_line(
                    id_pago,
                    "asiento_contable_not_found"
                    if not item["asiento_pdf_paths"]
                    else "extract_routes_missing",
                    credit_number_expected=credit_digits,
                    extracto_path=item["extracto_pdf_path"] or "-",
                )
            )
            continue
        credit_items.append(item)

    if not credit_items:
        if not skip_lines:
            skip_lines.append(
                _merge_skip_line(
                    id_pago,
                    "extract_routes_missing",
                    extracto_path="-",
                )
            )
        return [], skip_lines
    return credit_items, skip_lines


async def _prevalidate_abono_id_pago_group(
    graph: GraphApiPort,
    site_id: str,
    drive_id: str,
    id_pago: str,
    rows: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[str]]:
    """Valida grupo ABONO: asientos por crédito; extracto no requerido."""
    credit_accum: dict[str, dict[str, Any]] = {}
    skip_lines: list[str] = []
    creditos_sel = ", ".join(
        sorted(
            {
                str(r.get("credito_digits") or r.get("credito_label") or "").strip()
                for r in rows
                if str(r.get("credito_digits") or r.get("credito_label") or "").strip()
            }
        )
    )

    for row in rows:
        cliente = str(row.get("cliente") or "").strip()
        credito_label = str(row.get("credito_label") or "").strip()
        row_cred = str(row.get("credito_digits") or "").strip()
        row_requiere_extracto = bool(row.get("requiere_extracto"))
        row_rol = str(row.get("rol_extracto") or ExtractRole.NO_APLICA).strip().upper()
        tipo_visible = str(row.get("tipo_aplicacion_original") or TipoAplicacion.ABONO.value).strip()

        asientos_dir_ep = _ruta_asientos_from_cell(row.get("ruta_asientos_cell"))
        if not asientos_dir_ep:
            skip_lines.append(
                _merge_skip_line(
                    id_pago,
                    "missing_ruta_asientos_contables",
                    cliente=cliente,
                    credito_label=credito_label,
                    credit_number_expected=row_cred or "-",
                    tipo_aplicacion=tipo_visible,
                    requiere_extracto="SI" if row_requiere_extracto else "NO",
                    creditos_seleccionados=creditos_sel,
                )
            )
            continue

        if not row_cred:
            skip_lines.append(
                _merge_skip_line(
                    id_pago,
                    "credit_number_not_resolved",
                    cliente=cliente,
                    credito_label=credito_label,
                    tipo_aplicacion=tipo_visible,
                    requiere_extracto="SI" if row_requiere_extracto else "NO",
                    creditos_seleccionados=creditos_sel,
                )
            )
            continue

        extract_paths: list[str] = []
        if row_requiere_extracto and row_rol == ExtractRole.REFERENCIA_MORA:
            for p in await _collect_pdf_paths_from_ruta_cell(
                graph, site_id, drive_id, row.get("ruta_cell")
            ):
                extract_paths.append(p.strip().strip("/").replace("\\", "/"))
            extract_paths = unique_paths_preserve_order(extract_paths)
            if not extract_paths:
                skip_lines.append(
                    _merge_skip_line(
                        id_pago,
                        "extract_routes_missing",
                        cliente=cliente,
                        credito_label=credito_label,
                        credit_number_expected=row_cred,
                        extracto_path="-",
                        tipo_aplicacion=tipo_visible,
                        requiere_extracto="SI",
                        creditos_seleccionados=creditos_sel,
                    )
                )
                continue

        try:
            asiento_children = await _list_drive_folder_children(
                graph, site_id, drive_id, asientos_dir_ep
            )
        except Exception as exc:
            skip_lines.append(
                _merge_skip_line(
                    id_pago,
                    "asiento_folder_list_failed",
                    cliente=cliente,
                    credito_label=credito_label,
                    credit_number_expected=row_cred,
                    asiento_folder_path=asientos_dir_ep,
                    names_seen=str(exc)[:800],
                    tipo_aplicacion=tipo_visible,
                    requiere_extracto="SI" if row_requiere_extracto else "NO",
                    creditos_seleccionados=creditos_sel,
                )
            )
            continue

        names = _pdf_names_in_children(asiento_children)
        valid_names, rejected_names = _classify_asiento_pdf_names(names, row_cred)
        processed = await _list_procesados_pdf_names(
            graph, site_id, drive_id, asientos_dir_ep
        )
        valid_names = [n for n in valid_names if n.casefold() not in processed]
        for rej in rejected_names:
            skip_lines.append(
                _merge_skip_line(
                    id_pago,
                    "asiento_contable_credit_mismatch",
                    cliente=cliente,
                    credito_label=credito_label,
                    credit_number_expected=row_cred,
                    asiento_pdf_found=rej,
                    asiento_folder_path=asientos_dir_ep,
                    names_seen=", ".join(names) if names else "-",
                    tipo_aplicacion=tipo_visible,
                    requiere_extracto="SI" if row_requiere_extracto else "NO",
                    creditos_seleccionados=creditos_sel,
                )
            )
        if not valid_names:
            skip_lines.append(
                _merge_skip_line(
                    id_pago,
                    "abono_accounting_pdf_missing",
                    cliente=cliente,
                    credito_label=credito_label,
                    credit_number_expected=row_cred,
                    asiento_folder_path=asientos_dir_ep,
                    names_seen=", ".join(names) if names else "-",
                    tipo_aplicacion=tipo_visible,
                    requiere_extracto="SI" if row_requiere_extracto else "NO",
                    creditos_seleccionados=creditos_sel,
                )
            )
            continue

        policy = _row_application_policy(row, default_canonical=TipoAplicacion.ABONO.value)
        bucket = credit_accum.setdefault(
            row_cred,
            {
                "asiento_pdf_paths": [],
                "extracto_pdf_paths": [],
                "warnings": [],
                "ruta_asientos_contables": asientos_dir_ep,
                "policy": policy,
                "mora_reference_amount": _mora_reference_amount_from_row(row),
            },
        )
        for asiento_name in valid_names:
            asiento_rel = f"{asientos_dir_ep}/{asiento_name}".replace("//", "/")
            if asiento_rel not in bucket["asiento_pdf_paths"]:
                bucket["asiento_pdf_paths"].append(asiento_rel)
        bucket["extracto_pdf_paths"].extend(extract_paths)

    credit_items: list[dict[str, Any]] = []
    for credit_digits in sorted(credit_accum.keys(), key=lambda x: (len(x), x)):
        raw = credit_accum[credit_digits]
        raw_policy = raw.get("policy")
        item = _finalize_credit_item(
            credit_digits,
            raw["asiento_pdf_paths"],
            raw.get("extracto_pdf_paths") or [],
            warnings=raw.get("warnings"),
            tipo_aplicacion=str(
                raw_policy.tipo_aplicacion_canonica
                if raw_policy is not None
                else TipoAplicacion.ABONO.value
            ),
            ruta_asientos_contables=str(raw.get("ruta_asientos_contables") or ""),
            policy=raw_policy,
            mora_reference_amount=raw.get("mora_reference_amount"),
        )
        if not item["asiento_pdf_paths"]:
            skip_lines.append(
                _merge_skip_line(
                    id_pago,
                    "abono_accounting_pdf_missing",
                    credit_number_expected=credit_digits,
                    tipo_aplicacion=TipoAplicacion.ABONO.value,
                    requiere_extracto="NO",
                    creditos_seleccionados=creditos_sel,
                )
            )
            continue
        credit_items.append(item)

    if not credit_items:
        if not skip_lines:
            skip_lines.append(
                _merge_skip_line(
                    id_pago,
                    "abono_accounting_pdf_missing",
                    tipo_aplicacion=TipoAplicacion.ABONO.value,
                    requiere_extracto="NO",
                    creditos_seleccionados=creditos_sel,
                )
            )
        return [], skip_lines
    return credit_items, skip_lines


async def _build_consolidated_pdf_parts(
    graph: GraphApiPort,
    site_id: str,
    drive_id: str,
    id_pago: str,
    email_bytes: bytes,
    email_rel: str,
    credit_items: list[dict[str, Any]],
    *,
    include_extracts: bool = True,
) -> tuple[list[bytes], list[str], list[str]]:
    """
    Orden: email, luego por crédito (estable): todos los asientos, luego extracto(s) deduplicados.
    Devuelve (parts, labels, líneas skipped si falla una descarga).
    """
    parts: list[bytes] = [email_bytes]
    labels: list[str] = [f"email:{email_rel}"]
    build_skips: list[str] = []

    for item in sorted(credit_items, key=lambda x: str(x.get("credito") or "")):
        credito = str(item.get("credito") or "")
        for asiento_rel in item.get("asiento_pdf_paths") or []:
            try:
                asiento_bytes = await _graph_download_by_path(
                    graph, site_id, drive_id, str(asiento_rel)
                )
            except Exception as exc:
                build_skips.append(
                    _merge_skip_line(
                        id_pago,
                        "asiento_download_failed",
                        credito_label=credito,
                        credit_number_expected=credito,
                        asiento_folder_path=_parent_dir(str(asiento_rel)),
                        asiento_pdf_found=str(asiento_rel).rsplit("/", 1)[-1],
                        names_seen=str(exc)[:800],
                    )
                )
                return parts, labels, build_skips
            parts.append(asiento_bytes)
            labels.append(f"asiento:{asiento_rel}")

        if include_extracts:
            for ep in item.get("extracto_pdf_paths") or []:
                try:
                    extract_bytes = await _graph_download_by_path(graph, site_id, drive_id, str(ep))
                except Exception as exc:
                    build_skips.append(
                        _merge_skip_line(
                            id_pago,
                            "extracto_download_failed",
                            credito_label=credito,
                            credit_number_expected=credito,
                            extracto_path=str(ep),
                            names_seen=str(exc)[:800],
                        )
                    )
                    return parts, labels, build_skips
                parts.append(extract_bytes)
                labels.append(f"extracto:{ep}")

    return parts, labels, build_skips


def _unique_creditos_from_group(g: dict[str, Any]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for raw in g.get("creditos") or []:
        tok = _normalize_credito_excel_value(raw)
        if not tok:
            tok = re.sub(r"\D", "", str(raw).strip())
        if tok and tok not in seen:
            seen.add(tok)
            out.append(tok)
    return out


def _group_is_multi_credit(g: dict[str, Any], extract_paths: list[str]) -> bool:
    if len(extract_paths) > 1:
        return True
    return len(_unique_creditos_from_group(g)) > 1


def _classify_asiento_pdf_names(
    names: list[str],
    credit_digits: str,
) -> tuple[list[str], list[str]]:
    """
    Clasifica PDFs de la carpeta de asientos del crédito.
    Devuelve (válidos ordenados, rechazados por no coincidir con el crédito).
    """
    valid: list[str] = []
    rejected: list[str] = []
    for name in sorted(names):
        if _filename_contains_credit_isolated(name, credit_digits):
            valid.append(name)
        else:
            rejected.append(name)
    return valid, rejected


def _pick_single_asiento_pdf(names: list[str], credit_digits: str) -> tuple[str | None, str | None]:
    """
    Compatibilidad tests/helpers: primer PDF válido o motivo de fallo.
    Varios PDF válidos del mismo crédito no son ambiguos; use ``_classify_asiento_pdf_names``.
    """
    valid, rejected = _classify_asiento_pdf_names(names, credit_digits)
    if valid:
        return valid[0], None
    if rejected:
        return None, "asiento_contable_credit_mismatch"
    return None, "asiento_contable_not_found"


def _unique_asiento_paths_from_pairs(pair_asientos: list[tuple[str, str]]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for asiento_rel, _ep in pair_asientos:
        key = asiento_rel.strip().strip("/")
        if key and key not in seen:
            seen.add(key)
            out.append(key)
    return out


_MESES_ES = (
    "ENERO",
    "FEBRERO",
    "MARZO",
    "ABRIL",
    "MAYO",
    "JUNIO",
    "JULIO",
    "AGOSTO",
    "SEPTIEMBRE",
    "OCTUBRE",
    "NOVIEMBRE",
    "DICIEMBRE",
)


def _mes_reporte_upper(report_d: date) -> str:
    return _MESES_ES[report_d.month - 1]


def _credit_number_from_path_scan(rel: str) -> str:
    """Último segmento de la ruta que coincide con carpeta de crédito (p. ej. tokens en nombre de archivo)."""
    parts = [p for p in rel.replace("\\", "/").split("/") if str(p).strip()]
    for part in reversed(parts):
        hit = _credit_number_from_folder_segment(part)
        if hit:
            return hit
    return ""


def _client_folder_before_credit(rel: str) -> str:
    parts = [p for p in rel.replace("\\", "/").split("/") if p.strip()]
    for i, part in enumerate(parts):
        if _credit_number_from_folder_segment(part) and i > 0:
            return parts[i - 1].strip()
    return ""


def _normalize_credito_excel_value(raw: Any) -> str:
    """Número para el nombre del PDF (columna Crédito); no se usa para rutas en SharePoint."""
    from app.application.services.review_schema import normalize_credito_digits

    return normalize_credito_digits(raw)


def _merge_composite_client_token(s: str, max_len: int = 80) -> str:
    t = re.sub(r'[<>:"/\\|?*\x00-\x1f]', " ", str(s or "").strip())
    t = re.sub(r"\s+", " ", t).strip()
    return t[:max_len] if len(t) > max_len else t


def _merge_composite_credit_for_filename_display(credit_part: str) -> str:
    raw = (credit_part or "").strip()
    if not raw:
        return "SIN_CREDITO"
    cleaned = re.sub(r"[^0-9,\s]", "", raw)
    cleaned = re.sub(r"\s*,\s*", ", ", cleaned).strip()
    cleaned = re.sub(r",\s*,+", ", ", cleaned)
    if not cleaned or not re.search(r"\d", cleaned):
        return "SIN_CREDITO"
    return _merge_composite_client_token(cleaned, max_len=100)


def _credit_tokens_ordered_for_rows(
    rows: list[dict[str, Any]], extract_paths: list[str]
) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for row in rows:
        tok = str(row.get("credito_digits") or "").strip()
        if not tok:
            raw = row.get("credito_raw")
            tok = _normalize_credito_excel_value(raw)
            if not tok:
                tok = re.sub(r"\D", "", str(raw or "").strip())
        if tok and tok not in seen:
            seen.add(tok)
            out.append(tok)
    for ep in extract_paths:
        tok = _credit_number_from_extract_parent(ep) or _credit_number_from_path_scan(ep)
        if tok and tok not in seen:
            seen.add(tok)
            out.append(tok)
    return out


def _merge_composite_output_basename(
    report_d: date,
    client: str,
    credit_part: str,
    *,
    bank_code: str,
    tipo_aplicacion: str = TipoAplicacion.PAGO.value,
    name_token: str | None = None,
) -> str:
    """
    {DIA} {MES} {BANCO} {TOKEN} {CLIENTE} {CREDITOS}.pdf

    ``report_d`` debe ser Fecha banco del ID Pago (no la fecha del proceso).
    Observación / Aplicación sugerida NUNCA participan.
    """
    day = report_d.day
    mes = _mes_reporte_upper(report_d)
    bc = (bank_code or "").strip() or BANK_CODE_BOGOTA
    bank_token = resolve_bank_email_label(bc)
    cli = _merge_composite_client_token(client)
    cred = _merge_composite_credit_for_filename_display(credit_part)
    if not cli:
        cli = "CLIENTE"
    if name_token and str(name_token).strip():
        token = str(name_token).strip()
    else:
        token = merge_name_token_for_tipos([tipo_aplicacion])
    base = f"{day} {mes} {bank_token} {token} {cli} {cred}.pdf"
    return _sanitize_pdf_filename_component(base) or base


def _allocate_duplicate_pdf_name(base: str, tallies: dict[str, int]) -> str:
    stem = base[:-4] if base.lower().endswith(".pdf") else base
    ext = ".pdf" if base.lower().endswith(".pdf") else ""
    key = stem.casefold()
    tallies[key] = tallies.get(key, 0) + 1
    n = tallies[key]
    if n == 1:
        return f"{stem}{ext}"
    return f"{stem}_{n}{ext}"


@dataclass(frozen=True)
class MergeCompositePdfOutput:
    id_pago: str
    output_relative_path: str
    bytes_written: int
    sources_summary: str
    cliente: str = ""
    credito: str = ""
    email_pdf_path: str = ""
    asiento_pdf_path: str = ""
    asiento_pdf_paths: tuple[str, ...] = ()
    extracto_pdf_path: str = ""
    credit_items: tuple[dict[str, Any], ...] = ()
    tipo_aplicacion: str = TipoAplicacion.PAGO.value
    requiere_extracto: bool = True
    tipo_aplicacion_original: str = ""
    tipo_aplicacion_canonica: str = ""
    subtipo_aplicacion: str = ""
    rol_extracto: str = ""
    cierra_cuota: bool = False
    actualiza_ibr: bool | None = True
    payoff_expected: bool = False
    monto_banco: float | None = None
    fecha_banco: str = ""
    creditos_seleccionados: tuple[str, ...] = ()
    output_web_url: str = ""
    output_folder_web_url: str = ""
    output_folder_relative_path: str = ""
    asiento_assignment: tuple[dict[str, Any], ...] = ()


@dataclass(frozen=True)
class MergeCompositeValidadoPdfsResult:
    report_date_iso: str
    historico_excel_path: str
    estado_linea_contains: str
    email_pdf_used: str
    outputs: tuple[MergeCompositePdfOutput, ...] = ()
    skipped: tuple[str, ...] = ()
    merge_control_file_path: str = ""
    merge_control_updated: bool = False
    merge_control_status: str | None = None
    outputs_count: int = 0
    skipped_count: int = 0
    merge_manifest_path: str = ""
    # Phase 4 observabilidad (control por banco)
    bank_code: str = ""
    bank_name: str = ""
    bank_code_source: str = ""
    ready_banks_detected: tuple[str, ...] = ()
    process_key: str = ""
    process_control_file_path: str = ""
    process_control_updated: bool = False
    process_control_estado: str = ""
    historical_file_source: str = ""
    email_pdf_source: str = ""
    already_merged: bool = False
    file_action: str = ""
    merge_idempotency_key: str = ""
    pdf_created: bool = False
    pdf_reused: bool = False
    already_consolidated: bool = False
    force_rebuild_used: bool = False
    payment_outputs_count: int = 0
    abono_outputs_count: int = 0
    payment_skipped_count: int = 0
    abono_skipped_count: int = 0
    extracts_not_required_count: int = 0
    manifest_status: str = ""
    eligible_for_dry_run: bool = False
    incomplete_groups_count: int = 0
    payment_incomplete_groups_count: int = 0
    abono_incomplete_groups_count: int = 0
    complete_groups_count: int = 0
    failed_groups_count: int = 0
    consolidation_folder_web_url: str = ""
    consolidation_folder_relative_path: str = ""


def _http_url_only(raw: Any) -> str:
    s = str(raw or "").strip()
    if s.lower().startswith("http://") or s.lower().startswith("https://"):
        return s
    return ""


def _parent_folder_relative_path(file_rel: str) -> str:
    p = str(file_rel or "").strip().strip("/")
    if "/" not in p:
        return ""
    return p.rsplit("/", 1)[0]


async def _resolve_drive_item_web_url(
    graph: GraphApiPort,
    site_id: str,
    drive_id: str,
    relative_path: str,
) -> str:
    rel = str(relative_path or "").strip().strip("/")
    if not rel:
        return ""
    enc = encode_graph_drive_path(rel)
    try:
        resp = await graph.get(
            f"/sites/{site_id}/drives/{drive_id}/root:/{enc}",
            params={"$select": "webUrl"},
        )
        if isinstance(resp, dict):
            return _http_url_only(resp.get("webUrl"))
    except Exception:
        logger.debug(
            "merge: no se obtuvo webUrl path=%s",
            rel,
            exc_info=True,
        )
    return ""


async def _resolve_merge_output_share_links(
    graph: GraphApiPort,
    site_id: str,
    drive_id: str,
    *,
    output_relative_path: str,
    upload_response: dict[str, Any] | None = None,
) -> tuple[str, str, str]:
    """
    Retorna (output_web_url, output_folder_web_url, output_folder_relative_path).
    Preferir webUrl de put_bytes; si falta, GET del ítem. La carpeta se resuelve por GET.
    """
    file_rel = str(output_relative_path or "").strip().strip("/")
    folder_rel = _parent_folder_relative_path(file_rel)
    file_url = ""
    if isinstance(upload_response, dict):
        file_url = _http_url_only(upload_response.get("webUrl"))
    if not file_url and file_rel:
        file_url = await _resolve_drive_item_web_url(graph, site_id, drive_id, file_rel)
    folder_url = ""
    if folder_rel:
        folder_url = await _resolve_drive_item_web_url(graph, site_id, drive_id, folder_rel)
    return file_url, folder_url, folder_rel


def _first_consolidation_folder_from_outputs(
    outputs: list[MergeCompositePdfOutput] | tuple[MergeCompositePdfOutput, ...],
) -> tuple[str, str]:
    for o in outputs:
        folder_url = str(o.output_folder_web_url or "").strip()
        folder_rel = str(o.output_folder_relative_path or "").strip()
        if folder_url or folder_rel:
            return folder_url, folder_rel
    return "", ""


def _consolidation_folder_from_manifest(manifest: dict[str, Any] | None) -> tuple[str, str]:
    if not isinstance(manifest, dict):
        return "", ""
    for o in manifest.get("outputs") or []:
        if not isinstance(o, dict):
            continue
        folder_url = _http_url_only(o.get("output_folder_web_url"))
        folder_rel = str(o.get("output_folder_relative_path") or "").strip().strip("/")
        if not folder_rel:
            folder_rel = _parent_folder_relative_path(str(o.get("output_relative_path") or ""))
        if folder_url or folder_rel:
            return folder_url, folder_rel
    return "", ""


def _merge_logs_folder_relative() -> str:
    return resolve_logs_folder_path()


def _output_is_already_consolidated(output: MergeCompositePdfOutput) -> bool:
    return str(output.sources_summary).startswith("already_consolidated")


def _merge_pdf_observability(
    outputs: tuple[MergeCompositePdfOutput, ...] | list[MergeCompositePdfOutput],
    *,
    final_status: str,
) -> tuple[str, bool, bool, bool]:
    """
    Observabilidad agregada del merge (sin alterar la consolidación).

    - Todo reutilizado → file_action=reused, pdf_created=False, pdf_reused=True
    - Mezcla o solo creación → created/partial según final_status y qué se escribió
    """
    if not outputs:
        return "created" if final_status == "CONSOLIDADO" else "partial", False, False, False

    reused = [_output_is_already_consolidated(o) for o in outputs]
    any_reused = any(reused)
    any_created = any(not r for r in reused)

    if all(reused):
        return "reused", False, True, True
    if any_created and any_reused:
        action = "partial" if final_status == "MERGE_PARCIAL" else "created"
        return action, True, True, True
    action = "partial" if final_status == "MERGE_PARCIAL" else "created"
    return action, True, False, False


def _legacy_paths_from_credit_items(credit_items: list[dict[str, Any]]) -> tuple[list[str], str]:
    asiento_paths: list[str] = []
    extract_paths: list[str] = []
    for item in credit_items:
        asiento_paths.extend(item.get("asiento_pdf_paths") or [])
        extract_paths.extend(item.get("extracto_pdf_paths") or [])
    asiento_paths = unique_paths_preserve_order(asiento_paths)
    extract_paths = unique_paths_preserve_order(extract_paths)
    extracto_legacy = " | ".join(extract_paths)
    return asiento_paths, extracto_legacy


def _merge_output_record(
    *,
    id_pago: str,
    output_relative_path: str,
    bytes_written: int,
    sources_summary: str,
    cliente: str,
    credito: str,
    email_pdf_path: str,
    credit_items: list[dict[str, Any]],
    tipo_aplicacion: str = TipoAplicacion.PAGO.value,
    requiere_extracto: bool = True,
    policy: Any | None = None,
    monto_banco: float | None = None,
    fecha_banco: str = "",
    creditos_seleccionados: tuple[str, ...] = (),
    output_web_url: str = "",
    output_folder_web_url: str = "",
    output_folder_relative_path: str = "",
    asiento_assignment: list[dict[str, Any]] | tuple[dict[str, Any], ...] | None = None,
) -> MergeCompositePdfOutput:
    asiento_paths, extracto_path = _legacy_paths_from_credit_items(credit_items)
    legacy_asiento = asiento_paths[0] if asiento_paths else ""
    frozen_items = tuple(dict(ci) for ci in credit_items)
    resolved_policy = policy or resolve_manifest_policy(
        credit_items[0] if credit_items else {"tipo_aplicacion": tipo_aplicacion},
        default_canonical=tipo_aplicacion,
    )
    policy_fields = policy_fields_for_manifest(resolved_policy)
    folder_rel = (
        str(output_folder_relative_path or "").strip().strip("/")
        or _parent_folder_relative_path(output_relative_path)
    )
    return MergeCompositePdfOutput(
        id_pago=id_pago,
        output_relative_path=output_relative_path,
        bytes_written=bytes_written,
        sources_summary=sources_summary,
        cliente=cliente,
        credito=credito,
        email_pdf_path=email_pdf_path,
        asiento_pdf_path=legacy_asiento,
        asiento_pdf_paths=tuple(asiento_paths),
        extracto_pdf_path=extracto_path,
        credit_items=frozen_items,
        tipo_aplicacion=resolved_policy.tipo_aplicacion_canonica,
        requiere_extracto=bool(policy_fields.get("requiere_extracto", requiere_extracto)),
        tipo_aplicacion_original=str(policy_fields.get("tipo_aplicacion_original") or ""),
        tipo_aplicacion_canonica=str(policy_fields.get("tipo_aplicacion_canonica") or ""),
        subtipo_aplicacion=str(policy_fields.get("subtipo_aplicacion") or ""),
        rol_extracto=str(policy_fields.get("rol_extracto") or ""),
        cierra_cuota=bool(policy_fields.get("cierra_cuota")),
        actualiza_ibr=policy_fields.get("actualiza_ibr"),
        payoff_expected=bool(policy_fields.get("payoff_expected")),
        monto_banco=monto_banco,
        fecha_banco=fecha_banco,
        creditos_seleccionados=creditos_seleccionados,
        output_web_url=_http_url_only(output_web_url),
        output_folder_web_url=_http_url_only(output_folder_web_url),
        output_folder_relative_path=folder_rel,
        asiento_assignment=tuple(asiento_assignment or ()),
    )


def _manifest_output_dict(
    output: MergeCompositePdfOutput,
    *,
    expected_creditos: tuple[str, ...],
) -> dict[str, Any]:
    base = complete_output_manifest_dict(output, expected_creditos=expected_creditos)
    base.update(
        {
            "tipo_aplicacion_original": output.tipo_aplicacion_original,
            "tipo_aplicacion_canonica": output.tipo_aplicacion_canonica,
            "subtipo_aplicacion": output.subtipo_aplicacion,
            "rol_extracto": output.rol_extracto,
            "cierra_cuota": output.cierra_cuota,
            "actualiza_ibr": output.actualiza_ibr,
            "payoff_expected": output.payoff_expected,
            "output_web_url": output.output_web_url,
            "output_folder_web_url": output.output_folder_web_url,
            "output_folder_relative_path": output.output_folder_relative_path,
            "asiento_assignment": list(output.asiento_assignment or ()),
        }
    )
    return base


def _group_meta_from_rows(
    rows: list[dict[str, Any]],
    *,
    tipo_aplicacion: str,
) -> tuple[str, float | None, str, tuple[str, ...]]:
    """Metadata de grupo por ID Pago: monto/fecha canónicos (no solo fila[0])."""
    _ = tipo_aplicacion
    ref = rows[0] if rows else {}
    cliente = str(ref.get("cliente") or "").strip()
    monto_val: float | None = None
    fecha = ref.get("fecha_banco")
    for row in rows:
        if not cliente:
            cliente = str(row.get("cliente") or "").strip()
        raw_m = row.get("monto_banco")
        if monto_val is None and isinstance(raw_m, (int, float)) and float(raw_m) > 0:
            monto_val = float(raw_m)
        if fecha is None:
            fecha = row.get("fecha_banco")
    fecha_str = fecha.isoformat() if hasattr(fecha, "isoformat") else str(fecha or "")
    creditos: list[str] = []
    seen: set[str] = set()
    for row in sorted(rows, key=lambda x: str(x.get("credito_digits") or x.get("credito_label") or "")):
        c = str(row.get("credito_digits") or row.get("credito_label") or "").strip()
        if c and c not in seen:
            seen.add(c)
            creditos.append(c)
    return cliente, monto_val, fecha_str, tuple(creditos)


def _naming_date_for_group(
    group_rows: list[dict[str, Any]],
    fecha_meta: str,
    report_d: date,
) -> date:
    """Fecha banco del ID Pago para el nombre del PDF consolidado (no process_date)."""
    for row in group_rows:
        parsed = _coerce_historical_date(row.get("fecha_banco"))
        if parsed is not None:
            return parsed
    parsed_meta = _coerce_historical_date(fecha_meta)
    if parsed_meta is not None:
        return parsed_meta
    logger.warning(
        "merge_composite_validado: sin fecha_banco interpretable en grupo; se usa process_date %s.",
        report_d.isoformat(),
    )
    return report_d


_LOTE_STRICT_ERRORS = frozenset(
    {
        ASIENTO_ASSIGNMENT_AMBIGUOUS,
        ASIENTO_ASSIGNMENT_COMPLEXITY_LIMIT,
    }
)


def _staged_asiento_paths_globally_unambiguous(
    staged: list[tuple[str, str, list[dict[str, Any]], list[dict[str, Any]], list[str]]],
) -> bool:
    """Un PDF de asiento por crédito, sin reutilizar el mismo path entre ID Pagos."""
    if not staged:
        return False
    seen_paths: set[str] = set()
    for _id_pago, _tipo, group_rows, credit_items, _skips in staged:
        if not credit_items_cover_expected_creditos(group_rows, credit_items):
            return False
        if not credit_items_have_single_asiento_each(credit_items):
            return False
        for item in credit_items:
            paths = item.get("asiento_pdf_paths") or []
            key = _norm_asiento_path(str(paths[0])).casefold()
            if not key or key in seen_paths:
                return False
            seen_paths.add(key)
    return True


def _apply_lote_assignment_or_fallback(
    *,
    id_pago: str,
    group_rows: list[dict[str, Any]],
    credit_items: list[dict[str, Any]],
    pre_skips: list[str],
    lote_assignment: Any | None,
) -> tuple[list[dict[str, Any]], list[str]]:
    """Concilia asientos por monto cuando hace falta; si no, conserva prevalidación 1:1."""
    if lote_assignment is None:
        return credit_items, pre_skips

    assign_err = lote_assignment.errors.get(id_pago)
    assigned_paths = lote_assignment.assignment.get(id_pago) or ()
    assigned_fps = list(lote_assignment.fingerprints.get(id_pago) or [])
    if not assign_err:
        return (
            _apply_assignment_to_credit_items(credit_items, assigned_paths, assigned_fps),
            pre_skips,
        )

    if assign_err in _LOTE_STRICT_ERRORS:
        pre_skips = list(pre_skips) + [
            _merge_skip_line(
                id_pago,
                assign_err,
                creditos_seleccionados=", ".join(
                    str(r.get("credito_digits") or r.get("credito_label") or "")
                    for r in group_rows
                ),
            )
        ]
        return [], pre_skips

    if credit_items_cover_expected_creditos(
        group_rows, credit_items
    ) and credit_items_have_single_asiento_each(credit_items):
        logger.info(
            "merge lote fallback: id_pago=%s err=%s (un asiento por crédito prevalidado)",
            id_pago,
            assign_err,
        )
        return credit_items, pre_skips

    pre_skips = list(pre_skips) + [
        _merge_skip_line(
            id_pago,
            assign_err,
            creditos_seleccionados=", ".join(
                str(r.get("credito_digits") or r.get("credito_label") or "")
                for r in group_rows
            ),
        )
    ]
    return [], pre_skips


def _norm_asiento_path(path: str) -> str:
    return str(path or "").strip().strip("/").replace("\\", "/")


async def _parse_asiento_candidate_cached(
    graph: GraphApiPort,
    site_id: str,
    drive_id: str,
    path: str,
    credit: str,
    cache: dict[str, AsientoCandidate | CandidateParseFailure],
) -> AsientoCandidate | CandidateParseFailure:
    key = _norm_asiento_path(path).casefold()
    if key in cache:
        return cache[key]

    def _fail(stage: str, exc: BaseException) -> CandidateParseFailure:
        err = f"{type(exc).__name__}: {exc}"[:300]
        logger.warning(
            "asiento parse failed path=%s credit=%s stage=%s err=%s",
            path,
            credit,
            stage,
            err,
        )
        rec = CandidateParseFailure(
            path=_norm_asiento_path(path),
            credit=str(credit or "").strip(),
            stage=stage,
            error=err,
        )
        cache[key] = rec
        return rec

    try:
        raw = await _graph_download_by_path(graph, site_id, drive_id, path)
    except Exception as exc:
        return _fail("download", exc)
    digest = hashlib.sha256(raw).hexdigest()
    try:
        from app.application.sharepoint_resolution import encode_graph_drive_path

        encoded = encode_graph_drive_path(path)
        meta = await graph.get(
            f"/sites/{site_id}/drives/{drive_id}/root:/{encoded}:"
        )
        if not isinstance(meta, dict):
            raise TypeError("metadata Graph no es un objeto")
    except Exception as exc:
        return _fail("metadata", exc)
    etag = str(meta.get("eTag") or meta.get("etag") or "")
    ctag = str(meta.get("cTag") or meta.get("ctag") or "")
    try:
        text = extract_text_from_pdf(raw)
    except PdfTextNotExtractableError as exc:
        return _fail("pdf_text", exc)
    except Exception as exc:
        return _fail("pdf_text", exc)
    try:
        event = parse_accounting_text(
            text,
            {
                "id_pago": "",
                "cliente": "",
                "credito": credit,
                "asiento_pdf_path": path,
            },
        )
    except AccountingParseError as exc:
        return _fail("parser", exc)
    except Exception as exc:
        return _fail("parser", exc)
    cand = AsientoCandidate(
        path=_norm_asiento_path(path),
        credit=str(credit or "").strip(),
        valor_pagado_cliente=float(event.valor_pagado_cliente or 0),
        sha256=digest,
        etag=etag,
        ctag=ctag,
        comprobante=str(event.comprobante or ""),
        fecha_asiento=event.fecha_asiento,
        capital=float(event.capital or 0),
        intereses=float(event.intereses or 0),
        mora=float(event.mora or 0),
        retenciones=float(event.retenciones or 0),
        numero_asiento=str(event.numero_asiento or ""),
    )
    cache[key] = cand
    return cand


async def _resolve_lote_asiento_assignment(
    graph: GraphApiPort,
    site_id: str,
    drive_id: str,
    staged: list[tuple[str, str, list[dict[str, Any]], list[dict[str, Any]], list[str]]],
):
    """Parsea PDFs una vez y asigna conjuntos disjuntos por ID Pago (monto canónico F-01)."""
    cache: dict[str, AsientoCandidate | CandidateParseFailure] = {}
    candidates: list[AsientoCandidate] = []
    failures: list[CandidateParseFailure] = []
    targets: list[IdPagoTarget] = []
    seen_cand: set[str] = set()

    for id_pago, tipo_aplicacion, group_rows, credit_items, _skips in staged:
        _cli, monto, _fecha, creditos = _group_meta_from_rows(
            group_rows, tipo_aplicacion=tipo_aplicacion
        )
        credit_set = frozenset(
            str(c).strip()
            for c in (
                list(creditos)
                + [str(it.get("credito") or "").strip() for it in credit_items]
            )
            if str(c).strip()
        )
        targets.append(
            IdPagoTarget(
                id_pago=id_pago,
                monto_banco=float(monto or 0),
                credits=credit_set,
            )
        )
        for item in credit_items:
            credit = str(item.get("credito") or "").strip()
            for p in item.get("asiento_pdf_paths") or []:
                nk = _norm_asiento_path(p).casefold()
                if nk in seen_cand:
                    continue
                seen_cand.add(nk)
                parsed = await _parse_asiento_candidate_cached(
                    graph, site_id, drive_id, p, credit, cache
                )
                if isinstance(parsed, CandidateParseFailure):
                    failures.append(parsed)
                else:
                    candidates.append(parsed)

    return assign_asientos_unique(
        targets, candidates, parse_failures=failures
    )


def _apply_assignment_to_credit_items(
    credit_items: list[dict[str, Any]],
    assigned_paths: tuple[str, ...],
    fingerprints: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    want = {_norm_asiento_path(p).casefold() for p in assigned_paths}
    out: list[dict[str, Any]] = []
    for item in credit_items:
        row = dict(item)
        kept = [
            p
            for p in (row.get("asiento_pdf_paths") or [])
            if _norm_asiento_path(p).casefold() in want
        ]
        row["asiento_pdf_paths"] = kept
        row["asiento_pdf_path"] = kept[0] if kept else ""
        fps = [
            fp
            for fp in fingerprints
            if _norm_asiento_path(str(fp.get("path") or "")).casefold() in want
            and (
                not str(fp.get("credit") or "").strip()
                or str(fp.get("credit") or "").strip() == str(row.get("credito") or "").strip()
            )
        ]
        row["asiento_assignment"] = fps
        if kept:
            out.append(row)
    return out


async def _upload_merge_manifest(
    graph: GraphApiPort,
    site_id: str,
    drive_id: str,
    *,
    bank_code: str,
    report_date_iso: str,
    payload: dict[str, Any],
    process_id: str | None = None,
) -> str:
    from app.application.services.dated_artifact_layout import (
        ensure_parent_folders,
        join_dated_artifact_path,
        short_process_id,
    )

    folder = _merge_logs_folder_relative()
    id8 = short_process_id(process_id or "")
    name = f"merge_manifest_{bank_code}_{report_date_iso}_{id8}.json"
    rel = join_dated_artifact_path(folder, report_date_iso, name)
    await ensure_parent_folders(graph, site_id, drive_id, rel)
    enc = encode_graph_drive_path(rel)
    body = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
    await graph.put_bytes(
        f"/sites/{site_id}/drives/{drive_id}/root:/{enc}:/content",
        body,
        content_type="application/json",
    )
    return rel


async def merge_composite_validado_pdfs(
    graph: GraphApiPort,
    *,
    force_rebuild: bool = False,
    bank_code: str | None = None,
    historical_file_path: str | None = None,
    email_pdf_path: str | None = None,
    job_id: str | None = None,
) -> MergeCompositeValidadoPdfsResult:
    estado = os.getenv("GRAPH_VALIDAR_EXTRACTO_ESTADO_CONTAINS", "VALIDAR").strip()
    if not estado:
        estado = "VALIDAR"

    from app.application.use_cases.payment_validation_process_control import (
        read_process_control_snapshot,
        resolve_process_control_path_for_bank,
        update_process_control_row2,
        utc_now_iso,
        validate_bank_code,
    )
    from app.application.use_cases.setup_merge_control_workbook import build_payment_validation_process_key

    manual_hist = bool((historical_file_path or "").strip())
    manual_email = bool((email_pdf_path or "").strip())

    bank_code_source = "body" if (bank_code or "").strip() else "auto_detected"
    bank_code = (bank_code or "").strip() or None
    if bank_code:
        validate_bank_code(bank_code)

    ctx = await resolve_sharepoint_from_env(graph)
    site_id = ctx["site_id"]
    drive_id = ctx["drive_id"]

    ready_banks_detected: list[str] = []
    historico_rel = (historical_file_path or "").strip().strip("/")
    email_rel = (email_pdf_path or "").strip().strip("/")

    if not bank_code and not (manual_hist or manual_email):
        detected, ready = await _auto_detect_bank_ready_for_merge(graph, site_id, drive_id)
        ready_banks_detected = list(ready)
        if not detected:
            if not ready:
                raise ValueError("NO_READY_PROCESS")
            raise ValueError("MULTIPLE_READY_PROCESSES|" + ",".join(ready))
        bank_code = detected
        bank_code_source = "auto_detected"
        if not ready:
            raise ValueError("NO_READY_PROCESS")

    if not bank_code:
        # If paths were provided but bank_code missing, infer by substrings (best-effort).
        low = f"{historico_rel}/{email_rel}".lower()
        if "banco_bancolombia" in low:
            bank_code = BANK_CODE_BANCOLOMBIA
            bank_code_source = "body"
        else:
            bank_code = BANK_CODE_BOGOTA
            bank_code_source = "body"

    validate_bank_code(bank_code)
    bank_name = resolve_bank_display_name(bank_code)
    process_control_file_path = resolve_process_control_path_for_bank(bank_code).strip().strip("/")

    snap = await read_process_control_snapshot(graph, site_id, drive_id, bank_code=bank_code)
    process_key = (snap.process_key or "").strip()
    if not process_key:
        process_key = build_payment_validation_process_key(bank_code, today_colombia_iso())

    # Idempotencia: si ya consolidado, manifest COMPLETE y force_rebuild=false.
    prev_manifest: dict[str, Any] | None = None
    prev_manifest_path = (snap.merge_manifest_path or "").strip().strip("/")
    if prev_manifest_path:
        try:
            prev_raw = await _graph_download_by_path(
                graph, site_id, drive_id, prev_manifest_path
            )
            prev_manifest = json.loads(prev_raw.decode("utf-8"))
        except Exception:
            prev_manifest = None

    if (
        not force_rebuild
        and (snap.process_key or "").strip() == process_key
        and (snap.estado_proceso or "").strip() == "CONSOLIDADO"
        and prev_manifest_path
        and (snap.merge_idempotency_key or "").strip()
        and prev_manifest is not None
        and assess_manifest_completeness(prev_manifest).get("eligible_for_dry_run")
    ):
        folder_url, folder_rel = _consolidation_folder_from_manifest(prev_manifest)
        return MergeCompositeValidadoPdfsResult(
            report_date_iso="",
            historico_excel_path=snap.historical_file_path,
            estado_linea_contains=estado,
            email_pdf_used=snap.email_pdf_path,
            outputs=(),
            skipped=(),
            merge_control_file_path=process_control_file_path,
            merge_control_updated=False,
            merge_control_status="CONSOLIDADO",
            outputs_count=0,
            skipped_count=0,
            merge_manifest_path=prev_manifest_path,
            manifest_status=MANIFEST_STATUS_COMPLETE,
            eligible_for_dry_run=True,
            bank_code=bank_code,
            bank_name=bank_name,
            bank_code_source=bank_code_source,
            ready_banks_detected=tuple(ready_banks_detected),
            process_key=process_key,
            process_control_file_path=process_control_file_path,
            process_control_updated=False,
            process_control_estado="CONSOLIDADO",
            historical_file_source="control",
            email_pdf_source="control",
            already_merged=True,
            file_action="reused",
            merge_idempotency_key=snap.merge_idempotency_key,
            pdf_created=False,
            pdf_reused=True,
            already_consolidated=True,
            force_rebuild_used=force_rebuild,
            consolidation_folder_web_url=folder_url,
            consolidation_folder_relative_path=folder_rel,
        )

    # Resolver insumos: body override > control.
    if not historico_rel:
        historico_rel = (snap.historical_file_path or "").strip().strip("/")
    if not email_rel:
        email_rel = (snap.email_pdf_path or "").strip().strip("/")

    if not historico_rel:
        raise ValueError("missing_historical_file_path")
    if not email_rel:
        raise ValueError("missing_email_pdf_path")
    if not (manual_hist or manual_email):
        if (snap.estado_proceso or "").strip() not in MERGE_RUNNABLE_STATES or not snap.is_active:
            raise ValueError("control_not_ready_for_merge")

    consolidando_started = False
    try:
        await update_process_control_row2(
            graph,
            site_id,
            drive_id,
            bank_code=bank_code,
            updates={
                "EstadoProceso": "CONSOLIDANDO",
                "LastStepStatus": "RUNNING",
                "LastUpdatedAtProceso": utc_now_iso(),
            },
        )
        consolidando_started = True

        # Reporte del banco para fecha mínima (por banco).
        site_search = os.getenv("GRAPH_SHAREPOINT_SITE_SEARCH", "").strip()
        drive_name = os.getenv("GRAPH_SHAREPOINT_DRIVE_NAME", "").strip()
        report_path = resolve_bank_report_path(bank_code)
        if not report_path:
            raise ValueError("missing_sharepoint_folder")
        report_info = await resolve_sharepoint_path(graph, site_search, drive_name, report_path)
        report_bytes = await graph.get_bytes(
            f"/sites/{report_info['site_id']}/drives/{report_info['drive_id']}/root:/{report_info['path_encoded']}:/content"
        )
        report_d_bank, _, _ = _parse_bank_report_table_and_min_date(report_bytes)
        # Misma regla que Notify: no reescribir el ciclo con el mínimo de fechas del Excel.
        report_d = _process_date_from_process_key(process_key) or report_d_bank
        iso = report_d.isoformat()

        hist_bytes = await _graph_download_by_path(graph, site_id, drive_id, historico_rel)
        email_bytes = await _graph_download_by_path(graph, site_id, drive_id, email_rel)

        wb = load_workbook(filename=BytesIO(hist_bytes), data_only=True)
        try:
            all_rows = read_validated_application_rows(wb)
            application_groups = group_rows_by_id_pago(all_rows)
        finally:
            closer = getattr(wb, "close", None)
            if callable(closer):
                closer()

        if not application_groups:
            raise ValueError(
                f"No hay filas validadas (Validar Pago=SI) para merge en el histórico {historico_rel!r}."
            )

        out_folder = resolve_merge_output_folder_path()

        # El sitio de Contabilidad es opcional: sin él, el consolidado sigue en Operaciones.
        accounting_context: dict[str, str] | None = None
        accounting_resolver: AccountingDestinationResolver | None = None
        if accounting_site_is_configured():
            accounting_context = await resolve_accounting_context(graph)
            accounting_resolver = AccountingDestinationResolver(
                graph,
                accounting_context["site_id"],
                accounting_context["drive_id"],
            )

        outputs: list[MergeCompositePdfOutput] = []
        incomplete_groups: list[dict[str, Any]] = []
        skipped: list[str] = []
        out_name_tallies: dict[str, int] = {}
        payment_outputs_count = 0
        abono_outputs_count = 0
        payment_skipped_count = 0
        abono_skipped_count = 0
        payment_incomplete_groups_count = 0
        abono_incomplete_groups_count = 0
        failed_groups_count = 0
        extracts_not_required_count = sum(
            1
            for _id, grp in application_groups.items()
            if not any(bool(r.get("include_extract_in_composite", r.get("requiere_extracto"))) for r in grp)
        )
        expected_by_id_pago: dict[str, tuple[str, ...]] = {}

        work_queue: list[tuple[str, str, list[dict[str, Any]]]] = []
        for id_pago, group_rows in sorted(application_groups.items(), key=lambda x: x[0]):
            # Canónico documental del grupo (contadores); naming usa merge_name_token_for_tipos.
            canons = {
                str(r.get("tipo_aplicacion") or TipoAplicacion.PAGO.value).strip().upper()
                for r in group_rows
            }
            if canons == {TipoAplicacion.ABONO.value}:
                tipo_aplicacion = TipoAplicacion.ABONO.value
            else:
                tipo_aplicacion = TipoAplicacion.PAGO.value
            work_queue.append((id_pago, tipo_aplicacion, group_rows))

        staged: list[
            tuple[str, str, list[dict[str, Any]], list[dict[str, Any]], list[str]]
        ] = []
        for id_pago, tipo_aplicacion, group_rows in work_queue:
            is_abono = tipo_aplicacion == TipoAplicacion.ABONO.value
            if is_abono:
                credit_items, pre_skips = await _prevalidate_abono_id_pago_group(
                    graph, site_id, drive_id, id_pago, group_rows
                )
            else:
                credit_items, pre_skips = await _prevalidate_id_pago_group(
                    graph, site_id, drive_id, id_pago, group_rows
                )
            staged.append((id_pago, tipo_aplicacion, group_rows, credit_items, pre_skips))

        lote_assignment = None
        if not _staged_asiento_paths_globally_unambiguous(staged):
            lote_assignment = await _resolve_lote_asiento_assignment(
                graph, site_id, drive_id, staged
            )

        for id_pago, tipo_aplicacion, group_rows, credit_items, pre_skips in staged:
            is_abono = tipo_aplicacion == TipoAplicacion.ABONO.value
            name_token = merge_name_token_for_tipos(
                [r.get("tipo_aplicacion_original") for r in group_rows]
            )
            credit_items, pre_skips = _apply_lote_assignment_or_fallback(
                id_pago=id_pago,
                group_rows=group_rows,
                credit_items=credit_items,
                pre_skips=pre_skips,
                lote_assignment=lote_assignment,
            )
            assigned_fps: list[dict[str, Any]] = []
            if lote_assignment is not None and not lote_assignment.errors.get(id_pago):
                assigned_fps = list(lote_assignment.fingerprints.get(id_pago) or [])

            validation = validate_merge_group_completeness(
                id_pago=id_pago,
                tipo_aplicacion=tipo_aplicacion,
                group_rows=group_rows,
                credit_items=credit_items,
                pre_skips=pre_skips,
            )
            expected_creditos = validation.group.expected_creditos
            expected_by_id_pago[id_pago] = expected_creditos

            if not validation.is_complete:
                if pre_skips:
                    skipped.extend(pre_skips)
                incomplete_groups.append(
                    incomplete_group_record(validation, pre_skips=pre_skips)
                )
                if is_abono:
                    abono_incomplete_groups_count += 1
                    abono_skipped_count += 1
                else:
                    payment_incomplete_groups_count += 1
                    payment_skipped_count += 1
                continue

            client_meta, monto_meta, fecha_meta, _creditos_meta_unused = _group_meta_from_rows(
                group_rows, tipo_aplicacion=tipo_aplicacion
            )
            creditos_meta = expected_creditos
            all_extract_paths = [
                ep for item in credit_items for ep in (item.get("extracto_pdf_paths") or [])
            ]
            credit_tokens = _credit_tokens_ordered_for_rows(group_rows, all_extract_paths)
            if not credit_tokens:
                credit_tokens = [str(item.get("credito") or "") for item in credit_items]
            credit_for_filename = ", ".join(credit_tokens)

            client_from_cells = client_meta
            first_extract = all_extract_paths[0] if all_extract_paths else ""
            client_display = client_from_cells or _client_folder_before_credit(first_extract)
            if not client_display:
                client_display = "CLIENTE"

            # Naming: Fecha banco del ID Pago (no fecha del proceso).
            naming_date = _naming_date_for_group(group_rows, fecha_meta, report_d)
            out_base = _merge_composite_output_basename(
                naming_date,
                client_display,
                credit_for_filename,
                bank_code=bank_code,
                tipo_aplicacion=tipo_aplicacion,
                name_token=name_token,
            )
            try:
                target = await _resolve_output_target(
                    accounting_resolver=accounting_resolver,
                    accounting_context=accounting_context,
                    operations_site_id=site_id,
                    operations_drive_id=drive_id,
                    operations_folder=out_folder,
                    fecha_banco=fecha_meta,
                    fallback_date=report_d,
                    bank_code=bank_code,
                )
            except AccountingDestinationError as exc:
                failed_groups_count += 1
                skipped.append(
                    _merge_skip_line(
                        id_pago,
                        exc.code,
                        names_seen=exc.message[:800],
                        tipo_aplicacion=tipo_aplicacion,
                        creditos_seleccionados=", ".join(expected_creditos),
                    )
                )
                if is_abono:
                    abono_skipped_count += 1
                else:
                    payment_skipped_count += 1
                continue

            base_rel = f"{target.folder}/{out_base}".replace("//", "/")
            already_exists = await _drive_item_exists(
                graph, target.site_id, target.drive_id, base_rel
            )

            group_policy = _row_application_policy(
                group_rows[0] if group_rows else {},
                default_canonical=tipo_aplicacion,
            )
            group_include_extract = any(
                bool(r.get("include_extract_in_composite", r.get("requiere_extracto")))
                for r in group_rows
            )
            group_requiere_extracto = group_include_extract
            output_meta = dict(
                tipo_aplicacion=group_policy.tipo_aplicacion_canonica,
                requiere_extracto=group_policy.requiere_extracto,
                policy=group_policy,
                monto_banco=monto_meta,
                fecha_banco=fecha_meta,
                creditos_seleccionados=creditos_meta,
                asiento_assignment=assigned_fps,
            )

            legacy_incomplete_output = False
            can_reuse = False
            if already_exists and not force_rebuild:
                if prev_manifest is None:
                    can_reuse = True
                else:
                    can_reuse = group_can_reuse_existing_pdf(
                        id_pago=id_pago,
                        expected_creditos=expected_creditos,
                        prev_manifest=prev_manifest,
                    )
                if not can_reuse:
                    legacy_incomplete_output = True
            if can_reuse:
                labels_preview: list[str] = [f"email:{email_rel}"]
                for item in sorted(credit_items, key=lambda x: str(x.get("credito") or "")):
                    for a in item.get("asiento_pdf_paths") or []:
                        labels_preview.append(f"asiento:{a}")
                    if group_requiere_extracto:
                        for ep in item.get("extracto_pdf_paths") or []:
                            labels_preview.append(f"extracto:{ep}")
                file_url, folder_url, folder_rel = await _resolve_merge_output_share_links(
                    graph,
                    target.site_id,
                    target.drive_id,
                    output_relative_path=base_rel,
                )
                outputs.append(
                    _merge_output_record(
                        id_pago=id_pago,
                        output_relative_path=base_rel,
                        bytes_written=0,
                        sources_summary="already_consolidated | " + " | ".join(labels_preview[1:]),
                        cliente=client_display,
                        credito=credit_for_filename,
                        email_pdf_path=email_rel,
                        credit_items=credit_items,
                        output_web_url=file_url,
                        output_folder_web_url=folder_url,
                        output_folder_relative_path=folder_rel,
                        **output_meta,
                    )
                )
                if is_abono:
                    abono_outputs_count += 1
                else:
                    payment_outputs_count += 1
                logger.info(
                    "merge_composite_validado: id_pago=%s ya consolidado en %s",
                    id_pago,
                    base_rel,
                )
                continue

            parts, labels, build_skips = await _build_consolidated_pdf_parts(
                graph,
                site_id,
                drive_id,
                id_pago,
                email_bytes,
                email_rel,
                credit_items,
                include_extracts=group_requiere_extracto,
            )
            if build_skips:
                skipped.extend(build_skips)
                failed_groups_count += 1
                if is_abono:
                    abono_skipped_count += 1
                else:
                    payment_skipped_count += 1
                continue

            merged = _merge_pdf_bytes(parts)
            if not merged:
                failed_groups_count += 1
                skipped.append(
                    _merge_skip_line(
                        id_pago,
                        "consolidated_pdf_empty",
                        tipo_aplicacion=tipo_aplicacion,
                        creditos_seleccionados=", ".join(expected_creditos),
                    )
                )
                if is_abono:
                    abono_skipped_count += 1
                else:
                    payment_skipped_count += 1
                continue
            out_base = _merge_composite_output_basename(
                naming_date,
                client_display,
                credit_for_filename,
                bank_code=bank_code,
                tipo_aplicacion=tipo_aplicacion,
                name_token=name_token,
            )
            out_name = _allocate_duplicate_pdf_name(out_base, out_name_tallies)
            out_rel = f"{target.folder}/{out_name}".replace("//", "/")
            if already_exists and force_rebuild:
                out_rel = base_rel
            enc = encode_graph_drive_path(out_rel)
            try:
                upload_resp = await graph.put_bytes(
                    f"/sites/{target.site_id}/drives/{target.drive_id}/root:/{enc}:/content",
                    merged,
                    content_type="application/pdf",
                )
            except Exception as exc:
                skipped.append(
                    _merge_skip_line(
                        id_pago,
                        "consolidated_upload_failed",
                        extracto_path=first_extract or "-",
                        names_seen=str(exc)[:800],
                        tipo_aplicacion=tipo_aplicacion,
                        requiere_extracto="NO" if is_abono else "SI",
                        creditos_seleccionados=", ".join(expected_creditos),
                    )
                )
                failed_groups_count += 1
                if is_abono:
                    abono_skipped_count += 1
                else:
                    payment_skipped_count += 1
                continue

            sources_summary = " | ".join(labels)
            if legacy_incomplete_output:
                sources_summary = f"replaced_incomplete | {sources_summary}"
            file_url, folder_url, folder_rel = await _resolve_merge_output_share_links(
                graph,
                target.site_id,
                target.drive_id,
                output_relative_path=out_rel,
                upload_response=upload_resp if isinstance(upload_resp, dict) else None,
            )
            outputs.append(
                _merge_output_record(
                    id_pago=id_pago,
                    output_relative_path=out_rel,
                    bytes_written=len(merged),
                    sources_summary=sources_summary,
                    cliente=client_display,
                    credito=credit_for_filename,
                    email_pdf_path=email_rel,
                    credit_items=credit_items,
                    output_web_url=file_url,
                    output_folder_web_url=folder_url,
                    output_folder_relative_path=folder_rel,
                    **output_meta,
                )
            )
            if is_abono:
                abono_outputs_count += 1
            else:
                payment_outputs_count += 1

            logger.info(
                "merge_composite_validado: subido %s (%s bytes) id_pago=%s force_rebuild=%s",
                out_rel,
                len(merged),
                id_pago,
                force_rebuild,
            )

        oc = len(outputs)
        sc = len(skipped)
        incomplete_groups_count = len(incomplete_groups)
        complete_groups_count = oc
        merge_control_updated = True

        if incomplete_groups_count == 0 and oc > 0 and failed_groups_count == 0:
            final_status = "CONSOLIDADO"
            manifest_status = MANIFEST_STATUS_COMPLETE
            eligible_for_dry_run = True
        else:
            final_status = "MERGE_PARCIAL"
            manifest_status = MANIFEST_STATUS_PARTIAL
            eligible_for_dry_run = False

        manifest_path = ""
        try:
            manifest_payload: dict[str, Any] = {
                "report_date_iso": iso,
                "historico_excel_path": historico_rel,
                "email_pdf_used": email_rel,
                "merge_control_status": final_status,
                "manifest_status": manifest_status,
                "eligible_for_dry_run": eligible_for_dry_run,
                "complete_groups_count": complete_groups_count,
                "incomplete_groups_count": incomplete_groups_count,
                "failed_groups_count": failed_groups_count,
                "payment_outputs_count": payment_outputs_count,
                "abono_outputs_count": abono_outputs_count,
                "payment_incomplete_groups_count": payment_incomplete_groups_count,
                "abono_incomplete_groups_count": abono_incomplete_groups_count,
                "payment_skipped_count": payment_skipped_count,
                "abono_skipped_count": abono_skipped_count,
                "extracts_not_required_count": extracts_not_required_count,
                "outputs": [
                    _manifest_output_dict(
                        o,
                        expected_creditos=expected_by_id_pago.get(
                            o.id_pago, o.creditos_seleccionados
                        ),
                    )
                    for o in outputs
                ],
                "incomplete_groups": incomplete_groups,
                "skipped": list(skipped),
            }
            from app.application.use_cases.setup_merge_control_workbook import (
                process_id_from_process_key,
            )

            manifest_path = await _upload_merge_manifest(
                graph,
                site_id,
                drive_id,
                bank_code=bank_code,
                report_date_iso=iso,
                payload=manifest_payload,
                process_id=process_id_from_process_key(process_key) or None,
            )
            logger.info("merge_composite_validado: manifest %s", manifest_path)
        except Exception as man_exc:
            logger.warning("merge_composite_validado: no se pudo subir manifest: %s", man_exc)

        # F-04: CONSOLIDADO exige manifest durable (entrada de Dry-run/Apply).
        if final_status == "CONSOLIDADO" and not str(manifest_path or "").strip():
            logger.error(
                "merge_composite_validado: PDF/grupos OK pero manifest ausente → ERROR_MERGE"
            )
            final_status = "ERROR_MERGE"
            manifest_status = MANIFEST_STATUS_PARTIAL
            eligible_for_dry_run = False

        now_iso = utc_now_iso()
        control_updates: dict[str, Any] = {
            "ProcessKey": process_key,
            "ProcessDate": iso,
            "BankCode": bank_code,
            "BankName": bank_name,
            "HistoricalFilePath": historico_rel,
            "EmailPdfPath": email_rel,
            "MergeManifestPath": manifest_path,
            "EstadoProceso": final_status,
            "IsActive": True,
            "MergeIdempotencyKey": process_key if final_status == "CONSOLIDADO" else "",
            "MergeJobId": job_id or "",
            "MergeOutputCount": int(oc),
            "MergeSkippedCount": int(sc),
            "LastCompletedStep": "MERGE",
            "LastStepStatus": "COMPLETED" if final_status == "CONSOLIDADO" else (
                "FAILED" if final_status == "ERROR_MERGE" else "COMPLETED_WITH_WARNINGS"
            ),
            "LastStepErrorCode": (
                "missing_merge_manifest"
                if final_status == "ERROR_MERGE" and not str(manifest_path or "").strip()
                else ""
            ),
            "LastUpdatedAtProceso": now_iso,
        }
        # Consolidado OK: invalidar intento de amort fallido para no rehidratar
        # el modal/banner en fase 4 sin un nuevo clic en Amortizar.
        if final_status == "CONSOLIDADO":
            control_updates["LastAmortizationAttemptJson"] = ""
        await update_process_control_row2(
            graph,
            site_id,
            drive_id,
            bank_code=bank_code,
            updates=control_updates,
        )

        file_action, pdf_created, pdf_reused, already_consolidated_flag = _merge_pdf_observability(
            outputs, final_status=final_status
        )
        consol_folder_url, consol_folder_rel = _first_consolidation_folder_from_outputs(outputs)

        return MergeCompositeValidadoPdfsResult(
            report_date_iso=iso,
            historico_excel_path=historico_rel,
            estado_linea_contains=estado,
            email_pdf_used=email_rel,
            outputs=tuple(outputs),
            skipped=tuple(skipped),
            merge_control_file_path=process_control_file_path,
            merge_control_updated=True,
            merge_control_status=final_status,
            outputs_count=oc,
            skipped_count=sc,
            merge_manifest_path=manifest_path,
            bank_code=bank_code,
            bank_name=bank_name,
            bank_code_source=bank_code_source,
            ready_banks_detected=tuple(ready_banks_detected),
            process_key=process_key,
            process_control_file_path=process_control_file_path,
            process_control_updated=True,
            process_control_estado=final_status,
            historical_file_source="body" if manual_hist else "control",
            email_pdf_source="body" if manual_email else "control",
            already_merged=False,
            file_action=file_action,
            merge_idempotency_key=process_key if final_status == "CONSOLIDADO" else "",
            pdf_created=pdf_created,
            pdf_reused=pdf_reused,
            already_consolidated=already_consolidated_flag,
            force_rebuild_used=force_rebuild,
            payment_outputs_count=payment_outputs_count,
            abono_outputs_count=abono_outputs_count,
            payment_skipped_count=payment_skipped_count,
            abono_skipped_count=abono_skipped_count,
            extracts_not_required_count=extracts_not_required_count,
            manifest_status=manifest_status,
            eligible_for_dry_run=eligible_for_dry_run,
            incomplete_groups_count=incomplete_groups_count,
            payment_incomplete_groups_count=payment_incomplete_groups_count,
            abono_incomplete_groups_count=abono_incomplete_groups_count,
            complete_groups_count=complete_groups_count,
            failed_groups_count=failed_groups_count,
            consolidation_folder_web_url=consol_folder_url,
            consolidation_folder_relative_path=consol_folder_rel,
        )

    except Exception:
        if consolidando_started:
            try:
                await update_process_control_row2(
                    graph,
                    site_id,
                    drive_id,
                    bank_code=bank_code,
                    updates={
                        "EstadoProceso": "ERROR_MERGE",
                        "LastCompletedStep": "MERGE",
                        "LastStepStatus": "FAILED",
                        "LastStepErrorCode": "ERROR_MERGE",
                        "LastUpdatedAtProceso": utc_now_iso(),
                    },
                )
            except Exception:
                logger.exception("merge_composite_validado: no se pudo escribir ERROR_MERGE en el control")
        raise
