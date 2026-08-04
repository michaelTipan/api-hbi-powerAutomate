"""Disponibilidad pura de Cancelar lote / Cerrar sin amortizar (UI)."""

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
    "Cancelar lote solo aplica mientras el proceso está en revisión "
    "(antes de finalizar)."
)
_REASON_SOFT_CLOSE_PHASE = (
    "Cerrar sin amortizar solo aplica cuando el proceso ya consolidó o está "
    "en amortización y no se aplicarán las tablas por la API."
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
) -> ProcessControlActionAvailability:
    """Cancelar lote: solo REVISION_CREADA / ERROR_GENERATE (pre-Finalize)."""
    estado = (control_estado or "").strip().upper()
    if mutation_active:
        return ProcessControlActionAvailability(False, _REASON_LOCK_ACTIVE)
    if not write_allowed:
        return ProcessControlActionAvailability(False, _REASON_WRITE_DISABLED)
    if estado in CANCEL_ALLOWED_STATES and is_active:
        return ProcessControlActionAvailability(True, None)
    return ProcessControlActionAvailability(False, _REASON_CANCEL_PHASE)


def compute_soft_close_availability(
    *,
    write_allowed: bool,
    mutation_active: bool,
    control_estado: str | None,
) -> ProcessControlActionAvailability:
    """Cerrar sin amortizar: fase tardía (post-Merge / amort)."""
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
