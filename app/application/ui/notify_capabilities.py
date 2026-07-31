"""Cálculo puro de ``available_actions.notify`` para la UI.

Sin efectos secundarios: no adquiere locks, no envía correo, no lee CORREOS.xlsx,
no parsea históricos. Solo flags + snapshot de control + lectura del lock.
"""
from __future__ import annotations

from dataclasses import dataclass

from app.application.use_cases.payment_validation_process_control import (
    ProcessControlSnapshot,
)

_REASON_WRITE_DISABLED = (
    "Las escrituras desde la UI están deshabilitadas en este ambiente."
)
_REASON_NOTIFY_DISABLED = (
    "Notify desde la UI todavía no está habilitado."
)
_REASON_NOT_SANDBOX = (
    "Notify desde la UI solo está permitido en sandbox."
)
_REASON_NO_RECIPIENTS = (
    "No están configurados los destinatarios de prueba para Notify."
)
_REASON_LOCK_ACTIVE = (
    "Ya hay un Generate, Finalize o Notify en curso. Espere a que termine."
)
_REASON_NO_ACTIVE = (
    "No hay un proceso activo listo para Notify en este banco."
)
_REASON_KEY_MISMATCH = (
    "El ProcessKey no coincide con el proceso activo del control."
)
_REASON_STATE = (
    "El control no está en FINALIZADO; Notify no aplica todavía."
)
_REASON_NO_HISTORICAL = (
    "Falta HistoricalFilePath en el Excel de control."
)
_REASON_ALREADY = (
    "Notify ya fue completado para este proceso (idempotente)."
)


@dataclass(frozen=True)
class NotifyAvailability:
    allowed: bool
    reason: str | None


def compute_notify_availability(
    *,
    write_allowed: bool,
    notify_enabled: bool,
    sandbox: bool,
    sandbox_recipients_configured: bool,
    mutation_active: bool,
    snap: ProcessControlSnapshot | None,
    expected_process_key: str | None = None,
) -> NotifyAvailability:
    """Evalúa si la UI puede ofrecer Notify (informativo; el POST revalida)."""
    if not write_allowed:
        return NotifyAvailability(False, _REASON_WRITE_DISABLED)
    if not notify_enabled:
        return NotifyAvailability(False, _REASON_NOTIFY_DISABLED)
    if not sandbox:
        return NotifyAvailability(False, _REASON_NOT_SANDBOX)
    if not sandbox_recipients_configured:
        return NotifyAvailability(False, _REASON_NO_RECIPIENTS)
    if mutation_active:
        return NotifyAvailability(False, _REASON_LOCK_ACTIVE)
    if snap is None:
        return NotifyAvailability(False, _REASON_NO_ACTIVE)
    if not snap.is_active:
        return NotifyAvailability(False, _REASON_NO_ACTIVE)

    # Ya notificado: no ofrecer reintento que reenviaría (el POST sería idempotente).
    estado = (snap.estado_proceso or "").strip().upper()
    if (
        estado == "PENDIENTE_ASIENTOS"
        and (snap.email_pdf_path or "").strip()
        and (snap.notify_idempotency_key or "").strip()
    ):
        return NotifyAvailability(False, _REASON_ALREADY)

    if estado != "FINALIZADO":
        return NotifyAvailability(False, _REASON_STATE)
    if not (snap.historical_file_path or "").strip():
        return NotifyAvailability(False, _REASON_NO_HISTORICAL)
    if expected_process_key is not None:
        want = (expected_process_key or "").strip()
        got = (snap.process_key or "").strip()
        if not want or want != got:
            return NotifyAvailability(False, _REASON_KEY_MISMATCH)
    elif not (snap.process_key or "").strip():
        return NotifyAvailability(False, _REASON_NO_ACTIVE)
    return NotifyAvailability(True, None)
