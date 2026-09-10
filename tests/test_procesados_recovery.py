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
    assert any("2026-07-28_abc123__" in c for c in cands)


def test_match_processed_by_pago_token():
    listed = [
        "P/ASIENTOS CONTABLES CRED 224/PROCESADOS/2025-09-15_0123b757__asiento.pdf",
        "P/ASIENTOS CONTABLES CRED 224/PROCESADOS/otro.pdf",
    ]
    hit = match_processed_asiento_path(
        listed, id_pago="0123b757", credito="224", original_name="missing.pdf"
    )
    assert hit is not None
    assert "0123b757" in hit


def test_match_processed_multi_asiento_uses_event_index_not_first_hit():
    """Regresión prod crédito 200: no devolver evento-1 para ambos paths."""
    base = "C/ASIENTOS CONTABLES CRED 200/PROCESADOS"
    pago = "c701246a-4a52-4ef5-a682-78cf9a433e96"
    listed = [
        f"{base}/asiento_2026-09-07_banco_bancolombia_credito-200_pago-{pago}_evento-1.pdf",
        f"{base}/asiento_2026-09-07_banco_bancolombia_credito-200_pago-{pago}_evento-2.pdf",
    ]
    assert (
        match_processed_asiento_path(
            listed, id_pago=pago, credito="200", original_name="200-1.pdf"
        )
        is None
    )
    hit1 = match_processed_asiento_path(
        listed,
        id_pago=pago,
        credito="200",
        original_name="200.pdf",
        event_index=1,
    )
    hit2 = match_processed_asiento_path(
        listed,
        id_pago=pago,
        credito="200",
        original_name="200-1.pdf",
        event_index=2,
    )
    assert hit1 is not None and hit1.endswith("_evento-1.pdf")
    assert hit2 is not None and hit2.endswith("_evento-2.pdf")
    assert hit1 != hit2


def test_match_processed_prefers_original_basename():
    base = "C/ASIENTOS CONTABLES CRED 200/PROCESADOS"
    listed = [
        f"{base}/200-1.pdf",
        f"{base}/2026-09-07_abc_____200-1.pdf",
    ]
    hit = match_processed_asiento_path(
        listed, id_pago="abc", credito="200", original_name="200-1.pdf", event_index=1
    )
    assert hit == f"{base}/200-1.pdf"


def test_allocate_uses_fecha_pago_original_scheme():
    from app.application.services.accounting_pdf_processed_move import (
        _allocate_destination_path,
    )

    existing: set[str] = set()
    dest = _allocate_destination_path(
        "ASIENTOS/PROCESADOS",
        payment_date_iso="2026-09-07",
        bank_code="banco_bancolombia",
        credito="200",
        id_pago="c701246a-4a52-4ef5-a682-78cf9a433e96",
        event_index=2,
        use_event_suffix=True,
        existing_destinations=existing,
        original_basename="200-1.pdf",
    )
    assert dest.endswith("/2026-09-07_c701246a__200-1.pdf")
    dest2 = _allocate_destination_path(
        "ASIENTOS/PROCESADOS",
        payment_date_iso="2026-09-07",
        bank_code="banco_bancolombia",
        credito="200",
        id_pago="c701246a-4a52-4ef5-a682-78cf9a433e96",
        event_index=2,
        use_event_suffix=True,
        existing_destinations=existing,
        original_basename="200-1.pdf",
    )
    assert dest2.endswith("/2026-09-07_c701246a__200-1_1.pdf")


def test_find_procesados_path_with_pdf_hash_matches_expected():
    import asyncio

    from app.application.services.accounting_pdf_processed_move import (
        find_procesados_path_with_pdf_hash,
    )
    from app.application.services.amortization_apply_safety import (
        compute_asiento_pdf_hash,
    )

    base = "C/ASIENTOS CONTABLES CRED 200/PROCESADOS"
    pago = "c701246a-4a52-4ef5-a682-78cf9a433e96"
    files = {
        f"{base}/2026-09-07_c701246a__200.pdf": b"PDF-A",
        f"{base}/2026-09-07_c701246a__200-1.pdf": b"PDF-B",
    }
    expected = compute_asiento_pdf_hash(b"PDF-B")

    async def download(path: str) -> bytes:
        return files[path]

    async def list_proc(_path: str) -> list[str]:
        return list(files)

    matched = asyncio.run(
        find_procesados_path_with_pdf_hash(
            download,
            asiento_path="C/ASIENTOS CONTABLES CRED 200/200-1.pdf",
            expected_hash=expected,
            id_pago=pago,
            credito="200",
            list_procesados_fn=list_proc,
        )
    )
    assert matched is not None and matched.endswith("__200-1.pdf")


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
