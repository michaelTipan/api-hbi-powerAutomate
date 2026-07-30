"""Resolución barata de proceso activo para Finalize UI (sin parsear review Excel)."""
from __future__ import annotations

from dataclasses import dataclass

from app.application.use_cases.payment_validation_process_control import (
    ProcessControlSnapshot,
)


class FinalizeProcessIdentityError(Exception):
    """ProcessKey / banco / estado de control incompatibles (409)."""

    def __init__(self, error_code: str, message: str) -> None:
        super().__init__(message)
        self.error_code = error_code
        self.message = message


@dataclass(frozen=True)
class ResolvedFinalizeTarget:
    bank_code: str
    process_key: str
    validation_file_path: str
    snapshot: ProcessControlSnapshot


def resolve_finalize_target_from_control(
    snap: ProcessControlSnapshot,
    *,
    bank_code: str,
    process_key: str,
) -> ResolvedFinalizeTarget:
    """Valida identidad contra el snapshot de control ya leído.

    No descarga el Excel de revisión. No adquiere locks.
    """
    want_bank = (bank_code or "").strip()
    want_key = (process_key or "").strip()
    if not want_bank or not want_key:
        raise FinalizeProcessIdentityError(
            "invalid_finalize_identity",
            "bank_code y process_key son obligatorios.",
        )

    snap_bank = (snap.bank_code or "").strip() or want_bank
    if snap_bank and snap_bank != want_bank:
        raise FinalizeProcessIdentityError(
            "process_key_bank_mismatch",
            "El ProcessKey no pertenece al banco indicado.",
        )

    if not snap.is_active:
        raise FinalizeProcessIdentityError(
            "process_not_active",
            "No hay un proceso activo en el Excel de control para este banco.",
        )

    got_key = (snap.process_key or "").strip()
    if not got_key or got_key != want_key:
        raise FinalizeProcessIdentityError(
            "process_key_mismatch",
            "El ProcessKey no coincide con el proceso activo del control.",
        )

    estado = (snap.estado_proceso or "").strip().upper()
    if estado != "REVISION_CREADA":
        raise FinalizeProcessIdentityError(
            "control_not_ready_for_finalize",
            "El control no está en REVISION_CREADA; Finalize no aplica.",
        )

    vpath = (snap.validation_file_path or "").strip().strip("/")
    if not vpath:
        raise FinalizeProcessIdentityError(
            "missing_validation_file_path",
            "Falta ValidationFilePath en el Excel de control.",
        )

    return ResolvedFinalizeTarget(
        bank_code=want_bank,
        process_key=want_key,
        validation_file_path=vpath,
        snapshot=snap,
    )
