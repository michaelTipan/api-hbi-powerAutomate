"""Regresión: fecha límite en extractos HBI con capa de texto desordenada.

La plantilla visual es estable; pypdf a veces deja la fecha *antes* de
«PAGO INMEDIATO» y *después* de «Fecha Limite de pago» solo el aviso de cuenta.
No debe tomarse la fecha de desembolso ni exigir mora/PAGO INMEDIATO.
"""
from __future__ import annotations

from datetime import date

from app.application.services.payment_helpers import extract_fecha_limite_pago_from_pdf_text


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
