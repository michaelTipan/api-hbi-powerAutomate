"""Cálculo puro de ``available_actions.finalize`` para la UI.

Sin efectos secundarios: no adquiere locks, no descarga Excel de revisión,
no escribe Graph. Solo flags + snapshot de control + lectura del lock.
"""
from __future__ import annotations

from dataclasses import dataclass

from app.application.use_cases.payment_validation_process_control import (
    ProcessControlSnapshot,
)

_REASON_WRITE_DISABLED = (
    "Este ambiente no permite hacer cambios."
)
_REASON_FINALIZE_DISABLED = (
    "Finalizar la revisión todavía no está habilitado en este ambiente."
)
_REASON_NOT_SANDBOX = (
    "Finalizar la revisión no está permitido en este ambiente."
)
_REASON_LOCK_ACTIVE = (
    "Ya hay otra operación en curso. Espere a que termine."
)
_REASON_NO_ACTIVE = (
    "No hay un proceso activo listo para finalizar la revisión en este banco."
)
_REASON_KEY_MISMATCH = (
    "Este proceso ya no es el proceso activo del banco. Actualice la página."
)
_REASON_STATE = (
    "La revisión todavía no está lista para finalizar."
)
_REASON_NO_VALIDATION_PATH = (
    "No se encontró el archivo de revisión del proceso. Genere la revisión de nuevo."
)


@dataclass(frozen=True)
class FinalizeAvailability:
    allowed: bool
    reason: str | None


def compute_finalize_availability(
    *,
    write_allowed: bool,
    finalize_enabled: bool,
    sandbox: bool,
    generate_or_finalize_active: bool,
    snap: ProcessControlSnapshot | None,
    expected_process_key: str | None = None,
) -> FinalizeAvailability:
    """Evalúa si la UI puede ofrecer Finalize (informativo; el POST revalida)."""
    if not write_allowed:
        return FinalizeAvailability(False, _REASON_WRITE_DISABLED)
    if not finalize_enabled:
        return FinalizeAvailability(False, _REASON_FINALIZE_DISABLED)
    if not sandbox:
        return FinalizeAvailability(False, _REASON_NOT_SANDBOX)
    if generate_or_finalize_active:
        return FinalizeAvailability(False, _REASON_LOCK_ACTIVE)
    if snap is None:
        return FinalizeAvailability(False, _REASON_NO_ACTIVE)
    if not snap.is_active:
        return FinalizeAvailability(False, _REASON_NO_ACTIVE)
    estado = (snap.estado_proceso or "").strip().upper()
    if estado != "REVISION_CREADA":
        return FinalizeAvailability(False, _REASON_STATE)
    if not (snap.validation_file_path or "").strip():
        return FinalizeAvailability(False, _REASON_NO_VALIDATION_PATH)
    if expected_process_key is not None:
        want = (expected_process_key or "").strip()
        got = (snap.process_key or "").strip()
        if not want or want != got:
            return FinalizeAvailability(False, _REASON_KEY_MISMATCH)
    elif not (snap.process_key or "").strip():
        return FinalizeAvailability(False, _REASON_NO_ACTIVE)
    return FinalizeAvailability(True, None)
