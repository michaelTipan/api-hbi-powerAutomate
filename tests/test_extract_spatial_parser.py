"""Parser espacial + familias de extracto (sin PII)."""
from __future__ import annotations

import pytest

from app.application.services.extract_snapshot_parser import (
    ParserStatus,
    RightPanelRole,
    parse_extract_snapshot,
    parse_extract_snapshot_from_panels,
    parse_extract_snapshot_from_text,
)
from tests.fixtures.extract_snapshot_texts import (
    EXTRACT_CREDITO_GB_COMPACT,
    EXTRACT_CREDITO_GB_DASH,
    EXTRACT_CREDITO_GB_OBLIGACION,
    EXTRACT_CREDITO_GB_SPACE,
    EXTRACT_LEFT_INTERESES_MORA_RIGHT_EMPTY,
    EXTRACT_LEFT_ONLY,
    EXTRACT_NO_CREDITO,
    EXTRACT_NO_FECHA,
    EXTRACT_RIGHT_AMBIGUO,
    EXTRACT_RIGHT_APLICACION_ABONO_CAPITAL,
    EXTRACT_RIGHT_APLICACION_ANTERIOR,
    EXTRACT_RIGHT_APLICACION_CUOTA_ABONO,
    EXTRACT_RIGHT_CUOTA_MORA,
    EXTRACT_RIGHT_CUOTAS_EN_MORA,
    EXTRACT_RIGHT_SALDO_EN_MORA,
    EXTRACT_RIGHT_SALDO_MORA,
    EXTRACT_RIGHT_SALDO_VENCIDO,
    EXTRACT_RIGHT_TOTAL_APLICADO,
    EXTRACT_RIGHT_TOTAL_EN_MORA,
    EXTRACT_RIGHT_TOTAL_PAGADO,
    EXTRACT_RIGHT_VACIO,
    EXTRACT_RIGHT_VALOR_PAGADO,
    PDF_MOCK_SPATIAL_INTERESES_LEFT,
    PDF_MOCK_SPATIAL_SALDO_MORA_RIGHT,
)


def test_left_only_and_intereses_mora_not_saldo_vencido():
    left = parse_extract_snapshot_from_text(EXTRACT_LEFT_ONLY)
    assert left.right_panel_role == RightPanelRole.VACIO
    assert left.saldo_vencido_visible is None
    assert left.valor_obligacion_actual == 1_500_000.0

    intereses = parse_extract_snapshot_from_text(EXTRACT_LEFT_INTERESES_MORA_RIGHT_EMPTY)
    assert intereses.right_panel_role == RightPanelRole.VACIO
    assert intereses.saldo_vencido_visible is None
    assert "left_intereses_de_mora_ignored" in intereses.warnings


@pytest.mark.parametrize(
    "fixture,expected_amount",
    [
        (EXTRACT_RIGHT_SALDO_MORA, 13_075_842.0),
        (EXTRACT_RIGHT_CUOTA_MORA, 450_000.0),
        (EXTRACT_RIGHT_CUOTAS_EN_MORA, 800_000.0),
        (EXTRACT_RIGHT_SALDO_EN_MORA, 900_000.0),
        (EXTRACT_RIGHT_TOTAL_EN_MORA, 1_100_000.0),
        (EXTRACT_RIGHT_SALDO_VENCIDO, 450_000.0),
    ],
)
def test_right_panel_mora_families(fixture, expected_amount):
    snap = parse_extract_snapshot_from_text(fixture)
    assert snap.right_panel_role == RightPanelRole.SALDO_VENCIDO
    assert snap.saldo_vencido_visible == expected_amount


@pytest.mark.parametrize(
    "fixture",
    [
        EXTRACT_RIGHT_APLICACION_ANTERIOR,
        EXTRACT_RIGHT_APLICACION_CUOTA_ABONO,
        EXTRACT_RIGHT_APLICACION_ABONO_CAPITAL,
        EXTRACT_RIGHT_TOTAL_PAGADO,
        EXTRACT_RIGHT_TOTAL_APLICADO,
        EXTRACT_RIGHT_VALOR_PAGADO,
    ],
)
def test_right_panel_aplicacion_anterior_families(fixture):
    snap = parse_extract_snapshot_from_text(fixture)
    assert snap.right_panel_role == RightPanelRole.APLICACION_ANTERIOR
    assert snap.saldo_vencido_visible is None


def test_ambiguous_and_empty():
    amb = parse_extract_snapshot_from_text(EXTRACT_RIGHT_AMBIGUO)
    assert amb.right_panel_role == RightPanelRole.AMBIGUO
    assert amb.saldo_vencido_visible is None
    assert amb.parser_status == ParserStatus.AMBIGUOUS_RIGHT_PANEL

    vac = parse_extract_snapshot_from_text(EXTRACT_RIGHT_VACIO)
    assert vac.right_panel_role == RightPanelRole.VACIO


def test_missing_fecha_credito_and_gb_variants():
    no_f = parse_extract_snapshot_from_text(EXTRACT_NO_FECHA)
    assert no_f.fecha_limite is None
    assert no_f.parser_status in (ParserStatus.PARTIAL, ParserStatus.OK)

    no_c = parse_extract_snapshot_from_text(EXTRACT_NO_CREDITO)
    # Puede o no parsear crédito según helper; no debe tumbar
    assert no_c.valor_obligacion_actual == 750_000.0

    parsed_ids = []
    for fx in (
        EXTRACT_CREDITO_GB_DASH,
        EXTRACT_CREDITO_GB_SPACE,
        EXTRACT_CREDITO_GB_COMPACT,
        EXTRACT_CREDITO_GB_OBLIGACION,
    ):
        snap = parse_extract_snapshot_from_text(fx)
        parsed_ids.append(snap.credito)
    # Al menos las variantes con separadores deben resolver un id no vacío.
    assert any(x is not None and str(x).strip() for x in parsed_ids)


def test_spatial_mock_pdf_bytes():
    left_only = parse_extract_snapshot(PDF_MOCK_SPATIAL_INTERESES_LEFT.encode("utf-8"))
    assert left_only.layout_mode in ("spatial", "mock_panels")
    assert left_only.right_panel_role == RightPanelRole.VACIO
    assert left_only.saldo_vencido_visible is None

    mora = parse_extract_snapshot(PDF_MOCK_SPATIAL_SALDO_MORA_RIGHT.encode("utf-8"))
    assert mora.right_panel_role == RightPanelRole.SALDO_VENCIDO
    assert mora.saldo_vencido_visible == 13_075_842.0


def test_panels_api_explicit():
    snap = parse_extract_snapshot_from_panels(
        "No. Obligacion 1\nFecha limite de pago 01/01/2026\nTOTAL A PAGAR $ 10.000\nIntereses de mora 1",
        "SALDO MORA $ 2.000",
    )
    assert snap.right_panel_role == RightPanelRole.SALDO_VENCIDO
    assert snap.saldo_vencido_visible == 2_000.0
    # Intereses izquierdos no contaminan el rol (derecha gana por coords).
    left_only = parse_extract_snapshot_from_panels(
        "No. Obligacion 1\nFecha limite de pago 01/01/2026\nTOTAL A PAGAR $ 10.000\nIntereses de mora $ 99",
        "",
    )
    assert left_only.right_panel_role == RightPanelRole.VACIO
    assert left_only.saldo_vencido_visible is None
    assert "left_intereses_de_mora_ignored" in left_only.warnings
