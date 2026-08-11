"""Selección as-of fecha banco (abril ≠ junio)."""
from __future__ import annotations

from datetime import date

from app.application.services.extract_selection import (
    choose_extract_as_of_bank_date,
    select_extract_as_of_bank_date_from_bytes,
)


def _cand(name: str, path: str) -> dict:
    return {
        "name": name,
        "relative_path": path,
        "source_location": "EXTRACTOS",
        "id": name,
    }


def test_april_bank_does_not_select_june():
    april = date(2026, 4, 15)
    scored = [
        (_cand("abr", "EXTRACTOS/abr.pdf"), date(2026, 4, 23), b"APR", "h1"),
        (_cand("may", "EXTRACTOS/may.pdf"), date(2026, 5, 23), b"MAY", "h2"),
        (_cand("jun", "EXTRACTOS/jun.pdf"), date(2026, 6, 23), b"JUN", "h3"),
    ]
    out = choose_extract_as_of_bank_date(scored, april)
    assert out.error_code is None
    assert out.fecha_limite == date(2026, 4, 23)
    assert out.candidate["name"] == "abr"
    assert out.selection_reason == "same_month_max_fecha_limite"


def test_may_bank_selects_may_not_june():
    may = date(2026, 5, 10)
    scored = [
        (_cand("abr", "EXTRACTOS/abr.pdf"), date(2026, 4, 23), b"APR", "h1"),
        (_cand("may", "EXTRACTOS/may.pdf"), date(2026, 5, 23), b"MAY", "h2"),
        (_cand("jun", "EXTRACTOS/jun.pdf"), date(2026, 6, 23), b"JUN", "h3"),
    ]
    out = choose_extract_as_of_bank_date(scored, may)
    assert out.fecha_limite == date(2026, 5, 23)
    assert out.candidate["name"] == "may"


def test_only_future_extracts_fail_closed():
    april = date(2026, 4, 15)
    scored = [
        (_cand("may", "EXTRACTOS/may.pdf"), date(2026, 5, 23), b"MAY", "h2"),
        (_cand("jun", "EXTRACTOS/jun.pdf"), date(2026, 6, 23), b"JUN", "h3"),
    ]
    out = choose_extract_as_of_bank_date(scored, april)
    assert out.error_code == "extract_as_of_not_found"
    assert out.candidate is None


def test_prior_month_when_no_same_month():
    may = date(2026, 5, 10)
    scored = [
        (_cand("abr", "EXTRACTOS/abr.pdf"), date(2026, 4, 23), b"APR", "h1"),
        (_cand("jun", "EXTRACTOS/jun.pdf"), date(2026, 6, 23), b"JUN", "h3"),
    ]
    out = choose_extract_as_of_bank_date(scored, may)
    assert out.error_code is None
    assert out.fecha_limite == date(2026, 4, 23)
    assert out.selection_reason == "as_of_max_fecha_limite_le_bank_date"


def test_from_bytes_frozen_evidence_wins():
    pool = [
        _cand("new", "EXTRACTOS/new.pdf"),
        _cand("old", "EXTRACTOS/old.pdf"),
    ]
    content = {
        "EXTRACTOS/new.pdf": b"NEW",
        "EXTRACTOS/old.pdf": b"OLD",
    }

    def fecha_fn(data: bytes):
        return date(2026, 6, 1) if data == b"NEW" else date(2026, 4, 1)

    out = select_extract_as_of_bank_date_from_bytes(
        pool,
        bank_date=date(2026, 4, 15),
        content_by_relative_path=content,
        fecha_limite_fn=fecha_fn,
        frozen_evidence={"path": "EXTRACTOS/old.pdf", "item_id": "old"},
    )
    assert out.selection_reason == "frozen_evidence"
    assert out.candidate["name"] == "old"
