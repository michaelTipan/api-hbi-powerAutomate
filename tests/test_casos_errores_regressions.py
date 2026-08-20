"""Regresiones detectadas en campaña sandbox casos-errores (ago 2026)."""
from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest
from openpyxl import load_workbook

from app.application.services.amortization_workbook import detect_amortization_sheet
from app.application.services.extract_selection import (
    EXTRACT_SOURCE_EXTRACTOS,
    choose_extract_as_of_bank_date,
)
from app.application.services.extract_snapshot_parser import parse_extract_snapshot
from app.application.services.review_schema import normalize_credito_digits

_CASES = Path(__file__).resolve().parents[1] / "casos-errores"


def _cand(name: str, path: str, **extra: object) -> dict:
    out = {
        "name": name,
        "relative_path": path,
        "source_location": EXTRACT_SOURCE_EXTRACTOS,
    }
    out.update(extra)
    return out


@pytest.mark.skipif(not (_CASES / "Extracto Junio 24-06-2026 Obligacion # 53.pdf").exists(), reason="fixture")
def test_credito_53_saldo_mora_from_panel_before_label():
    pdf = (_CASES / "Extracto Junio 24-06-2026 Obligacion # 53.pdf").read_bytes()
    snap = parse_extract_snapshot(pdf)
    assert snap.saldo_vencido == 3_173_346.0


@pytest.mark.skipif(not (_CASES / "Extracto Junio 16-06-2026 Obligacion # 99.pdf").exists(), reason="fixture")
def test_credito_99_saldo_mora_after_label_still_works():
    pdf = (_CASES / "Extracto Junio 16-06-2026 Obligacion # 99.pdf").read_bytes()
    snap = parse_extract_snapshot(pdf)
    assert snap.saldo_vencido == 48_796_722.0


def test_normalize_credito_folder_credito_2_hash_99():
    assert normalize_credito_digits("CREDITO 2 # 99 VIGENTE") == "99"


def test_extract_tiebreak_by_filename_when_created_equal():
    fl = date(2026, 7, 4)
    ts = "2026-08-19T20:06:12Z"
    scored = [
        (
            _cand("Extracto Julio 12-06-2026 Obligacion # 16.pdf", "EXTRACTOS/a.pdf", createdDateTime=ts),
            fl,
            b"A",
            "ha",
        ),
        (
            _cand("Extracto Julio 25-06-2026 Julio Obligacion # 16.pdf", "EXTRACTOS/b.pdf", createdDateTime=ts),
            fl,
            b"B",
            "hb",
        ),
    ]
    out = choose_extract_as_of_bank_date(scored, date(2026, 8, 1))
    assert out.error_code is None
    assert "25-06-2026" in out.candidate["name"]
    assert out.selection_reason == "max_fecha_limite_filename_date"


@pytest.mark.skipif(not (_CASES / "Tabla de amortizacion1.xlsx").exists(), reason="fixture")
def test_ingeorozcol_amortization_sheet_detects_capital_alias():
    path = _CASES / "Tabla de amortizacion1.xlsx"
    wb = load_workbook(path, read_only=True, data_only=True)
    match = detect_amortization_sheet(wb, tabla_amortizacion_path=str(path))
    assert match.worksheet.title == "INGEOROZCOL"
    assert "abono_k" in match.headers
