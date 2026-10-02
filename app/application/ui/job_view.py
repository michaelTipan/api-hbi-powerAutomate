"""Construcción de UiJobView para GET /jobs y embebido en detalle de proceso."""
from __future__ import annotations

from typing import Any

from app.application.job_status_enrichment import enrich_job_for_http_response
from app.application.ui.job_read import JobReadResult
from app.application.ui.last_attempt import build_operational_issues_from_finalize_job
from app.application.ui.schemas import UiJobView


def build_ui_job_view(
    job_id: str,
    found: JobReadResult,
    environment: str,
) -> UiJobView:
    payload = enrich_job_for_http_response(found.payload)
    result = payload.get("result")
    result_summary: dict[str, Any] | None = None
    if isinstance(result, dict):
        result_summary = {
            k: result.get(k)
            for k in (
                "process_key",
                "bank_code",
                "already_generated",
                "already_finalized",
                "already_merged",
                "already_applied",
                "already_notified",
                "merge_control_error_code",
                "merge_control_warning",
                "merge_control_status",
                "historical_file_path",
                "historical_file_url",
                "secretary_file_path",
                "secretary_file_url",
                "validation_file_path",
                "validation_file_url",
                "email_pdf_path",
                "email_pdf_url",
                "email_pdf_links",
                "merge_pdf_links",
                "user_message",
                "next_action",
                "error_code",
                "status",
                "file_action",
                "outcome",
                "can_apply",
                "operational_issues",
                "process_control_estado",
                "force_rebuild_used",
                "manifest_status",
                "outputs_count",
                "tables_uploaded_count",
                "tables_updated_links",
                "had_amortization_writes",
                "partial_only_exclusions",
            )
            if k in result
        }
        if result.get("merge_control_error_code") == "already_notified":
            result_summary["already_notified"] = True
        summary = result.get("summary")
        if isinstance(summary, dict) and "errores" in summary:
            try:
                errores_n = int(summary.get("errores"))
            except (TypeError, ValueError):
                errores_n = None
            if errores_n is not None and errores_n >= 0:
                result_summary["errores"] = errores_n
    err = payload.get("error")
    safe_error: dict[str, Any] | None = None
    if isinstance(err, dict):
        safe_error = {
            k: err.get(k)
            for k in (
                "type",
                "message",
                "error_code",
                "user_message",
                "next_action",
                "severity",
                "review_folder_web_url",
            )
            if k in err
        }
        job_type = str(payload.get("type") or "").lower()
        job_status = str(payload.get("status") or "").lower()
        if (
            safe_error is not None
            and job_type == "finalize"
            and job_status == "failed"
            and "issues" not in safe_error
        ):
            try:
                op_issues = build_operational_issues_from_finalize_job(found)
            except Exception:  # noqa: BLE001
                op_issues = []
            if op_issues:
                # Incluir title/category/stage/technical_reference: la SPA reutiliza
                # sanitizeOperationalIssue (default «Problema de amortización» si falta title).
                safe_error["issues"] = [
                    {
                        "issue_id": issue.issue_id,
                        "stage": issue.stage,
                        "category": issue.category,
                        "severity": issue.severity,
                        "recoverable": issue.recoverable,
                        "title": issue.title,
                        "user_message": issue.user_message,
                        "next_action": issue.next_action,
                        "technical_reference": issue.technical_reference,
                        "location": (
                            {
                                "file_name": issue.location.file_name,
                                "sheet": issue.location.sheet,
                                "row": issue.location.row,
                                "column": issue.location.column,
                                "credit": issue.location.credit,
                                "payment_id": issue.location.payment_id,
                                "client_name": issue.location.client_name,
                            }
                            if issue.location
                            else None
                        ),
                        "value_found": issue.value_found,
                        "expected_values": list(issue.expected_values or []),
                        "retry": (
                            {
                                "allowed": issue.retry.allowed,
                                "action": issue.retry.action,
                                "label": issue.retry.label,
                            }
                            if issue.retry
                            else None
                        ),
                    }
                    for issue in op_issues
                ]
    return UiJobView(
        job_id=job_id,
        type=str(payload.get("type") or "") or None,
        status=str(payload.get("status") or "unknown"),
        store=found.store,
        process_key=(
            str((result or {}).get("process_key") or payload.get("process_key") or "")
            or None
            if isinstance(result, dict) or payload.get("process_key")
            else None
        ),
        bank_code=(
            str((result or {}).get("bank_code") or payload.get("bank_code") or "") or None
            if isinstance(result, dict) or payload.get("bank_code")
            else None
        ),
        environment=environment,
        created_at=str(payload.get("created_at") or payload.get("queued_at") or "") or None,
        started_at=str(payload.get("started_at") or "") or None,
        finished_at=str(payload.get("finished_at") or "") or None,
        result_summary=result_summary,
        error=safe_error,
        user_message=str(payload.get("user_message") or "") or None,
        next_action=str(payload.get("next_action") or "") or None,
        severity=str(payload.get("severity") or "") or None,
        progress=payload.get("progress")
        if isinstance(payload.get("progress"), dict)
        else None,
        raw_available=True,
    )
