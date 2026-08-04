"""Tests del builder de operational_issues para amortización requires_correction."""

from __future__ import annotations

from app.application.job_status_enrichment import enrich_job_for_http_response
from app.application.services.abono_dry_run import ABONO_ASIENTOS_NO_CUADRAN
from app.application.ui.amortization_operational_issues import (
    attach_operational_issues_to_amortization_result,
    build_operational_issues_from_amortization_result,
)


def _completed(job_type: str, result: dict) -> dict:
    return {
        "job_id": "j-amort",
        "type": job_type,
        "status": "completed",
        "result": result,
    }


def test_abono_group_produces_one_issue_per_blocked_group() -> None:
    result = {
        "outcome": "requires_correction",
        "can_apply": False,
        "blocking_abono_groups": [
            {
                "id_pago": "AB1",
                "creditos_seleccionados": ["264"],
                "reconciliation_status": "FAILED",
                "blocking_errors": [
                    {
                        "error_code": ABONO_ASIENTOS_NO_CUADRAN,
                        "message": "La suma híbrida no cuadra con el monto bancario",
                        "credito": "264",
                        "paths": [
                            "clientes/X/CREDITO # 264/ASIENTOS CONTABLES CRED 264"
                        ],
                    }
                ],
            }
        ],
    }

    issues = build_operational_issues_from_amortization_result(result)

    assert len(issues) == 1
    issue = issues[0]
    assert issue["stage"] == "amortization"
    assert issue["category"] == "correction_required"
    assert issue["severity"] == "business"
    assert issue["recoverable"] is True
    assert issue["issue_id"].startswith("amort-")
    assert "264" in issue["title"]
    assert "cuadra" in issue["user_message"].lower()
    assert issue["technical_reference"] == ABONO_ASIENTOS_NO_CUADRAN
    assert issue["links"]
    assert issue["links"][0]["rel"] == "asientos"
    assert "ASIENTOS" in issue["links"][0]["label"]


def test_dry_run_items_with_errors_when_no_abono_block() -> None:
    result = {
        "outcome": "requires_correction",
        "can_apply": False,
        "items": [
            {
                "id_pago": "P1",
                "credito": "258",
                "cliente": "EQUINORTE",
                "application_status": "ERROR",
                "error_code": "TABLE_PATH_NOT_FOUND",
                "asiento_pdf_path": "clientes/E/asiento.pdf",
            }
        ],
    }

    issues = build_operational_issues_from_amortization_result(result)

    assert len(issues) == 1
    assert issues[0]["issue_id"].startswith("amort-TABLE_PATH_NOT_FOUND-258")
    assert "258" in issues[0]["title"]
    assert "tabla" in issues[0]["user_message"].lower() or "amortización" in issues[0][
        "user_message"
    ].lower()
    assert issues[0]["location"]["credit"] == "258"
    assert issues[0]["location"]["payment_id"] == "P1"


def test_merge_incomplete_block_expands_incomplete_groups() -> None:
    result = {
        "outcome": "requires_correction",
        "can_apply": False,
        "merge_incomplete_block": {
            "error_code": "MERGE_GROUP_PENDING_INPUTS",
            "user_message": "La unión quedó incompleta.",
            "next_action": "Revise Asientos_Pendientes.",
            "incomplete_groups": [
                {"id_pago": "G1", "missing_creditos": ["100", "200"]},
                {"id_pago": "G2", "missing_creditos": ["300"]},
            ],
        },
    }

    issues = build_operational_issues_from_amortization_result(result)

    assert len(issues) == 2
    assert all(i["category"] == "correction_required" for i in issues)
    assert "100" in issues[0]["user_message"]
    assert "300" in issues[1]["user_message"]


def test_attach_sets_summary_and_operational_issues() -> None:
    result = {
        "outcome": "requires_correction",
        "can_apply": False,
        "user_message": "Mensaje largo específico del gate.",
        "items": [
            {
                "id_pago": "P1",
                "credito": "1",
                "application_status": "ERROR",
                "error_code": "ASIENTO_PATH_MISSING",
            },
            {
                "id_pago": "P2",
                "credito": "2",
                "application_status": "ERROR",
                "error_code": "PDF_TEXT_NOT_EXTRACTABLE",
            },
        ],
    }

    enriched = attach_operational_issues_to_amortization_result(result)

    assert len(enriched["operational_issues"]) == 2
    assert enriched["user_message"] == (
        "La amortización encontró 2 problema(s). No se modificó ninguna tabla."
    )
    assert "SharePoint" in enriched["next_action"]


def test_enrichment_uses_issue_count_summary_for_amortization_process() -> None:
    raw = _completed(
        "amortization_process",
        {
            "outcome": "requires_correction",
            "can_apply": False,
            "operational_issues": [
                {
                    "issue_id": "amort-x-1-0",
                    "stage": "amortization",
                    "category": "correction_required",
                    "severity": "business",
                    "recoverable": True,
                    "title": "T",
                    "user_message": "Detalle",
                    "links": [],
                },
                {
                    "issue_id": "amort-x-2-1",
                    "stage": "amortization",
                    "category": "correction_required",
                    "severity": "business",
                    "recoverable": True,
                    "title": "T2",
                    "user_message": "Detalle 2",
                    "links": [],
                },
            ],
            "user_message": "La amortización encontró 2 problema(s). No se modificó ninguna tabla.",
        },
    )

    out = enrich_job_for_http_response(raw)

    assert out["severity"] == "warning"
    assert "2 problema" in out["user_message"].lower()
    assert "ninguna tabla" in out["user_message"].lower()


def test_fallback_issue_when_requires_correction_without_details() -> None:
    result = {
        "outcome": "requires_correction",
        "can_apply": False,
        "error_code": "preflight_errors",
    }

    issues = build_operational_issues_from_amortization_result(result)

    assert len(issues) == 1
    assert issues[0]["technical_reference"] == "preflight_errors"
    assert "validación previa" in issues[0]["user_message"].lower()
