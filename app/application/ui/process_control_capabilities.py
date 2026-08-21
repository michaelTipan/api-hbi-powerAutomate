"""Disponibilidad pura de Cancelar proceso / Cerrar sin amortizar (UI)."""

from __future__ import annotations

from dataclasses import dataclass

from app.application.use_cases.payment_validation_cancel import CANCEL_ALLOWED_STATES
from app.application.use_cases.payment_validation_soft_close import (
    SOFT_CLOSE_ALLOWED_STATES,
    SOFT_CLOSE_ESTADO,
)

_REASON_WRITE_DISABLED = (
    "Las escrituras desde la UI están deshabilitadas en este ambiente."
)
_REASON_LOCK_ACTIVE = (
    "Ya hay una operación en curso. Espere a que termine antes de iniciar otra."
)
_REASON_CANCEL_PHASE = (
    "Cancelar proceso solo está disponible antes de consolidar. "
    "En amortización use Cerrar sin amortizar."
)
_REASON_FINANCIAL_WRITES = (
    "Este proceso ya registró escrituras financieras. Continúe con la recuperación "
    "o el reintento de amortización; no se revierte contabilidad."
)
_REASON_SOFT_CLOSE_PHASE = (
    "Cerrar sin amortizar solo aplica en la fase de amortización "
    "(proceso ya consolidado) cuando no se aplicarán las tablas por la API."
)
_REASON_ALREADY_CLOSED = (
    "Este proceso ya está cerrado. Puede iniciar una validación nueva "
    "desde el panel."
)


@dataclass(frozen=True)
class ProcessControlActionAvailability:
    allowed: bool
    reason: str | None = None


def compute_cancel_lote_availability(
    *,
    write_allowed: bool,
    mutation_active: bool,
    control_estado: str | None,
    is_active: bool = True,
    process_key: str | None = None,
    apply_idempotency_key: str | None = None,
) -> ProcessControlActionAvailability:
    """Cancelar proceso en fases activas sin Apply financiero confirmado."""
    estado = (control_estado or "").strip().upper()
    key = (process_key or "").strip()
    apply_key = (apply_idempotency_key or "").strip()
    if mutation_active:
        return ProcessControlActionAvailability(False, _REASON_LOCK_ACTIVE)
    if not write_allowed:
        return ProcessControlActionAvailability(False, _REASON_WRITE_DISABLED)
    if (key and key == apply_key) or estado in {
        "AMORTIZACION_PARCIAL",
        "AMORTIZACION_APLICADA",
    }:
        return ProcessControlActionAvailability(False, _REASON_FINANCIAL_WRITES)
    if estado in {"CONSOLIDADO", "ERROR_APPLY"}:
        return ProcessControlActionAvailability(False, _REASON_CANCEL_PHASE)
    if estado in CANCEL_ALLOWED_STATES and is_active:
        return ProcessControlActionAvailability(True, None)
    return ProcessControlActionAvailability(False, _REASON_CANCEL_PHASE)


def compute_soft_close_availability(
    *,
    write_allowed: bool,
    mutation_active: bool,
    control_estado: str | None,
) -> ProcessControlActionAvailability:
    """Cerrar sin amortizar: solo fase de amortización (post-CONSOLIDADO)."""
    estado = (control_estado or "").strip().upper()
    if mutation_active:
        return ProcessControlActionAvailability(False, _REASON_LOCK_ACTIVE)
    if not write_allowed:
        return ProcessControlActionAvailability(False, _REASON_WRITE_DISABLED)
    if estado == SOFT_CLOSE_ESTADO:
        return ProcessControlActionAvailability(False, _REASON_ALREADY_CLOSED)
    if estado in SOFT_CLOSE_ALLOWED_STATES:
        return ProcessControlActionAvailability(True, None)
    return ProcessControlActionAvailability(False, _REASON_SOFT_CLOSE_PHASE)
