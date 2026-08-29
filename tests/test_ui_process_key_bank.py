"""Tests parse_bank_from_process_key."""
from __future__ import annotations

from app.application.ui.process_key import parse_bank_from_process_key


def test_parse_bank_from_canonical_process_key() -> None:
    key = "payment-validation|banco_bancolombia|2026-07-29|abc-123"
    assert parse_bank_from_process_key(key) == "banco_bancolombia"


def test_parse_bank_bogota() -> None:
    key = "payment-validation|banco_bogota|2026-01-15|uuid-here"
    assert parse_bank_from_process_key(key) == "banco_bogota"


def test_parse_bank_invalid_returns_none() -> None:
    assert parse_bank_from_process_key("pk-legacy") is None
    assert parse_bank_from_process_key("payment-validation|unknown|2026-01-01|x") is None
