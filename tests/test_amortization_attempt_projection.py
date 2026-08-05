"""Proyección de last_amortization_attempt desde Control Excel."""
from __future__ import annotations

import json

from app.application.ui.amortization_attempt import (
    build_last_amortization_attempt_snapshot,
    parse_last_amortization_attempt_json,
)
from app.application.ui.process_projection import (
    PaymentProcessProjectionService,
    ProjectionSources,
)
from tests.ui_fixtures import make_snap


def test_build_attempt_snapshot_requires_correction():
    result = {
        "outcome": "requires_correction",
        "can_apply": False,
        "items": [
            {
                "id_pago": "P-42",
                "credito": "264",
                "cliente": "Cliente Demo",
                "error_code": "ACCOUNTING_PARSE_FAILED",
                "asiento_pdf_path": "clientes/X/ASIENTOS/asiento.pdf",
            }
        ],
    }
    attempt = build_last_amortization_attempt_snapshot(
        result, attempt_id="job-abc", outcome="requires_correction"
    )
    assert attempt is not None
    assert attempt.attempt_id == "job-abc"
    assert attempt.outcome == "requires_correction"
    assert len(attempt.operational_issues) >= 1
    assert "P-42" in attempt.affected_payment_ids
    issue = attempt.operational_issues[0]
    assert issue.location is not None
    assert issue.location.credit == "264"
    assert issue.location.payment_id == "P-42"
    assert issue.location.client_name == "Cliente Demo"


def test_build_attempt_snapshot_clears_on_applied():
    attempt = build_last_amortization_attempt_snapshot(
        {"outcome": "applied", "status": "ok"},
        attempt_id="job-ok",
        outcome="applied",
    )
    assert attempt is None


def test_parse_last_amortization_attempt_json_roundtrip():
    raw = {
        "attempt_id": "job-x",
        "outcome": "requires_correction",
        "created_at": "2026-08-01T10:00:00-05:00",
        "operational_issues": [
            {
                "issue_id": "amort-test-1",
                "stage": "amortization",
                "category": "correction_required",
                "severity": "business",
                "recoverable": True,
                "title": "Documento contable",
                "user_message": "Corrija el PDF.",
                "location": {
                    "credit": "264",
                    "payment_id": "P1",
                    "client_name": "ACME",
                },
                "expected_values": [],
                "links": [],
            }
        ],
        "affected_payment_ids": ["P1"],
        "user_message": "La amortización encontró 1 problema(s).",
        "next_action": "Revise cada punto.",
    }
    text = json.dumps(raw, ensure_ascii=False)
    parsed = parse_last_amortization_attempt_json(text)
    assert parsed is not None
    assert parsed.attempt_id == "job-x"
    assert len(parsed.operational_issues) == 1
    assert parsed.operational_issues[0].location is not None
    assert parsed.operational_issues[0].location.client_name == "ACME"


def test_process_projection_exposes_last_amortization_attempt():
    attempt_json = json.dumps(
        {
            "attempt_id": "job-persisted",
            "outcome": "requires_correction",
            "created_at": "2026-08-01T10:00:00-05:00",
            "operational_issues": [
                {
                    "issue_id": "amort-persisted-1",
                    "stage": "amortization",
                    "category": "correction_required",
                    "severity": "business",
                    "recoverable": True,
                    "title": "Documento contable · Crédito 264",
                    "user_message": "El PDF no tiene el formato esperado.",
                    "location": {"credit": "264", "payment_id": "PX"},
                    "expected_values": [],
                    "links": [],
                    "technical_reference": "ACCOUNTING_PARSE_FAILED",
                }
            ],
            "affected_payment_ids": ["PX"],
            "user_message": "La amortización encontró 1 problema(s).",
            "next_action": "Corrija y reintente.",
        },
        ensure_ascii=False,
    )
    snap = make_snap(
        estado_proceso="CONSOLIDADO",
        last_amortization_attempt_json=attempt_json,
    )
    detail = PaymentProcessProjectionService().project(ProjectionSources(snapshot=snap))
    assert detail.last_amortization_attempt is not None
    assert detail.last_amortization_attempt.attempt_id == "job-persisted"
    assert len(detail.last_amortization_attempt.operational_issues) == 1
    assert (
        detail.last_amortization_attempt.operational_issues[0].location is not None
    )
    assert detail.last_amortization_attempt.operational_issues[0].location.credit == "264"


def test_process_projection_omits_attempt_when_control_empty():
    snap = make_snap(estado_proceso="CONSOLIDADO", last_amortization_attempt_json="")
    detail = PaymentProcessProjectionService().project(ProjectionSources(snapshot=snap))
    assert detail.last_amortization_attempt is None
