"""CAPA B: edita solo las 6 columnas humanas del review Aplicacion_Pagos."""
from __future__ import annotations

import io
from typing import Any, Callable

from openpyxl import load_workbook

from app.application.services.review_schema import AplicacionPagosCols, ReviewSheets

HUMAN_COLS = frozenset(AplicacionPagosCols.SECRETARY_EDITABLE)
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


def _recalc_totals(ws, col: dict[str, int]) -> None:
    """Total por fila + Saldo por asignar por ID Pago (solo Validar=SI)."""
    if AplicacionPagosCols.TOTAL_ASIGNADO not in col:
        return
    first_row_by_id: dict[str, int] = {}
    assigned_by_id: dict[str, float] = {}
    banco_by_id: dict[str, float] = {}
    for excel_row in range(2, ws.max_row + 1):
        pid = ""
        if AplicacionPagosCols.ID_PAGO in col:
            pid = str(ws.cell(excel_row, col[AplicacionPagosCols.ID_PAGO]).value or "").strip()
        total = (
            _as_float(
                ws.cell(excel_row, col[AplicacionPagosCols.APLICAR_OBLIGACION_ACTUAL]).value
                if AplicacionPagosCols.APLICAR_OBLIGACION_ACTUAL in col
                else 0
            )
            + _as_float(
                ws.cell(excel_row, col[AplicacionPagosCols.APLICAR_SALDO_VENCIDO]).value
                if AplicacionPagosCols.APLICAR_SALDO_VENCIDO in col
                else 0
            )
            + _as_float(
                ws.cell(excel_row, col[AplicacionPagosCols.ABONO_ADICIONAL_CAPITAL]).value
                if AplicacionPagosCols.ABONO_ADICIONAL_CAPITAL in col
                else 0
            )
        )
        ws.cell(excel_row, col[AplicacionPagosCols.TOTAL_ASIGNADO]).value = total
        if not pid:
            continue
        first_row_by_id.setdefault(pid, excel_row)
        if AplicacionPagosCols.MONTO_BANCO in col:
            monto = _as_float(ws.cell(excel_row, col[AplicacionPagosCols.MONTO_BANCO]).value)
            if monto > 0:
                banco_by_id[pid] = monto
        validar = ""
        if AplicacionPagosCols.VALIDAR_PAGO in col:
            validar = str(
                ws.cell(excel_row, col[AplicacionPagosCols.VALIDAR_PAGO]).value or ""
            ).strip().upper()
        if validar == "SI":
            assigned_by_id[pid] = assigned_by_id.get(pid, 0.0) + total
    if AplicacionPagosCols.SALDO_POR_ASIGNAR not in col:
        return
    for excel_row in range(2, ws.max_row + 1):
        pid = ""
        if AplicacionPagosCols.ID_PAGO in col:
            pid = str(ws.cell(excel_row, col[AplicacionPagosCols.ID_PAGO]).value or "").strip()
        if not pid:
            continue
        saldo = round(banco_by_id.get(pid, 0.0) - assigned_by_id.get(pid, 0.0), 2)
        ws.cell(excel_row, col[AplicacionPagosCols.SALDO_POR_ASIGNAR]).value = (
            saldo if excel_row == first_row_by_id.get(pid) else None
        )


def edit_aplicacion_pagos_rows(
    raw: bytes,
    *,
    row_updater: Callable[[dict[str, Any], int], dict[str, Any] | None],
) -> tuple[bytes, list[dict[str, Any]]]:
    """Aplica updater a cada fila de datos (solo columnas humanas)."""
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
        applied.append({"excel_row": excel_row, "updates": updates})

    _recalc_totals(ws, col)
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
    credito_contains: str = "231",
    force_monto_banco: float | None = None,
) -> tuple[bytes, list[dict[str, Any]]]:
    """Marca SI el crédito objetivo; el resto del ID Pago queda NO (nunca POR DEFINIR).

    ``force_monto_banco``: deja Monto banco float **solo en la fila SI** del ID Pago.
    Elimina filas hermanas del mismo ID (candidatos NO) para que esa SI sea también
    la primera fila del grupo: Finalize (monto_casos / no-duplicate) y Merge/histórico
    (solo lee SI) coinciden. Necesario para ABONO cuando Generate deja Monto banco
    solo en la primera candidata o como fórmula/texto.
    """
    chosen: int | None = None
    chosen_pid: str = ""

    def updater(row: dict[str, Any], excel_row: int) -> dict[str, Any] | None:
        nonlocal chosen, chosen_pid
        credito = str(row.get(AplicacionPagosCols.CREDITO) or "")
        if not credito.strip():
            return None
        is_target = (not credito_contains) or (credito_contains in credito)
        if is_target and chosen is None:
            chosen = excel_row
            chosen_pid = str(row.get(AplicacionPagosCols.ID_PAGO) or "").strip()
            monto = row.get(AplicacionPagosCols.MONTO_BANCO)
            try:
                monto_f = float(monto) if monto is not None else 0.0
            except (TypeError, ValueError):
                monto_f = 0.0
            a = obligacion if obligacion is not None else monto_f
            updates = {
                AplicacionPagosCols.VALIDAR_PAGO: "SI",
                AplicacionPagosCols.APLICAR_OBLIGACION_ACTUAL: a,
                AplicacionPagosCols.APLICAR_SALDO_VENCIDO: vencido,
                AplicacionPagosCols.ABONO_ADICIONAL_CAPITAL: capital,
                AplicacionPagosCols.TIPO_APLICACION: tipo,
                AplicacionPagosCols.OBSERVACION: observacion,
            }
            return updates
        return {
            AplicacionPagosCols.VALIDAR_PAGO: "NO",
            AplicacionPagosCols.APLICAR_OBLIGACION_ACTUAL: 0,
            AplicacionPagosCols.APLICAR_SALDO_VENCIDO: 0,
            AplicacionPagosCols.ABONO_ADICIONAL_CAPITAL: 0,
            AplicacionPagosCols.TIPO_APLICACION: "",
            AplicacionPagosCols.OBSERVACION: observacion,
        }

    edited, applied = edit_aplicacion_pagos_rows(raw, row_updater=updater)
    if force_monto_banco is None or not chosen_pid or chosen is None:
        return edited, applied
    wb = load_workbook(io.BytesIO(edited))
    ws = wb[ReviewSheets.APLICACION_PAGOS]
    col = _header_map(ws)
    if AplicacionPagosCols.MONTO_BANCO not in col or AplicacionPagosCols.ID_PAGO not in col:
        return edited, applied
    # Quitar candidatas NO del mismo ID Pago (de abajo hacia arriba).
    drop: list[int] = []
    for excel_row in range(2, ws.max_row + 1):
        pid = str(ws.cell(excel_row, col[AplicacionPagosCols.ID_PAGO]).value or "").strip()
        if pid == chosen_pid and excel_row != chosen:
            drop.append(excel_row)
    for excel_row in reversed(drop):
        ws.delete_rows(excel_row, 1)
    # Reubicar SI (índice pudo moverse) y fijar Monto banco float único.
    si_row: int | None = None
    for excel_row in range(2, ws.max_row + 1):
        pid = str(ws.cell(excel_row, col[AplicacionPagosCols.ID_PAGO]).value or "").strip()
        if pid != chosen_pid:
            continue
        validar = str(
            ws.cell(excel_row, col[AplicacionPagosCols.VALIDAR_PAGO]).value or ""
        ).strip().upper()
        if validar == "SI":
            si_row = excel_row
            break
    if si_row is None:
        return edited, applied
    for excel_row in range(2, ws.max_row + 1):
        pid = str(ws.cell(excel_row, col[AplicacionPagosCols.ID_PAGO]).value or "").strip()
        if pid != chosen_pid:
            continue
        if excel_row == si_row:
            ws.cell(excel_row, col[AplicacionPagosCols.MONTO_BANCO]).value = float(
                force_monto_banco
            )
        else:
            ws.cell(excel_row, col[AplicacionPagosCols.MONTO_BANCO]).value = None
    _recalc_totals(ws, col)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue(), applied


def approve_credits_split(
    raw: bytes,
    *,
    splits: list[dict[str, Any]],
    observacion: str = "RC-E2E-split",
) -> tuple[bytes, list[dict[str, Any]]]:
    """Aprueba varias filas crédito; no-matches quedan NO."""
    used: set[int] = set()

    def updater(row: dict[str, Any], excel_row: int) -> dict[str, Any] | None:
        if excel_row in used:
            return None
        credito = str(row.get(AplicacionPagosCols.CREDITO) or "")
        if not credito.strip():
            return None
        for spec in splits:
            needle = str(spec.get("credito_contains") or "").strip()
            if not needle or needle not in credito:
                continue
            used.add(excel_row)
            return {
                AplicacionPagosCols.VALIDAR_PAGO: "SI",
                AplicacionPagosCols.APLICAR_OBLIGACION_ACTUAL: float(
                    spec.get("obligacion") or 0
                ),
                AplicacionPagosCols.APLICAR_SALDO_VENCIDO: float(spec.get("vencido") or 0),
                AplicacionPagosCols.ABONO_ADICIONAL_CAPITAL: float(
                    spec.get("capital") or 0
                ),
                AplicacionPagosCols.TIPO_APLICACION: str(spec.get("tipo") or ""),
                AplicacionPagosCols.OBSERVACION: observacion,
            }
        return {
            AplicacionPagosCols.VALIDAR_PAGO: "NO",
            AplicacionPagosCols.APLICAR_OBLIGACION_ACTUAL: 0,
            AplicacionPagosCols.APLICAR_SALDO_VENCIDO: 0,
            AplicacionPagosCols.ABONO_ADICIONAL_CAPITAL: 0,
            AplicacionPagosCols.TIPO_APLICACION: "",
            AplicacionPagosCols.OBSERVACION: observacion,
        }

    return edit_aplicacion_pagos_rows(raw, row_updater=updater)
