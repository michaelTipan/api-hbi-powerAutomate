"""Pruebas de regresión y seguridad para tablas de amortización con dimensiones anómalas (OOM protection)."""

from datetime import date
import io
import openpyxl
import pytest

from app.application.services.amortization_workbook import (
    _effective_amortization_max_row,
    find_application_row_detailed,
    detect_headers,
)
from app.application.services.accounting_pdf_parser import PaymentApplicationEvent
from app.application.use_cases.payment_validation_generate import (
    _extract_last_payment_date_from_amortization,
    _extract_pending_installment,
)


def _create_mock_amortization_bytes(total_rows: int = 40, inflated_dim: bool = False) -> bytes:
    """Crea una tabla de amortización válida con datos hasta `total_rows`."""
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "TABLA_CLIENTE"

    # Encabezados en fila 1
    headers = [
        "Cuota", "dia", "mes", "año", "Fecha límite", "Fecha pago",
        "Valor intereses", "Abono a K", "Intereses de mora", "Valor pagado cliente", "Saldo a capital"
    ]
    ws.append(headers)

    # 35 cuotas válidas
    for i in range(1, total_rows + 1):
        ws.append([
            i, 15, (i % 12) + 1, 2026,
            date(2026, (i % 12) + 1, 15),
            date(2026, (i % 12) + 1, 14) if i <= 10 else None,  # Cuotas 1 a 10 pagadas
            100000.0, 500000.0, 0.0, 600000.0 if i <= 10 else None, 10000000.0 - (i * 500000.0)
        ])

    if inflated_dim:
        # Simula el comportamiento de Excel donde los metadatos se inflan a 1.048.576 filas
        # pero las celdas intermedias son None
        ws.cell(row=1048576, column=54, value=None)

    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def test_extract_last_payment_date_normal_table():
    """Verifica que en una tabla normal se extrae la fecha máxima de pago correctamente."""
    tb = _create_mock_amortization_bytes(total_rows=30, inflated_dim=False)
    last_pay = _extract_last_payment_date_from_amortization(tb, "CLIENTE")
    assert last_pay == date(2026, 11, 14)


def test_extract_last_payment_date_inflated_dimensions_safety():
    """Verifica que en una tabla con 1.048.576 filas, corta en milisegundos sin OOM."""
    tb = _create_mock_amortization_bytes(total_rows=30, inflated_dim=True)
    import time
    t0 = time.perf_counter()
    last_pay = _extract_last_payment_date_from_amortization(tb, "CLIENTE")
    elapsed = time.perf_counter() - t0

    assert last_pay == date(2026, 11, 14)
    assert elapsed < 0.2, f"Demoró {elapsed:.3f}s, debería ser casi instantáneo (< 200ms)"


def test_extract_pending_installment_inflated_dimensions_safety():
    """Verifica extracción de cuota pendiente en tabla inflada."""
    tb = _create_mock_amortization_bytes(total_rows=30, inflated_dim=True)
    res = _extract_pending_installment(tb, "CLIENTE")
    assert res["row_number"] == 12  # fila 1 header + 10 pagadas = fila 12 es la primera no pagada
    assert res["fecha_limite"] == date(2026, 12, 15)


def test_effective_amortization_max_row_detects_real_boundary():
    """Verifica que _effective_amortization_max_row ignora el millón de filas vacías."""
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "AMORT"
    ws.append(["Cuota", "Fecha pago", "Valor pagado cliente"])
    for i in range(1, 41):
        ws.append([i, date(2026, 1, 1), 100000])

    # Inflar dimensión
    ws.cell(row=1048576, column=30, value=None)
    assert ws.max_row == 1048576

    eff = _effective_amortization_max_row(ws, header_row=1)
    assert eff == 41  # 1 cabecera + 40 filas con datos


def test_find_application_row_detailed_suggests_realistic_row_on_inflated_sheet():
    """Verifica que no sugiere la fila 1.048.577 para escribir nueva cuota."""
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "AMORT"
    ws.append(["dia", "mes", "año", "CUOTA", "Valor intereses", "Abono a K", "Fecha pago", "Valor pagado cliente"])
    for i in range(1, 21):
        ws.append([15, (i % 12) + 1, 2026, 600000, 100000, 500000, date(2026, 1, 15), 600000])

    # Inflar
    ws.cell(row=1048576, column=30, value=None)
    assert ws.max_row == 1048576

    headers = detect_headers(ws, header_row=1)
    event = PaymentApplicationEvent(
        id_pago="pago-1",
        cliente="CLIENTE",
        credito="1",
        asiento_pdf_path="asiento.pdf",
        comprobante="123",
        fecha_asiento=date(2026, 1, 15),
        raw_text="",
        valor_pagado_cliente=600000.0,
        capital=500000.0,
        intereses=100000.0,
        mora=0.0,
        retenciones=0.0,
        saldos_menores=0.0,
    )

    result = find_application_row_detailed(
        ws,
        headers,
        event,
        due_date_row=None,
        header_row=1,
    )
    # No debe sugerir row 1048577; debe ser una fila razonable contigua
    if result.suggested_row is not None:
        assert result.suggested_row < 100, f"suggested_row={result.suggested_row} es excesivo"
