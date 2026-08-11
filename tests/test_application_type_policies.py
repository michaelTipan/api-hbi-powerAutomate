"""Policies / tipos confirmados v3 (sin Tipo Aplicación bancario)."""

import asyncio
from datetime import date

import pytest

from app.application.services.review_schema import (
    APPLICATION_TYPES_SUPPORTED,
    ApplicationSubtype,
    CanonicalApplicationType,
    ReviewSheets,
    TipoAplicacion,
    TipoAplicacionConfirmado,
    resolve_policy_from_tipo_confirmado,
    resolve_application_policy,
)
from app.application.use_cases.payment_validation_generate import generate_payment_validation
from tests.test_generate_tipo_aplicacion import _run_with_pdf_mock
from tests.test_generate_validation import (
    MockGraphClient,
    create_bank_excel,
    load_generated_workbook,
    set_env_vars,
    setup_client_structure)

@pytest.mark.parametrize("tipo", TipoAplicacionConfirmado.OPTIONS_ORDERED)
def test_confirmed_tipos_resolve_policy(tipo):
    policy = resolve_policy_from_tipo_confirmado(tipo)
    assert policy.tipo_aplicacion_original == tipo
    assert "genera_siguiente_extracto" not in policy.policy_dict()

def test_bank_tipo_removed():
    with pytest.raises(ValueError, match="tipo_aplicacion_from_bank_removed"):
        resolve_application_policy("PAGO", from_bank=True)

def test_application_types_supported_are_confirmed_nine():
    assert len(APPLICATION_TYPES_SUPPORTED) == 9
    assert "MIXTO" not in APPLICATION_TYPES_SUPPORTED

def test_abono_capital_policy_is_abono_canonical():
    p = resolve_policy_from_tipo_confirmado(TipoAplicacionConfirmado.ABONO_A_CAPITAL)
    assert p.canonical_enum == TipoAplicacion.ABONO
    assert p.subtipo_aplicacion == ApplicationSubtype.CAPITAL
    assert p.requiere_extracto is False

def test_cancelacion_sets_payoff_expected():
    p = resolve_policy_from_tipo_confirmado(TipoAplicacionConfirmado.CANCELACION_PAGO_TOTAL)
    assert p.payoff_expected is True
    assert p.tipo_aplicacion_canonica == CanonicalApplicationType.PAGO
    assert p.include_extract_in_composite is False

def test_parcial_does_not_auto_ibr():
    p = resolve_policy_from_tipo_confirmado(
        TipoAplicacionConfirmado.PAGO_PARCIAL_OBLIGACION_ACTUAL
    )
    assert p.actualiza_ibr is False
    assert p.include_extract_in_composite is True

def test_abono_excludes_extract_from_composite():
    p = resolve_policy_from_tipo_confirmado(TipoAplicacionConfirmado.ABONO_A_CAPITAL)
    assert p.include_extract_in_composite is False

def test_merge_name_tokens():
    from app.application.services.review_schema import (
        MERGE_NAME_TOKEN_MULTIPLE,
        merge_name_token_for_tipos)

    assert (
        merge_name_token_for_tipos([TipoAplicacionConfirmado.PAGO_OBLIGACION_ACTUAL]) == "PAGO"
    )
    assert (
        merge_name_token_for_tipos([TipoAplicacionConfirmado.ABONO_A_CAPITAL]) == "ABONO CAPITAL"
    )
    assert (
        merge_name_token_for_tipos([TipoAplicacionConfirmado.CANCELACION_PAGO_TOTAL])
        == "PAGO TOTAL"
    )
    assert (
        merge_name_token_for_tipos(
            [
                TipoAplicacionConfirmado.PAGO_OBLIGACION_ACTUAL,
                TipoAplicacionConfirmado.ABONO_A_CAPITAL,
            ]
        )
        == MERGE_NAME_TOKEN_MULTIPLE
    )

