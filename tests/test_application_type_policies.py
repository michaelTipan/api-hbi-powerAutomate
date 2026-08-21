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

def test_application_types_supported_are_confirmed_seven():
    assert len(APPLICATION_TYPES_SUPPORTED) == 7
    assert "MIXTO" not in APPLICATION_TYPES_SUPPORTED
    assert TipoAplicacionConfirmado.SALDO_VENCIDO_Y_ABONO_CAPITAL not in APPLICATION_TYPES_SUPPORTED
    assert TipoAplicacionConfirmado.PAGO_PARCIAL_OBLIGACION_ACTUAL not in APPLICATION_TYPES_SUPPORTED

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

def test_parcial_legacy_alias_is_obligacion_actual_ibr_by_cut():
    from app.application.services.review_schema import normalize_tipo_aplicacion_confirmado

    assert (
        normalize_tipo_aplicacion_confirmado(
            TipoAplicacionConfirmado.PAGO_PARCIAL_OBLIGACION_ACTUAL
        )
        == TipoAplicacionConfirmado.PAGO_OBLIGACION_ACTUAL
    )
    p = resolve_policy_from_tipo_confirmado(
        TipoAplicacionConfirmado.PAGO_PARCIAL_OBLIGACION_ACTUAL
    )
    assert p.tipo_aplicacion_original == TipoAplicacionConfirmado.PAGO_OBLIGACION_ACTUAL
    assert p.subtipo_aplicacion == ApplicationSubtype.CUOTA
    assert p.actualiza_ibr is None
    assert p.include_extract_in_composite is True

def test_abono_excludes_extract_from_composite():
    p = resolve_policy_from_tipo_confirmado(TipoAplicacionConfirmado.ABONO_A_CAPITAL)
    assert p.include_extract_in_composite is False

def test_merge_name_tokens():
    from app.application.services.review_schema import (
        MERGE_NAME_TOKEN_MULTIPLE,
        merge_name_token_for_tipos)

    assert (
        merge_name_token_for_tipos(
            [TipoAplicacionConfirmado.PAGO_PARCIAL_OBLIGACION_ACTUAL]
        )
        == "PAGO CUOTA"
    )
    assert (
        merge_name_token_for_tipos([TipoAplicacionConfirmado.ABONO_A_CAPITAL])
        == "ABONO A CAPITAL"
    )
    assert (
        merge_name_token_for_tipos([TipoAplicacionConfirmado.CANCELACION_PAGO_TOTAL])
        == "PAGO TOTAL"
    )
    assert (
        merge_name_token_for_tipos([TipoAplicacionConfirmado.APLICACION_SALDO_VENCIDO])
        == "ABONO A CUOTAS EN MORA"
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


def test_ibr_on_time_parcial_and_adelantado():
    from datetime import date as date_cls

    from app.application.services.review_schema import resolve_actualiza_ibr

    p = resolve_policy_from_tipo_confirmado(
        TipoAplicacionConfirmado.PAGO_OBLIGACION_ACTUAL
    )
    limite = date_cls(2026, 6, 15)
    assert (
        resolve_actualiza_ibr(p, payment_date=limite, fecha_limite=limite) is True
    )
    assert (
        resolve_actualiza_ibr(
            p, payment_date=date_cls(2026, 6, 1), fecha_limite=limite
        )
        is False
    )
    vencido = resolve_policy_from_tipo_confirmado(
        TipoAplicacionConfirmado.APLICACION_SALDO_VENCIDO
    )
    assert (
        resolve_actualiza_ibr(vencido, payment_date=limite, fecha_limite=limite)
        is False
    )


def test_combinado_does_not_imply_cuota_cerrada():
    p = resolve_policy_from_tipo_confirmado(TipoAplicacionConfirmado.PAGO_COMBINADO)
    assert p.cierra_cuota is False
    assert p.tipo_aplicacion_original == TipoAplicacionConfirmado.PAGO_COMBINADO
    assert (
        resolve_policy_from_tipo_confirmado(
            TipoAplicacionConfirmado.PAGO_COMBINADO_Y_ABONO_CAPITAL
        ).cierra_cuota
        is False
    )


def test_legacy_combinado_alias_normalizes():
    from app.application.services.review_schema import (
        normalize_tipo_aplicacion_confirmado,
    )

    assert (
        normalize_tipo_aplicacion_confirmado(
            "PAGO COMBINADO (SALDO VENCIDO + OBLIGACIÓN ACTUAL)"
        )
        == TipoAplicacionConfirmado.PAGO_COMBINADO
    )
    assert (
        normalize_tipo_aplicacion_confirmado("PAGO COMBINADO + ABONO A CAPITAL")
        == TipoAplicacionConfirmado.PAGO_COMBINADO_Y_ABONO_CAPITAL
    )


def test_everyday_labels_and_pre_rename_aliases():
    from app.application.services.review_schema import (
        TIPO_CONFIRMADO_ALIASES,
        normalize_tipo_aplicacion_confirmado,
    )

    assert TipoAplicacionConfirmado.PAGO_OBLIGACION_ACTUAL == "PAGO CUOTA"
    assert TipoAplicacionConfirmado.APLICACION_SALDO_VENCIDO == "ABONO A CUOTAS EN MORA"
    assert TipoAplicacionConfirmado.ABONO_A_CAPITAL == "ABONO A CAPITAL"
    assert TipoAplicacionConfirmado.CANCELACION_PAGO_TOTAL == "PAGO TOTAL"
    assert "CANCELACIÓN" not in TipoAplicacionConfirmado.CANCELACION_PAGO_TOTAL

    for legacy, canonical in TIPO_CONFIRMADO_ALIASES.items():
        assert normalize_tipo_aplicacion_confirmado(legacy) == canonical

    p = resolve_policy_from_tipo_confirmado("CANCELACIÓN / PAGO TOTAL")
    assert p.payoff_expected is True
    assert p.tipo_aplicacion_original == TipoAplicacionConfirmado.CANCELACION_PAGO_TOTAL

