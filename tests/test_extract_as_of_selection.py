"""Selección as-of fecha banco (abril ≠ junio)."""
from __future__ import annotations

from datetime import date

from app.application.services.extract_selection import (
    choose_extract_as_of_bank_date,
    select_extract_as_of_bank_date_from_bytes,
)
from app.application.services.colombia_time import graph_datetime_colombia_date


def _cand(name: str, path: str, **extra) -> dict:
    out = {
        "name": name,
        "relative_path": path,
        "source_location": "EXTRACTOS",
        "id": name,
    }
    out.update(extra)
    return out


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


def test_a_same_fecha_limite_max_created_wins():
    bank = date(2026, 8, 15)
    fl = date(2026, 8, 15)
    scored = [
        (_cand("a", "EXTRACTOS/a.pdf", createdDateTime="2026-08-01T15:00:00Z"), fl, b"A", "ha"),
        (_cand("b", "EXTRACTOS/b.pdf", createdDateTime="2026-08-10T17:00:00Z"), fl, b"B", "hb"),
        (_cand("c", "EXTRACTOS/c.pdf", createdDateTime="2026-08-14T15:00:00Z"), fl, b"C", "hc"),
    ]
    out = choose_extract_as_of_bank_date(scored, bank)
    assert out.error_code is None
    assert out.candidate["name"] == "c"


def test_b_same_day_later_created_wins():
    bank = date(2026, 8, 15)
    fl = date(2026, 8, 15)
    scored = [
        (_cand("am", "EXTRACTOS/am.pdf", createdDateTime="2026-08-15T14:00:00Z"), fl, b"AM", "h9"),
        (_cand("pm", "EXTRACTOS/pm.pdf", createdDateTime="2026-08-15T22:00:00Z"), fl, b"PM", "h17"),
    ]
    out = choose_extract_as_of_bank_date(scored, bank)
    assert out.candidate["name"] == "pm"


def test_c_created_next_day_excluded():
    bank = date(2026, 8, 15)
    fl = date(2026, 8, 15)
    scored = [
        (_cand("ok", "EXTRACTOS/ok.pdf", createdDateTime="2026-08-15T22:00:00Z"), fl, b"OK", "hok"),
        (_cand("late", "EXTRACTOS/late.pdf", createdDateTime="2026-08-16T13:00:00Z"), fl, b"L", "hlate"),
    ]
    out = choose_extract_as_of_bank_date(scored, bank)
    assert out.error_code is None
    assert out.candidate["name"] == "ok"


def test_d_identical_created_different_hashes_is_tie():
    bank = date(2026, 8, 15)
    fl = date(2026, 8, 15)
    ts = "2026-08-10T12:00:00Z"
    scored = [
        (_cand("a", "EXTRACTOS/a.pdf", createdDateTime=ts), fl, b"A", "hash-a"),
        (_cand("b", "EXTRACTOS/b.pdf", createdDateTime=ts), fl, b"B", "hash-b"),
    ]
    out = choose_extract_as_of_bank_date(scored, bank)
    assert out.error_code == "extract_tie_as_of_bank_date"
    assert out.candidate is None


def test_e_frozen_evidence_ignores_newer_extract():
    pool = [
        _cand("new", "EXTRACTOS/new.pdf", createdDateTime="2026-08-14T15:00:00Z"),
        _cand("old", "EXTRACTOS/old.pdf", createdDateTime="2026-08-01T15:00:00Z"),
    ]
    content = {"EXTRACTOS/new.pdf": b"NEW", "EXTRACTOS/old.pdf": b"OLD"}

    def fecha_fn(data: bytes):
        return date(2026, 8, 15)

    out = select_extract_as_of_bank_date_from_bytes(
        pool,
        bank_date=date(2026, 8, 15),
        content_by_relative_path=content,
        fecha_limite_fn=fecha_fn,
        frozen_evidence={"path": "EXTRACTOS/old.pdf", "item_id": "old"},
    )
    assert out.selection_reason == "frozen_evidence"
    assert out.candidate["name"] == "old"


def test_f_last_modified_does_not_override_created():
    bank = date(2026, 8, 15)
    fl = date(2026, 8, 15)
    scored = [
        (
            _cand(
                "older",
                "EXTRACTOS/older.pdf",
                createdDateTime="2026-08-10T12:00:00Z",
                lastModifiedDateTime="2026-08-20T12:00:00Z",
            ),
            fl,
            b"O",
            "ho",
        ),
        (
            _cand(
                "newer_created",
                "EXTRACTOS/newer.pdf",
                createdDateTime="2026-08-14T12:00:00Z",
                lastModifiedDateTime="2026-08-11T12:00:00Z",
            ),
            fl,
            b"N",
            "hn",
        ),
    ]
    out = choose_extract_as_of_bank_date(scored, bank)
    assert out.candidate["name"] == "newer_created"


def test_g_utc_next_day_still_colombia_bank_date_is_eligible():
    assert graph_datetime_colombia_date("2026-08-16T03:30:00Z") == date(2026, 8, 15)
    assert graph_datetime_colombia_date("2026-08-16T06:30:00Z") == date(2026, 8, 16)
    bank = date(2026, 8, 15)
    fl = date(2026, 8, 15)
    scored = [
        (
            _cand("col_d", "EXTRACTOS/col.pdf", createdDateTime="2026-08-16T03:30:00Z"),
            fl,
            b"C",
            "hc",
        ),
        (
            _cand("utc_d1", "EXTRACTOS/utc.pdf", createdDateTime="2026-08-16T06:30:00Z"),
            fl,
            b"U",
            "hu",
        ),
    ]
    out = choose_extract_as_of_bank_date(scored, bank)
    assert out.error_code is None
    assert out.candidate["name"] == "col_d"
