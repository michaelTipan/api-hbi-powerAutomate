"""CAPA B: edita solo las 6 columnas humanas del review Aplicacion_Pagos."""
from __future__ import annotations

import io
from typing import Any, Callable

from openpyxl import load_workbook

from app.application.services.review_schema import AplicacionPagosCols, ReviewSheets

HUMAN_COLS = frozenset(AplicacionPagosCols.SECRETARY_EDITABLE)
# Tras editar A/V/K, Excel Online recalcula estas celdas; CAPA B debe simularlo.
FORMULA_RESULT_COLS = frozenset(
    {
        AplicacionPagosCols.TOTAL_ASIGNADO,
        AplicacionPagosCols.SALDO_POR_ASIGNAR,
    }
)


def _as_float(value: object) -> float:
    if value is None or value == "":
        return 0.0
    try:
        return float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return 0.0


def _header_map(ws) -> dict[str, int]:
    headers = [str(c.value).strip() if c.value is not None else "" for c in ws[1]]
    return {h: i + 1 for i, h in enumerate(headers) if h}


def edit_aplicacion_pagos_rows(
    raw: bytes,
    *,
    row_updater: Callable[[dict[str, Any], int], dict[str, Any] | None],
) -> tuple[bytes, list[dict[str, Any]]]:
    """Aplica updater a cada fila de datos.

    ``row_updater(row_dict, excel_row)`` debe devolver un dict con SOLO keys humanas
    a escribir, o None para no tocar la fila.
    Tras escribir, recalcula Total asignado / Saldo por asignar (como Excel Online).
    """
    wb = load_workbook(io.BytesIO(raw))
    sheet_name = ReviewSheets.APLICACION_PAGOS
    if sheet_name not in wb.sheetnames:
        candidates = [n for n in wb.sheetnames if "aplicacion" in n.lower()]
        if not candidates:
            raise RuntimeError(f"missing_sheet:{sheet_name}; have={wb.sheetnames}")
        sheet_name = candidates[0]
    ws = wb[sheet_name]
    col = _header_map(ws)
    missing = HUMAN_COLS - set(col)
    if missing:
        raise RuntimeError(f"missing_human_cols:{sorted(missing)}")

    applied: list[dict[str, Any]] = []
    for excel_row in range(2, ws.max_row + 1):
        row_dict: dict[str, Any] = {}
        empty = True
        for name, idx in col.items():
            val = ws.cell(excel_row, idx).value
            if val is not None and str(val).strip() != "":
                empty = False
            row_dict[name] = val
        if empty:
            continue
        updates = row_updater(row_dict, excel_row)
        if not updates:
            continue
        bad = set(updates) - HUMAN_COLS
        if bad:
            raise RuntimeError(f"human_cols_only_violation:{sorted(bad)}")
        for name, value in updates.items():
            ws.cell(excel_row, col[name]).value = value
            row_dict[name] = value
        # Simular recálculo Excel Online de totales.
        if AplicacionPagosCols.TOTAL_ASIGNADO in col and AplicacionPagosCols.SALDO_POR_ASIGNAR in col:
            total = (
                _as_float(row_dict.get(AplicacionPagosCols.APLICAR_OBLIGACION_ACTUAL))
                + _as_float(row_dict.get(AplicacionPagosCols.APLICAR_SALDO_VENCIDO))
                + _as_float(row_dict.get(AplicacionPagosCols.ABONO_ADICIONAL_CAPITAL))
            )
            monto = _as_float(row_dict.get(AplicacionPagosCols.MONTO_BANCO))
            # Saldo por ID Pago: aproximación 1 fila = monto - total (multi-fila se refina en escenarios).
            saldo = round(monto - total, 2)
            ws.cell(excel_row, col[AplicacionPagosCols.TOTAL_ASIGNADO]).value = total
            ws.cell(excel_row, col[AplicacionPagosCols.SALDO_POR_ASIGNAR]).value = saldo
        applied.append({"excel_row": excel_row, "updates": updates})

    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue(), applied


def approve_single_credit_pago(
    raw: bytes,
    *,
    tipo: str,
    obligacion: float | None = None,
    vencido: float = 0.0,
    capital: float = 0.0,
    observacion: str = "RC-E2E",
) -> tuple[bytes, list[dict[str, Any]]]:
    """Marca la primera fila con crédito como SI + montos/tipo dados."""

    def updater(row: dict[str, Any], _excel_row: int) -> dict[str, Any] | None:
        credito = row.get(AplicacionPagosCols.CREDITO)
        if credito is None or str(credito).strip() == "":
            return None
        monto = row.get(AplicacionPagosCols.MONTO_BANCO)
        try:
            monto_f = float(monto) if monto is not None else 0.0
        except (TypeError, ValueError):
            monto_f = 0.0
        a = obligacion if obligacion is not None else monto_f
        return {
            AplicacionPagosCols.VALIDAR_PAGO: "SI",
            AplicacionPagosCols.APLICAR_OBLIGACION_ACTUAL: a,
            AplicacionPagosCols.APLICAR_SALDO_VENCIDO: vencido,
            AplicacionPagosCols.ABONO_ADICIONAL_CAPITAL: capital,
            AplicacionPagosCols.TIPO_APLICACION: tipo,
            AplicacionPagosCols.OBSERVACION: observacion,
        }

    return edit_aplicacion_pagos_rows(raw, row_updater=updater)
