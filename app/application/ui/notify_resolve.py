"""Resolución barata de proceso activo para Notify UI (sin CORREOS.xlsx)."""
from __future__ import annotations

from dataclasses import dataclass

from app.application.use_cases.payment_validation_process_control import (
    ProcessControlSnapshot,
)


class NotifyProcessIdentityError(Exception):
    """ProcessKey / banco / estado de control incompatibles (409)."""

    def __init__(self, error_code: str, message: str) -> None:
        super().__init__(message)
        self.error_code = error_code
        self.message = message


@dataclass(frozen=True)
class ResolvedNotifyTarget:
    bank_code: str
    process_key: str
    historical_file_path: str
    snapshot: ProcessControlSnapshot


def resolve_notify_target_from_control(
    snap: ProcessControlSnapshot,
    *,
    bank_code: str,
    process_key: str,
) -> ResolvedNotifyTarget:
    """Valida identidad contra el snapshot de control ya leído.

    No lee CORREOS.xlsx. No adquiere locks. No envía correo.
    """
    want_bank = (bank_code or "").strip()
    want_key = (process_key or "").strip()
    if not want_bank or not want_key:
        raise NotifyProcessIdentityError(
            "invalid_notify_identity",
            "bank_code y process_key son obligatorios.",
        )

    snap_bank = (snap.bank_code or "").strip() or want_bank
    if snap_bank and snap_bank != want_bank:
        raise NotifyProcessIdentityError(
            "process_key_bank_mismatch",
            "El ProcessKey no pertenece al banco indicado.",
        )

    if not snap.is_active:
        raise NotifyProcessIdentityError(
            "process_not_active",
            "No hay un proceso activo en el Excel de control para este banco.",
        )

    got_key = (snap.process_key or "").strip()
    if not got_key or got_key != want_key:
        raise NotifyProcessIdentityError(
            "process_key_mismatch",
            "El ProcessKey no coincide con el proceso activo del control.",
        )

    estado = (snap.estado_proceso or "").strip().upper()
    already = (
        estado == "PENDIENTE_ASIENTOS"
        and (snap.email_pdf_path or "").strip()
        and (snap.notify_idempotency_key or "").strip()
    )
    if not already and estado != "FINALIZADO":
        raise NotifyProcessIdentityError(
            "control_not_ready_for_notify",
            "El control no está en FINALIZADO; Notify no aplica.",
        )

    hpath = (snap.historical_file_path or "").strip().strip("/")
    if not hpath:
        raise NotifyProcessIdentityError(
            "missing_historical_file_path",
            "Falta HistoricalFilePath en el Excel de control.",
        )

    return ResolvedNotifyTarget(
        bank_code=want_bank,
        process_key=want_key,
        historical_file_path=hpath,
        snapshot=snap,
    )
