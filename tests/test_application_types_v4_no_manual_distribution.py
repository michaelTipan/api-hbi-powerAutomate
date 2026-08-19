"""Los tipos del desplegable no requieren A/V/K del workbook."""
from __future__ import annotations

import pytest

from app.application.services.finalize_aplicacion_pagos import collect_aplicacion_pagos_issues
from app.application.services.review_schema import (
    AplicacionPagosCols,
    TipoAplicacionConfirmado,
    ValidarPago,
    resolve_policy_from_tipo_confirmado,
)


@pytest.mark.parametrize("tipo", list(TipoAplicacionConfirmado.OPTIONS_ORDERED))
def test_nine_tipos_finalize_without_manual_avk(tipo):
    row = {
        AplicacionPagosCols.ID_PAGO: "p1",
        AplicacionPagosCols.CLIENTE: "C",
        AplicacionPagosCols.CREDITO: "1",
        AplicacionPagosCols.MONTO_BANCO: 100,
        AplicacionPagosCols.VALIDAR_PAGO: ValidarPago.SI,
        AplicacionPagosCols.TIPO_APLICACION: tipo,
        "_excel_row": 4,
    }
    assert collect_aplicacion_pagos_issues([row]) == []
    policy = resolve_policy_from_tipo_confirmado(tipo)
    assert policy.tipo_aplicacion_original == tipo
    dumped = policy.policy_dict()
    assert "Aplicar a obligación actual" not in dumped
    for banned in (
        "aplicar_obligacion_actual",
        "aplicar_saldo_vencido",
        "abono_adicional_capital",
        "total_asignado",
        "saldo_por_asignar",
    ):
        assert banned not in dumped


def test_invalid_tipo_does_not_invent_pago_or_abono_policy():
    from app.application.use_cases.payment_validation_finalize import (
        _resolve_abono_policy,
        _resolve_distrib_policy,
    )

    bad = {
        AplicacionPagosCols.TIPO_APLICACION: "TIPO INVENTADO",
        AplicacionPagosCols.VALIDAR_PAGO: ValidarPago.SI,
    }
    with pytest.raises(ValueError, match="tipo_aplicacion_(invalid|required)"):
        _resolve_distrib_policy(bad)
    with pytest.raises(ValueError, match="tipo_aplicacion_(invalid|required)"):
        _resolve_abono_policy(bad)

    empty = {
        AplicacionPagosCols.TIPO_APLICACION: "",
        AplicacionPagosCols.VALIDAR_PAGO: ValidarPago.SI,
    }
    with pytest.raises(ValueError, match="tipo_aplicacion_required"):
        _resolve_distrib_policy(empty)
