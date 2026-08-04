"""Cálculo puro de ``available_actions.generate`` para la UI (GET /banks).

Sin efectos secundarios: no adquiere locks de ``JobManager``, no escribe nada.
El llamador (router) resuelve los booleanos de entrada (feature flags, ambiente,
lock de generate/finalize vía lectura pura ``is_generate_or_finalize_active()``,
y el estado del Control del banco) y esta función solo decide la disponibilidad
y la acción primaria del dashboard.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

DashboardPrimaryAction = Literal["generate", "resume", "retry_read"]

_REASON_WRITE_DISABLED = (
    "Las escrituras desde la UI están deshabilitadas en este ambiente."
)
_REASON_LOCK_ACTIVE = (
    "Ya hay una operación en curso. Espere a que termine antes de iniciar otra."
)
_REASON_ACTIVE_PROCESS = (
    "Ya existe una validación activa para este banco. Abra el proceso existente "
    "para continuar desde el último paso completado."
)
_REASON_CONTROL_UNREADABLE = (
    "No pudimos leer el estado de este banco. Vuelva a intentar la consulta "
    "antes de iniciar una validación nueva."
)

# Alineado con Generate: tras cierre (amort aplicada, cancelado, soft-close
# o vacío) se permite un lote nuevo el mismo día.
_CONTROL_FREE_FOR_NEW_GENERATE = frozenset(
    {
        "",
        "VACIO",
        "AMORTIZACION_APLICADA",
        "CANCELADO",
        "CERRADO_SIN_AMORTIZAR",
    }
)
_OPERATIONAL_FREE_FOR_NEW_GENERATE = frozenset(
    {
        "NUEVO",
        "COMPLETADO",
        "CANCELADO",
        "CERRADO_SIN_AMORTIZAR",
    }
)


def bank_blocks_new_generate(
    *,
    process_key: str | None,
    control_estado: str | None,
    operational_status: str | None = None,
    is_active: bool = False,
) -> bool:
    """True si el Control del banco debe mostrar «Retomar» (no Generate nuevo)."""
    key = (process_key or "").strip()
    estado = (control_estado or "").strip().upper()
    operational = (operational_status or "").strip().upper()
    if not key:
        return False
    if estado in _CONTROL_FREE_FOR_NEW_GENERATE:
        return False
    if operational in _OPERATIONAL_FREE_FOR_NEW_GENERATE:
        return False
    if estado:
        return True
    return bool(is_active)


@dataclass(frozen=True)
class GenerateAvailability:
    allowed: bool
    reason: str | None = None
    dashboard_primary_action: DashboardPrimaryAction = "generate"


def compute_generate_availability(
    *,
    write_allowed: bool,
    generate_or_finalize_active: bool,
    control_readable: bool = True,
    has_active_process: bool = False,
) -> GenerateAvailability:
    """Función pura: mismos argumentos siempre producen el mismo resultado."""
    if not control_readable:
        return GenerateAvailability(
            allowed=False,
            reason=_REASON_CONTROL_UNREADABLE,
            dashboard_primary_action="retry_read",
        )
    if has_active_process:
        return GenerateAvailability(
            allowed=False,
            reason=_REASON_ACTIVE_PROCESS,
            dashboard_primary_action="resume",
        )
    if not write_allowed:
        return GenerateAvailability(
            allowed=False,
            reason=_REASON_WRITE_DISABLED,
            dashboard_primary_action="generate",
        )
    if generate_or_finalize_active:
        return GenerateAvailability(
            allowed=False,
            reason=_REASON_LOCK_ACTIVE,
            dashboard_primary_action="generate",
        )
    return GenerateAvailability(
        allowed=True,
        reason=None,
        dashboard_primary_action="generate",
    )
