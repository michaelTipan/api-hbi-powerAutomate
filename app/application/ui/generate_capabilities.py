"""Cálculo puro de ``available_actions.generate`` para la UI (GET /banks).

Sin efectos secundarios: no adquiere locks de ``JobManager``, no escribe nada.
El llamador (router) resuelve los booleanos de entrada (feature flags, ambiente,
lock de generate/finalize vía lectura pura ``is_generate_or_finalize_active()``)
y esta función solo decide la disponibilidad.
"""
from __future__ import annotations

from dataclasses import dataclass

_REASON_WRITE_DISABLED = (
    "Las escrituras desde la UI están deshabilitadas en este ambiente."
)
_REASON_LOCK_ACTIVE = (
    "Ya existe un proceso Generate, Finalize o Notify activo. Espere a que termine."
)


@dataclass(frozen=True)
class GenerateAvailability:
    allowed: bool
    reason: str | None = None


def compute_generate_availability(
    *,
    write_allowed: bool,
    generate_or_finalize_active: bool,
) -> GenerateAvailability:
    """Función pura: mismos argumentos siempre producen el mismo resultado."""
    if not write_allowed:
        return GenerateAvailability(allowed=False, reason=_REASON_WRITE_DISABLED)
    if generate_or_finalize_active:
        return GenerateAvailability(allowed=False, reason=_REASON_LOCK_ACTIVE)
    return GenerateAvailability(allowed=True, reason=None)
