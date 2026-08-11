"""Builder mínimo del workbook de revisión schema v3."""
from __future__ import annotations

import io
from datetime import date
from typing import Any

import openpyxl
from openpyxl.styles import Alignment, Font, PatternFill, Protection
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.datavalidation import DataValidation

from app.application.services.review_schema import (
    REVIEW_SCHEMA_VERSION,
    AplicacionPagosCols,
    AplicacionSugerida,
    ErroresCols,
    MetaCols,
    ReviewSheets,
    TipoAplicacionConfirmado,
    ValidarPago,
    compute_aplicacion_sugerida,
    dias_respecto_vencimiento,
)


_HEADER_FILL = PatternFill(fill_type="solid", fgColor="002060")
_HEADER_FONT = Font(name="Calibri", bold=True, size=11, color="FFFFFF")
_LOCKED = Protection(locked=True)
_UNLOCKED = Protection(locked=False)


def _errores_row(rec: dict[str, Any]) -> list[Any]:
    values = {
        ErroresCols.ID_PAGO: rec.get("id_pago"),
        ErroresCols.CLIENTE: rec.get("cliente"),
        ErroresCols.CREDITO: rec.get("credito"),
        ErroresCols.TIPO_CASO: rec.get("tipo_caso") or "",
        ErroresCols.DESCRIPCION: rec.get("descripcion") or rec.get("message") or "",
        ErroresCols.QUE_DEBE_HACER: rec.get("que_debe_hacer") or "",
        ErroresCols.REQUIERE_SOPORTE: rec.get("requiere_soporte") or "",
        ErroresCols.LINK_EXTRACTO: rec.get("link_extracto") or "",
        ErroresCols.LINK_CARPETA_CREDITO: rec.get("link_carpeta_credito") or "",
        ErroresCols.CODIGO_TECNICO: rec.get("codigo") or rec.get("code") or "",
    }
    return [values[c] for c in ErroresCols.HEADERS]


def build_aplicacion_pagos_row(
    payment: dict[str, Any],
    candidate: dict[str, Any],
) -> dict[str, Any]:
    """Fila neutra: Validar Pago = POR DEFINIR; sin autoselección SI."""
    due = candidate.get("fecha_limite")
    fecha_banco = payment["fecha_banco"]
    dias = dias_respecto_vencimiento(fecha_banco, due)

    valor_oblig = candidate.get("valor_obligacion_actual")
    if valor_oblig is None:
        valor_oblig = candidate.get("valor_extracto")

    saldo_vis = candidate.get("saldo_vencido_visible")
    if "saldo_vencido_visible" not in candidate:
        # Fail-closed: sin rol explícito no inventar saldo.
        saldo_vis = None

    row = {
        AplicacionPagosCols.ID_PAGO: payment["id_pago"],
        AplicacionPagosCols.CLIENTE: payment["cliente"],
        AplicacionPagosCols.CREDITO: candidate.get("credito"),
        AplicacionPagosCols.MONTO_BANCO: payment["monto_banco"],
        AplicacionPagosCols.FECHA_BANCO: fecha_banco.isoformat()
        if hasattr(fecha_banco, "isoformat")
        else fecha_banco,
        AplicacionPagosCols.FECHA_LIMITE: due.isoformat() if hasattr(due, "isoformat") else (due or ""),
        AplicacionPagosCols.DIAS_RESPECTO_VENCIMIENTO: dias if dias is not None else "",
        AplicacionPagosCols.VALOR_OBLIGACION_ACTUAL: valor_oblig if valor_oblig is not None else "",
        AplicacionPagosCols.SALDO_VENCIDO: saldo_vis if saldo_vis is not None else "",
        AplicacionPagosCols.VALIDAR_PAGO: ValidarPago.POR_DEFINIR,
        AplicacionPagosCols.APLICAR_OBLIGACION_ACTUAL: "",
        AplicacionPagosCols.APLICAR_SALDO_VENCIDO: "",
        AplicacionPagosCols.ABONO_ADICIONAL_CAPITAL: "",
        AplicacionPagosCols.TOTAL_ASIGNADO: "",
        AplicacionPagosCols.SALDO_POR_ASIGNAR: "",
        AplicacionPagosCols.APLICACION_SUGERIDA: AplicacionSugerida.POR_DEFINIR,
        AplicacionPagosCols.TIPO_APLICACION: "",
        AplicacionPagosCols.LINK_EXTRACTO: candidate.get("link_extracto", ""),
        AplicacionPagosCols.LINK_TABLA: candidate.get("link_tabla", ""),
        AplicacionPagosCols.LINK_CARPETA_CREDITO: candidate.get("link_carpeta_credito", ""),
        AplicacionPagosCols.OBSERVACION: candidate.get("observacion_extra") or "",
    }
    # Evidencia congelada (vive en _Meta / modelos; no columnas visibles).
    row["_evidence"] = candidate.get("extract_evidence") or {}
    row["_right_panel_role"] = candidate.get("right_panel_role") or ""
    row["_parser_status"] = candidate.get("parser_status") or ""
    return row


def build_review_workbook_v3_bytes(
    *,
    process_id: str,
    process_date: date,
    bank_code: str,
    aplicacion_rows: list[dict[str, Any]],
    error_records: list[dict[str, Any]],
) -> bytes:
    wb = openpyxl.Workbook()

    ws = wb.active
    ws.title = ReviewSheets.APLICACION_PAGOS
    ws.append(list(AplicacionPagosCols.HEADERS))
    for cell in ws[1]:
        cell.fill = _HEADER_FILL
        cell.font = _HEADER_FONT
        cell.alignment = Alignment(wrap_text=True, vertical="center")

    # Agrupar por ID Pago para Saldo por asignar solo en primera fila SI/grupo.
    seen_monto: set[str] = set()
    for row in aplicacion_rows:
        pid = str(row.get(AplicacionPagosCols.ID_PAGO) or "").strip()
        values = []
        for h in AplicacionPagosCols.HEADERS:
            val = row.get(h, "")
            if h == AplicacionPagosCols.MONTO_BANCO and pid:
                if pid in seen_monto:
                    val = None
                else:
                    seen_monto.add(pid)
            if h == AplicacionPagosCols.APLICACION_SUGERIDA:
                val = compute_aplicacion_sugerida(
                    validar_pago=row.get(AplicacionPagosCols.VALIDAR_PAGO),
                    aplicar_obligacion=row.get(AplicacionPagosCols.APLICAR_OBLIGACION_ACTUAL),
                    aplicar_saldo_vencido=row.get(AplicacionPagosCols.APLICAR_SALDO_VENCIDO),
                    abono_capital=row.get(AplicacionPagosCols.ABONO_ADICIONAL_CAPITAL),
                    valor_obligacion_actual=row.get(AplicacionPagosCols.VALOR_OBLIGACION_ACTUAL),
                )
            values.append(val)
        ws.append(values)

    first_data = 2
    last_data = max(first_data, ws.max_row)
    # Fórmulas Total asignado / Saldo por asignar / Aplicación sugerida se dejan
    # como valores iniciales; Excel humano puede recalcular al editar.
    # Total = K+L+M (cols 11,12,13) → col 14
    col_total = AplicacionPagosCols.HEADERS.index(AplicacionPagosCols.TOTAL_ASIGNADO) + 1
    col_a = AplicacionPagosCols.HEADERS.index(AplicacionPagosCols.APLICAR_OBLIGACION_ACTUAL) + 1
    col_v = AplicacionPagosCols.HEADERS.index(AplicacionPagosCols.APLICAR_SALDO_VENCIDO) + 1
    col_k = AplicacionPagosCols.HEADERS.index(AplicacionPagosCols.ABONO_ADICIONAL_CAPITAL) + 1
    col_saldo = AplicacionPagosCols.HEADERS.index(AplicacionPagosCols.SALDO_POR_ASIGNAR) + 1
    col_monto = AplicacionPagosCols.HEADERS.index(AplicacionPagosCols.MONTO_BANCO) + 1
    col_id = AplicacionPagosCols.HEADERS.index(AplicacionPagosCols.ID_PAGO) + 1
    col_vp = AplicacionPagosCols.HEADERS.index(AplicacionPagosCols.VALIDAR_PAGO) + 1

    for r in range(first_data, last_data + 1):
        ws.cell(r, col_total).value = (
            f"={get_column_letter(col_a)}{r}+{get_column_letter(col_v)}{r}+{get_column_letter(col_k)}{r}"
        )
        # Saldo por asignar: Monto banco del grupo − suma totales SI del mismo ID.
        # Fórmula orientativa por fila (secretaria ve el residual del grupo).
        id_cell = f"{get_column_letter(col_id)}{r}"
        ws.cell(r, col_saldo).value = (
            f"=IF({get_column_letter(col_monto)}{r}=\"\",\"\","
            f"{get_column_letter(col_monto)}{r}-SUMIF({get_column_letter(col_id)}${first_data}:{get_column_letter(col_id)}${last_data},"
            f"{id_cell},"
            f"{get_column_letter(col_total)}${first_data}:{get_column_letter(col_total)}${last_data}))"
        )

    # Listas + dropdowns
    ws_lists = wb.create_sheet(ReviewSheets.LISTAS)
    ws_lists.append(["ValidarPago"])
    for i, opt in enumerate(ValidarPago.OPTIONS_ORDERED, start=2):
        ws_lists.cell(i, 1, opt)
    ws_lists.cell(1, 2, "TipoAplicacion")
    for i, opt in enumerate(TipoAplicacionConfirmado.OPTIONS_ORDERED, start=2):
        ws_lists.cell(i, 2, opt)
    ws_lists.sheet_state = "hidden"

    dv_vp = DataValidation(
        type="list",
        formula1=f"={ReviewSheets.LISTAS}!$A$2:$A${1 + len(ValidarPago.OPTIONS_ORDERED)}",
        allow_blank=False,
    )
    ws.add_data_validation(dv_vp)
    dv_vp.add(
        f"{get_column_letter(col_vp)}{first_data}:{get_column_letter(col_vp)}{max(last_data, first_data + 50)}"
    )

    col_tipo = AplicacionPagosCols.HEADERS.index(AplicacionPagosCols.TIPO_APLICACION) + 1
    dv_tipo = DataValidation(
        type="list",
        formula1=f"={ReviewSheets.LISTAS}!$B$2:$B${1 + len(TipoAplicacionConfirmado.OPTIONS_ORDERED)}",
        allow_blank=True,
    )
    ws.add_data_validation(dv_tipo)
    dv_tipo.add(
        f"{get_column_letter(col_tipo)}{first_data}:{get_column_letter(col_tipo)}{max(last_data, first_data + 50)}"
    )

    # Protección: desbloquear editables
    editable_idx = {
        AplicacionPagosCols.HEADERS.index(c) + 1 for c in AplicacionPagosCols.SECRETARY_EDITABLE
    }
    for r in range(first_data, last_data + 1):
        for c in range(1, len(AplicacionPagosCols.HEADERS) + 1):
            cell = ws.cell(r, c)
            cell.protection = _UNLOCKED if c in editable_idx else _LOCKED
    ws.protection.sheet = True

    # Errores
    ws_err = wb.create_sheet(ReviewSheets.ERRORES)
    ws_err.append(list(ErroresCols.HEADERS))
    for cell in ws_err[1]:
        cell.fill = _HEADER_FILL
        cell.font = _HEADER_FONT
    for rec in error_records:
        ws_err.append(_errores_row(rec))
    if not error_records:
        ws_err.sheet_state = "hidden"

    # Meta + evidencia congelada
    ws_meta = wb.create_sheet(ReviewSheets.META)
    ws_meta.append([MetaCols.CAMPO, MetaCols.VALOR])
    ws_meta.append([MetaCols.ROW_REVIEW_SCHEMA_VERSION, REVIEW_SCHEMA_VERSION])
    ws_meta.append([MetaCols.ROW_PROCESS_ID, process_id])
    ws_meta.append([MetaCols.ROW_PROCESS_DATE, process_date.isoformat()])
    ws_meta.append([MetaCols.ROW_BANK_CODE, bank_code])
    ws_meta.append(["EvidenceHeaders", "row|item_id|path|etag|sha256|fecha_limite|right_panel_role|parser_status"])
    for idx, row in enumerate(aplicacion_rows, start=first_data):
        ev = row.get("_evidence") or {}
        ws_meta.append(
            [
                f"EvidenceRow{idx}",
                "|".join(
                    [
                        str(idx),
                        str(ev.get("item_id") or ""),
                        str(ev.get("path") or ""),
                        str(ev.get("etag") or ""),
                        str(ev.get("sha256") or ""),
                        str(ev.get("fecha_limite") or row.get(AplicacionPagosCols.FECHA_LIMITE) or ""),
                        str(row.get("_right_panel_role") or ""),
                        str(row.get("_parser_status") or ""),
                    ]
                ),
            ]
        )
    ws_meta.sheet_state = "hidden"

    # Sin hojas legacy
    forbidden = {
        "Control",
        "Resumen",
        "Casos_Pago",
        "Distribucion_Pagos",
        "Distribucion_Abonos",
        "Distribucion",
    }
    for name in list(wb.sheetnames):
        if name in forbidden:
            del wb[name]

    out = io.BytesIO()
    wb.save(out)
    return out.getvalue()
