"""Merge: fallback de asignación lote y fecha banco en nombre PDF."""
from __future__ import annotations

from datetime import date

from app.application.services.asiento_lote_assignment import (
    ASIENTO_ASSIGNMENT_NO_MATCH,
    ASIENTO_ASSIGNMENT_PARSE_FAILED,
    AssignmentOutcome,
)
from app.application.services.historical_application_rows import _coerce_historical_date
from app.application.services.merge_group_validation import (
    credit_items_cover_expected_creditos,
    credit_items_have_single_asiento_each,
)
from app.application.use_cases.merge_composite_validado_pdfs import (
    _apply_lote_assignment_or_fallback,
    _naming_date_for_group,
    _staged_asiento_paths_globally_unambiguous,
)


def _group_row(*, credito: str = "258", monto: float = 1_000_000) -> dict:
    return {
        "credito_digits": credito,
        "credito_label": f"CREDITO # {credito}",
        "monto_banco": monto,
        "fecha_banco": "2026-08-04 00:00:00",
        "include_extract_in_composite": True,
        "requiere_extracto": True,
    }


def _credit_item(credito: str, path: str) -> dict:
    return {
        "credito": credito,
        "asiento_pdf_paths": [path],
        "extracto_pdf_paths": ["clientes/x/extracto.pdf"],
    }


def test_coerce_historical_date_parses_iso_datetime_string():
    assert _coerce_historical_date("2026-08-04 00:00:00") == date(2026, 8, 4)


def test_naming_date_for_group_uses_fecha_banco_not_process_date():
    rows = [_group_row()]
    naming = _naming_date_for_group(rows, "", date(2026, 8, 17))
    assert naming == date(2026, 8, 4)


def test_staged_paths_unambiguous_single_pdf_per_credit():
    staged = [
        (
            "p1",
            "PAGO",
            [_group_row(credito="258")],
            [_credit_item("258", "asientos/a.pdf")],
            [],
        ),
        (
            "p2",
            "PAGO",
            [_group_row(credito="99", monto=500_000)],
            [_credit_item("99", "asientos/b.pdf")],
            [],
        ),
    ]
    assert _staged_asiento_paths_globally_unambiguous(staged) is True


def test_staged_paths_not_unambiguous_when_same_pdf_reused():
    staged = [
        (
            "p1",
            "PAGO",
            [_group_row(credito="258")],
            [_credit_item("258", "asientos/shared.pdf")],
            [],
        ),
        (
            "p2",
            "PAGO",
            [_group_row(credito="99")],
            [_credit_item("99", "asientos/shared.pdf")],
            [],
        ),
    ]
    assert _staged_asiento_paths_globally_unambiguous(staged) is False


def test_lote_fallback_keeps_prevalidated_items_on_parse_or_no_match():
    rows = [_group_row()]
    items = [_credit_item("258", "asientos/a.pdf")]
    assert credit_items_cover_expected_creditos(rows, items)
    assert credit_items_have_single_asiento_each(items)

    lote = AssignmentOutcome(
        assignment={"p1": ()},
        errors={"p1": ASIENTO_ASSIGNMENT_PARSE_FAILED},
    )
    out_items, skips = _apply_lote_assignment_or_fallback(
        id_pago="p1",
        group_rows=rows,
        credit_items=items,
        pre_skips=[],
        lote_assignment=lote,
    )
    assert out_items == items
    assert skips == []


def test_lote_fallback_clears_items_when_multiple_asientos_same_credit():
    rows = [_group_row()]
    items = [
        {
            "credito": "258",
            "asiento_pdf_paths": ["asientos/a.pdf", "asientos/b.pdf"],
            "extracto_pdf_paths": [],
        }
    ]
    lote = AssignmentOutcome(
        assignment={"p1": ()},
        errors={"p1": ASIENTO_ASSIGNMENT_NO_MATCH},
    )
    out_items, skips = _apply_lote_assignment_or_fallback(
        id_pago="p1",
        group_rows=rows,
        credit_items=items,
        pre_skips=[],
        lote_assignment=lote,
    )
    assert out_items == []
    assert any(ASIENTO_ASSIGNMENT_NO_MATCH in s for s in skips)


def test_merge_failure_operator_message_detects_assignment_codes():
    from app.application.job_status_enrichment import _merge_failure_operator_message

    msg = _merge_failure_operator_message(
        {
            "skipped": ["id_pago=x ASIENTO_ASSIGNMENT_NO_MATCH credito=258"],
            "incomplete_groups": [],
        }
    )
    assert msg is not None
    assert "monto banco" in msg[0].lower()


def test_finalize_message_for_code_tipo_aplicacion_not_unknown():
    from app.application.job_status_enrichment import finalize_message_for_code

    user, nxt = finalize_message_for_code("tipo_aplicacion_required")
    assert "inconveniente técnico" not in user.lower()
    assert "Tipo de aplicación" in user
    assert nxt.strip()
