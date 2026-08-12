"""Regresión CAPA B: Saldo por asignar solo suma SI; extras se marcan NO."""
from __future__ import annotations

from openpyxl import Workbook

from app.application.services.review_schema import AplicacionPagosCols, ReviewSheets
from scripts.e2e_rc.review_edit import approve_single_credit_pago


def _two_credit_review() -> bytes:
    wb = Workbook()
    ws = wb.active
    assert ws is not None
    ws.title = ReviewSheets.APLICACION_PAGOS
    headers = list(AplicacionPagosCols.HEADERS)
    for col, h in enumerate(headers, start=1):
        ws.cell(1, col).value = h
    idx = {h: i + 1 for i, h in enumerate(headers)}
    # Fila 2: 231 con monto banco
    ws.cell(2, idx[AplicacionPagosCols.ID_PAGO]).value = "P1"
    ws.cell(2, idx[AplicacionPagosCols.CLIENTE]).value = "GEOEXCON"
    ws.cell(2, idx[AplicacionPagosCols.CREDITO]).value = "CREDITO # 231"
    ws.cell(2, idx[AplicacionPagosCols.MONTO_BANCO]).value = 19_102_163
    ws.cell(2, idx[AplicacionPagosCols.VALIDAR_PAGO]).value = "POR DEFINIR"
    # Fila 3: 299 extra (sin monto)
    ws.cell(3, idx[AplicacionPagosCols.ID_PAGO]).value = "P1"
    ws.cell(3, idx[AplicacionPagosCols.CLIENTE]).value = "GEOEXCON"
    ws.cell(3, idx[AplicacionPagosCols.CREDITO]).value = "CREDITO # 299"
    ws.cell(3, idx[AplicacionPagosCols.VALIDAR_PAGO]).value = "POR DEFINIR"
    from io import BytesIO

    buf = BytesIO()
    wb.save(buf)
    return buf.getvalue()


def test_approve_single_marks_extra_credit_no_and_sumifs_zero_saldo() -> None:
    raw = _two_credit_review()
    edited, applied = approve_single_credit_pago(
        raw, tipo="PAGO DE OBLIGACIÓN ACTUAL", credito_contains="231"
    )
    assert len(applied) == 2
    from openpyxl import load_workbook
    from io import BytesIO

    wb = load_workbook(BytesIO(edited))
    ws = wb[ReviewSheets.APLICACION_PAGOS]
    headers = [c.value for c in ws[1]]
    idx = {h: i + 1 for i, h in enumerate(headers)}
    assert ws.cell(2, idx[AplicacionPagosCols.VALIDAR_PAGO]).value == "SI"
    assert ws.cell(3, idx[AplicacionPagosCols.VALIDAR_PAGO]).value == "NO"
    assert ws.cell(3, idx[AplicacionPagosCols.TIPO_APLICACION]).value in ("", None)
    assert float(ws.cell(2, idx[AplicacionPagosCols.TOTAL_ASIGNADO]).value) == 19_102_163
    assert float(ws.cell(2, idx[AplicacionPagosCols.SALDO_POR_ASIGNAR]).value) == 0
    assert ws.cell(3, idx[AplicacionPagosCols.SALDO_POR_ASIGNAR]).value in (None, "")
