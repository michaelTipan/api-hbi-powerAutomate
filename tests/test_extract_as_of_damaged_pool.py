"""Selección as-of: dañados no invalidan pool si hay legibles."""
from __future__ import annotations

from datetime import date

from app.application.services.extract_selection import select_extract_as_of_bank_date_from_bytes


def test_damaged_sibling_does_not_block_readable_as_of() -> None:
    bank = date(2026, 5, 23)
    good = b"%PDF-good%"
    bad = b"%PDF-bad%"
    pool = [
        {
            "name": "Extracto bueno.pdf",
            "relative_path": "c/Extracto bueno.pdf",
            "source_location": "credit_root",
        },
        {
            "name": "Extracto malo.pdf",
            "relative_path": "c/Extracto malo.pdf",
            "source_location": "credit_root",
        },
    ]
    content = {
        "c/Extracto bueno.pdf": good,
        "c/Extracto malo.pdf": bad,
    }

    def fecha_fn(raw: bytes) -> date | None:
        if raw == good:
            return date(2026, 5, 23)
        return None

    outcome = select_extract_as_of_bank_date_from_bytes(
        pool,
        bank_date=bank,
        content_by_relative_path=content,
        fecha_limite_fn=fecha_fn,
    )
    assert outcome.error_code is None
    assert outcome.candidate is not None
    assert outcome.candidate["name"] == "Extracto bueno.pdf"
    assert outcome.fecha_limite == date(2026, 5, 23)
    assert (outcome.meta or {}).get("damaged_count") == 1


def test_all_damaged_still_blocks() -> None:
    pool = [
        {
            "name": "Extracto malo.pdf",
            "relative_path": "c/Extracto malo.pdf",
            "source_location": "credit_root",
        }
    ]
    outcome = select_extract_as_of_bank_date_from_bytes(
        pool,
        bank_date=date(2026, 5, 23),
        content_by_relative_path={"c/Extracto malo.pdf": b"x"},
        fecha_limite_fn=lambda _b: None,
    )
    assert outcome.error_code == "fecha_limite_extracto_not_readable"
