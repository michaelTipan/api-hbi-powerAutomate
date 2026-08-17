"""Selección del último extracto de la unidad (máx. fecha límite)."""
from __future__ import annotations

from datetime import date

from app.application.services.extract_selection import (
    EXTRACT_SOURCE_EXTRACTOS,
    choose_extract_as_of_bank_date,
    select_extract_as_of_bank_date_from_bytes,
)
from app.application.services.colombia_time import graph_datetime_colombia_date


def _cand(name: str, path: str, **extra) -> dict:
    out = {
        "name": name,
        "relative_path": path,
        "source_location": EXTRACT_SOURCE_EXTRACTOS,
        "id": name,
    }
    out.update(extra)
    return out


def test_max_fecha_limite_selects_latest_even_if_after_bank_month():
    """ui-stable: el último extracto de la unidad (máx. fecha límite), no as-of mes banco."""
    april = date(2026, 4, 15)
    scored = [
        (_cand("abr", "EXTRACTOS/abr.pdf"), date(2026, 4, 23), b"APR", "h1"),
        (_cand("may", "EXTRACTOS/may.pdf"), date(2026, 5, 23), b"MAY", "h2"),
        (_cand("jun", "EXTRACTOS/jun.pdf"), date(2026, 6, 23), b"JUN", "h3"),
    ]
    out = choose_extract_as_of_bank_date(scored, april)
    assert out.error_code is None
    assert out.fecha_limite == date(2026, 6, 23)
    assert out.candidate["name"] == "jun"
    assert out.selection_reason == "max_fecha_limite"


def test_may_bank_still_selects_june_if_june_is_latest():
    may = date(2026, 5, 10)
    scored = [
        (_cand("abr", "EXTRACTOS/abr.pdf"), date(2026, 4, 23), b"APR", "h1"),
        (_cand("may", "EXTRACTOS/may.pdf"), date(2026, 5, 23), b"MAY", "h2"),
        (_cand("jun", "EXTRACTOS/jun.pdf"), date(2026, 6, 23), b"JUN", "h3"),
    ]
    out = choose_extract_as_of_bank_date(scored, may)
    assert out.fecha_limite == date(2026, 6, 23)
    assert out.candidate["name"] == "jun"


def test_only_later_month_extracts_are_still_selected():
    april = date(2026, 4, 15)
    scored = [
        (_cand("may", "EXTRACTOS/may.pdf"), date(2026, 5, 23), b"MAY", "h2"),
        (_cand("jun", "EXTRACTOS/jun.pdf"), date(2026, 6, 23), b"JUN", "h3"),
    ]
    out = choose_extract_as_of_bank_date(scored, april)
    assert out.error_code is None
    assert out.candidate["name"] == "jun"


def test_prior_month_when_it_is_the_latest():
    may = date(2026, 5, 10)
    scored = [
        (_cand("abr", "EXTRACTOS/abr.pdf"), date(2026, 4, 23), b"APR", "h1"),
        (_cand("feb", "EXTRACTOS/feb.pdf"), date(2026, 2, 23), b"FEB", "h0"),
    ]
    out = choose_extract_as_of_bank_date(scored, may)
    assert out.error_code is None
    assert out.fecha_limite == date(2026, 4, 23)
    assert out.selection_reason == "max_fecha_limite"


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


def test_c_later_created_wins_even_if_calendar_day_after_bank():
    bank = date(2026, 8, 15)
    fl = date(2026, 8, 15)
    scored = [
        (_cand("ok", "EXTRACTOS/ok.pdf", createdDateTime="2026-08-15T22:00:00Z"), fl, b"OK", "hok"),
        (_cand("late", "EXTRACTOS/late.pdf", createdDateTime="2026-08-16T13:00:00Z"), fl, b"L", "hlate"),
    ]
    out = choose_extract_as_of_bank_date(scored, bank)
    assert out.error_code is None
    assert out.candidate["name"] == "late"


def test_d_identical_created_different_hashes_is_tie():
    bank = date(2026, 8, 15)
    fl = date(2026, 8, 15)
    ts = "2026-08-10T12:00:00Z"
    scored = [
        (_cand("a", "EXTRACTOS/a.pdf", createdDateTime=ts), fl, b"A", "hash-a"),
        (_cand("b", "EXTRACTOS/b.pdf", createdDateTime=ts), fl, b"B", "hash-b"),
    ]
    out = choose_extract_as_of_bank_date(scored, bank)
    assert out.error_code == "extract_tie_max_fecha_limite"
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
    assert out.candidate["name"] == "utc_d1"


def test_same_hash_prefers_extractos_folder_over_credit_root():
    bank = date(2026, 5, 10)
    fl = date(2026, 5, 23)
    scored = [
        (
            _cand("root", "CREDITO/root.pdf", source_location="credit_root"),
            fl,
            b"SAME",
            "same-hash",
        ),
        (
            _cand("canon", "CREDITO/EXTRACTOS/canon.pdf"),
            fl,
            b"SAME",
            "same-hash",
        ),
    ]
    out = choose_extract_as_of_bank_date(scored, bank)
    assert out.error_code is None
    assert out.candidate["name"] == "canon"
