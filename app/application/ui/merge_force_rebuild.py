"""Gating de ``force_rebuild`` desde la UI (recuperación post-formato de asiento).

CONSOLIDADO (pre-aplicar / dry-run fallido) siempre puede reconsolidar.
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
    "No se puede reconsolidar automáticamente en amortización parcial: "
    "los asientos pueden estar en PROCESADOS. Restaure los PDF a ASIENTOS "
    "o use la herramienta de Power Automate."
)
_MSG_NOT_ALLOWED = (
    "Solo se puede reconsolidar cuando el proceso está consolidado "
    "y aún no se aplicó la amortización."
)
_MSG_INACTIVE = "No hay un proceso activo para reconsolidar."


@dataclass(frozen=True)
class ForceRebuildGate:
    allowed: bool
    error_code: str | None = None
    user_message: str | None = None
    next_action: str | None = None


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
                "Si el fallo es de tabla Excel, corríjala y vuelva a procesar "
                "la amortización. Si es de formato de asiento, reemplace el PDF "
                "en ASIENTOS (o restaure desde PROCESADOS) y reconsolide.",
            )
        # Hay créditos de formato: el job restaurará solo esos PDF.
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


__all__ = ["ForceRebuildGate", "assess_ui_force_rebuild"]
