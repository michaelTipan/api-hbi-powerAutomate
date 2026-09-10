"""Fail-closed: can_apply exige todos los PAGO listos; sin Apply parcial."""


def test_payment_applicable_false_when_any_pago_has_error():
    """Un crédito listo y otro en error → payment_applicable False (fail-closed)."""
    items = [
        {
            "tipo_aplicacion": "PAGO",
            "application_status": "WOULD_APPLY",
            "error_code": None,
            "tabla_amortizacion_path": "CLIENT/A/tabla.xlsx",
        },
        {
            "tipo_aplicacion": "PAGO",
            "application_status": "ERROR",
            "error_code": "TABLE_HEADERS_NOT_FOUND",
            "tabla_amortizacion_path": "CLIENT/B/tabla.xlsx",
        },
    ]
    payment_applicable = all(
        it.get("application_status")
        in ("WOULD_APPLY", "WOULD_ADOPT_EXISTING", "ALREADY_APPLIED")
        and not it.get("error_code")
        for it in items
    )
    assert payment_applicable is False

    from app.application.use_cases.amortization_fill_apply import _writable_planned_items

    dry = {"items": items}
    writable = _writable_planned_items(dry)
    # Apply parcial sigue omitiendo ítems con error si se llegara a ejecutar;
    # con fail-closed can_apply=false no se entra a Apply.
    assert list(writable.keys()) == ["CLIENT/A/tabla.xlsx"]


def test_payment_applicable_true_when_all_pagos_ready():
    items = [
        {
            "tipo_aplicacion": "PAGO",
            "application_status": "WOULD_APPLY",
            "error_code": None,
            "tabla_amortizacion_path": "CLIENT/A/tabla.xlsx",
        },
        {
            "tipo_aplicacion": "PAGO",
            "application_status": "ALREADY_APPLIED",
            "error_code": None,
            "tabla_amortizacion_path": "CLIENT/B/tabla.xlsx",
        },
    ]
    payment_applicable = all(
        it.get("application_status")
        in ("WOULD_APPLY", "WOULD_ADOPT_EXISTING", "ALREADY_APPLIED")
        and not it.get("error_code")
        for it in items
    )
    assert payment_applicable is True


def test_event_incomplete_with_uploads_is_partial_not_failed():
    """Manifest incompleto + tablas subidas → status partial (AMORTIZACION_PARCIAL)."""
    tables_uploaded = ["CLIENT/A/tabla.xlsx"]
    event_completeness = {"all_expected_events_completed": False}
    status = "ok"
    apply_errors: list = []
    if apply_errors and not tables_uploaded:
        status = "failed"
    elif apply_errors:
        status = "partial"
    if status == "ok" and not event_completeness.get("all_expected_events_completed"):
        if tables_uploaded:
            status = "partial"
        else:
            status = "failed"
    assert status == "partial"
