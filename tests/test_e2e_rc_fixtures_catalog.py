"""Tests locales del catálogo de fixtures RC y guards Notify sandbox."""

import pytest

from scripts.e2e_rc.fixtures_catalog import (
    CRITICAL_FIXTURE_GAPS,
    HBI_DOMAIN_BLOCK,
    SANDBOX_NOTIFY_ALLOWLIST,
    assert_sandbox_notify_recipients,
    blank_image_like_pdf,
    catalog_as_dicts,
    gaps_by_scenario,
    minimal_text_pdf,
)
from scripts.e2e_rc.review_edit import approve_credits_split
from scripts.e2e_rc.path_guard import AUTHORIZED_CLIENTS_BASE


def test_fixture_catalog_covers_known_blocked_ids():
    ids = {n.scenario_id for n in CRITICAL_FIXTURE_GAPS}
    for sid in ("E05", "E13", "E25", "E28", "E40"):
        assert sid in ids
    assert all(AUTHORIZED_CLIENTS_BASE in d["clients_base"] for d in catalog_as_dicts())
    assert "E15" not in ids  # E15 es producto/harness, no gap de fixture extracto


def test_gaps_by_scenario_groups():
    grouped = gaps_by_scenario()
    assert "E28" in grouped
    assert grouped["E28"][0].local_generator == "blank_image_like_pdf"


def test_minimal_and_blank_pdf_generators():
    text_pdf = minimal_text_pdf(title="RC unit")
    blank = blank_image_like_pdf()
    assert text_pdf[:4] == b"%PDF"
    assert blank[:4] == b"%PDF"
    assert len(text_pdf) > len(blank)


def test_notify_allowlist_blocks_hbi_domain():
    assert "herramientas.jsakedev@gmail.com" in SANDBOX_NOTIFY_ALLOWLIST
    out = assert_sandbox_notify_recipients(["herramientas.jsakedev@gmail.com"])
    assert out == ["herramientas.jsakedev@gmail.com"]
    with pytest.raises(ValueError, match="blocked_hbi|not_sandbox"):
        assert_sandbox_notify_recipients([f"ops{HBI_DOMAIN_BLOCK}"])


def test_approve_credits_split_edits_two_rows():
    from openpyxl import Workbook
    import io
    from app.application.services.review_schema import (
        AplicacionPagosCols,
        REVIEW_SCHEMA_VERSION,
        ReviewSheets,
    )

    wb = Workbook()
    ws = wb.active
    ws.title = ReviewSheets.APLICACION_PAGOS
    ws.append(list(AplicacionPagosCols.HEADERS))
    base = {h: "" for h in AplicacionPagosCols.HEADERS}
    for cred, monto in (("CREDITO # 231", 10.0), ("CREDITO # 254", 5.0)):
        row = dict(base)
        row.update(
            {
                AplicacionPagosCols.ID_PAGO: "p1",
                AplicacionPagosCols.CLIENTE: "GEOEXCON",
                AplicacionPagosCols.CREDITO: cred,
                AplicacionPagosCols.MONTO_BANCO: monto,
            }
        )
        ws.append([row[h] for h in AplicacionPagosCols.HEADERS])
    meta = wb.create_sheet(ReviewSheets.META)
    meta.append(["Campo", "Valor"])
    meta.append(["ReviewSchemaVersion", REVIEW_SCHEMA_VERSION])
    buf = io.BytesIO()
    wb.save(buf)
    edited, applied = approve_credits_split(
        buf.getvalue(),
        splits=[
            {"credito_contains": "231", "tipo": "PAGO DE OBLIGACIÓN ACTUAL", "obligacion": 10.0},
            {"credito_contains": "254", "tipo": "ABONO A CAPITAL", "obligacion": 0.0, "capital": 5.0},
        ],
    )
    assert len(applied) == 2
    assert edited[:2] == b"PK"  # xlsx zip
