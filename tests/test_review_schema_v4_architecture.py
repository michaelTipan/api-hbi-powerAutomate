"""Anti-regresión: el flujo operativo v4 no reintroduce distribución manual."""
from __future__ import annotations

from pathlib import Path

BANNED_HEADERS = (
    "Aplicar a obligación actual",
    "Aplicar a saldo vencido",
    "Abono adicional a capital",
    "Total asignado al crédito",
    "Saldo por asignar",
)

ALLOW_PATH_PARTS = (
    "review_schema.py",
    "setup_payment_followup_workbooks.py",
    "payment_followup_finalize.py",
)

ROOT = Path(__file__).resolve().parents[1] / "app"


def test_v4_operational_code_has_no_manual_distribution_headers():
    hits: list[str] = []
    for path in ROOT.rglob("*.py"):
        rel = path.as_posix()
        if any(part in rel.replace("\\", "/") for part in ALLOW_PATH_PARTS):
            continue
        text = path.read_text(encoding="utf-8")
        for banned in BANNED_HEADERS:
            if banned in text:
                for i, line in enumerate(text.splitlines(), start=1):
                    if banned in line:
                        hits.append(f"{path.relative_to(ROOT.parent)}:{i}:{banned}")
    assert hits == [], "Referencias v4 no justificadas:\n" + "\n".join(hits)


def test_v4_headers_constant_excludes_manual_distribution():
    from app.application.services.review_schema import (
        AplicacionPagosCols,
        MANUAL_DISTRIBUTION_HEADERS_V3,
    )

    assert set(AplicacionPagosCols.HEADERS).isdisjoint(MANUAL_DISTRIBUTION_HEADERS_V3)


def test_productive_v3_workbook_builder_removed():
    assert not (ROOT / "application" / "services" / "review_workbook_v3.py").exists()
