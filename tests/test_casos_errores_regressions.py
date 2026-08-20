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
from app.application.services.payment_helpers import extract_fecha_limite_pago_from_pdf_text
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


@pytest.mark.skipif(
    not (_CASES / "Extracto Julio 25-06-2026 Julio Obligacion # 16.pdf").exists(),
    reason="fixture",
)
def test_servipetroleos_16_saldo_mora_from_footer_not_intereses():
    """Pie SALDO MORA 22.960.350; no el renglón 4.996.092 de intereses corrientes."""
    pdf = (_CASES / "Extracto Julio 25-06-2026 Julio Obligacion # 16.pdf").read_bytes()
    snap = parse_extract_snapshot(pdf)
    assert snap.valor_obligacion_actual == 21_099_070.0
    assert snap.saldo_vencido == 22_960_350.0
    assert snap.saldo_vencido_visible == 22_960_350.0


@pytest.mark.skipif(
    not (_CASES / "Extracto Julio 12-06-2026 Obligacion # 16.pdf").exists(),
    reason="fixture",
)
def test_servipetroleos_16_julio_12_saldo_mora_footer():
    pdf = (_CASES / "Extracto Julio 12-06-2026 Obligacion # 16.pdf").read_bytes()
    snap = parse_extract_snapshot(pdf)
    assert snap.saldo_vencido == 44_890_005.0


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


def test_pago_inmediato_recognized_as_fecha_limite():
    text = "TOTAL A PAGAR 55.596.854 PAGO INMEDIATO 4/08/2026"
    assert extract_fecha_limite_pago_from_pdf_text(text) == date(2026, 8, 4)


@pytest.mark.skipif(
    not (_CASES / "Extracto Agosto 3-08-2026 Obligación # 16.pdf").exists(),
    reason="fixture",
)
def test_agosto_16_post_aplicacion_reads_fecha_and_total_from_linear_text():
    pdf = (_CASES / "Extracto Agosto 3-08-2026 Obligación # 16.pdf").read_bytes()
    snap = parse_extract_snapshot(pdf)
    assert snap.fecha_limite == date(2026, 8, 4)
    assert snap.valor_obligacion_actual == 55_596_854.0
    assert snap.saldo_vencido_visible is None
    assert snap.parser_status.value in {"OK", "PARTIAL"}
