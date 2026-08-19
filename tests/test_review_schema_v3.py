"""Tests del schema v4 (columnas visibles) y ExtractSnapshot; v3 queda histórico."""
from __future__ import annotations

from datetime import date

import openpyxl
import pytest

from app.application.services.extract_snapshot_parser import (
    ParserStatus,
    RightPanelRole,
    parse_extract_snapshot_from_text)
from app.application.services.finalize_aplicacion_pagos import collect_aplicacion_pagos_issues
from app.application.services.review_schema import (
    REVIEW_SCHEMA_VERSION,
    AplicacionPagosCols,
    ReviewSheets,
    TipoAplicacionConfirmado,
    ValidarPago,
    dias_respecto_vencimiento,
    require_review_schema_v4,
)
from tests.fixtures.extract_snapshot_texts import (
    EXTRACT_LEFT_ONLY,
    EXTRACT_RIGHT_AMBIGUO,
    EXTRACT_RIGHT_APLICACION_ANTERIOR,
    EXTRACT_RIGHT_SALDO_VENCIDO,
    EXTRACT_RIGHT_VACIO)

def test_review_schema_version_is_4_and_v3_is_historical():
    assert REVIEW_SCHEMA_VERSION == 4
    from app.application.services.review_schema import (
        AplicacionPagosColsV3,
        REVIEW_SCHEMA_VERSION_V3,
    )

    assert REVIEW_SCHEMA_VERSION_V3 == 3
    assert len(AplicacionPagosColsV3.HEADERS) == 21


def test_aplicacion_pagos_has_exactly_15_columns_in_order():
    expected = [
        "ID Pago",
        "Cliente",
        "Crédito",
        "Monto banco",
        "Fecha banco",
        "Fecha límite",
        "Días respecto vencimiento",
        "Valor obligación actual",
        "Saldo vencido",
        "Validar Pago",
        "Tipo de aplicación",
        "Link extracto",
        "Link tabla amortización",
        "Link carpeta crédito",
        "Observación",
    ]
    assert list(AplicacionPagosCols.HEADERS) == expected
    assert len(AplicacionPagosCols.HEADERS) == 15

def test_tipo_aplicacion_has_8_options_without_vk_or_mixto():
    assert len(TipoAplicacionConfirmado.OPTIONS_ORDERED) == 8
    joined = " | ".join(TipoAplicacionConfirmado.OPTIONS_ORDERED)
    assert "MIXTO" not in joined
    assert "APLICACIÓN A SALDO VENCIDO + ABONO A CAPITAL" not in joined
    assert "PAGO COMBINADO" not in joined

def test_dias_respecto_vencimiento_examples():
    assert dias_respecto_vencimiento(date(2026, 5, 20), date(2026, 5, 23)) == -3
    assert dias_respecto_vencimiento(date(2026, 5, 23), date(2026, 5, 23)) == 0
    assert dias_respecto_vencimiento(date(2026, 5, 30), date(2026, 5, 23)) == 7


def test_extract_snapshot_roles():
    left = parse_extract_snapshot_from_text(EXTRACT_LEFT_ONLY)
    assert left.right_panel_role == RightPanelRole.VACIO
    assert left.saldo_vencido_visible is None
    assert left.valor_obligacion_actual == 1500000.0

    ant = parse_extract_snapshot_from_text(EXTRACT_RIGHT_APLICACION_ANTERIOR)
    assert ant.right_panel_role == RightPanelRole.APLICACION_ANTERIOR
    assert ant.saldo_vencido_visible is None

    mora = parse_extract_snapshot_from_text(EXTRACT_RIGHT_SALDO_VENCIDO)
    assert mora.right_panel_role == RightPanelRole.SALDO_VENCIDO
    assert mora.saldo_vencido_visible == 450000.0

    amb = parse_extract_snapshot_from_text(EXTRACT_RIGHT_AMBIGUO)
    assert amb.right_panel_role == RightPanelRole.AMBIGUO
    assert amb.saldo_vencido_visible is None
    assert amb.parser_status == ParserStatus.AMBIGUOUS_RIGHT_PANEL
    assert "right_panel_ambiguous_not_zeroed" in amb.warnings

    vac = parse_extract_snapshot_from_text(EXTRACT_RIGHT_VACIO)
    assert vac.right_panel_role == RightPanelRole.VACIO

def test_finalize_rejects_por_definir_and_accepts_si_with_tipo():
    base = {
        AplicacionPagosCols.ID_PAGO: "p1",
        AplicacionPagosCols.CLIENTE: "C",
        AplicacionPagosCols.CREDITO: "1",
        AplicacionPagosCols.MONTO_BANCO: 100,
        "_excel_row": 2,
    }
    pending = {
        **base,
        AplicacionPagosCols.VALIDAR_PAGO: ValidarPago.POR_DEFINIR,
    }
    issues = collect_aplicacion_pagos_issues([pending])
    assert any(i["error_code"] == "payment_without_selected_credit" for i in issues)

    ok = {
        **base,
        AplicacionPagosCols.VALIDAR_PAGO: ValidarPago.SI,
        AplicacionPagosCols.TIPO_APLICACION: TipoAplicacionConfirmado.PAGO_OBLIGACION_ACTUAL,
        AplicacionPagosCols.OBSERVACION: "",
    }
    issues_ok = collect_aplicacion_pagos_issues([ok])
    assert issues_ok == []

def test_finalize_suggestion_mismatch_and_observation_do_not_block():
    row = {
        AplicacionPagosCols.ID_PAGO: "p1",
        AplicacionPagosCols.CLIENTE: "C",
        AplicacionPagosCols.CREDITO: "1",
        AplicacionPagosCols.MONTO_BANCO: 100,
        AplicacionPagosCols.VALIDAR_PAGO: ValidarPago.SI,
        AplicacionPagosCols.TIPO_APLICACION: TipoAplicacionConfirmado.CANCELACION_PAGO_TOTAL,
        AplicacionPagosCols.OBSERVACION: "nota humana irrelevante",
        "_excel_row": 2,
    }
    assert collect_aplicacion_pagos_issues([row]) == []

def test_unsupported_schema_version_fail_closed():
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = ReviewSheets.APLICACION_PAGOS
    ws.append(["ID Pago", "Cliente"])  # incompleto
    with pytest.raises(ValueError, match="unsupported_review_schema_version"):
        require_review_schema_v4(wb)
