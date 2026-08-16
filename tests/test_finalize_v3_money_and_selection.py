"""Validaciones Finalize v4: all-NO, AMBIGUO, parseo de monto banco."""
from __future__ import annotations

import pytest

from app.application.services.finalize_aplicacion_pagos import (
    collect_aplicacion_pagos_issues,
    parse_editable_money,
    InvalidMonetaryValue,
)
from app.application.services.review_schema import (
    AplicacionPagosCols,
    TipoAplicacionConfirmado,
    ValidarPago,
)


def _row(**overrides):
    base = {
        AplicacionPagosCols.ID_PAGO: "p1",
        AplicacionPagosCols.CLIENTE: "C",
        AplicacionPagosCols.CREDITO: "1",
        AplicacionPagosCols.MONTO_BANCO: 100,
        AplicacionPagosCols.VALIDAR_PAGO: ValidarPago.SI,
        AplicacionPagosCols.TIPO_APLICACION: TipoAplicacionConfirmado.PAGO_OBLIGACION_ACTUAL,
        "_excel_row": 2,
    }
    base.update(overrides)
    return base


def test_si_and_no_same_id_ok():
    si = _row(**{AplicacionPagosCols.CREDITO: "1", "_excel_row": 2})
    no = _row(
        **{
            AplicacionPagosCols.CREDITO: "2",
            AplicacionPagosCols.VALIDAR_PAGO: ValidarPago.NO,
            AplicacionPagosCols.TIPO_APLICACION: "",
            "_excel_row": 3,
        }
    )
    issues = collect_aplicacion_pagos_issues([si, no])
    assert not any(i["error_code"] == "amount_mismatch" for i in issues)


def test_all_no_blocks_payment_without_selected_credit():
    rows = [
        _row(
            **{
                AplicacionPagosCols.VALIDAR_PAGO: ValidarPago.NO,
                AplicacionPagosCols.TIPO_APLICACION: "",
                AplicacionPagosCols.CREDITO: "1",
                "_excel_row": 2,
            }
        ),
        _row(
            **{
                AplicacionPagosCols.VALIDAR_PAGO: ValidarPago.NO,
                AplicacionPagosCols.TIPO_APLICACION: "",
                AplicacionPagosCols.CREDITO: "2",
                "_excel_row": 3,
            }
        ),
    ]
    issues = collect_aplicacion_pagos_issues(rows)
    assert any(i["error_code"] == "payment_without_selected_credit" for i in issues)


def test_ambiguous_accepted_with_si_tipo():
    row = _row(
        **{
            "_parser_status": "AMBIGUOUS_RIGHT_PANEL",
            "_right_panel_role": "AMBIGUO",
            AplicacionPagosCols.OBSERVACION: "no debe ser override",
        }
    )
    issues = collect_aplicacion_pagos_issues([row])
    assert issues == []
    assert row.get("human_review_override") is True


@pytest.mark.parametrize(
    "raw,ok,expected",
    [
        (None, True, 0.0),
        ("", True, 0.0),
        (100, True, 100.0),
        ("1.500,50", True, 1500.50),
        ("5O00000", False, None),
        ("abc", False, None),
        (float("nan"), False, None),
        (float("inf"), False, None),
        (-10, False, None),
    ],
)
def test_parse_editable_money_strict(raw, ok, expected):
    if ok:
        assert parse_editable_money(raw) == expected
    else:
        with pytest.raises(InvalidMonetaryValue):
            parse_editable_money(raw)
