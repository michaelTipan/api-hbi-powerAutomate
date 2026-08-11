"""Vista previa de IBR_DIARIO.xlsx para la fase de amortización (solo lectura).

No aplica tasas: solo muestra lo que dry-run leería para la fecha del proceso
y un resumen de rangos del libro.
"""

from __future__ import annotations

import io
import logging
import os
import unicodedata
from datetime import date, datetime
from typing import Any

import openpyxl

from app.application.config.payment_validation_settings import resolve_ibr_workbook_path
from app.application.services.ibr_workbook import find_ibr_for_date, normalize_ibr_value
from app.application.sharepoint_resolution import (
    require_operations_site_config,
    resolve_sharepoint_path,
)
from app.application.use_cases.setup_ibr_workbook import IBR_COLUMNS, IBR_SHEET_NAME
from app.application.use_cases.setup_merge_control_workbook import (
    process_date_from_process_key,
)
from app.application.use_cases.validate_payment_report import (
    _graph_download_by_path,
    _graph_get_item_metadata_by_path,
)
from app.domain.ports.graph import GraphApiPort

logger = logging.getLogger(__name__)

_AUTOSAVE_HINT = (
    "Si acabas de editar IBR_DIARIO.xlsx en Excel Online, espera unos segundos, "
    "guarda y pulsa Actualizar antes de procesar la amortización."
)
_MAX_RANGES = 8


def _accent_fold_upper(text: str) -> str:
    raw = unicodedata.normalize("NFC", str(text or ""))
    nfkd = unicodedata.normalize("NFD", raw)
    return "".join(c for c in nfkd if unicodedata.category(c) != "Mn").strip().upper()


def _parse_excel_date_value(raw: Any) -> date | None:
    if raw is None:
        return None
    if isinstance(raw, datetime):
        return raw.date()
    if isinstance(raw, date):
        return raw
    text = str(raw).strip()
    if not text:
        return None
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%Y/%m/%d"):
        try:
            return datetime.strptime(text[:10], fmt).date()
        except ValueError:
            continue
    return None


def _list_ibr_ranges(workbook_bytes: bytes, *, limit: int = _MAX_RANGES) -> list[dict[str, Any]]:
    wb = openpyxl.load_workbook(io.BytesIO(workbook_bytes), data_only=True)
    try:
        if IBR_SHEET_NAME not in wb.sheetnames:
            return []
        ws = wb[IBR_SHEET_NAME]
        col_inicio = col_fin = col_valor = None
        for c in range(1, (ws.max_column or 1) + 1):
            h = _accent_fold_upper(str(ws.cell(1, c).value or ""))
            if h == _accent_fold_upper(IBR_COLUMNS[0]):
                col_inicio = c
            elif h == _accent_fold_upper(IBR_COLUMNS[1]):
                col_fin = c
            elif h == _accent_fold_upper(IBR_COLUMNS[2]):
                col_valor = c
        if not col_inicio or not col_fin or not col_valor:
            return []
        rows: list[dict[str, Any]] = []
        for r in range(2, (ws.max_row or 1) + 1):
            inicio = _parse_excel_date_value(ws.cell(r, col_inicio).value)
            fin = _parse_excel_date_value(ws.cell(r, col_fin).value)
            valor = normalize_ibr_value(ws.cell(r, col_valor).value)
            if inicio is None or fin is None or valor is None:
                continue
            rows.append(
                {
                    "inicio": inicio.isoformat(),
                    "fin": fin.isoformat(),
                    "valor": valor,
                    "valor_pct": round(valor * 100, 5),
                }
            )
        # Preferir los más recientes al final del libro.
        return rows[-limit:]
    finally:
        closer = getattr(wb, "close", None)
        if callable(closer):
            closer()


async def load_ibr_preview(graph: GraphApiPort, *, process_key: str) -> dict[str, Any]:
    """Lee IBR_DIARIO y resuelve la tasa para la fecha del ProcessKey."""
    require_operations_site_config()
    key = (process_key or "").strip()
    process_date = process_date_from_process_key(key)
    rel = resolve_ibr_workbook_path().strip().strip("/")
    site_search = (os.getenv("GRAPH_SHAREPOINT_SITE_SEARCH") or "").strip()
    drive_name = (os.getenv("GRAPH_SHAREPOINT_DRIVE_NAME") or "").strip()
    info = await resolve_sharepoint_path(graph, site_search, drive_name, rel)
    site_id = str(info["site_id"])
    drive_id = str(info["drive_id"])
    meta = await _graph_get_item_metadata_by_path(graph, site_id, drive_id, rel)
    last_modified = str(meta.get("lastModifiedDateTime") or "").strip() or None
    data = await _graph_download_by_path(graph, site_id, drive_id, rel)
    ranges = _list_ibr_ranges(data)
    rate: float | None = None
    rate_status = "no_process_date"
    if process_date is not None:
        rate = find_ibr_for_date(data, process_date)
        rate_status = "found" if rate is not None else "missing_for_date"
    warnings: list[str] = [_AUTOSAVE_HINT]
    if rate_status == "missing_for_date":
        warnings.append(
            "No hay rango IBR para la fecha del proceso. El dry-run marcará PENDING_IBR "
            "en los cortes que lo requieran."
        )
    warnings.append(
        "La amortización resuelve IBR por fecha límite de cada crédito; "
        "la tasa mostrada es la de la fecha del lote como referencia."
    )
    user_message = (
        f"IBR de referencia para {process_date.isoformat()}: {rate * 100:.5f}%."
        if process_date is not None and rate is not None
        else (
            f"Sin tasa IBR para la fecha del proceso ({process_date.isoformat()})."
            if process_date is not None
            else "No se pudo obtener la fecha del proceso para resolver IBR."
        )
    )
    return {
        "ok": True,
        "source_path": rel,
        "process_key": key,
        "process_date": process_date.isoformat() if process_date else None,
        "rate": rate,
        "rate_pct": round(rate * 100, 5) if rate is not None else None,
        "rate_status": rate_status,
        "ranges": ranges,
        "file_last_modified": last_modified,
        "warnings": warnings,
        "user_message": user_message,
    }
