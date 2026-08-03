"""Cálculo puro de ``available_actions.notify`` para la UI.

Sin efectos secundarios de escritura: no adquiere locks, no envía correo.
Los destinatarios efectivos se leen de CORREOS.xlsx en el use case (como PA).
Consulta evidencia local de JobManager (jobs persistidos) para cubrir la
ventana stale de SharePoint tras un Notify exitoso.
"""
from __future__ import annotations

from dataclasses import dataclass

from app.application.job_manager import get_job_manager
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
    "Notify desde la UI no está permitido en este ambiente."
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
    "El correo de este proceso ya fue enviado."
)


@dataclass(frozen=True)
class NotifyAvailability:
    allowed: bool
    reason: str | None


def control_indicates_already_notified(snap: ProcessControlSnapshot) -> bool:
    """Evidencia de control: no usar solo la existencia de un PDF suelto.

    Las claves/PDF de un ProcessKey anterior (mismo banco, día nuevo) no cuentan:
    Generate/Finalize deben limpiarlas, pero la proyección falla cerrada ante residuales.
    """
    estado = (snap.estado_proceso or "").strip().upper()
    process_key = (snap.process_key or "").strip()
    idem = (snap.notify_idempotency_key or "").strip()
    email = (snap.email_pdf_path or "").strip()
    # Solo evidencia del proceso activo.
    if idem and process_key and idem != process_key:
        idem = ""
    if not idem:
        # PDF huérfano sin clave del proceso actual → no bloquea Notify.
        email = ""
    has_idem = bool(idem)
    has_email = bool(email)
    if estado == "PENDIENTE_ASIENTOS" and (has_idem or has_email):
        return True
    if has_idem and has_email:
        return True
    return False


def compute_notify_availability(
    *,
    write_allowed: bool,
    notify_enabled: bool,
    sandbox: bool,
    mutation_active: bool,
    snap: ProcessControlSnapshot | None,
    expected_process_key: str | None = None,
    sandbox_recipients_configured: bool | None = None,
) -> NotifyAvailability:
    """Evalúa si la UI puede ofrecer Notify (informativo; el POST revalida).

    ``sandbox_recipients_configured`` queda aceptado por compatibilidad y se
    ignora: los destinatarios vienen de CORREOS.xlsx en el envío.
    """
    del sandbox_recipients_configured  # legacy; no bloquea Notify UI
    if not write_allowed:
        return NotifyAvailability(False, _REASON_WRITE_DISABLED)
    if not notify_enabled:
        return NotifyAvailability(False, _REASON_NOTIFY_DISABLED)
    if not sandbox:
        return NotifyAvailability(False, _REASON_NOT_SANDBOX)
    if mutation_active:
        return NotifyAvailability(False, _REASON_LOCK_ACTIVE)
    if snap is None:
        return NotifyAvailability(False, _REASON_NO_ACTIVE)
    if not snap.is_active:
        return NotifyAvailability(False, _REASON_NO_ACTIVE)

    pk = (expected_process_key or snap.process_key or "").strip()

    # Capa 1a: control ya refleja Notify.
    if control_indicates_already_notified(snap):
        return NotifyAvailability(False, _REASON_ALREADY)

    # Capa 1b: evidencia local JobManager (cubre control stale FINALIZADO).
    if pk and get_job_manager().has_completed_notify(pk):
        return NotifyAvailability(False, _REASON_ALREADY)

    estado = (snap.estado_proceso or "").strip().upper()
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
