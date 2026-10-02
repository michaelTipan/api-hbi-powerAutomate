"""Gating de ``force_rebuild`` desde la UI (recuperación post-formato de asiento).

CONSOLIDADO (pre-aplicar / dry-run fallido) siempre puede reconsolidar.
ERROR_APPLY solo si el intento no escribió ninguna tabla: sin ApplyIdempotencyKey
del proceso y sin créditos registrados en el último intento (los asientos siguen en
ASIENTOS porque solo se archivan con amortización completa).
AMORTIZACION_PARCIAL solo si el último intento dejó créditos con fallo de
formato: el job restaura esos PDF desde PROCESADOS (no las tablas ya aplicadas).
"""
from __future__ import annotations

from dataclasses import dataclass

from app.application.services.asiento_format_gate import (
    format_recovery_credits_from_attempt_json,
)
from app.application.use_cases.payment_validation_process_control import (
    ProcessControlSnapshot,
)

# Estados de control donde la UI puede pedir regenerar el consolidado.
_FORCE_REBUILD_OK_ESTADOS = frozenset({"CONSOLIDADO"})

_MSG_PARCIAL = (
    "No se puede reconsolidar en amortización parcial: el último intento no dejó "
    "créditos con asientos por corregir."
)
_MSG_NOT_ALLOWED = (
    "Solo se puede reconsolidar cuando el proceso está consolidado "
    "y aún no se aplicó la amortización."
)
_MSG_INACTIVE = "No hay un proceso activo para reconsolidar."
_MSG_ERROR_APPLY_WRITES = (
    "No se puede reconsolidar: este proceso ya registró pagos en tablas de amortización."
)


def error_apply_without_writes(snap: ProcessControlSnapshot) -> bool:
    """ERROR_APPLY sin ninguna tabla escrita en este proceso (equivale a CONSOLIDADO)."""
    from app.application.ui.amortization_attempt import parse_last_amortization_attempt_json

    process_key = (snap.process_key or "").strip()
    apply_key = (getattr(snap, "apply_idempotency_key", "") or "").strip()
    if not process_key or apply_key == process_key:
        return False
    attempt = parse_last_amortization_attempt_json(
        getattr(snap, "last_amortization_attempt_json", "") or ""
    )
    plan = attempt.plan_summary if attempt is not None else None
    return not (plan is not None and plan.applied_by_credit)


@dataclass(frozen=True)
class ForceRebuildGate:
    allowed: bool
    error_code: str | None = None
    user_message: str | None = None
    next_action: str | None = None


@dataclass(frozen=True)
class ForceRebuildAvailability:
    allowed: bool
    reason: str | None


_REASON_WRITE_DISABLED = (
    "Las escrituras desde la UI están deshabilitadas en este ambiente."
)
_REASON_MERGE_DISABLED = "Merge desde la UI todavía no está habilitado."
_REASON_NOT_SANDBOX = "Merge desde la UI no está permitido en este ambiente."
_REASON_LOCK_ACTIVE = (
    "Ya hay un Generate, Finalize, Notify o Merge en curso. Espere a que termine."
)


def compute_force_rebuild_availability(
    *,
    write_allowed: bool,
    merge_enabled: bool,
    sandbox: bool,
    mutation_active: bool,
    snap: ProcessControlSnapshot | None,
) -> ForceRebuildAvailability:
    """Evalúa si la UI puede ofrecer Reconsolidar (``force_rebuild=true``)."""
    if not write_allowed:
        return ForceRebuildAvailability(False, _REASON_WRITE_DISABLED)
    if not merge_enabled:
        return ForceRebuildAvailability(False, _REASON_MERGE_DISABLED)
    if not sandbox:
        return ForceRebuildAvailability(False, _REASON_NOT_SANDBOX)
    if mutation_active:
        return ForceRebuildAvailability(False, _REASON_LOCK_ACTIVE)
    gate = assess_ui_force_rebuild(snap)
    if not gate.allowed:
        return ForceRebuildAvailability(False, gate.user_message)
    return ForceRebuildAvailability(True, None)


def assess_ui_force_rebuild(snap: ProcessControlSnapshot | None) -> ForceRebuildGate:
    """Evalúa si el POST UI puede pasar ``force_rebuild=true``."""
    if snap is None or not snap.is_active:
        return ForceRebuildGate(
            False,
            "force_rebuild_not_allowed",
            _MSG_INACTIVE,
            "Actualice el detalle del proceso.",
        )
    estado = (snap.estado_proceso or "").strip().upper()
    format_credits = format_recovery_credits_from_attempt_json(
        getattr(snap, "last_amortization_attempt_json", "") or ""
    )
    if estado == "AMORTIZACION_PARCIAL":
        if not format_credits:
            return ForceRebuildGate(
                False,
                "force_rebuild_partial_blocked",
                _MSG_PARCIAL,
                "Si el fallo es de la tabla de amortización, corríjala y vuelva a "
                "procesar la amortización. Si no, excluya el crédito o cierre el "
                "proceso con amortización incompleta.",
            )
        # Hay créditos de formato: el job restaurará solo esos PDF.
    elif estado == "ERROR_APPLY":
        if not error_apply_without_writes(snap):
            return ForceRebuildGate(
                False,
                "force_rebuild_after_writes",
                _MSG_ERROR_APPLY_WRITES,
                "Excluya el crédito para procesar los demás, o cierre el proceso con "
                "amortización incompleta.",
            )
    elif estado not in _FORCE_REBUILD_OK_ESTADOS:
        return ForceRebuildGate(
            False,
            "force_rebuild_not_allowed",
            _MSG_NOT_ALLOWED,
            "Corrija los asientos y use reconsolidar solo en estado consolidado.",
        )
    if not (snap.historical_file_path or "").strip():
        return ForceRebuildGate(
            False,
            "missing_historical_file_path",
            "Falta HistoricalFilePath en el Excel de control.",
            "Actualice el detalle del proceso y verifique el Excel de control.",
        )
    if not (snap.email_pdf_path or "").strip():
        return ForceRebuildGate(
            False,
            "missing_email_pdf_path",
            "Falta EmailPdfPath en el Excel de control (correo de Notify).",
            "Actualice el detalle del proceso y verifique el Excel de control.",
        )
    return ForceRebuildGate(True)


__all__ = [
    "ForceRebuildAvailability",
    "ForceRebuildGate",
    "assess_ui_force_rebuild",
    "compute_force_rebuild_availability",
]
