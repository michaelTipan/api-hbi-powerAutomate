"""Helpers de snapshot Control para tests UI."""
from __future__ import annotations

from app.application.use_cases.payment_validation_process_control import (
    ProcessControlSnapshot,
)


def make_snap(**overrides: object) -> ProcessControlSnapshot:
    base = dict(
        control_file_path="control/control_proceso_validacion_pagos_banco_bancolombia.xlsx",
        estado_proceso="REVISION_CREADA",
        is_active=True,
        process_key="payment-validation|banco_bancolombia|2026-07-29|abc-123",
        process_id="abc-123",
        validation_file_path="revisión/validacion_pagos_demo.xlsx",
        historical_file_path="",
        secretary_file_path="",
        email_pdf_path="",
        notify_idempotency_key="",
        merge_manifest_path="",
        merge_idempotency_key="",
        apply_idempotency_key="",
        bank_code="banco_bancolombia",
        bank_name="Bancolombia",
        execution_id="",
        execution_log_path="",
    )
    base.update(overrides)
    return ProcessControlSnapshot(**base)  # type: ignore[arg-type]
