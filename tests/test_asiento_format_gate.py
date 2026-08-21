"""Gate de formato ERP de asientos (fase 3 = mismo parser que amortización)."""
from __future__ import annotations

from io import BytesIO

from pypdf import PdfWriter

from app.application.services.asiento_format_gate import (
    ACCOUNTING_PARSE_FAILED,
    PDF_TEXT_NOT_EXTRACTABLE,
    classify_asiento_pdf_bytes,
    format_recovery_credits_from_attempt_json,
)
from tests.test_merge_composite_control_workbook import _asiento_pdf


def _tiny_pdf() -> bytes:
    writer = PdfWriter()
    writer.add_blank_page(width=72, height=72)
    buf = BytesIO()
    writer.write(buf)
    return buf.getvalue()


def test_classify_parseable_asiento_ok() -> None:
    raw = _asiento_pdf(1_000.0, credit="264")
    assert classify_asiento_pdf_bytes(raw, credit="264", path="a.pdf") is None


def test_classify_blank_pdf_not_extractable() -> None:
    assert classify_asiento_pdf_bytes(_tiny_pdf(), credit="264") == PDF_TEXT_NOT_EXTRACTABLE


def test_classify_garbage_bytes_parse_failed() -> None:
    assert classify_asiento_pdf_bytes(b"not-a-pdf", credit="1") in {
        PDF_TEXT_NOT_EXTRACTABLE,
        ACCOUNTING_PARSE_FAILED,
    }


def test_format_recovery_credits_from_attempt() -> None:
    raw = (
        '{"attempt_id":"j1","outcome":"partial","created_at":"2026-08-20T12:00:00-05:00",'
        '"operational_issues":[{"issue_id":"i1","stage":"amortization",'
        '"category":"correction_required","severity":"business","recoverable":true,'
        '"title":"Crédito 53","user_message":"ilegible",'
        '"location":{"credit":"53"},"technical_reference":"PDF_TEXT_NOT_EXTRACTABLE"}],'
        '"affected_payment_ids":[]}'
    )
    assert format_recovery_credits_from_attempt_json(raw) == frozenset({"53"})


def test_format_recovery_credits_ignores_table_errors() -> None:
    raw = (
        '{"attempt_id":"j1","outcome":"partial","created_at":"2026-08-20T12:00:00-05:00",'
        '"operational_issues":[{"issue_id":"i1","stage":"amortization",'
        '"category":"partial_result","severity":"business","recoverable":true,'
        '"title":"Crédito 53","user_message":"locked",'
        '"location":{"credit":"53"},"technical_reference":"EXCEL_LOCKED"}],'
        '"affected_payment_ids":[]}'
    )
    assert format_recovery_credits_from_attempt_json(raw) == frozenset()
