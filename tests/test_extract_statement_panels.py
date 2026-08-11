from io import BytesIO

import pytest
from reportlab.pdfgen import canvas

from app.application.services.payment_helpers import (
    ExtractRightPanelRole,
    classify_extract_right_panel,
    extract_statement_values_from_pdf,
)


@pytest.mark.parametrize(
    ("right_text", "expected_role", "expected_amount"),
    [
        ("", ExtractRightPanelRole.VACIO, None),
        ("Intereses de mora 25.000", ExtractRightPanelRole.AMBIGUO, None),
        ("SALDO MORA 13.075.842", ExtractRightPanelRole.SALDO_VENCIDO, 13_075_842),
        ("CUOTA MORA / MARZO\nTOTAL 1.250.000", ExtractRightPanelRole.SALDO_VENCIDO, 1_250_000),
        ("CUOTAS EN MORA\nTOTAL 2.450.000", ExtractRightPanelRole.SALDO_VENCIDO, 2_450_000),
        ("SALDO EN MORA 3.075.842", ExtractRightPanelRole.SALDO_VENCIDO, 3_075_842),
        ("TOTAL EN MORA 4.075.842", ExtractRightPanelRole.SALDO_VENCIDO, 4_075_842),
        ("APLICACIÓN PAGO CUOTA JULIO\nTOTAL PAGADO 9.000.000", ExtractRightPanelRole.APLICACION_ANTERIOR, None),
        (
            "APLICACIÓN DE PAGO CUOTA Y ABONO ABRIL\nTOTAL APLICADO 8.000.000",
            ExtractRightPanelRole.APLICACION_ANTERIOR,
            None,
        ),
        ("APLICACIÓN ABONO CAPITAL\nVALOR PAGADO 7.000.000", ExtractRightPanelRole.APLICACION_ANTERIOR, None),
        ("Información complementaria sin concepto", ExtractRightPanelRole.AMBIGUO, None),
    ],
)
def test_classify_extract_right_panel(right_text, expected_role, expected_amount):
    role, amount = classify_extract_right_panel(right_text)

    assert role is expected_role
    assert amount == expected_amount


def _two_panel_pdf(left_lines: list[str], right_lines: list[str]) -> bytes:
    output = BytesIO()
    pdf = canvas.Canvas(output)
    for index, line in enumerate(left_lines):
        pdf.drawString(50, 740 - index * 18, line)
    for index, line in enumerate(right_lines):
        pdf.drawString(350, 740 - index * 18, line)
    pdf.save()
    return output.getvalue()


def test_pdf_parser_uses_coordinates_and_ignores_left_intereses_mora():
    pdf = _two_panel_pdf(
        ["Intereses de mora 25.000", "TOTAL A PAGAR 1.500.000"],
        ["APLICACIÓN PAGO CUOTA JULIO", "TOTAL PAGADO 1.500.000"],
    )

    values = extract_statement_values_from_pdf(pdf)

    assert values.total_a_pagar == 1_500_000
    assert values.right_panel_role is ExtractRightPanelRole.APLICACION_ANTERIOR
    assert values.saldo_vencido is None


def test_pdf_parser_reads_saldo_mora_only_from_right_panel():
    pdf = _two_panel_pdf(
        ["TOTAL A PAGAR 1.500.000"],
        ["SALDO MORA", "13.075.842"],
    )

    values = extract_statement_values_from_pdf(pdf)

    assert values.total_a_pagar == 1_500_000
    assert values.right_panel_role is ExtractRightPanelRole.SALDO_VENCIDO
    assert values.saldo_vencido == 13_075_842
