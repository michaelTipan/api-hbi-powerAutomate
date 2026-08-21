"""Recuperación de asientos en PROCESADOS y gate ABONO."""

from __future__ import annotations

import asyncio

from app.application.services.abono_apply_gate import evaluate_abono_apply_block
from app.application.services.accounting_pdf_processed_move import (
    candidate_processed_asiento_paths,
    match_processed_asiento_path,
    restore_processed_asientos_for_credit,
)


def test_candidate_processed_paths_include_original_basename():
    src = (
        "CLIENTES/X/ASIENTOS CONTABLES CRED 224/"
        "Asiento 28-JUL-2026 PAGO CUOTA.pdf"
    )
    cands = candidate_processed_asiento_paths(
        src,
        payment_date_iso="2026-07-28",
        bank_code="banco_bogota",
        credito="224",
        id_pago="abc123",
        event_index=1,
    )
    assert any(c.endswith("Asiento 28-JUL-2026 PAGO CUOTA.pdf") for c in cands)
    assert any("asiento_2026-07-28_banco_bogota_credito-224_pago-abc123" in c for c in cands)


def test_match_processed_by_pago_token():
    listed = [
        "P/ASIENTOS CONTABLES CRED 224/PROCESADOS/asiento_2025-09-15_banco_bogota_credito-224_pago-0123b757.pdf",
        "P/ASIENTOS CONTABLES CRED 224/PROCESADOS/otro.pdf",
    ]
    hit = match_processed_asiento_path(
        listed, id_pago="0123b757", credito="224", original_name="missing.pdf"
    )
    assert hit is not None
    assert "pago-0123b757" in hit


def test_abono_gate_ignores_can_apply_false_when_groups_ready():
    """can_apply=False por errores PAGO no debe bloquear como si fuera ABONO."""
    dry = {
        "can_apply": False,
        "abono_groups_total": 1,
        "requires_business_rule": False,
        "abono_group_results": [
            {
                "id_pago": "p1",
                "creditos_seleccionados": ["92"],
                "group_ready_for_apply": True,
                "reconciliation_status": "PASSED",
                "schedule_resolution_status": "NOT_REQUIRED",
                "blocking_errors": [],
            }
        ],
    }
    assert evaluate_abono_apply_block(dry) is None


class _RestoreGraph:
    def __init__(self, *, parent_pdfs: list[str], processed_pdfs: list[str]) -> None:
        self.parent_pdfs = parent_pdfs
        self.processed_pdfs = processed_pdfs
        self.patched: list[tuple[str, dict]] = []

    async def get(self, endpoint: str) -> dict:
        if endpoint.endswith("/children"):
            if "/PROCESADOS" in endpoint or ":/PROCESADOS:" in endpoint:
                names = self.processed_pdfs
            else:
                names = self.parent_pdfs
            return {"value": [{"name": n, "file": {}} for n in names]}
        return {}

    async def patch_json(self, endpoint: str, body: dict) -> dict:
        self.patched.append((endpoint, body))
        return {}


def test_restore_skips_when_asientos_already_has_credit_pdf() -> None:
    parent = "CLIENTES/X/ASIENTOS CONTABLES CRED 53"
    graph = _RestoreGraph(
        parent_pdfs=["Asiento ERP CRED 53.pdf"],
        processed_pdfs=["asiento_2026-08-01_banco_bogota_credito-53_pago-abc.pdf"],
    )
    recs = asyncio.run(
        restore_processed_asientos_for_credit(
            graph, "s1", "d1", asientos_dir=parent, credit="53"
        )
    )
    assert recs and recs[0].status == "skipped"
    assert recs[0].reason == "asientos_already_has_credit_pdf"
    assert graph.patched == []


def test_restore_moves_from_procesados_when_asientos_empty() -> None:
    parent = "CLIENTES/X/ASIENTOS CONTABLES CRED 53"
    processed_name = "asiento_2026-08-01_banco_bogota_credito-53_pago-abc.pdf"
    graph = _RestoreGraph(parent_pdfs=[], processed_pdfs=[processed_name])
    recs = asyncio.run(
        restore_processed_asientos_for_credit(
            graph, "s1", "d1", asientos_dir=parent, credit="53"
        )
    )
    assert len(recs) == 1
    assert recs[0].status == "moved"
    assert recs[0].reason == "restored_from_PROCESADOS"
    assert len(graph.patched) == 1
    assert graph.patched[0][1]["name"] == processed_name
