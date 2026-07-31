"""Construcción segura de UiLastAttempt / attempts desde jobs persistidos."""
from __future__ import annotations

import json
from typing import Any

from app.application.ui.job_read import JobReadResult
from app.application.ui.job_stage_types import (
    STAGE_JOB_TYPES,
    classify_finalize_failure,
    job_type_matches_stage,
    stage_for_job_type,
)
from app.application.ui.schemas import (
    UiAttempt,
    UiIssueLocation,
    UiIssueRetry,
    UiLastAttempt,
    UiLink,
    UiOperationalIssue,
)

_ACTIVE = frozenset({"queued", "running"})
_TERMINAL = frozenset(
    {"completed", "failed", "cancelled", "canceled", "interrupted"}
)


def _nz(value: object) -> str | None:
    text = str(value or "").strip()
    return text or None


def _job_ts(payload: dict[str, Any]) -> str:
    return (
        _nz(payload.get("finished_at"))
        or _nz(payload.get("updated_at"))
        or _nz(payload.get("started_at"))
        or _nz(payload.get("queued_at"))
        or ""
    )


def _error_blob(payload: dict[str, Any]) -> dict[str, Any]:
    err = payload.get("error")
    if isinstance(err, dict):
        return err
    return {}


def _safe_parse_code_json(message: str) -> tuple[str | None, dict[str, Any]]:
    """Parsea ``codigo|JSON`` sin romper si el JSON está corrupto."""
    raw = (message or "").strip()
    # Quitar prefijos tipo ValueError: ...
    if ":" in raw and raw.split(":", 1)[0].endswith("Error"):
        raw = raw.split(":", 1)[1].strip()
    if "|" not in raw:
        return (raw or None), {}
    code, rest = raw.split("|", 1)
    code = code.strip() or None
    rest = rest.strip()
    if not rest:
        return code, {}
    if not (rest.startswith("{") or rest.startswith("[")):
        return code, {}
    try:
        parsed = json.loads(rest)
    except (json.JSONDecodeError, TypeError, ValueError):
        return code, {}
    if isinstance(parsed, dict):
        return code, parsed
    return code, {}


def parse_finalize_error_details(payload: dict[str, Any]) -> dict[str, Any]:
    err = _error_blob(payload)
    message = str(err.get("message") or err.get("technical_message") or "")
    code = _nz(err.get("error_code"))
    parsed_code, details = _safe_parse_code_json(message)
    if not code:
        code = parsed_code
    return {
        "error_code": code,
        "details": details,
        "user_message": _nz(err.get("user_message")),
        "next_action": _nz(err.get("next_action")),
        "severity": _nz(err.get("severity")) or "warning",
        "message": message,
    }


def build_last_attempt_from_job(
    job: JobReadResult | dict[str, Any],
    *,
    stage: str | None = None,
) -> UiLastAttempt | None:
    if isinstance(job, JobReadResult):
        payload = job.payload
        job_id = job.job_id
    else:
        payload = job
        job_id = str(payload.get("job_id") or "")
    if not job_id:
        return None
    jtype = str(payload.get("type") or "")
    resolved_stage = stage or stage_for_job_type(jtype) or "unknown"
    status = str(payload.get("status") or "").lower()
    result = payload.get("result") if isinstance(payload.get("result"), dict) else {}
    parsed = parse_finalize_error_details(payload)
    error_code = parsed["error_code"]
    outcome = _nz(result.get("outcome")) if status == "completed" else None
    recoverable = False
    if status == "failed":
        kind = classify_finalize_failure(
            error_code, severity=parsed.get("severity")
        )
        recoverable = True
        if resolved_stage == "amortization" and outcome == "requires_correction":
            recoverable = True
    elif outcome in {"requires_correction", "partial"}:
        recoverable = True

    severity = parsed.get("severity") or ("warning" if recoverable else "info")
    if status == "failed" and not recoverable:
        severity = "fatal"

    technical = None
    if error_code or job_id:
        technical = f"job:{job_id}"
        if error_code:
            technical = f"{technical}|code:{error_code}"

    return UiLastAttempt(
        stage=resolved_stage,
        job_id=job_id,
        job_type=jtype or "unknown",
        status=status or "unknown",
        outcome=outcome,
        recoverable=recoverable,
        error_code=error_code,
        severity=severity,  # type: ignore[arg-type]
        user_message=parsed.get("user_message"),
        next_action=parsed.get("next_action"),
        started_at=_nz(payload.get("started_at")),
        finished_at=_nz(payload.get("finished_at")),
        progress=payload.get("progress")
        if isinstance(payload.get("progress"), dict)
        else None,
        technical_reference=technical,
    )


def build_attempts_from_jobs(
    jobs: list[JobReadResult | dict[str, Any]],
) -> list[UiAttempt]:
    """Más reciente primero."""
    enriched: list[tuple[str, UiAttempt]] = []
    counters: dict[str, int] = {}
    # Primero orden cronológico ascendente para numerar; luego invertir.
    dated: list[tuple[str, JobReadResult | dict[str, Any]]] = []
    for job in jobs:
        payload = job.payload if isinstance(job, JobReadResult) else job
        dated.append((_job_ts(payload), job))
    dated.sort(key=lambda x: x[0])
    for _ts, job in dated:
        payload = job.payload if isinstance(job, JobReadResult) else job
        jtype = str(payload.get("type") or "")
        stage = stage_for_job_type(jtype) or jtype or "unknown"
        counters[stage] = counters.get(stage, 0) + 1
        job_id = (
            job.job_id
            if isinstance(job, JobReadResult)
            else str(payload.get("job_id") or "")
        )
        trigger = _nz(payload.get("trigger_source"))
        enriched.append(
            (
                _job_ts(payload),
                UiAttempt(
                    stage=stage,
                    attempt_number=counters[stage],
                    status=_nz(payload.get("status")),
                    at=_job_ts(payload) or None,
                    trigger_source=trigger if trigger in {"power_automate", "web_ui", "admin"} else None,  # type: ignore[arg-type]
                    requested_by=_nz(payload.get("requested_by")),
                    job_id=job_id or None,
                ),
            )
        )
    enriched.sort(key=lambda x: x[0], reverse=True)
    return [a for _, a in enriched]


def latest_attempts_by_stage(
    jobs_by_stage: dict[str, JobReadResult],
) -> dict[str, UiLastAttempt]:
    out: dict[str, UiLastAttempt] = {}
    for stage, job in jobs_by_stage.items():
        attempt = build_last_attempt_from_job(job, stage=stage)
        if attempt:
            out[stage] = attempt
    return out


def pick_last_attempt(
    by_stage: dict[str, UiLastAttempt],
) -> UiLastAttempt | None:
    if not by_stage:
        return None
    ranked = sorted(
        by_stage.values(),
        key=lambda a: (a.finished_at or a.started_at or ""),
        reverse=True,
    )
    return ranked[0]


def build_operational_issue_from_finalize_job(
    job: JobReadResult,
    *,
    review_link: UiLink | None = None,
    file_name: str | None = None,
) -> UiOperationalIssue | None:
    payload = job.payload
    if str(payload.get("status") or "").lower() != "failed":
        return None
    parsed = parse_finalize_error_details(payload)
    code = parsed["error_code"] or "finalize_failed"
    details = parsed["details"]
    kind = classify_finalize_failure(code, severity=parsed.get("severity"))
    category = (
        "temporary_failure" if kind == "failed_retryable" else "correction_required"
    )
    severity = "recoverable" if kind == "failed_retryable" else "warning"

    location = UiIssueLocation(
        file_name=file_name,
        sheet=_nz(details.get("sheet")) or "Distribucion_Pagos",
        row=_int_or_none(details.get("excel_row") or details.get("row")),
        column=_nz(details.get("field") or details.get("column")),
        credit=_nz(details.get("credito") or details.get("credit")),
        payment_id=_nz(details.get("id_pago") or details.get("payment_id")),
        client_name=_nz(details.get("cliente") or details.get("client_name")),
    )
    value_found = _nz(details.get("value_found") or details.get("value"))
    expected = details.get("expected_values")
    expected_values: list[str] = []
    if isinstance(expected, list):
        expected_values = [str(x) for x in expected if str(x).strip()]
    elif code == "invalid_estado_pago":
        expected_values = ["ADELANTADO", "ATRASADO", "NORMAL", "REVISION_MANUAL"]

    title = (
        "No pudimos completar la operación por un problema temporal."
        if category == "temporary_failure"
        else "La revisión requiere correcciones."
    )
    user_message = parsed.get("user_message") or (
        "No se pudo finalizar el archivo de revisión."
    )
    next_action = parsed.get("next_action") or (
        "Corrija el valor, guarde el archivo y vuelva a verificar."
        if category == "correction_required"
        else "Cierre el archivo y vuelva a intentarlo."
    )
    links = [review_link] if review_link else []
    return UiOperationalIssue(
        issue_id=f"HBI-FINALIZE-{code}-{job.job_id[:8]}",
        stage="finalize",
        category=category,  # type: ignore[arg-type]
        severity=severity,  # type: ignore[arg-type]
        recoverable=True,
        title=title,
        user_message=user_message,
        location=location,
        value_found=value_found,
        expected_values=expected_values,
        next_action=next_action,
        retry=UiIssueRetry(
            allowed=True,
            action="finalize",
            label="Verificar nuevamente"
            if category == "correction_required"
            else "Volver a intentar",
        ),
        links=links,
        technical_reference=f"job:{job.job_id}|code:{code}",
    )


def _int_or_none(value: object) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


def collect_jobs_for_stages(
    jobs: dict[str, JobReadResult],
) -> dict[str, JobReadResult]:
    """Normaliza claves de evidencia a etapas canónicas."""
    out: dict[str, JobReadResult] = {}
    for key, job in jobs.items():
        stage = key if key in STAGE_JOB_TYPES else stage_for_job_type(
            str(job.payload.get("type") or key)
        )
        if not stage:
            continue
        # amortization_process mapea a amortization (y apply en timeline).
        if stage == "apply" and job_type_matches_stage(
            str(job.payload.get("type") or ""), "amortization"
        ):
            stage = "amortization"
        prev = out.get(stage)
        if prev is None or _job_ts(job.payload) >= _job_ts(prev.payload):
            out[stage] = job
    return out


__all__ = [
    "build_attempts_from_jobs",
    "build_last_attempt_from_job",
    "build_operational_issue_from_finalize_job",
    "collect_jobs_for_stages",
    "latest_attempts_by_stage",
    "parse_finalize_error_details",
    "pick_last_attempt",
]
