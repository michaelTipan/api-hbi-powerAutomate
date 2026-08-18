import hashlib
import io
import json
import logging
import os
import re
import unicodedata
import uuid
import asyncio
from datetime import date, datetime
from typing import Any

import httpx
import openpyxl
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

from app.application.services.payment_helpers import (
    _normalize_str,
    extract_client_from_bank_row,
    extract_credit_id_from_extract_pdf,
    extract_fecha_limite_pago_from_pdf,
    extract_total_a_pagar_from_pdf,
    filter_amortization_excel_filenames,
    find_best_amortization_table,
    parse_bank_amount,
    parse_bank_date,
    parse_statement_name,
)
from app.application.services.extract_selection import (
    choose_extract_as_of_bank_date,
)
from app.application.services.extract_snapshot_parser import (
    ParserStatus,
    RightPanelRole,
    evidence_from_graph_item,
    parse_extract_snapshot,
    parse_frozen_evidence_from_meta_sheet,
    prefer_frozen_extract_candidate,
)
from app.application.services.review_schema import (
    AplicacionPagosCols,
    ErroresCols,
    ReviewSheets,
    ValidarPago,
    normalize_credito_digits,
)
from app.application.services.review_workbook_v4 import (
    build_aplicacion_pagos_row,
    build_review_workbook_v4_bytes,
)
from app.application.sharepoint_resolution import (
    encode_graph_drive_path,
    require_operations_site_config,
    resolve_sharepoint_path,
)
from app.domain.ports.graph import GraphApiPort

logger = logging.getLogger(__name__)

def _candidate_extract_fields(
    statement_bytes: bytes,
    statement_item: dict[str, Any],
    statement_path: str,
    *,
    site_id: str | None = None,
    drive_id: str | None = None,
    fallback_valor: float | None = None,
    fallback_fecha: Any = None,
) -> dict[str, Any]:
    """Parsea ExtractSnapshot y congela evidencia; fail-closed en panel derecho."""
    evidence = evidence_from_graph_item(
        statement_item,
        path=statement_path.replace("\\", "/"),
        site_id=site_id,
        drive_id=drive_id,
        fecha_limite=fallback_fecha if hasattr(fallback_fecha, "isoformat") else None,
    )
    snap = parse_extract_snapshot(statement_bytes, evidence=evidence)
    valor = snap.valor_obligacion_actual
    if valor is None:
        valor = fallback_valor
    fields: dict[str, Any] = {
        "valor_extracto": valor,
        "valor_obligacion_actual": valor,
        "saldo_vencido_visible": snap.saldo_vencido_visible,
        "right_panel_role": snap.right_panel_role.value,
        "parser_status": snap.parser_status.value,
        "extract_evidence": snap.evidence.to_meta_dict() if snap.evidence else evidence.to_meta_dict(),
    }
    if snap.fecha_limite is not None:
        fields["fecha_limite_snapshot"] = snap.fecha_limite
    if snap.right_panel_role == RightPanelRole.AMBIGUO:
        fields["observacion_panel"] = "Saldo vencido ambiguo: revisar extracto (no se asume 0)."
    return fields

def _build_content_endpoint(site_id: str, drive_id: str, file_path: str) -> str:
    return f"/sites/{site_id}/drives/{drive_id}/root:/{encode_graph_drive_path(file_path)}:/content"

def _normalize_header(value: Any) -> str:
    return _normalize_str(str(value or "")).replace(" ", "")

def _find_header_index(headers: list[Any], aliases: list[str]) -> int:
    normalized_headers = [_normalize_header(header) for header in headers]
    normalized_aliases = {_normalize_header(alias) for alias in aliases}
    for index, header in enumerate(normalized_headers):
        if header in normalized_aliases:
            return index
    return -1

def _is_bank_header_row(row: tuple[Any, ...] | list[Any]) -> bool:
    texts = [_normalize_str(str(value)) if value else "" for value in row]
    return "fecha" in texts and ("credito" in texts or "monto" in texts)

def _is_processable_bank_row(row: list[Any], col_map: dict[str, int], process_date: date) -> bool:
    if not row or not any(value is not None and str(value).strip() for value in row):
        return False
    if _is_bank_header_row(row):
        return False
    fecha_idx = col_map.get("fecha", -1)
    monto_idx = col_map.get("credito", -1)
    if fecha_idx < 0 or monto_idx < 0:
        return False
    fecha_raw = row[fecha_idx] if fecha_idx < len(row) else None
    monto_raw = row[monto_idx] if monto_idx < len(row) else None
    if _is_blank(fecha_raw) and _is_blank(monto_raw):
        return False
    joined = " ".join(_normalize_str(str(value)) for value in row if value is not None)
    if "total" in joined and _is_blank(monto_raw):
        return False
    try:
        parse_bank_date(fecha_raw, process_date)
        parse_bank_amount(monto_raw)
    except (ValueError, TypeError, IndexError):
        return False
    return True

def _parse_bank_sheet_headers(
    bank_sheet: Any,
) -> tuple[dict[str, int], int, list[str], int]:
    """Headers bancarios HBI/original: Fecha, Monto/Credito, Concepto, Transaccion.

    Si el archivo ORIGINAL del banco trae «Tipo Aplicación», se IGNORA
    (nunca controla la lógica). La plantilla controlada por HBI ya no la incluye.
    """
    col_map: dict[str, int] = {}
    start_row = 2
    header_row_index = 0
    detected_headers: list[str] = []

    for row_index, row in enumerate(bank_sheet.iter_rows(values_only=True), 1):
        if not row:
            continue
        texts = [_normalize_str(str(value)) if value else "" for value in row]
        if "fecha" not in texts or ("credito" not in texts and "monto" not in texts):
            continue

        header_row_index = row_index
        detected_headers = [str(value).strip() if value is not None else "" for value in row]
        fecha_idx = texts.index("fecha")
        credito_idx = texts.index("credito") if "credito" in texts else texts.index("monto")
        concepto_idx = _find_header_index(list(row), ["Concepto", "concepto"])
        transaccion_idx = _find_header_index(list(row), ["Transacción", "Transaccion", "transaccion"])
        # Tipo Aplicación (si existe en Excel original del banco) → no se mapea.

        col_map = {
            "fecha": fecha_idx,
            "credito": credito_idx,
            "concepto": concepto_idx,
            "transaccion": transaccion_idx,
        }
        start_row = row_index + 1
        break

    if not col_map:
        raise ValueError("bank_headers_not_found")

    return col_map, start_row, detected_headers, header_row_index

def _collect_processable_bank_rows(
    bank_sheet: Any,
    col_map: dict[str, int],
    start_row: int,
    process_date: date,
) -> list[dict[str, Any]]:
    """Filas bancarias procesables sin Tipo Aplicacion (Generate neutro)."""
    processable_rows: list[dict[str, Any]] = []
    for row_index in range(start_row, bank_sheet.max_row + 1):
        row = [cell.value for cell in bank_sheet[row_index]]
        if not _is_processable_bank_row(row, col_map, process_date):
            continue
        concepto = row[col_map["concepto"]] if col_map["concepto"] >= 0 else ""
        transaccion = row[col_map["transaccion"]] if col_map["transaccion"] >= 0 else ""
        processable_rows.append(
            {
                "row_index": row_index,
                "row": row,
                "concepto": concepto,
                "transaccion": transaccion,
            }
        )
    return processable_rows

def _is_blank(value: Any) -> bool:
    return value is None or str(value).strip() == ""

def _parse_cell_date(value: Any) -> date | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y"):
            try:
                return datetime.strptime(text, fmt).date()
            except ValueError:
                continue
    return None

def _parse_cell_amount(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str) and value.strip():
        try:
            return parse_bank_amount(value)
        except ValueError:
            return None
    return None

def _score_sheet(worksheet: Any, client_name: str = "") -> int:
    score = 0
    ws_title = worksheet.title.lower()
    
    if client_name and _normalize_str(client_name) in _normalize_str(ws_title):
        score += 5
    if "amortiza" in ws_title or "tabla" in ws_title or "credito" in ws_title:
        score += 3
        
    for row in worksheet.iter_rows(min_row=1, max_row=15, values_only=True):
        if not any(row):
            continue
        row_str = " ".join([_normalize_str(str(v)) for v in row if v])
        for kw in ["cuota", "pagado", "dia", "mes", "ano", "fecha", "saldo", "kf", "ki"]:
            if kw in row_str:
                score += 1
    return score

def _extract_pending_installment(table_bytes: bytes, client_name: str = "") -> dict[str, Any]:
    if not table_bytes:
        raise ValueError("amortization_table_not_found")

    workbook = openpyxl.load_workbook(io.BytesIO(table_bytes), data_only=True)
    
    best_sheet = None
    best_score = -1
    for sheet_name in workbook.sheetnames:
        lower_name = sheet_name.lower()
        if "tasa" in lower_name or "hoja1" in lower_name or "hoja2" in lower_name:
            continue
            
        ws = workbook[sheet_name]
        score = _score_sheet(ws, client_name)
        if score > best_score:
            best_score = score
            best_sheet = ws
            
    if best_sheet is None or best_score == 0:
        raise ValueError("amortization_sheet_not_found")
        
    worksheet = best_sheet
    
    header_row_idx = -1
    headers = []
    best_header_score = -1
    
    for row_idx, row in enumerate(worksheet.iter_rows(min_row=1, max_row=15, values_only=True), 1):
        if not any(row):
            continue
        texts = [_normalize_str(str(v)).replace(" ", "") for v in row if v is not None]
        row_score = 0
        for text in texts:
            if text in ["ki", "cuota", "kf", "dia", "mes", "ano", "fechapago", "fechadepago", "valorpagado", "valorpagadocliente", "saldoacapital", "interesesdemora", "fechalimite"]:
                row_score += 1
        
        if row_score > best_header_score and row_score >= 2:
            best_header_score = row_score
            header_row_idx = row_idx
            headers = [cell for cell in row]
            
    if header_row_idx == -1:
        raise ValueError("pending_installment_not_found")
        
    due_index = _find_header_index(headers, ["Fecha límite", "Fecha limite"])
    day_index = _find_header_index(headers, ["dia", "día"])
    month_index = _find_header_index(headers, ["mes"])
    year_index = _find_header_index(headers, ["año", "ano"])
    
    pay_index = _find_header_index(headers, ["Fecha pago", "Fecha de pago"])
    total_paid_index = _find_header_index(headers, ["Total pagado", "Valor pagado cliente"])
    
    extract_value_index = _find_header_index(headers, ["Cuota"])
    if extract_value_index == -1:
        extract_value_index = _find_header_index(headers, ["Valor extracto", "Valor cuota base", "Total a pagar", "Valor cuota"])

    for row_idx, row in enumerate(worksheet.iter_rows(min_row=header_row_idx + 1, values_only=True), header_row_idx + 1):
        if not any(row):
            continue
            
        pay_value = row[pay_index] if pay_index >= 0 and pay_index < len(row) else None
        total_paid_value = row[total_paid_index] if total_paid_index >= 0 and total_paid_index < len(row) else None
        
        is_paid = False
        if pay_index != -1:
            is_paid = not _is_blank(pay_value)
        elif total_paid_index != -1:
            is_paid = not _is_blank(total_paid_value)
            
        if not is_paid:
            due_date = None
            if due_index != -1 and due_index < len(row):
                due_date = _parse_cell_date(row[due_index])
                
            if due_date is None and day_index != -1 and month_index != -1 and year_index != -1:
                try:
                    if not _is_blank(row[day_index]) and not _is_blank(row[month_index]) and not _is_blank(row[year_index]):
                        d = int(float(row[day_index]))
                        m = int(float(row[month_index]))
                        y = int(float(row[year_index]))
                        due_date = date(y, m, d)
                except (ValueError, TypeError):
                    pass
                    
            if due_date is None:
                continue
                
            value = None
            if extract_value_index != -1 and extract_value_index < len(row):
                value = _parse_cell_amount(row[extract_value_index])
                
            if value is None:
                continue
                
            return {
                "fecha_limite": due_date, 
                "valor_extracto": value,
                "row_number": row_idx,
                "sheet_name": worksheet.title,
                "header_row": header_row_idx
            }

    raise ValueError("pending_installment_not_found")

def _extract_last_payment_date_from_amortization(table_bytes: bytes, client_name: str = "") -> date | None:
    """
    Última fecha (máximo) encontrada en columna «Fecha pago» / «Fecha de pago» con valor parseable.
    None si no hay columna o no hay fechas fiables.
    """
    if not table_bytes:
        return None
    try:
        workbook = openpyxl.load_workbook(io.BytesIO(table_bytes), data_only=True)
    except Exception:
        return None

    best_sheet = None
    best_score = -1
    for sheet_name in workbook.sheetnames:
        lower_name = sheet_name.lower()
        if "tasa" in lower_name or "hoja1" in lower_name or "hoja2" in lower_name:
            continue
        ws = workbook[sheet_name]
        score = _score_sheet(ws, client_name)
        if score > best_score:
            best_score = score
            best_sheet = ws

    if best_sheet is None or best_score == 0:
        return None

    worksheet = best_sheet
    header_row_idx = -1
    headers: list[Any] = []
    best_header_score = -1

    for row_idx, row in enumerate(worksheet.iter_rows(min_row=1, max_row=15, values_only=True), 1):
        if not any(row):
            continue
        texts = [_normalize_str(str(v)).replace(" ", "") for v in row if v is not None]
        row_score = 0
        for text in texts:
            if text in [
                "ki",
                "cuota",
                "kf",
                "dia",
                "mes",
                "ano",
                "fechapago",
                "fechadepago",
                "valorpagado",
                "valorpagadocliente",
                "saldoacapital",
                "interesesdemora",
                "fechalimite",
            ]:
                row_score += 1
        if row_score > best_header_score and row_score >= 2:
            best_header_score = row_score
            header_row_idx = row_idx
            headers = [cell for cell in row]

    if header_row_idx == -1:
        return None

    pay_index = _find_header_index(headers, ["Fecha pago", "Fecha de pago"])
    if pay_index < 0:
        return None

    last_pay: date | None = None
    for row in worksheet.iter_rows(min_row=header_row_idx + 1, values_only=True):
        if not any(row):
            continue
        if pay_index >= len(row):
            continue
        pay_value = row[pay_index]
        if _is_blank(pay_value):
            continue
        parsed = _parse_cell_date(pay_value)
        if parsed is None:
            continue
        if last_pay is None or parsed > last_pay:
            last_pay = parsed

    return last_pay

def _find_statement_item(items: list[dict[str, Any]], credit_id: str, due_date: date | None) -> dict[str, Any] | None:
    extract_items = [item for item in items if "extracto" in str(item.get("name", "")).lower()]
    for item in extract_items:
        parsed_date, parsed_credit = parse_statement_name(item.get("name", ""))
        if parsed_credit == str(credit_id) and (due_date is None or parsed_date == due_date):
            return item
    for item in extract_items:
        parsed_date, parsed_credit = parse_statement_name(item.get("name", ""))
        if parsed_credit == str(credit_id):
            return item
        if due_date is not None and parsed_date == due_date:
            return item
    return extract_items[0] if extract_items else None

def _is_strict_extract_pdf_file_item(item: dict[str, Any]) -> bool:
    if "folder" in item:
        return False
    name = str(item.get("name", ""))
    if "extracto" not in name.lower():
        return False
    return name.lower().endswith(".pdf")

def _find_extractos_folder_item(items: list[dict[str, Any]]) -> dict[str, Any] | None:
    for it in items:
        if "folder" not in it:
            continue
        if str(it.get("name", "")).casefold() == "extractos":
            return it
    return None

_INFRA_FOLDER_LABELS = frozenset(
    {
        "extractos",
        "asientos contables",
        "asiento contables",
        "asientos contables generados",
        "email",
        "historico",
        "control",
    }
)

_TERMINAL_FOLDER_SAFE_TOKENS = frozenset({"vigente", "repuestos", "reestructuracion"})

def _normalize_folder_label(name: str) -> str:
    v = unicodedata.normalize("NFD", str(name or "").strip().lower())
    v = "".join(ch for ch in v if unicodedata.category(ch) != "Mn")
    return re.sub(r"\s+", " ", v)

def _is_infra_folder(folder_name: str) -> bool:
    return _normalize_folder_label(folder_name) in _INFRA_FOLDER_LABELS

def _is_terminal_credit_folder_name(folder_name: str) -> bool:
    """
    Carpetas de crédito cerradas (TERMINADO/PAGADO/…) — no son unidad operativa.

    Tokens seguros (vigente, etc.) evitan falsos positivos aunque el nombre
    contenga también alguna palabra terminal.
    """
    n = _normalize_folder_label(folder_name)
    if not n:
        return False
    for safe in _TERMINAL_FOLDER_SAFE_TOKENS:
        if re.search(rf"\b{re.escape(safe)}\b", n):
            return False
    for pattern in (
        r"\bterminad[oa]\b",
        r"\bfinalizad[oa]\b",
        r"\bcancelad[oa]\b",
        r"\bpagad[oa]\b",
        r"\bliquidad[oa]\b",
    ):
        if re.search(pattern, n):
            return True
    return False

def _looks_like_standard_credit_folder(folder_name: str) -> bool:
    n = _normalize_folder_label(folder_name)
    if not n:
        return False
    if "credito" in n or "obligacion" in n:
        return True
    if re.search(r"#\s*\d+", n):
        return True
    if re.search(r"\b\d{3,}\b", n):
        return True
    return False

def _root_has_strict_extract_pdfs(items: list[dict[str, Any]]) -> bool:
    return any(_is_strict_extract_pdf_file_item(it) for it in items if "folder" not in it)

async def _items_have_operational_signal(
    client: GraphApiPort,
    site_id: str,
    drive_id: str,
    folder_path: str,
    items: list[dict[str, Any]],
    cliente_folder: str,
    credit_name: str,
) -> bool:
    if _root_has_strict_extract_pdfs(items):
        return True
    file_names = [str(it.get("name", "")) for it in items if it.get("name")]
    excel_only = filter_amortization_excel_filenames(file_names)
    if excel_only:
        try:
            find_best_amortization_table(excel_only, cliente_folder, credit_name)
            return True
        except ValueError:
            pass
    extractos_item = _find_extractos_folder_item(items)
    if extractos_item is not None:
        ex_name = str(extractos_item.get("name", "EXTRACTOS"))
        extractos_path = f"{folder_path}/{ex_name}".replace("//", "/")
        children = await _get_drive_folder_children(client, site_id, drive_id, extractos_path)
        if any(_is_strict_extract_pdf_file_item(it) for it in children):
            return True
    return False

def _resolve_credit_id_for_unit(
    credit_name: str,
    cliente_folder: str,
    *,
    is_flat_unit: bool,
    is_root_unit: bool,
    statement_filename: str,
    statement_bytes: bytes | None,
) -> tuple[str, bool]:
    """Devuelve (credit_id, is_non_standard_folder)."""
    _, parsed_credit_fn = parse_statement_name(statement_filename)
    inferred_pdf = (
        extract_credit_id_from_extract_pdf(statement_bytes) if statement_bytes else None
    )
    is_non_standard = (
        not is_flat_unit
        and not is_root_unit
        and not _looks_like_standard_credit_folder(credit_name)
    )
    if is_flat_unit or is_root_unit:
        credit_id = inferred_pdf or parsed_credit_fn or cliente_folder
    elif is_non_standard:
        credit_id = inferred_pdf or parsed_credit_fn or credit_name
    else:
        credit_id = credit_name
    return str(credit_id), is_non_standard

def _norm_ruta_rel(ruta: str | None) -> str:
    return str(ruta or "").strip().replace("\\", "/").lower()

def _norm_ruta_extracto(ruta: str | None) -> str:
    return _norm_ruta_rel(ruta)

def _dedupe_credit_candidates(candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen_ruta: set[str] = set()
    seen_secondary: set[tuple[Any, ...]] = set()
    out: list[dict[str, Any]] = []
    for cand in candidates:
        ruta = _norm_ruta_extracto(cand.get("ruta_extracto_pdf"))
        if ruta:
            if ruta in seen_ruta:
                continue
            seen_ruta.add(ruta)
            out.append(cand)
            continue
        fecha = cand.get("fecha_limite")
        fecha_key = fecha.isoformat() if hasattr(fecha, "isoformat") else str(fecha or "")
        valor = cand.get("valor_extracto")
        try:
            valor_key = round(float(valor), 2) if valor is not None else None
        except (TypeError, ValueError):
            valor_key = None
        link_key = str(cand.get("link_extracto") or "").strip().lower()
        sec_key = (
            str(cand.get("credito") or ""),
            fecha_key,
            valor_key,
            link_key,
        )
        if sec_key in seen_secondary:
            continue
        seen_secondary.add(sec_key)
        out.append(cand)
    return out

def _possibly_finalized_observation(credit_folder_name: str) -> str | None:
    """Observación si se procesara una carpeta terminal (discovery ya las omite)."""
    if _is_terminal_credit_folder_name(credit_folder_name):
        return _OBS_POSSIBLE_FINALIZED
    return None

async def _discover_operational_credit_units(
    client: GraphApiPort,
    site_id: str,
    drive_id: str,
    cliente_folder_path: str,
    cliente_folder: str,
    subfolder_items: list[dict[str, Any]],
) -> tuple[
    list[tuple[str, str, list[dict[str, Any]], dict[str, Any] | None]],
    bool,
]:
    """
    Subcarpetas que son unidades de crédito activas.

    Omite infra y carpetas terminales (PAGADO/TERMINADO/…).
    Devuelve (unidades, skipped_terminal).
    """
    operational_units: list[
        tuple[str, str, list[dict[str, Any]], dict[str, Any] | None]
    ] = []
    skipped_terminal = False
    for credit_folder in subfolder_items:
        credit_name = str(credit_folder.get("name", "") or "").strip()
        if not credit_name or _is_infra_folder(credit_name):
            continue
        if _is_terminal_credit_folder_name(credit_name):
            skipped_terminal = True
            continue
        credit_path = f"{cliente_folder_path}/{credit_name}"
        credit_encoded = encode_graph_drive_path(credit_path)
        files_resp = await client.get(
            f"/sites/{site_id}/drives/{drive_id}/root:/{credit_encoded}:/children"
        )
        children = list(files_resp.get("value", []))
        is_standard = _looks_like_standard_credit_folder(credit_name)
        if is_standard or await _items_have_operational_signal(
            client,
            site_id,
            drive_id,
            credit_path,
            children,
            cliente_folder,
            credit_name,
        ):
            operational_units.append((credit_name, credit_path, children, credit_folder))
    return operational_units, skipped_terminal

_OBS_TABLA_NO_VERIFICAR_NOT_FOUND = (
    "No se pudo verificar contra tabla de amortización: tabla no encontrada."
)
_OBS_TABLA_NO_VERIFICAR_AMBIGUOUS = (
    "No se pudo verificar contra tabla de amortización: tabla ambigua."
)
_OBS_TABLA_NO_VERIFICAR_NOPARSE = (
    "No se pudo verificar contra tabla de amortización: no parseable."
)
_OBS_EXTRACTO_FECHA_VS_TABLA_IGUAL = (
    "Advertencia: la fecha límite del extracto coincide con la última fecha de pago "
    "registrada en la tabla de amortización."
)
_OBS_EXTRACTO_FECHA_VS_TABLA_ANTERIOR = (
    "Advertencia: la fecha límite del extracto es anterior a la última fecha de pago "
    "registrada en la tabla de amortización."
)
_OBS_ROOT_UNIT = (
    "Unidad de crédito detectada en la raíz del cliente; revisar estructura documental."
)
_OBS_NON_STANDARD_FOLDER = (
    "Carpeta de crédito detectada por contenido, pero el nombre no sigue el estándar CREDITO #."
)
_OBS_POSSIBLE_FINALIZED = (
    "Carpeta marcada como TERMINADO/FINALIZADO/CANCELADO/PAGADO/LIQUIDADO: "
    "revisar si el crédito sigue vigente."
)
_OBS_EXTRACT_OUTSIDE_CANONICAL = (
    "Se encontró y utilizó el extracto correspondiente, pero está ubicado en la raíz "
    "de la unidad de crédito. Para mantener la organización documental, muévalo "
    "posteriormente a la carpeta EXTRACTOS."
)

# Ubicación del PDF candidato (pool combinado raíz + EXTRACTOS).
EXTRACT_SOURCE_CREDIT_ROOT = "credit_root"
EXTRACT_SOURCE_EXTRACTOS = "extractos_folder"

async def _get_drive_folder_children(
    client: GraphApiPort,
    site_id: str,
    drive_id: str,
    folder_path: str,
) -> list[dict[str, Any]]:
    enc = encode_graph_drive_path(folder_path)
    resp = await client.get(f"/sites/{site_id}/drives/{drive_id}/root:/{enc}:/children")
    return list(resp.get("value", []))

def _extract_candidate(
    item: dict[str, Any],
    *,
    parent_path: str,
    source_location: str,
) -> dict[str, Any]:
    name = str(item.get("name", "") or "")
    parent = str(parent_path or "").replace("\\", "/").rstrip("/")
    relative = f"{parent}/{name}" if name else parent
    fsi = item.get("fileSystemInfo") if isinstance(item.get("fileSystemInfo"), dict) else {}
    created = item.get("createdDateTime") or fsi.get("createdDateTime")
    return {
        "item": item,
        "name": name,
        "parent_path": parent,
        "relative_path": relative.replace("//", "/"),
        "source_location": source_location,
        "id": item.get("id"),
        "createdDateTime": created,
        "eTag": item.get("eTag") or item.get("etag"),
        "cTag": item.get("cTag") or item.get("ctag"),
    }

async def _resolve_extract_pdf_pool(
    client: GraphApiPort,
    site_id: str,
    drive_id: str,
    credit_path: str,
    credit_folder_items: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """
    Recopila PDFs extracto strict de la raíz del crédito y de EXTRACTOS (si existe).

    EXTRACTOS es canónica para desempate, pero nunca oculta los PDF de la raíz.
    No busca en otras subcarpetas.
    """
    credit_norm = str(credit_path or "").replace("\\", "/").rstrip("/")
    candidates: list[dict[str, Any]] = []
    for it in credit_folder_items:
        if _is_strict_extract_pdf_file_item(it):
            candidates.append(
                _extract_candidate(
                    it,
                    parent_path=credit_norm,
                    source_location=EXTRACT_SOURCE_CREDIT_ROOT,
                )
            )

    extractos_item = _find_extractos_folder_item(credit_folder_items)
    if extractos_item is not None:
        ex_name = str(extractos_item.get("name", "EXTRACTOS"))
        extractos_path = f"{credit_norm}/{ex_name}".replace("//", "/")
        children = await _get_drive_folder_children(client, site_id, drive_id, extractos_path)
        for it in children:
            if _is_strict_extract_pdf_file_item(it):
                candidates.append(
                    _extract_candidate(
                        it,
                        parent_path=extractos_path,
                        source_location=EXTRACT_SOURCE_EXTRACTOS,
                    )
                )
    return candidates

async def select_extract_as_of_bank_date(
    client: GraphApiPort,
    site_id: str,
    drive_id: str,
    pool: list[dict[str, Any]],
    *,
    bank_date: date,
    frozen_evidence: dict[str, Any] | None = None,
) -> tuple[dict[str, Any] | None, bytes | None, date | None, str | None, dict[str, Any] | None]:
    """
    Último extracto de la unidad (máx. fecha límite), igual que ui-stable.

    createdDateTime Graph solo desempatan. Un PDF dañado o ilegible en el pool
    falla cerrado. Congela evidencia en retry si coincide.
    Retorna (item, bytes, fecha_limite, error_code, meta).
    """
    if not pool:
        return None, None, None, "extract_not_found", None

    frozen_cand = prefer_frozen_extract_candidate(pool, frozen_evidence)
    if frozen_cand is not None:
        fpath = str(frozen_cand.get("relative_path") or "")
        name = str(frozen_cand.get("name") or "")
        try:
            pdf_bytes = await client.get_bytes(
                _build_content_endpoint(site_id, drive_id, fpath)
            )
        except Exception:
            logger.warning(
                "frozen_extract_download_failed name=%s path=%s; falling back to as-of",
                name,
                fpath,
                exc_info=True,
            )
        else:
            fe = await asyncio.to_thread(extract_fecha_limite_pago_from_pdf, pdf_bytes)
            if fe is None:
                logger.warning(
                    "frozen_extract_fecha_limite_not_readable path=%s; falling back",
                    fpath,
                )
            else:
                return frozen_cand, pdf_bytes, fe, None, frozen_cand

    scored: list[tuple[dict[str, Any], date, bytes, str]] = []
    damaged: list[dict[str, Any]] = []
    damaged_details: list[dict[str, str]] = []
    for cand in pool:
        fpath = str(cand.get("relative_path") or "")
        name = str(cand.get("name") or "")
        try:
            pdf_bytes = await client.get_bytes(
                _build_content_endpoint(site_id, drive_id, fpath)
            )
        except Exception:
            logger.warning(
                "extract_candidate_damaged download_failed name=%s path=%s",
                name,
                fpath,
                exc_info=True,
            )
            damaged.append(cand)
            damaged_details.append(
                {
                    "name": name or fpath or "(sin nombre)",
                    "relative_path": fpath,
                    "source_location": str(cand.get("source_location") or ""),
                    "reason": "download_failed",
                }
            )
            continue
        fe = await asyncio.to_thread(extract_fecha_limite_pago_from_pdf, pdf_bytes)
        if fe is None:
            logger.warning(
                "extract_candidate_damaged fecha_limite_not_readable path=%s source=%s",
                fpath,
                cand.get("source_location"),
            )
            damaged.append(cand)
            damaged_details.append(
                {
                    "name": name or fpath or "(sin nombre)",
                    "relative_path": fpath,
                    "source_location": str(cand.get("source_location") or ""),
                    "reason": "fecha_limite_not_readable",
                }
            )
            continue
        digest = hashlib.sha256(pdf_bytes).hexdigest()
        scored.append((cand, fe, pdf_bytes, digest))

    if damaged:
        focus = next(
            (
                c
                for c in damaged
                if str(c.get("source_location") or "") == EXTRACT_SOURCE_EXTRACTOS
            ),
            damaged[0],
        )
        return (
            None,
            None,
            None,
            "fecha_limite_extracto_not_readable",
            {
                "damaged_focus": focus,
                "damaged_count": len(damaged),
                "readable_count": len(scored),
                "archivos_problema": damaged_details,
            },
        )

    outcome = choose_extract_as_of_bank_date(scored, bank_date)
    if outcome.error_code:
        return None, None, None, outcome.error_code, outcome.meta
    cand = outcome.candidate
    assert cand is not None and outcome.pdf_bytes is not None and outcome.fecha_limite is not None
    item = cand.get("item") if isinstance(cand.get("item"), dict) else cand
    meta = dict(outcome.meta or {})
    meta["selection_reason"] = outcome.selection_reason
    # Adjuntar candidato seleccionado para callers que esperan meta=cand
    if isinstance(cand, dict):
        cand = {**cand, "_selection_meta": meta}
    return item, outcome.pdf_bytes, outcome.fecha_limite, None, cand


def _link_url_for_fecha_limite_error(
    pool: list[dict[str, Any]],
    selected_meta: dict[str, Any] | None,
) -> str:
    """Prioriza el PDF dañado (EXTRACTOS) para el hipervínculo en Errores."""
    focus = None
    if isinstance(selected_meta, dict):
        raw_focus = selected_meta.get("damaged_focus")
        if isinstance(raw_focus, dict):
            focus = raw_focus
    if focus is not None:
        item = focus.get("item") if isinstance(focus.get("item"), dict) else focus
        path = str(focus.get("relative_path") or "")
        if isinstance(item, dict) and path:
            return _item_link_url(item, path)
    first_it, first_path = _first_pool_item_and_path(pool)
    if first_it is not None and first_path:
        return _item_link_url(first_it, first_path)
    return ""

def _archivos_problema_from_meta(selected_meta: dict[str, Any] | None) -> list[dict[str, str]]:
    if not isinstance(selected_meta, dict):
        return []
    raw = selected_meta.get("archivos_problema")
    if not isinstance(raw, list):
        return []
    out: list[dict[str, str]] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "").strip()
        if not name:
            continue
        out.append(
            {
                "name": name,
                "relative_path": str(item.get("relative_path") or ""),
                "source_location": str(item.get("source_location") or ""),
                "reason": str(item.get("reason") or ""),
                "fecha_limite": str(item.get("fecha_limite") or ""),
            }
        )
    return out

def _pool_has_extractos_folder(pool: list[dict[str, Any]]) -> bool:
    return any(
        str(c.get("source_location") or "") == EXTRACT_SOURCE_EXTRACTOS for c in pool
    )

def _first_pool_item_and_path(
    pool: list[dict[str, Any]],
) -> tuple[dict[str, Any] | None, str]:
    if not pool:
        return None, ""
    first = pool[0]
    item = first.get("item") if isinstance(first.get("item"), dict) else first
    path = str(first.get("relative_path") or "")
    return item if isinstance(item, dict) else None, path

def _item_link(item: dict[str, Any], fallback_path: str) -> str:
    return item.get("webUrl") or fallback_path

def _http_url_only(raw: Any) -> str:
    s = str(raw or "").strip()
    return s if s.lower().startswith("http") else ""

DIST_MONEY_COL_WIDTH = 16.0
CASOS_OBS_COL_WIDTH = 48.0
CASOS_OBS_COL_CAP_WIDTH = 100.0

def _distrib_freeze_panes_cell(first_data_row: int) -> str:
    """Congela ID Pago, Cliente y Crédito; el scroll horizontal empieza en Monto banco."""
    col_credito = AplicacionPagosCols.HEADERS.index(AplicacionPagosCols.CREDITO) + 1
    return f"{get_column_letter(col_credito + 1)}{first_data_row}"

def _item_link_url(item: dict[str, Any], fallback_path: str) -> str:
    return _http_url_only(_item_link(item, fallback_path))

async def _fetch_folder_web_url(
    client: GraphApiPort,
    site_id: str,
    drive_id: str,
    folder_path: str,
) -> str | None:
    enc = encode_graph_drive_path(folder_path)
    try:
        resp = await client.get(
            f"/sites/{site_id}/drives/{drive_id}/root:/{enc}",
            params={"$select": "webUrl"},
        )
        if isinstance(resp, dict):
            web = resp.get("webUrl")
            if web and str(web).strip():
                return str(web).strip()
    except Exception:
        logger.debug(
            "fetch_folder_web_url failed path=%s", folder_path, exc_info=True
        )
    return None

async def _resolve_client_folder_web_url(
    client: GraphApiPort,
    site_id: str,
    drive_id: str,
    clients_path: str,
    cliente_folder: str,
) -> str | None:
    """webUrl de la carpeta del cliente: primero desde listado padre, luego GET del ítem."""
    cliente_folder_path = f"{clients_path}/{cliente_folder}"
    try:
        enc_parent = encode_graph_drive_path(clients_path)
        resp = await client.get(
            f"/sites/{site_id}/drives/{drive_id}/root:/{enc_parent}:/children"
        )
        for it in resp.get("value") or []:
            if str(it.get("name", "")).strip() == cliente_folder:
                web = it.get("webUrl")
                if web and str(web).strip():
                    return str(web).strip()
    except Exception:
        logger.debug(
            "resolve_client_folder_web_url: parent children failed cliente=%s",
            cliente_folder,
            exc_info=True,
        )
    return await _fetch_folder_web_url(client, site_id, drive_id, cliente_folder_path)

def _carpeta_link_url_for_errores(
    credit_folder_drive_item: dict[str, Any] | None,
    unit_path: str,
    *,
    client_folder_web_url: str | None,
    is_flat_unit: bool,
    is_root_unit: bool,
) -> str:
    """Solo URL http(s) para hipervínculo en Errores; vacío si Graph no devolvió webUrl."""
    if is_flat_unit or is_root_unit:
        return _http_url_only(client_folder_web_url)
    return _http_url_only((credit_folder_drive_item or {}).get("webUrl"))

def _build_aplicacion_rows(
    payment: dict[str, Any],
    candidates: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Una fila por credito activo candidato; Validar Pago = NO."""
    return [build_aplicacion_pagos_row(payment, candidate) for candidate in candidates]

# Filas 1–2: bloque título; fila 3: encabezados de tabla o banda de sección (como referencia visual Claude)
_SHEET_BANNER_ROWS = 2

CONTROL_TITLE = "VALIDACIÓN DE PAGOS"
CONTROL_SUBTITLE = "Panel de control del proceso"
CONTROL_HELP = (
    "Revise el archivo, complete la distribución en la hoja «Aplicacion_Pagos» "
    "y cambie Validar Pago a SI cuando esté listo."
)
RESUMEN_TITLE = "RESUMEN DEL PROCESO"
RESUMEN_SUBTITLE = "Vista ejecutiva del lote de validación"
RESUMEN_SECTION = "MÉTRICAS GENERALES"
DISTRIB_TITLE = "DISTRIBUCIÓN DE PAGOS — HOJA PRINCIPAL"
DISTRIB_HELP = (
    "Complete únicamente las celdas editables: Aplicar a extracto, Mora a aplicar, Abono a capital, "
    "Otros valores, "
    "Validar Pago y Tipo de aplicación. "
    "Revise los links si necesita validar documentos. Al terminar, vaya a Control y cambie Procesar a SI."
)
ABONO_TITLE = "DISTRIBUCIÓN DE ABONOS"
ABONO_HELP = (
    "Marque Validar Abono = SI en uno o más créditos candidatos para el abono. "
    "Revise los links de tabla y carpeta si necesita validar documentos."
)
CASOS_TITLE = "CASOS DE PAGO"
CASOS_SUBTITLE = (
    "Consulte aquí el resumen de pagos detectados. Esta hoja es informativa; "
    "complete la distribución en la hoja Aplicacion_Pagos."
)
ERRORES_HELP = (
    "Revise estos casos manualmente. Use la descripción, la acción recomendada y los links "
    "para corregir documentos o carpetas antes de volver a generar."
)
ERRORES_TITLE = "REGISTRO DE ERRORES"
ERRORES_OK_MSG = "Sin errores técnicos detectados en este proceso."
ERRORES_BAD_MSG = (
    "Se registraron casos que requieren acción en las filas siguientes. "
    "Consulte «Descripción para revisión» y «Qué debe hacer»."
)


_FILL_NAVY = PatternFill(fill_type="solid", fgColor="002060")
_FILL_HEADER_STRONG = _FILL_NAVY
_FILL_HEADER_SOFT = PatternFill(fill_type="solid", fgColor="5B9BD5")
_FILL_SECTION_BAND = PatternFill(fill_type="solid", fgColor="D9E2F3")
_FILL_CASOS_SUBBAR = PatternFill(fill_type="solid", fgColor="E7E8ED")
_FILL_PANEL = PatternFill(fill_type="solid", fgColor="F5F6F8")
_FILL_CONTROL_LABEL = PatternFill(fill_type="solid", fgColor="E8EDF2")
_FILL_DISTRIB_HINT = PatternFill(fill_type="solid", fgColor="E6EEF5")
_FILL_ZEBRA = PatternFill(fill_type="solid", fgColor="F9FAFB")
_FILL_SALDO_COL = PatternFill(fill_type="solid", fgColor="FFF9E6")
_FILL_DIAS_MORA_WARN = PatternFill(fill_type="solid", fgColor="FDE9D9")
_FILL_STATUS_OK = PatternFill(fill_type="solid", fgColor="D4EDDA")
_FILL_STATUS_BAD = PatternFill(fill_type="solid", fgColor="F8D7DA")
_FILL_GROUP_A = PatternFill(fill_type="solid", fgColor="FCFCFD")
_FILL_GROUP_B = PatternFill(fill_type="solid", fgColor="F6F8FA")
_FILL_EDITABLE_COL = PatternFill(fill_type="solid", fgColor="E2F4E8")
_FILL_SHEET_INSTRUCTION = PatternFill(fill_type="solid", fgColor="E8F2FA")
_TAB_COLOR_DISTRIB = "FF00B050"
_TAB_COLOR_ABONOS = "FF7030A0"
_TAB_COLOR_ERRORES = "FFFF6969"
_FILL_CONTROL_PROCESAR_ROW = PatternFill(fill_type="solid", fgColor="E8EEF5")
_FILL_PROCESAR_SI = PatternFill(fill_type="solid", fgColor="FF32CD32")
_FILL_PROCESAR_NO = PatternFill(fill_type="solid", fgColor="FFFF6969")
_FILL_ESTADO_VALIDAR = PatternFill(fill_type="solid", fgColor="C8E6C9")
_FILL_ESTADO_PENDIENTE_MORA = PatternFill(fill_type="solid", fgColor="FFF9C4")
_FILL_ESTADO_REPROGRAMAR = PatternFill(fill_type="solid", fgColor="FFE0B2")
_FILL_ESTADO_NO_VALIDAR = PatternFill(fill_type="solid", fgColor="FFCDD2")
_FILL_ESTADO_REVISION_MANUAL = PatternFill(fill_type="solid", fgColor="E1BEE7")
_FILL_OBS_WARNING = PatternFill(fill_type="solid", fgColor="FFF9ED")
_FONT_HEADER = Font(name="Calibri", bold=True, color="FFFFFF", size=11)
_FONT_TITLE_NAVY = Font(name="Calibri", bold=True, size=16, color="FFFFFF")
_FONT_SUB_NAVY = Font(name="Calibri", size=11, color="FFFFFF")
_FONT_SECTION = Font(name="Calibri", bold=True, size=11, color="002060")
_FONT_TITLE = Font(name="Calibri", bold=True, size=20, color="1A2F36")
_FONT_SUBTITLE = Font(name="Calibri", size=11, color="3D4F5C", italic=True)
_FONT_BODY = Font(name="Calibri", size=11)
_FONT_LABEL_BOLD = Font(name="Calibri", bold=True, size=11, color="000000")
_FONT_ESTADO_CTRL = Font(name="Calibri", size=11, color="2F5597")
_FONT_PROCESAR_LABEL = Font(name="Calibri", bold=True, size=14, color="002060")
_FONT_PROCESAR_VALUE = Font(name="Calibri", bold=True, size=16, color="FFFFFF")
_FONT_SHEET_INSTRUCTION = Font(name="Calibri", size=12, color="1A2F36")
_THIN = Side(style="thin", color="D0D5DD")
_MEDIUM_CLIENT_EDGE = Side(style="medium", color="002060")
_BORDER_PROCESAR_VALUE = Border(
    left=Side(style="medium", color="002060"),
    right=Side(style="medium", color="002060"),
    top=Side(style="medium", color="002060"),
    bottom=Side(style="medium", color="002060"),
)
_BORDER_LIGHT = Border(left=_THIN, right=_THIN, top=_THIN, bottom=_THIN)
_ALIGN_PROCESAR_LABEL = Alignment(vertical="center", horizontal="left")
_ALIGN_PROCESAR_VALUE = Alignment(vertical="center", horizontal="center")

_ALIGN_WRAP = Alignment(vertical="center", horizontal="left", wrap_text=True)
_ALIGN_VCENTER = Alignment(vertical="center", horizontal="left")
_ALIGN_RIGHT = Alignment(vertical="center", horizontal="right")
_ALIGN_CENTER = Alignment(vertical="center", horizontal="center", wrap_text=True)
# Código OOXML/Excel estándar: Excel aplica miles/decimales según configuración regional
# (p. ej. en español se ve 1.234.567,89). No usar «#.##0,00» en el archivo: en muchos
# entornos se interpreta mal y aparece «,000» u otros artefactos.
_FMT_MONEY = "#,##0.00"
_FMT_DATE = "yyyy-mm-dd"
# Estilo estándar de hipervínculo Excel (azul + subrayado); fondo suave para que no parezca texto plano.
_HLINK_FONT = Font(name="Calibri", color="0563C1", size=11, underline="single")
_FILL_HLINK = PatternFill(fill_type="solid", fgColor="E8F4FC")
_GROUP_BAND_FILLS = (_FILL_GROUP_A, _FILL_GROUP_B)

_TAB_COLOR_CONTROL = "FF002060"
_TAB_COLOR_RESUMEN = "FF4472C4"
_TAB_COLOR_CASOS = "FF595959"
_TAB_COLOR_LISTAS = "FFB4B4B4"


async def _append_candidate_without_extract(
    *,
    candidates: list[dict[str, Any]],
    credit_issues: list[dict[str, Any]],
    credit_name: str,
    credit_path: str,
    items: list[dict[str, Any]],
    cliente_folder: str,
    carpeta_link_url: str,
    is_flat_unit: bool,
    is_root_unit: bool,
    issue_code: str,
    link_extracto_url: str = "",
    selected_meta: dict[str, Any] | None = None,
) -> None:
    """Crédito activo sin extracto usable → fila candidata + warning (no skip)."""
    credit_issues.append(
        {
            "code": issue_code,
            "severity": "WARNING_REVIEW_REQUIRED",
            "unidad_credito": credit_name,
            "link_extracto_url": link_extracto_url,
            "link_carpeta_credito_url": carpeta_link_url,
            "archivos_problema": _archivos_problema_from_meta(selected_meta),
        }
    )
    file_names = [item.get("name", "") for item in items if item.get("name")]
    excel_only = filter_amortization_excel_filenames(file_names)
    table_item = None
    table_path = ""
    link_tabla_val = ""
    try:
        table_name_res = find_best_amortization_table(excel_only, cliente_folder, credit_name)
        table_item = next((item for item in items if item.get("name") == table_name_res), None)
        table_path = f"{credit_path}/{table_name_res}"
        if table_item is not None:
            link_tabla_val = _item_link(table_item, table_path)
    except ValueError:
        pass
    credit_id, is_non_standard = _resolve_credit_id_for_unit(
        credit_name,
        cliente_folder,
        is_flat_unit=is_flat_unit,
        is_root_unit=is_root_unit,
        statement_filename="",
        statement_bytes=None,
    )
    cred_norm = normalize_credito_digits(credit_id) or str(credit_id)
    obs_parts = ["extracto_no_disponible"]
    if is_root_unit:
        obs_parts.append(_OBS_ROOT_UNIT)
    if is_non_standard:
        obs_parts.append(_OBS_NON_STANDARD_FOLDER)
    obs_ter = _possibly_finalized_observation(credit_name)
    if obs_ter:
        obs_parts.append(obs_ter)
    candidates.append(
        {
            "credito": str(credit_id),
            "credito_normalizado": cred_norm,
            "fecha_limite": None,
            "link_extracto": "",
            "link_tabla": link_tabla_val,
            "link_carpeta_credito": carpeta_link_url,
            "ruta_extracto_pdf": "",
            "ruta_unidad_credito": credit_path.replace("\\", "/"),
            "ruta_tabla_amortizacion": table_path.replace("\\", "/").strip("/") if table_path else "",
            "valor_extracto": None,
            "valor_obligacion_actual": None,
            "saldo_vencido_visible": None,
            "right_panel_role": "VACIO",
            "parser_status": "FAILED",
            "extract_evidence": {},
            "observacion_extra": " | ".join(obs_parts),
        }
    )

async def _load_credit_candidates(
    client: GraphApiPort,
    site_search: str,
    drive_name: str,
    clients_path: str,
    cliente_folder: str,
    *,
    bank_date: date,
    bank_code: str = "",
    process_date: date | None = None,
    frozen_evidence_rows: list[dict[str, str]] | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    """Devuelve candidatos distribuibles por unidad de crédito + incidencias por unidad (hoja Errores)."""
    clients_info = await resolve_sharepoint_path(client, site_search, drive_name, clients_path)
    cliente_folder_path = f"{clients_path}/{cliente_folder}"
    cliente_folder_encoded = encode_graph_drive_path(cliente_folder_path)
    credit_children = await client.get(
        f"/sites/{clients_info['site_id']}/drives/{clients_info['drive_id']}/root:/{cliente_folder_encoded}:/children"
    )
    all_items: list[dict[str, Any]] = list(credit_children.get("value", []))

    candidates: list[dict[str, Any]] = []
    credit_issues: list[dict[str, Any]] = []
    site_id = clients_info["site_id"]
    drive_id = clients_info["drive_id"]
    client_folder_web_url = await _resolve_client_folder_web_url(
        client, site_id, drive_id, clients_path, cliente_folder
    )

    async def process_credit_unit(
        credit_name: str,
        credit_path: str,
        items: list[dict[str, Any]],
        credit_folder_drive_item: dict[str, Any] | None = None,
        *,
        is_flat_unit: bool = False,
        is_root_unit: bool = False,
    ) -> None:
        carpeta_link_url = _carpeta_link_url_for_errores(
            credit_folder_drive_item,
            credit_path,
            client_folder_web_url=client_folder_web_url,
            is_flat_unit=is_flat_unit,
            is_root_unit=is_root_unit,
        )
        if (is_flat_unit or is_root_unit) and not carpeta_link_url:
            logger.warning(
                "generate errores: link_carpeta_credito_url vacío cliente=%r unidad=%r "
                "credit_path=%r graph_client_web_url=%r",
                cliente_folder,
                credit_name,
                credit_path,
                client_folder_web_url,
            )
        file_names = [item.get("name", "") for item in items if item.get("name")]
        excel_only = filter_amortization_excel_filenames(file_names)
        warnings: list[str] = []
        pool = await _resolve_extract_pdf_pool(
            client, site_id, drive_id, credit_path, items
        )
        frozen_for_credit = _frozen_evidence_for_credit_path(
            frozen_evidence_rows, credit_path
        )
        statement_item, statement_bytes, fecha_limite_pdf, sel_err, selected = (
            await select_extract_as_of_bank_date(
                client,
                site_id,
                drive_id,
                pool,
                bank_date=bank_date,
                frozen_evidence=frozen_for_credit,
            )
        )
        if (
            sel_err
            or statement_item is None
            or statement_bytes is None
            or fecha_limite_pdf is None
            or selected is None
        ):
            issue_code = sel_err or "extract_not_found"
            link_extracto_url = ""
            if pool and issue_code in {
                "fecha_limite_extracto_not_readable",
                "extract_tie_max_fecha_limite",
                "extract_tie_as_of_bank_date",
                "extract_as_of_not_found",
                "extract_amount_not_found",
            }:
                link_extracto_url = _link_url_for_fecha_limite_error(pool, selected)
            await _append_candidate_without_extract(
                candidates=candidates,
                credit_issues=credit_issues,
                credit_name=credit_name,
                credit_path=credit_path,
                items=items,
                cliente_folder=cliente_folder,
                carpeta_link_url=carpeta_link_url,
                is_flat_unit=is_flat_unit,
                is_root_unit=is_root_unit,
                issue_code=issue_code,
                link_extracto_url=link_extracto_url,
                selected_meta=selected if isinstance(selected, dict) else None,
            )
            return

        statement_path = str(selected.get("relative_path") or "")
        if (
            str(selected.get("source_location") or "") == EXTRACT_SOURCE_CREDIT_ROOT
            and _pool_has_extractos_folder(pool)
        ):
            warnings.append(_OBS_EXTRACT_OUTSIDE_CANONICAL)

        try:
            extract_value = extract_total_a_pagar_from_pdf(statement_bytes)
        except ValueError:
            pdf_name = str(statement_item.get("name") or selected.get("name") or "").strip()
            credit_issues.append(
                {
                    "code": "extract_amount_not_found",
                    "unidad_credito": credit_name,
                    "link_extracto_url": _item_link_url(statement_item, statement_path),
                    "link_carpeta_credito_url": carpeta_link_url,
                    "archivos_problema": (
                        [
                            {
                                "name": pdf_name,
                                "relative_path": statement_path,
                                "source_location": str(
                                    selected.get("source_location") or ""
                                ),
                                "reason": "extract_amount_not_found",
                            }
                        ]
                        if pdf_name
                        else []
                    ),
                }
            )
            return

        credit_id, is_non_standard = _resolve_credit_id_for_unit(
            credit_name,
            cliente_folder,
            is_flat_unit=is_flat_unit,
            is_root_unit=is_root_unit,
            statement_filename=str(statement_item.get("name", "")),
            statement_bytes=statement_bytes,
        )

        table_item = None
        table_path = ""
        table_name_res: str | None = None

        try:
            table_name_res = find_best_amortization_table(
                excel_only, cliente_folder, credit_name
            )
        except ValueError as e:
            code = str(e)
            if code == "amortization_table_not_found":
                warnings.append(_OBS_TABLA_NO_VERIFICAR_NOT_FOUND)
            elif code == "amortization_table_ambiguous":
                warnings.append(_OBS_TABLA_NO_VERIFICAR_AMBIGUOUS)
            else:
                warnings.append(_OBS_TABLA_NO_VERIFICAR_NOPARSE)
        else:
            table_item = next(
                (item for item in items if item.get("name") == table_name_res), None
            )
            table_path = f"{credit_path}/{table_name_res}"
            try:
                tb = await client.get_bytes(
                    _build_content_endpoint(site_id, drive_id, table_path)
                )
                last_pay = _extract_last_payment_date_from_amortization(tb, cliente_folder)
                if last_pay is None:
                    warnings.append(_OBS_TABLA_NO_VERIFICAR_NOPARSE)
                elif fecha_limite_pdf < last_pay:
                    warnings.append(_OBS_EXTRACTO_FECHA_VS_TABLA_ANTERIOR)
                elif fecha_limite_pdf == last_pay:
                    warnings.append(_OBS_EXTRACTO_FECHA_VS_TABLA_IGUAL)
            except Exception:
                logger.debug(
                    "amortization_aux_verify_failed credit=%s", credit_name, exc_info=True
                )
                warnings.append(_OBS_TABLA_NO_VERIFICAR_NOPARSE)

        obs_ter = _possibly_finalized_observation(credit_name)
        extra_parts = [w for w in warnings if w]
        if is_root_unit:
            extra_parts.append(_OBS_ROOT_UNIT)
        if is_non_standard:
            extra_parts.append(_OBS_NON_STANDARD_FOLDER)
        if obs_ter:
            extra_parts.append(obs_ter)
        obs_extra = " | ".join(extra_parts) if extra_parts else None

        link_tabla_val = ""
        if table_item is not None and table_path:
            link_tabla_val = _item_link(table_item, table_path)

        cred_norm = normalize_credito_digits(credit_id) or str(credit_id)
        ruta_tabla = table_path.replace("\\", "/").strip("/") if table_path else ""
        snap_fields = _candidate_extract_fields(
            statement_bytes,
            statement_item,
            statement_path,
            site_id=site_id,
            drive_id=drive_id,
            fallback_valor=extract_value,
            fallback_fecha=fecha_limite_pdf,
        )
        panel_obs = snap_fields.pop("observacion_panel", None)
        if panel_obs:
            obs_extra = f"{obs_extra} | {panel_obs}" if obs_extra else panel_obs
        if snap_fields.get("parser_status") == ParserStatus.AMBIGUOUS_RIGHT_PANEL.value:
            credit_issues.append(
                {
                    "code": "extract_right_panel_ambiguous",
                    "unidad_credito": credit_name,
                    "link_extracto_url": _item_link_url(statement_item, statement_path),
                    "link_carpeta_credito_url": carpeta_link_url,
                }
            )
        candidates.append(
            {
                "credito": str(credit_id),
                "credito_normalizado": cred_norm,
                "fecha_limite": fecha_limite_pdf,
                "link_extracto": _item_link(statement_item, statement_path),
                "link_tabla": link_tabla_val,
                "link_carpeta_credito": carpeta_link_url,
                "ruta_extracto_pdf": statement_path.replace("\\", "/"),
                "ruta_unidad_credito": credit_path.replace("\\", "/"),
                "ruta_tabla_amortizacion": ruta_tabla,
                **snap_fields,
                **({"observacion_extra": obs_extra} if obs_extra else {}),
            }
        )
        return

    root_file_items = [it for it in all_items if "folder" not in it]
    subfolder_items = [it for it in all_items if "folder" in it]
    operational_units, skipped_terminal = await _discover_operational_credit_units(
        client,
        site_id,
        drive_id,
        cliente_folder_path,
        cliente_folder,
        subfolder_items,
    )

    if operational_units:
        for credit_name, credit_path, children, folder_item in operational_units:
            await process_credit_unit(
                credit_name,
                credit_path,
                children,
                credit_folder_drive_item=folder_item,
                is_flat_unit=False,
                is_root_unit=False,
            )
        if _root_has_strict_extract_pdfs(root_file_items):
            await process_credit_unit(
                cliente_folder,
                cliente_folder_path,
                root_file_items,
                credit_folder_drive_item=None,
                is_flat_unit=False,
                is_root_unit=True,
            )
    elif _root_has_strict_extract_pdfs(root_file_items):
        await process_credit_unit(
            cliente_folder,
            cliente_folder_path,
            root_file_items,
            credit_folder_drive_item=None,
            is_flat_unit=False,
            is_root_unit=True,
        )
    elif skipped_terminal:
        raise ValueError("only_terminal_credit_folders")
    else:
        await process_credit_unit(
            cliente_folder,
            cliente_folder_path,
            all_items,
            credit_folder_drive_item=None,
            is_flat_unit=True,
            is_root_unit=False,
        )

    candidates = _dedupe_credit_candidates(candidates)

    if not candidates and not credit_issues:
        raise ValueError("credit_folder_not_found")

    return candidates, credit_issues

async def _sharepoint_drive_file_exists(
    client: GraphApiPort,
    site_id: str,
    drive_id: str,
    file_path: str,
) -> bool:
    """True si el item existe en el drive; 404 → False. Otros errores Graph se propagan."""
    rel = str(file_path or "").replace("\\", "/").strip().strip("/")
    if not rel:
        return False
    enc = encode_graph_drive_path(rel)
    endpoint = f"/sites/{site_id}/drives/{drive_id}/root:/{enc}"
    try:
        await client.get(endpoint, params={"$select": "id,name"})
        return True
    except httpx.HTTPStatusError as exc:
        if exc.response is not None and exc.response.status_code == 404:
            return False
        raise

# Estados en los que aún es seguro recrear el Excel de revisión si el archivo ya no está.
_GENERATE_RECREATE_ALLOWED_STATES = frozenset({"REVISION_CREADA", "ERROR_GENERATE"})
# Tras un Regenerar a medias el Control puede quedar idle; se permite reintentar Generate
# con force_regenerate + process_date (sin exigir carpeta vacía a mano).
_FORCE_REGENERATE_IDLE_STATES = frozenset({"", "VACIO", "CANCELADO"})

def _append_credit_issue_records(
    error_records: list[dict[str, Any]],
    *,
    payment_id: str,
    cliente_folder: str,
    credit_issues: list[dict[str, Any]],
) -> None:
    """Una fila Errores por crédito problemático (no por cada pago del banco)."""
    for ci in credit_issues:
        error_records.append(
            {
                "id_pago": payment_id,
                "cliente": cliente_folder,
                "credito": str(ci["unidad_credito"]),
                "code": str(ci["code"]),
                "link_extracto_url": _http_url_only(
                    ci.get("link_extracto_url") or ci.get("link_extracto")
                ),
                "link_carpeta_credito_url": _http_url_only(
                    ci.get("link_carpeta_credito_url") or ci.get("link_carpeta")
                ),
                "archivos_problema": list(ci.get("archivos_problema") or []),
            }
        )


def _frozen_evidence_for_credit_path(
    frozen_rows: list[dict[str, str]] | None,
    credit_path: str,
) -> dict[str, str] | None:
    """Elige evidencia congelada cuyo path pertenezca a la unidad de crédito."""
    if not frozen_rows:
        return None
    credit_norm = str(credit_path or "").replace("\\", "/").strip().strip("/").casefold()
    if not credit_norm:
        return None
    for row in frozen_rows:
        path = str(row.get("path") or "").replace("\\", "/").strip().strip("/").casefold()
        if path and (path == credit_norm or path.startswith(credit_norm + "/")):
            return row
    return None


async def _load_frozen_evidence_from_review_children(
    client: GraphApiPort,
    *,
    site_id: str,
    drive_id: str,
    children: list[dict[str, Any]],
) -> list[dict[str, str]]:
    """Lee evidencia congelada desde el Excel de revisión existente (pre-purge)."""
    for item in children:
        name = str(item.get("name") or "")
        if not name.lower().endswith(".xlsx") or name.startswith("~$"):
            continue
        item_id = str(item.get("id") or "").strip()
        if not item_id:
            continue
        try:
            raw = await client.get_bytes(
                f"/sites/{site_id}/drives/{drive_id}/items/{item_id}/content"
            )
            wb = await asyncio.to_thread(openpyxl.load_workbook, io.BytesIO(raw), data_only=True)
        except Exception:
            logger.warning("frozen_evidence_load_failed name=%s", name, exc_info=True)
            continue
        if ReviewSheets.META not in wb.sheetnames:
            continue
        rows = parse_frozen_evidence_from_meta_sheet(wb[ReviewSheets.META])
        if rows:
            return rows
    return []

async def _purge_review_folder_loose_files(
    client: GraphApiPort,
    *,
    site_id: str,
    drive_id: str,
    review_folder_path: str,
    children: list[dict[str, Any]],
) -> list[str]:
    """Elimina archivos sueltos en la carpeta de revisión (no subcarpetas ni ~$).

    Usado solo en Regenerar (`force_regenerate`) para no exigir limpieza manual
    ni fallar con ``review_folder_not_empty`` tras cancelar el lote.
    """
    folder = str(review_folder_path or "").replace("\\", "/").strip().strip("/")
    purged: list[str] = []
    for item in children:
        name = str(item.get("name") or "").strip()
        if not name or name.startswith("~$"):
            continue
        if item.get("folder") is not None:
            continue
        rel = f"{folder}/{name}" if folder else name
        enc = encode_graph_drive_path(rel)
        endpoint = f"/sites/{site_id}/drives/{drive_id}/root:/{enc}:"
        try:
            await client.delete(endpoint)
            purged.append(rel)
            logger.info("generate: purge revisión path=%s", rel)
        except httpx.HTTPStatusError as exc:
            code = exc.response.status_code if exc.response is not None else 0
            if code == 404:
                continue
            logger.warning(
                "generate: no se pudo purgar archivo de revisión path=%s http=%s",
                rel,
                code,
            )
        except Exception as exc:
            logger.warning(
                "generate: error purgando archivo de revisión path=%s: %s",
                rel,
                exc,
            )
    return purged

def _build_review_workbook_bytes(
    *,
    process_id: str,
    process_date: date,
    payment_cases: list[dict[str, Any]],
    distribution_rows: list[dict[str, Any]],
    abono_distribution_rows: list[dict[str, Any]],
    error_records: list[dict[str, Any]],
    transacciones_banco: int,
    pagos_detectados: int,
    abonos_detectados: int,
    bank_code: str = "",
) -> tuple[bytes, str]:
    """Construye Excel de revision schema v4 (Aplicacion_Pagos)."""
    _ = (
        payment_cases,
        abono_distribution_rows,
        transacciones_banco,
        pagos_detectados,
        abonos_detectados,
    )
    payload = build_review_workbook_v4_bytes(
        process_id=process_id,
        process_date=process_date,
        bank_code=bank_code or "",
        aplicacion_rows=distribution_rows,
        error_records=error_records,
    )
    return payload, "v4"


async def _announce_control_generating(
    client: GraphApiPort,
    *,
    site_id: str,
    drive_id: str,
    bank_code: str,
    job_id: str | None,
    snap: Any,
    process_key: str,
    process_id: str,
    process_date: date,
    bank_name: str,
) -> None:
    """Publica progreso durable para que Panel/ficha no lean CANCELADO/VACIO a medias."""
    from app.application.use_cases.payment_validation_process_control import (
        update_process_control_row2,
        utc_now_iso,
    )

    updates: dict[str, Any] = {
        "EstadoProceso": "GENERANDO",
        "IsActive": True,
        "GenerateJobId": job_id or "",
        "LastStepStatus": "RUNNING",
        "LastUpdatedAtProceso": utc_now_iso(),
        "LastStepErrorCode": "",
        "LastErrorUserMessage": "",
        "LastErrorNextAction": "",
    }
    if not (snap.process_key or "").strip():
        updates["ProcessKey"] = process_key
        updates["ProcessId"] = process_id
        updates["ProcessDate"] = process_date.isoformat()
        updates["BankCode"] = bank_code
        updates["BankName"] = bank_name
    await update_process_control_row2(
        client, site_id, drive_id, bank_code=bank_code, updates=updates
    )


async def announce_control_generate_failed(
    client: GraphApiPort,
    *,
    bank_code: str,
    job_id: str | None = None,
) -> None:
    """Best-effort: si Generate falló tras anunciar GENERANDO, no dejar el Control colgado."""
    from app.application.config.payment_validation_settings import require_bank_code
    from app.application.sharepoint_resolution import (
        require_operations_site_config,
        resolve_sharepoint_path,
    )
    from app.application.use_cases.payment_validation_process_control import (
        update_process_control_row2,
        utc_now_iso,
    )

    try:
        bank_code = require_bank_code(bank_code)
        require_operations_site_config()
        site_search = os.getenv("GRAPH_SHAREPOINT_SITE_SEARCH", "").strip()
        drive_name = os.getenv("GRAPH_SHAREPOINT_DRIVE_NAME", "").strip()
        review_path = os.getenv("GRAPH_PAYMENT_VALIDATION_REVIEW_PATH", "").strip()
        if not review_path:
            from app.application.config.payment_validation_settings import (
                get_payment_validation_paths,
            )

            review_path = get_payment_validation_paths().review
        if not all([site_search, drive_name, review_path]):
            return
        review_info = await resolve_sharepoint_path(
            client, site_search, drive_name, review_path
        )
        await update_process_control_row2(
            client,
            review_info["site_id"],
            review_info["drive_id"],
            bank_code=bank_code,
            updates={
                "EstadoProceso": "ERROR_GENERATE",
                "IsActive": True,
                "GenerateJobId": job_id or "",
                "LastStepStatus": "FAILED",
                "LastUpdatedAtProceso": utc_now_iso(),
            },
        )
    except Exception:
        logger.warning(
            "generate: no se pudo escribir ERROR_GENERATE bank=%s",
            bank_code,
            exc_info=True,
        )


async def generate_payment_validation(
    client: GraphApiPort,
    process_date: date,
    *,
    bank_code: str,
    job_id: str | None = None,
    force_regenerate: bool = False,
) -> dict[str, Any]:
    site_search = os.getenv("GRAPH_SHAREPOINT_SITE_SEARCH", "").strip()
    drive_name = os.getenv("GRAPH_SHAREPOINT_DRIVE_NAME", "").strip()
    review_path = os.getenv("GRAPH_PAYMENT_VALIDATION_REVIEW_PATH", "").strip()
    clients_path = os.getenv("GRAPH_CLIENTS_BASE_PATH", "").strip()
    file_prefix = os.getenv("GRAPH_VALIDATION_FILE_PREFIX", "").strip()

    from app.application.config.payment_validation_settings import (
        get_payment_validation_paths,
        is_excluded_client_folder,
        require_bank_code,
        resolve_bank_display_name,
        resolve_bank_input_file_path,
        resolve_client_folder_exclusions,
    )
    from app.application.use_cases.payment_validation_process_control import (
        read_process_control_snapshot,
        resolve_process_control_path_for_bank,
        update_process_control_row2,
        utc_now_iso,
        validate_bank_code,
    )
    from app.application.use_cases.setup_merge_control_workbook import (
        build_payment_validation_process_key,
        build_process_artifact_filename,
        process_date_from_process_key,
        process_id_from_process_key,
    )

    bank_code = require_bank_code(bank_code)

    paths = get_payment_validation_paths()
    if not review_path:
        review_path = paths.review

    bank_path = resolve_bank_input_file_path(bank_code)

    require_operations_site_config()
    if not all([review_path, bank_path, clients_path, file_prefix]):
        raise ValueError("missing_sharepoint_folder")

    review_info = await resolve_sharepoint_path(client, site_search, drive_name, review_path)
    site_id = review_info["site_id"]
    drive_id = review_info["drive_id"]

    # Idempotencia: reutilizar el lote en curso del mismo día calendario.
    # Tras AMORTIZACION_APLICADA / soft-close / VACIO / CANCELADO se permite
    # un lote nuevo el mismo día.
    # Si el Excel registrado ya no existe y el lote sigue en revisión (pre-Finalize),
    # se permite recrear (p. ej. secretaria borró el archivo para regenerar).
    closed_for_new_lote = frozenset(
        {
            "AMORTIZACION_APLICADA",
            "VACIO",
            "CANCELADO",
            "CERRADO_SIN_AMORTIZAR",
        }
    )
    already_generated = False
    file_action = "created"
    recreate_missing_review = False
    control_updated = False
    bank_name = resolve_bank_display_name(bank_code)
    process_control_file_path = resolve_process_control_path_for_bank(bank_code).strip().strip("/")

    snap = await read_process_control_snapshot(client, site_id, drive_id, bank_code=bank_code)
    terminal = {
        "VACIO",
        "CONSOLIDADO",
        "MERGE_PARCIAL",
        "AMORTIZACION_APLICADA",
        "ERROR_GENERATE",
        "ERROR_FINALIZE",
        "ERROR_NOTIFY",
        "ERROR_MERGE",
        "ERROR_APPLY",
    }
    estado = (snap.estado_proceso or "").strip()
    # True = Regenerar desde UI: no exigir carpeta vacía; purgar Excels sueltos.
    regenerate_mode = False

    # Regeneración forzada (UI): cancelar lote pre-Finalize y continuar Generate.
    # Si el Control ya quedó idle (p. ej. cancel OK pero Generate falló después),
    # se reintenta el Generate con la fecha pedida sin volver a exigir REVISION_CREADA.
    # GENERANDO huérfano (job muerto tras anunciar progreso): reanudar sin cancelar.
    if force_regenerate:
        preserved_date = process_date_from_process_key(snap.process_key) or process_date
        if (estado or "").strip().upper() == "GENERANDO":
            process_date = preserved_date
            regenerate_mode = True
            logger.info(
                "generate: force_regenerate resume GENERANDO bank=%s date=%s",
                bank_code,
                process_date.isoformat(),
            )
        elif snap.is_active and estado in _GENERATE_RECREATE_ALLOWED_STATES:
            from app.application.use_cases.payment_validation_cancel import (
                cancel_active_payment_validation,
            )

            await cancel_active_payment_validation(
                client,
                bank_code=bank_code,
                process_key=(snap.process_key or "").strip() or None,
                job_id=job_id,
            )
            process_date = preserved_date
            snap = await read_process_control_snapshot(
                client, site_id, drive_id, bank_code=bank_code
            )
            estado = (snap.estado_proceso or "").strip()
            regenerate_mode = True
            logger.info(
                "generate: force_regenerate bank=%s date=%s estado_tras_cancel=%s",
                bank_code,
                process_date.isoformat(),
                estado,
            )
        elif (not snap.is_active) and estado.upper() in _FORCE_REGENERATE_IDLE_STATES:
            process_date = preserved_date
            regenerate_mode = True
            logger.info(
                "generate: force_regenerate recovery idle bank=%s date=%s estado=%s",
                bank_code,
                process_date.isoformat(),
                estado or "VACIO",
            )
        else:
            raise ValueError(f"force_regenerate_not_allowed|{estado or 'VACIO'}")

    existing_date = process_date_from_process_key(snap.process_key)
    if (
        (snap.process_key or "").strip()
        and (snap.validation_file_path or "").strip()
        and existing_date == process_date
        and estado not in closed_for_new_lote
    ):
        registered_path = str(snap.validation_file_path or "").strip()
        review_file_exists = await _sharepoint_drive_file_exists(
            client, site_id, drive_id, registered_path
        )
        if review_file_exists:
            already_generated = True
            file_action = "reused"
            return {
                "process_id": (snap.process_id or process_id_from_process_key(snap.process_key) or ""),
                "validation_file": registered_path.rsplit("/", 1)[-1],
                "validation_file_path": registered_path,
                "validation_file_url": None,
                "summary": {"pagos_banco": 0, "errores": 0, "conditional_formatting": "n/a"},
                "bank_code": bank_code,
                "bank_name": bank_name,
                "process_key": snap.process_key,
                "process_control_file_path": process_control_file_path,
                "process_control_updated": False,
                "process_control_estado": estado or "REVISION_CREADA",
                "already_generated": True,
                "file_action": file_action,
                "generate_idempotency_key": snap.process_key,
            }
        if estado in _GENERATE_RECREATE_ALLOWED_STATES:
            recreate_missing_review = True
            logger.warning(
                "generate: Excel de revisión ausente path=%r estado=%r process_key=%r → se recreará",
                registered_path,
                estado,
                snap.process_key,
            )
        else:
            # Proceso ya avanzó (p. ej. FINALIZADO): no recrear por ausencia de archivo.
            already_generated = True
            file_action = "reused"
            return {
                "process_id": (snap.process_id or process_id_from_process_key(snap.process_key) or ""),
                "validation_file": registered_path.rsplit("/", 1)[-1],
                "validation_file_path": registered_path,
                "validation_file_url": None,
                "summary": {"pagos_banco": 0, "errores": 0, "conditional_formatting": "n/a"},
                "bank_code": bank_code,
                "bank_name": bank_name,
                "process_key": snap.process_key,
                "process_control_file_path": process_control_file_path,
                "process_control_updated": False,
                "process_control_estado": estado or "REVISION_CREADA",
                "already_generated": True,
                "file_action": file_action,
                "generate_idempotency_key": snap.process_key,
            }

    if (
        snap.is_active
        and (estado not in terminal)
        and snap.process_key
        and not recreate_missing_review
        and not regenerate_mode
    ):
        raise ValueError(f"active_process_exists|{snap.process_key}|{estado}")

    process_id = str(uuid.uuid4())
    process_key = build_payment_validation_process_key(
        bank_code, process_date.isoformat(), process_id
    )

    # Iniciar validación (Panel): carpeta de revisión debe estar vacía.
    # Regenerar (force_regenerate): purga Excels sueltos y continúa (con o sin archivo).
    review_children = await client.get(
        f"/sites/{site_id}/drives/{drive_id}/root:/{review_info['path_encoded']}:/children"
    )
    valid_children = [
        item
        for item in review_children.get("value", [])
        if not str(item.get("name") or "").startswith("~$")
    ]
    frozen_evidence_rows: list[dict[str, str]] = []
    if regenerate_mode:
        if valid_children:
            frozen_evidence_rows = await _load_frozen_evidence_from_review_children(
                client,
                site_id=site_id,
                drive_id=drive_id,
                children=valid_children,
            )
            await _purge_review_folder_loose_files(
                client,
                site_id=site_id,
                drive_id=drive_id,
                review_folder_path=review_path,
                children=valid_children,
            )
    elif valid_children:
        raise ValueError("review_folder_not_empty")

    try:
        await _announce_control_generating(
            client,
            site_id=site_id,
            drive_id=drive_id,
            bank_code=bank_code,
            job_id=job_id,
            snap=snap,
            process_key=process_key,
            process_id=process_id,
            process_date=process_date,
            bank_name=bank_name,
        )
    except Exception:
        logger.warning(
            "generate: no se pudo anunciar GENERANDO bank=%s",
            bank_code,
            exc_info=True,
        )

    bank_info = await resolve_sharepoint_path(client, site_search, drive_name, bank_path)
    bank_bytes = await client.get_bytes(
        _build_content_endpoint(bank_info["site_id"], bank_info["drive_id"], bank_info["file_path"])
    )

    # openpyxl sync fuera del event loop (1 worker Azure: no bloquear /jobs|/health).
    bank_workbook = await asyncio.to_thread(
        openpyxl.load_workbook, io.BytesIO(bank_bytes), data_only=True
    )
    bank_sheet = bank_workbook.active

    col_map, start_row, _detected_headers, _header_row_index = _parse_bank_sheet_headers(bank_sheet)
    processable_bank_rows = _collect_processable_bank_rows(
        bank_sheet, col_map, start_row, process_date
    )
    transacciones_banco = len(processable_bank_rows)
    # Generate neutro: aun no hay Tipo; metricas de pagos/abonos se resuelven en Finalize.
    pagos_detectados = transacciones_banco
    pagos_con_abono_capital_detectados = 0
    abonos_capital_detectados = 0
    abonos_mora_detectados = 0
    abonos_detectados = 0

    clients_info = await resolve_sharepoint_path(client, site_search, drive_name, clients_path)
    client_children = await client.get(
        f"/sites/{clients_info['site_id']}/drives/{clients_info['drive_id']}/root:/{clients_info['path_encoded']}:/children"
    )
    # Las carpetas de automatización conviven con los clientes; excluirlas evita
    # coincidencias parciales espurias al emparejar el nombre del cliente.
    client_exclusions = resolve_client_folder_exclusions(clients_path)
    client_folders = [
        item
        for item in client_children.get("value", [])
        if "folder" in item
        and not is_excluded_client_folder(str(item.get("name", "")), client_exclusions)
    ]
    client_index = {_normalize_str(item.get("name", "")): item.get("name", "") for item in client_folders}

    payment_cases: list[dict[str, Any]] = []
    distribution_rows: list[dict[str, Any]] = []
    abono_distribution_rows: list[dict[str, Any]] = []
    error_records: list[dict[str, Any]] = []
    # Cache por carpeta de cliente: en lotes de estrés reutiliza extractos/créditos
    # ya resueltos (evita N× Graph/PDF por el mismo cliente).
    credit_cache_pago: dict[tuple[str, str], tuple[list[dict[str, Any]], list[dict[str, Any]]]] = {}
    credit_cache_abono: dict[str, tuple[list[dict[str, Any]], list[dict[str, Any]]]] = {}
    credit_cache_abono_mora: dict[str, tuple[list[dict[str, Any]], list[dict[str, Any]]]] = {}

    total_bank_rows = len(processable_bank_rows)
    for row_idx, entry in enumerate(processable_bank_rows, start=1):
        # Cede el event loop: evita que /health y GET /jobs se queden sin responder
        # durante lotes grandes (causa recycles del App Service).
        await asyncio.sleep(0)
        if job_id and row_idx % 5 == 1:
            try:
                from app.application.job_manager import JobManager
                from app.application.services.colombia_time import now_colombia_iso

                await JobManager().set_job(
                    job_id,
                    {
                        "updated_at": now_colombia_iso(),
                        "progress": {
                            "bank_rows_done": row_idx - 1,
                            "bank_rows_total": total_bank_rows,
                        },
                    },
                )
            except Exception:
                logger.exception("job %s: no se pudo registrar progress Generate", job_id)
        row = entry["row"]
        payment_id = str(uuid.uuid4())
        concepto = entry["concepto"]
        transaccion = entry["transaccion"]
        cliente_raw = "Desconocido"
        try:
            fecha_banco = parse_bank_date(row[col_map["fecha"]], process_date)
            monto_banco = parse_bank_amount(row[col_map["credito"]])
            cliente_raw = extract_client_from_bank_row(concepto, transaccion)
            cliente_norm = _normalize_str(cliente_raw)

            if cliente_norm in client_index:
                cliente_folder = client_index[cliente_norm]
            else:
                candidates = [
                    name
                    for norm, name in client_index.items()
                    if cliente_norm in norm or norm in cliente_norm
                ]
                if not candidates:
                    raise ValueError("customer_not_found")
                if len(candidates) > 1:
                    raise ValueError("customer_ambiguous")
                cliente_folder = candidates[0]

            payment = {
                "id_pago": payment_id,
                "fecha_banco": fecha_banco,
                "monto_banco": monto_banco,
                "cliente": cliente_folder,
                "concepto": concepto,
                "transaccion": transaccion,
            }

            # Discovery por cliente + fecha banco (as-of); no reutilizar abril en mayo.
            cache_key = (cliente_folder, fecha_banco.isoformat())
            if cache_key in credit_cache_pago:
                credit_candidates, credit_issues = credit_cache_pago[cache_key]
                record_credit_issues = False
            else:
                credit_candidates, credit_issues = await _load_credit_candidates(
                    client,
                    site_search,
                    drive_name,
                    clients_path,
                    cliente_folder,
                    bank_date=fecha_banco,
                    bank_code=bank_code,
                    process_date=process_date,
                    frozen_evidence_rows=frozen_evidence_rows,
                )
                credit_cache_pago[cache_key] = (credit_candidates, credit_issues)
                record_credit_issues = True
            if record_credit_issues:
                _append_credit_issue_records(
                    error_records,
                    payment_id=payment_id,
                    cliente_folder=cliente_folder,
                    credit_issues=credit_issues,
                )

            if not credit_candidates:
                continue

            payment_distribution_rows = _build_aplicacion_rows(payment, credit_candidates)
            distribution_rows.extend(payment_distribution_rows)
            payment_cases.append(
                {
                    "id_pago": payment_id,
                    "cliente": cliente_folder,
                    "monto_banco": monto_banco,
                    "fecha_banco": fecha_banco.isoformat(),
                }
            )
        except Exception as exc:
            code = str(exc)
            logger.warning(
                "generate_payment_validation bank_row_failed payment_id=%s code=%s",
                payment_id,
                code,
                exc_info=True,
            )
            link_carpeta_exc_url = ""
            cf = locals().get("cliente_folder")
            if isinstance(cf, str) and cf and code == "credit_folder_not_found":
                link_carpeta_exc_url = ""
            error_records.append(
                {
                    "id_pago": payment_id,
                    "cliente": cliente_raw,
                    "credito": "",
                    "code": code,
                    "link_extracto_url": "",
                    "link_carpeta_credito_url": link_carpeta_exc_url,
                }
            )

    # Construcción Excel (CPU intensiva) fuera del event loop.
    xlsx_bytes, formatting_strategy = await asyncio.to_thread(
        _build_review_workbook_bytes,
        process_id=process_id,
        process_date=process_date,
        payment_cases=payment_cases,
        distribution_rows=distribution_rows,
        abono_distribution_rows=abono_distribution_rows,
        error_records=error_records,
        transacciones_banco=transacciones_banco,
        pagos_detectados=pagos_detectados,
        abonos_detectados=abonos_detectados,
        bank_code=bank_code,
    )

    file_name = build_process_artifact_filename(
        kind=file_prefix,
        bank_code=bank_code,
        process_date=process_date.isoformat(),
        process_id=process_id,
    )
    upload_path = f"{review_path}/{file_name}"
    upload_resp = await client.put_bytes(
        _build_content_endpoint(review_info["site_id"], review_info["drive_id"], upload_path),
        xlsx_bytes,
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
    validation_file_url: str | None = (
        upload_resp.get("webUrl") if isinstance(upload_resp, dict) else None
    )

    # Si se reemplaza un lote previo (p. ej. tras AMORTIZACION_APLICADA),
    # archivar snapshot del Control anterior (red de seguridad Fase 2).
    prior_key = str(snap.process_key or "").strip()
    if prior_key and prior_key != process_key:
        try:
            from app.application.ui.process_archive import try_archive_process_snapshot

            await try_archive_process_snapshot(
                client,
                site_id,
                drive_id,
                snap,
                archive_reason="generate_overwrite",
            )
        except Exception:
            pass

    # Actualizar control por banco al éxito.
    now_iso = utc_now_iso()
    updates: dict[str, Any] = {
        "ProcessKey": process_key,
        "ProcessDate": process_date.isoformat(),
        "BankCode": bank_code,
        "BankName": bank_name,
        "ProcessId": process_id,
        "ValidationFilePath": upload_path.strip().strip("/"),
        "EstadoProceso": "REVISION_CREADA",
        "IsActive": True,
        "GenerateIdempotencyKey": process_key,
        "GenerateJobId": job_id or "",
        "LastCompletedStep": "GENERATE",
        "LastStepStatus": "COMPLETED",
        "LastStepErrorCode": "",
        "LastUpdatedAtProceso": now_iso,
        # Limpiar evidencia de lotes anteriores del mismo banco (Notify/Merge/Apply).
        "HistoricalFilePath": "",
        "SecretaryFilePath": "",
        "EmailPdfPath": "",
        "MergeManifestPath": "",
        "FinalizeIdempotencyKey": "",
        "NotifyIdempotencyKey": "",
        "MergeIdempotencyKey": "",
        "ApplyIdempotencyKey": "",
        "FinalizeJobId": "",
        "NotifyJobId": "",
        "MergeJobId": "",
        "ApplyJobId": "",
        "MergeOutputCount": 0,
        "MergeSkippedCount": 0,
        "LastErrorUserMessage": "",
        "LastErrorNextAction": "",
    }
    if not (str(snap.process_key or "").strip()) or snap.process_key != process_key:
        updates["CreatedAtProceso"] = now_iso
    await update_process_control_row2(client, site_id, drive_id, bank_code=bank_code, updates=updates)
    control_updated = True

    result_payload: dict[str, Any] = {
        "process_id": process_id,
        "validation_file": file_name,
        "validation_file_path": upload_path,
        "validation_file_url": validation_file_url,
        "application_types_supported": [],  # Tipo se decide en revision (schema v4)
        "pagos_detectados": pagos_detectados,
        "pagos_con_abono_capital_detectados": pagos_con_abono_capital_detectados,
        "abonos_capital_detectados": abonos_capital_detectados,
        "abonos_mora_detectados": abonos_mora_detectados,
        "abonos_detectados": abonos_detectados,
        "distribution_payments_sheet": ReviewSheets.APLICACION_PAGOS,
        "distribution_abonos_sheet": None,  # v4: hoja unica Aplicacion_Pagos
        "summary": {
            "pagos_banco": transacciones_banco,
            "transacciones_banco": transacciones_banco,
            "pagos_detectados": pagos_detectados,
            "pagos_con_abono_capital_detectados": pagos_con_abono_capital_detectados,
            "abonos_capital_detectados": abonos_capital_detectados,
            "abonos_mora_detectados": abonos_mora_detectados,
            "abonos_detectados": abonos_detectados,
            "filas_distribucion_pagos": len(distribution_rows),
            "filas_distribucion_abonos": len(abono_distribution_rows),
            "errores": len(error_records),
            "conditional_formatting": formatting_strategy,
        },
        "bank_code": bank_code,
        "bank_name": bank_name,
        "process_key": process_key,
        "process_control_file_path": process_control_file_path,
        "process_control_updated": control_updated,
        "process_control_estado": "REVISION_CREADA",
        "already_generated": False,
        "file_action": "recreated" if recreate_missing_review else file_action,
        "generate_idempotency_key": process_key,
    }
    if abonos_detectados > 0:
        result_payload["user_message"] = (
            "Se creó el archivo de revisión con pagos y abonos. "
            "Revise la hoja Aplicacion_Pagos para los pagos y Aplicacion_Pagos para seleccionar "
            "los créditos de los abonos."
        )
        result_payload["next_action"] = (
            "Abra el Excel de la carpeta de revisión. Complete Aplicacion_Pagos (pagos) y marque Validar Abono en "
            "Aplicacion_Pagos. En Control ponga Procesar = SI cuando termine."
        )
    return result_payload
