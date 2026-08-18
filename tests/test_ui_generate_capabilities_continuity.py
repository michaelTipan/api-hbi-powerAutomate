"""Tests puros de generate_capabilities (continuidad R3.3)."""
from __future__ import annotations

from app.application.ui.generate_capabilities import (
    bank_blocks_new_generate,
    compute_generate_availability,
)


def test_generate_allowed_cuando_banco_libre() -> None:
    av = compute_generate_availability(
        write_allowed=True,
        generate_or_finalize_active=False,
        control_readable=True,
        has_active_process=False,
    )
    assert av.allowed is True
    assert av.dashboard_primary_action == "generate"
    assert av.reason is None


def test_resume_cuando_hay_proceso_activo() -> None:
    av = compute_generate_availability(
        write_allowed=True,
        generate_or_finalize_active=False,
        control_readable=True,
        has_active_process=True,
    )
    assert av.allowed is False
    assert av.dashboard_primary_action == "resume"
    assert "validación activa" in (av.reason or "").lower()
    assert "|" not in (av.reason or "")
    assert "PENDIENTE_ASIENTOS" not in (av.reason or "")


def test_retry_read_cuando_control_ilegible() -> None:
    av = compute_generate_availability(
        write_allowed=True,
        generate_or_finalize_active=False,
        control_readable=False,
        has_active_process=False,
    )
    assert av.allowed is False
    assert av.dashboard_primary_action == "retry_read"
    assert "vuelva a intentar" in (av.reason or "").lower()


def test_control_ilegible_tiene_prioridad_sobre_proceso_activo() -> None:
    av = compute_generate_availability(
        write_allowed=True,
        generate_or_finalize_active=False,
        control_readable=False,
        has_active_process=True,
    )
    assert av.dashboard_primary_action == "retry_read"
    assert av.allowed is False


def test_write_disabled_solo_si_banco_libre() -> None:
    av = compute_generate_availability(
        write_allowed=False,
        generate_or_finalize_active=False,
        control_readable=True,
        has_active_process=False,
    )
    assert av.allowed is False
    assert av.dashboard_primary_action == "generate"


def test_amortizacion_aplicada_no_bloquea_nuevo_generate() -> None:
    assert (
        bank_blocks_new_generate(
            process_key="payment-validation|banco_bancolombia|2026-08-01|abc",
            control_estado="AMORTIZACION_APLICADA",
            operational_status="COMPLETADO",
            is_active=True,
        )
        is False
    )


def test_cancelado_no_bloquea_nuevo_generate() -> None:
    assert (
        bank_blocks_new_generate(
            process_key="payment-validation|banco_bancolombia|2026-08-01|abc",
            control_estado="CANCELADO",
            operational_status="CANCELADO",
            is_active=False,
        )
        is False
    )


def test_cerrado_sin_amortizar_no_bloquea_nuevo_generate() -> None:
    assert (
        bank_blocks_new_generate(
            process_key="payment-validation|banco_bancolombia|2026-08-01|abc",
            control_estado="CERRADO_SIN_AMORTIZAR",
            operational_status="CERRADO_SIN_AMORTIZAR",
            is_active=False,
        )
        is False
    )


def test_pendiente_asientos_si_bloquea_nuevo_generate() -> None:
    assert (
        bank_blocks_new_generate(
            process_key="payment-validation|banco_bancolombia|2026-08-01|abc",
            control_estado="PENDIENTE_ASIENTOS",
            operational_status="ESPERANDO_SOPORTES",
            is_active=True,
        )
        is True
    )


def test_generando_bloquea_nuevo_generate() -> None:
    assert (
        bank_blocks_new_generate(
            process_key="payment-validation|banco_bancolombia|2026-08-01|abc",
            control_estado="GENERANDO",
            operational_status="GENERANDO",
            is_active=True,
        )
        is True
    )
