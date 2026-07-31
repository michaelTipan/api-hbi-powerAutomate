"""Resolución barata de proceso activo para Merge UI (sin unir PDFs)."""
from __future__ import annotations

from dataclasses import dataclass

from app.application.job_manager import get_job_manager
from app.application.ui.merge_capabilities import control_indicates_already_merged
from app.application.use_cases.merge_composite_validado_pdfs import (
    MERGE_RUNNABLE_STATES,
)
from app.application.use_cases.payment_validation_process_control import (
    ProcessControlSnapshot,
)

_ALREADY_MSG = "Los soportes de este proceso ya fueron consolidados."


class MergeProcessIdentityError(Exception):
    """ProcessKey / banco / estado de control incompatibles (409)."""

    def __init__(self, error_code: str, message: str) -> None:
        super().__init__(message)
        self.error_code = error_code
        self.message = message


@dataclass(frozen=True)
class ResolvedMergeTarget:
    bank_code: str
    process_key: str
    historical_file_path: str
    email_pdf_path: str
    snapshot: ProcessControlSnapshot


def resolve_merge_target_from_control(
    snap: ProcessControlSnapshot,
    *,
    bank_code: str,
    process_key: str,
) -> ResolvedMergeTarget:
    """Valida identidad contra el snapshot de control ya leído.

    No une PDFs. No adquiere locks. No escribe Graph.
    Rechaza ProcessKey ya consolidados (control o evidencia JobManager).
    """
    want_bank = (bank_code or "").strip()
    want_key = (process_key or "").strip()
    if not want_bank or not want_key:
        raise MergeProcessIdentityError(
            "invalid_merge_identity",
            "bank_code y process_key son obligatorios.",
        )

    snap_bank = (snap.bank_code or "").strip() or want_bank
    if snap_bank and snap_bank != want_bank:
        raise MergeProcessIdentityError(
            "process_key_bank_mismatch",
            "El ProcessKey no pertenece al banco indicado.",
        )

    if not snap.is_active:
        raise MergeProcessIdentityError(
            "process_not_active",
            "No hay un proceso activo en el Excel de control para este banco.",
        )

    got_key = (snap.process_key or "").strip()
    if not got_key or got_key != want_key:
        raise MergeProcessIdentityError(
            "process_key_mismatch",
            "El ProcessKey no coincide con el proceso activo del control.",
        )

    if control_indicates_already_merged(snap) or get_job_manager().has_completed_merge(
        want_key
    ):
        raise MergeProcessIdentityError("already_merged", _ALREADY_MSG)

    estado = (snap.estado_proceso or "").strip().upper()
    if estado not in MERGE_RUNNABLE_STATES:
        raise MergeProcessIdentityError(
            "control_not_ready_for_merge",
            "El control no está en un estado que permita consolidar soportes.",
        )
    if estado == "CONSOLIDADO":
        raise MergeProcessIdentityError("already_merged", _ALREADY_MSG)

    hpath = (snap.historical_file_path or "").strip().strip("/")
    if not hpath:
        raise MergeProcessIdentityError(
            "missing_historical_file_path",
            "Falta HistoricalFilePath en el Excel de control.",
        )
    epath = (snap.email_pdf_path or "").strip().strip("/")
    if not epath:
        raise MergeProcessIdentityError(
            "missing_email_pdf_path",
            "Falta EmailPdfPath en el Excel de control (correo de Notify).",
        )

    return ResolvedMergeTarget(
        bank_code=want_bank,
        process_key=want_key,
        historical_file_path=hpath,
        email_pdf_path=epath,
        snapshot=snap,
    )
