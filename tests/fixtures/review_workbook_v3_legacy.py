"""Fixture mínimo de workbook v3 (21 columnas) para detección fail-closed.

No es un builder productivo. Generate emite solo v4; Finalize exige regenerar v3.
"""
from __future__ import annotations

from datetime import date
from io import BytesIO
from typing import Any

import openpyxl

from app.application.services.review_schema import (
    REVIEW_SCHEMA_VERSION_V3,
    AplicacionPagosColsV3,
    MetaCols,
    ReviewSheets,
)


def build_review_workbook_v3_bytes(
    *,
    process_id: str = "legacy",
    process_date: date | None = None,
    bank_code: str = "banco_bogota",
    aplicacion_rows: list[dict[str, Any]] | None = None,
    error_records: list[dict[str, Any]] | None = None,
) -> bytes:
    _ = (process_date, error_records)
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = ReviewSheets.APLICACION_PAGOS
    ws.append(["APLICACIÓN DE PAGOS (esquema histórico v3)"])
    ws.append(["Este archivo no es el contrato operativo actual."])
    ws.append(list(AplicacionPagosColsV3.HEADERS))
    for row in aplicacion_rows or []:
        ws.append([row.get(h, "") for h in AplicacionPagosColsV3.HEADERS])
    ws_meta = wb.create_sheet(ReviewSheets.META)
    ws_meta.append(["Campo", "Valor"])
    ws_meta.append([MetaCols.ROW_REVIEW_SCHEMA_VERSION, REVIEW_SCHEMA_VERSION_V3])
    ws_meta.append(["ProcessId", process_id])
    ws_meta.append(["BankCode", bank_code])
    out = BytesIO()
    wb.save(out)
    return out.getvalue()
