"""Resolución barata de identidad de proceso para Amortización UI (sin dry-run)."""
from __future__ import annotations

from dataclasses import dataclass

from app.application.job_manager import get_job_manager
from app.application.ui.amortization_capabilities import (
    control_indicates_already_applied,
)
from app.application.use_cases.amortization_fill_dry_run import (
    AMORTIZATION_RUNNABLE_STATES,
)
from app.application.use_cases.payment_validation_process_control import (
    ProcessControlSnapshot,
)

_ALREADY_MSG = "La amortización de este proceso ya fue aplicada anteriormente."
_MERGE_INCOMPLETE_MSG = (
    "La consolidación de soportes quedó parcial; complétela antes de amortizar."
)


class AmortizationProcessIdentityError(Exception):
    """ProcessKey / banco / estado de control incompatibles (409)."""

    def __init__(self, error_code: str, message: str) -> None:
        super().__init__(message)
        self.error_code = error_code
        self.message = message


@dataclass(frozen=True)
class ResolvedAmortizationTarget:
    bank_code: str
    process_key: str
    historical_file_path: str
    merge_manifest_path: str
    snapshot: ProcessControlSnapshot


def resolve_amortization_target_from_control(
    snap: ProcessControlSnapshot,
    *,
    bank_code: str,
    process_key: str,
) -> ResolvedAmortizationTarget:
    """Valida identidad contra el snapshot de control ya leído.

    No ejecuta dry-run ni Apply. No adquiere locks. No escribe Graph.
    Rechaza ProcessKey ya aplicados (control o evidencia JobManager).
    """
    want_bank = (bank_code or "").strip()
    want_key = (process_key or "").strip()
    if not want_bank or not want_key:
        raise AmortizationProcessIdentityError(
            "invalid_amortization_identity",
            "bank_code y process_key son obligatorios.",
        )

    snap_bank = (snap.bank_code or "").strip() or want_bank
    if snap_bank and snap_bank != want_bank:
        raise AmortizationProcessIdentityError(
            "process_key_bank_mismatch",
            "El ProcessKey no pertenece al banco indicado.",
        )

    if not snap.is_active:
        raise AmortizationProcessIdentityError(
            "process_not_active",
            "No hay un proceso activo en el Excel de control para este banco.",
        )

    got_key = (snap.process_key or "").strip()
    if not got_key or got_key != want_key:
        raise AmortizationProcessIdentityError(
            "process_key_mismatch",
            "El ProcessKey no coincide con el proceso activo del control.",
        )

    if control_indicates_already_applied(snap) or get_job_manager().has_completed_amortization(
        want_key
    ):
        raise AmortizationProcessIdentityError("already_applied", _ALREADY_MSG)

    estado = (snap.estado_proceso or "").strip().upper()
    if estado not in AMORTIZATION_RUNNABLE_STATES:
        raise AmortizationProcessIdentityError(
            "control_not_ready_for_amortization",
            "El control no está en un estado que permita procesar amortización.",
        )
    if estado == "MERGE_PARCIAL":
        raise AmortizationProcessIdentityError(
            "merge_incomplete_not_applicable", _MERGE_INCOMPLETE_MSG
        )

    manifest_path = (snap.merge_manifest_path or "").strip().strip("/")
    if not manifest_path:
        raise AmortizationProcessIdentityError(
            "missing_merge_manifest_path",
            "Falta MergeManifestPath en el Excel de control.",
        )
    hist_path = (snap.historical_file_path or "").strip().strip("/")
    if not hist_path:
        raise AmortizationProcessIdentityError(
            "missing_historical_file_path",
            "Falta HistoricalFilePath en el Excel de control.",
        )

    return ResolvedAmortizationTarget(
        bank_code=want_bank,
        process_key=want_key,
        historical_file_path=hist_path,
        merge_manifest_path=manifest_path,
        snapshot=snap,
    )
