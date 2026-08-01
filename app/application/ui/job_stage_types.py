"""Mapeo etapa UI ↔ tipos reales de JobManager.

No adivinar: solo los strings que escriben las colas.
"""
from __future__ import annotations

from typing import Final

# Tipos canónicos escritos por enqueue (fuente de verdad).
STAGE_JOB_TYPES: Final[dict[str, tuple[str, ...]]] = {
    "generate": ("generate",),
    "finalize": ("finalize",),
    "notify": ("notify_validar_extractos",),
    "merge": ("merge_composite_validado_pdfs",),
    # UI usa amortization_process; PA conserva dry_run/apply.
    "amortization": (
        "amortization_process",
        "amortization_dry_run",
        "amortization_apply",
    ),
    # Steps internos del timeline (dry_run/apply) para proyección legacy.
    "dry_run": ("amortization_dry_run",),
    "apply": ("amortization_apply", "amortization_process"),
}

# Alias de lectura tolerados (jobs antiguos / heurísticas).
STAGE_TYPE_ALIASES: Final[dict[str, tuple[str, ...]]] = {
    "notify": ("notify",),
    "merge": ("merge",),
}

# Errores de Finalize corregibles por el operador (datos del Excel).
FINALIZE_BUSINESS_ERROR_CODES: Final[frozenset[str]] = frozenset(
    {
        "review_has_open_errors",
        "process_not_approved",
        "missing_control_state",
        "invalid_control_state",
        "empty_estado_pago",
        "invalid_estado_pago",
        "multiple_review_errors",
        "INCOMPLETO_NOT_SUPPORTED",
        "estado_pago_no_finalizable",
        "empty_validar_pago",
        "invalid_validar_pago",
        "no_validar_requires_observation",
        "validar_requires_positive_total",
        "amount_mismatch",
        "missing_valor_intereses",
        "missing_abono_k",
        "missing_abono_capital",
        "missing_mora_a_aplicar",
        "missing_otros_valores",
        "pago_y_abono_requires_positive_cuota",
        "pago_y_abono_requires_positive_capital",
        "pago_y_abono_requires_zero_saldo",
        "abono_capital_requires_positive_capital",
        "abono_mora_requires_positive_mora",
        "abono_group_inconsistent",
        "abono_missing_bank_amount",
        "abono_missing_bank_date",
        "missing_reference_extract_route",
        "review_schema_version_1_requires_regenerate",
        "credit_folder_not_found",
        "amortization_table_not_found",
        "amortization_sheet_not_found",
        "sheet_missing",
        "header_modified",
    }
)

# Fallos temporales / infraestructura → reintento sin cambiar datos.
FINALIZE_TEMPORARY_ERROR_CODES: Final[frozenset[str]] = frozenset(
    {
        "excel_locked",
        "file_locked",
        "upload_failed",
        "graph_config_error",
        "sharepoint_locked",
        "timeout",
        "temporarily_unavailable",
    }
)


def job_type_matches_stage(job_type: str, stage: str) -> bool:
    typ = (job_type or "").strip().lower()
    if not typ:
        return False
    for token in STAGE_JOB_TYPES.get(stage, ()):
        if typ == token or token in typ:
            return True
    for token in STAGE_TYPE_ALIASES.get(stage, ()):
        if typ == token or token in typ:
            return True
    return False


def stage_for_job_type(job_type: str) -> str | None:
    typ = (job_type or "").strip().lower()
    if not typ:
        return None
    # Orden: más específico primero.
    for stage in (
        "amortization",
        "apply",
        "dry_run",
        "merge",
        "notify",
        "finalize",
        "generate",
    ):
        if job_type_matches_stage(typ, stage):
            if stage in {"dry_run", "apply"}:
                return "amortization" if stage == "apply" and "process" in typ else stage
            return stage
    return None


def classify_finalize_failure(error_code: str | None, *, severity: str | None = None) -> str:
    """Devuelve failed_business | failed_retryable."""
    code = (error_code or "").strip()
    sev = (severity or "").strip().lower()
    if code in FINALIZE_TEMPORARY_ERROR_CODES or "locked" in code.lower():
        return "failed_retryable"
    if code in FINALIZE_BUSINESS_ERROR_CODES:
        return "failed_business"
    if sev == "recoverable":
        return "failed_retryable"
    if sev in {"warning", "business"}:
        return "failed_business"
    # Por defecto: corrección de datos (fail-safe operativo).
    return "failed_business"
