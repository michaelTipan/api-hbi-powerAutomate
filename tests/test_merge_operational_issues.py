"""Issues operativos de Merge proyectados desde el último job."""
from __future__ import annotations

from app.application.ui.job_read import JobReadResult
from app.application.ui.merge_operational_issues import (
    build_operational_issues_from_merge_job,
)
from app.application.ui.process_projection import (
    PaymentProcessProjectionService,
    ProjectionSources,
    TechnicalJobEvidence,
)
from tests.ui_fixtures import make_snap

PROCESS_KEY = "payment-validation|banco_bancolombia|2026-08-04|abc-123"


def _merge_job_parcial() -> JobReadResult:
    job_id = "merge-parcial-1"
    return JobReadResult(
        job_id=job_id,
        store="job_manager",
        payload={
            "job_id": job_id,
            "type": "merge_composite_validado_pdfs",
            "status": "completed",
            "process_key": PROCESS_KEY,
            "finished_at": "2026-08-04T12:00:00-05:00",
            "result": {
                "outputs": [],
                "skipped": [
                    "id_pago=p1 | reason=ASIENTO_ASSIGNMENT_AMBIGUOUS | credito=- | "
                    "creditos_seleccionados=258, 99"
                ],
                "skipped_count": 1,
                "incomplete_groups_count": 1,
                "incomplete_groups": [
                    {
                        "id_pago": "p1",
                        "missing_creditos": ["258", "99"],
                        "missing_inputs": [
                            {
                                "credito": "258",
                                "document_type": "ASIENTO_CONTABLE",
                                "error_code": "ASIENTO_ASSIGNMENT_AMBIGUOUS",
                            },
                            {
                                "credito": "99",
                                "document_type": "ASIENTO_CONTABLE",
                                "error_code": "ASIENTO_ASSIGNMENT_AMBIGUOUS",
                            },
                        ],
                        "skip_lines": [
                            "id_pago=p1 | reason=ASIENTO_ASSIGNMENT_AMBIGUOUS | "
                            "creditos_seleccionados=258, 99"
                        ],
                    }
                ],
            },
        },
    )


def test_merge_job_issues_one_per_credit_with_asientos_link() -> None:
    job = _merge_job_parcial()
    issues = build_operational_issues_from_merge_job(
        job,
        folder_links=[
            {
                "credito": "258",
                "path": "clientes/258/ASIENTOS",
                "web_url": "https://sp/258",
            }
        ],
    )
    assert len(issues) == 2
    by_credit = {i.location.credit if i.location else None: i for i in issues}
    assert "258" in by_credit
    assert "99" in by_credit
    assert "cuadrar" in by_credit["258"].user_message.lower()
    assert "inconveniente técnico" not in by_credit["258"].user_message.lower()
    assert by_credit["258"].retry is None
    assert by_credit["258"].links
    assert by_credit["258"].links[0].rel == "asientos"
    assert by_credit["99"].links == []


def test_projection_exposes_merge_issues_on_merge_parcial() -> None:
    snap = make_snap(
        estado_proceso="MERGE_PARCIAL",
        process_key=PROCESS_KEY,
        historical_file_path="hist.xlsx",
        email_pdf_path="mail.pdf",
    )
    detail = PaymentProcessProjectionService().project(
        ProjectionSources(
            snapshot=snap,
            jobs=TechnicalJobEvidence(
                job_manager_by_type={"merge": _merge_job_parcial()}
            ),
        )
    )
    merge_issues = [i for i in detail.operational_issues if i.stage == "merge"]
    assert len(merge_issues) >= 2
    assert detail.errors
    assert "cuadrar" in (detail.errors[0].user_message or "").lower() or (
        "asiento" in (detail.errors[0].user_message or "").lower()
    )
    assert detail.last_attempt is not None
    assert detail.last_attempt.user_message
