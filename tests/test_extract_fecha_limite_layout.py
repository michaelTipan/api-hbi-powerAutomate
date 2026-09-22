"""Regresión: fecha límite en extractos HBI con capa de texto desordenada.

La plantilla visual es estable; pypdf a veces deja la fecha *antes* de
«PAGO INMEDIATO» y *después* de «Fecha Limite de pago» solo el aviso de cuenta.
Con PDF bytes, la fecha límite se lee **solo** con pdfplumber (tabla → texto).
No debe tomarse la fecha de desembolso ni exigir mora/PAGO INMEDIATO.
"""
from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from app.application.services.payment_helpers import (
    _extract_fecha_limite_from_table_rows,
    extract_fecha_limite_pago_from_pdf,
    extract_fecha_limite_pago_from_pdf_text,
)

_DOWNLOADS = Path(r"C:\Users\j-mic\Downloads")


def test_torres_nino_al_dia_date_after_fecha_limite_without_pago_inmediato():
    """Extracto sin mora: la fecha sigue junto a la etiqueta; no hay PAGO INMEDIATO."""
    text = """
EXTRACTO MENSUAL OPERACION DE CREDITO
INVERSIONES TORRES & NIÑO S.A.S
Fecha desembolso 22/10/2024
Saldo actual 187.446.046
TOTAL A PAGAR 6.479.752
Fecha Limite de pago
22/08/2026
Favor tener presente que nuestra cuenta recaudadora ha cambiado
"""
    assert extract_fecha_limite_pago_from_pdf_text(text) == date(2026, 8, 22)


def test_bc_mora_date_before_pago_inmediato_not_after_fecha_limite_label():
    """Crédito 60 B&C (prod): etiqueta sin fecha; 27/09/2026 pegada a PAGO INMEDIATO."""
    text = """
INFORMACION OBLIGACION
No, Obligacion GB-1022-060
Fecha desembolso 27/12/2023
Saldo Actual 294.092.522
TOTAL A PAGAR 12.899.180
SALDO MORA 12.868.283
 Fecha Limite de pago
Favor tener presente que nuestra cuenta recaudadora ha cambiado, por lo cual
agradecemos no utilizar la cuenta del BANCO DE BOGOTA
TIEMBRE CUOTA MORA /  AGOSTO
27/09/2026 PAGO INMEDIATO
"""
    assert extract_fecha_limite_pago_from_pdf_text(text) == date(2026, 9, 27)


def test_bc_cred59_date_before_pago_inmediato():
    text = """
Fecha desembolso 20/12/2023
SALDO MORA 11.910.089
 Fecha Limite de pago
Favor tener presente que nuestra cuenta recaudadora ha cambiado
EMBRE CUOTAS EN MORA  AGOSTO
20/09/2026 PAGO INMEDIATO
"""
    assert extract_fecha_limite_pago_from_pdf_text(text) == date(2026, 9, 20)


def test_pago_inmediato_still_reads_date_after_label():
    """Regresión: extractos que ya funcionaban (fecha *después* de PAGO INMEDIATO)."""
    text = "TOTAL A PAGAR 55.596.854 PAGO INMEDIATO 4/08/2026"
    assert extract_fecha_limite_pago_from_pdf_text(text) == date(2026, 8, 4)


def test_does_not_pick_desembolso_when_limite_has_no_nearby_date():
    """Fail-closed: sin fecha anclada a límite/PAGO INMEDIATO, no usar desembolso."""
    text = """
Fecha desembolso 27/12/2023
Fecha Limite de pago
Favor tener presente que nuestra cuenta recaudadora ha cambiado
Agradecemos efectuar su pago Cuenta de Ahorros
"""
    assert extract_fecha_limite_pago_from_pdf_text(text) is None


def test_date_immediately_before_fecha_limite_label_without_mora():
    """Algunos exports dejan 22/08/2026 justo antes de la etiqueta, sin PAGO INMEDIATO."""
    text = """
Fecha desembolso 22/10/2024
TOTAL A PAGAR 6.479.752
22/08/2026 Fecha Limite de pago
Favor tener presente que nuestra cuenta recaudadora ha cambiado
"""
    assert extract_fecha_limite_pago_from_pdf_text(text) == date(2026, 8, 22)


def test_classic_after_label_still_beats_earlier_desembolso():
    text = "Fecha desembolso 23/10/2025  ...  Fecha Limite de pago 23/04/2026  fin"
    assert extract_fecha_limite_pago_from_pdf_text(text) == date(2026, 4, 23)


def test_fecha_de_pago_alias_reads_due_date_case_insensitive():
    """Plantilla nueva HBI: «FECHA DE PAGO» sustituye a «Fecha Limite de pago»."""
    text = """
INFORMACION OBLIGACION
No, Obligación GB-1022-213
Fecha desembolso 25/06/2025
TOTAL A PAGAR 24.637.411 TOTAL PAGADO 38.000.000
FECHA DE PAGO
25/09/2026
Favor tener presente que nuestra cuenta recaudadora ha cambiado
Los datos acá consignados corresponden a los liquidados si el pago se hace en la fecha de vencimiento
"""
    assert extract_fecha_limite_pago_from_pdf_text(text) == date(2026, 9, 25)
    # Casing mixto / minúsculas
    assert (
        extract_fecha_limite_pago_from_pdf_text(
            "Fecha desembolso 25/06/2025\nfecha de pago\n25/09/2026\n"
        )
        == date(2026, 9, 25)
    )


def test_fecha_limite_label_still_beats_fecha_de_pago_alias():
    """Si ambas etiquetas existen, gana «Fecha límite…» (prioridad primaria)."""
    text = """
Fecha desembolso 01/01/2020
Fecha Limite de pago 15/08/2026
FECHA DE PAGO
25/09/2026
"""
    assert extract_fecha_limite_pago_from_pdf_text(text) == date(2026, 8, 15)


def test_fecha_pago_without_de_is_not_an_anchor():
    """No anclar «FECHA PAGO» suelta (no observada en prod; demasiado genérica)."""
    text = """
Fecha desembolso 25/06/2025
FECHA PAGO
25/09/2026
Favor tener presente que nuestra cuenta recaudadora ha cambiado
"""
    assert extract_fecha_limite_pago_from_pdf_text(text) is None


def test_table_row_fecha_de_pago_alias():
    tables = [
        [
            ["No, Obligacion GB-1022-213", "Fecha desembolso 25/06/2025"],
            ["FECHA DE PAGO", "25/09/2026", ""],
        ]
    ]
    assert _extract_fecha_limite_from_table_rows(tables) == date(2026, 9, 25)


def test_table_row_fecha_limite_same_row_preferred():
    """Plan A: misma fila visual label | fecha (como pdfplumber.extract_tables)."""
    tables = [
        [
            ["No, Obligacion GB-1022-060", "Fecha desembolso 27/12/2023"],
            ["Fecha Limite de pago", "27/05/2026", ""],
            ["Favor tener presente que nuestra cuenta recaudadora", ""],
        ]
    ]
    assert _extract_fecha_limite_from_table_rows(tables) == date(2026, 5, 27)


def test_table_row_rejects_garbage_and_impossible_dates():
    assert (
        _extract_fecha_limite_from_table_rows(
            [[["Fecha Limite de pago", "22/^%@/dkjb"]]]
        )
        is None
    )
    assert (
        _extract_fecha_limite_from_table_rows(
            [[["Fecha Limite de pago", "30/02/2026"]]]
        )
        is None
    )


def test_table_row_does_not_use_desembolso_cell_as_limite():
    """Si la fila de límite no trae fecha usable, no saltar a desembolso de otra fila."""
    tables = [
        [
            ["Fecha desembolso", "27/12/2023"],
            ["Fecha Limite de pago", ""],
        ]
    ]
    assert _extract_fecha_limite_from_table_rows(tables) is None


@pytest.mark.parametrize(
    ("filename", "expected"),
    [
        ("Extracto Mayo 20-05-2026 Obligacion # 60.pdf", date(2026, 5, 27)),
        ("Extracto Julio 26-06-2026 Obligacion # 59.pdf", date(2026, 7, 20)),
    ],
)
def test_pdfplumber_bytes_bc_may_jul_al_dia(filename: str, expected: date):
    """Carmen B&C: pypdf fallaba; pdfplumber (tabla/texto) debe leer la celda visual."""
    path = _DOWNLOADS / filename
    if not path.is_file():
        pytest.skip(f"PDF local no disponible: {path}")
    assert extract_fecha_limite_pago_from_pdf(path.read_bytes()) == expected


def test_pdfplumber_bytes_empty_or_tiny_fail_closed():
    assert extract_fecha_limite_pago_from_pdf(b"") is None
    assert extract_fecha_limite_pago_from_pdf(b"%PDF-1.4 tiny") is None
