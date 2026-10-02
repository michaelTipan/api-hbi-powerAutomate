"""El job de consolidación expone si el manifest quedó completo (reconsolidar desde amortización parcial)."""
from __future__ import annotations

from app.application.services.merge_queue_service import _result_to_dict
from app.application.ui.job_read import JobReadResult
from app.application.ui.job_view import build_ui_job_view
from app.application.use_cases.merge_composite_validado_pdfs import (
    MergeCompositeValidadoPdfsResult,
)


def _job_view(manifest_status: str, eligible: bool):
    result = MergeCompositeValidadoPdfsResult(
        report_date_iso="2026-10-01",
        historico_excel_path="h.xlsx",
        estado_linea_contains="",
        email_pdf_used="e.pdf",
        merge_control_status="AMORTIZACION_PARCIAL",
        process_control_estado="AMORTIZACION_PARCIAL",
        force_rebuild_used=True,
        manifest_status=manifest_status,
        eligible_for_dry_run=eligible,
    )
    payload = {
        "job_id": "job-r",
        "type": "merge_composite_validado_pdfs",
        "status": "completed",
        "result": _result_to_dict(result),
    }
    return build_ui_job_view("job-r", JobReadResult("job-r", payload, "job_manager"), "sandbox")


def test_reconsolidar_completo_expone_manifest_complete():
    view = _job_view("COMPLETE", True)
    assert view.result_summary is not None
    assert view.result_summary["manifest_status"] == "COMPLETE"
    assert view.result_summary["process_control_estado"] == "AMORTIZACION_PARCIAL"


def test_reconsolidar_con_pendientes_expone_manifest_partial():
    view = _job_view("PARTIAL", False)
    assert view.result_summary is not None
    assert view.result_summary["manifest_status"] == "PARTIAL"
