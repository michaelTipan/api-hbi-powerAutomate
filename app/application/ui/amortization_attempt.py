"""Persistencia y proyección de ``last_amortization_attempt`` en Control Excel."""
from __future__ import annotations

import json
import logging
from typing import Any, Literal

from app.application.services.colombia_time import now_colombia_iso
from app.application.ui.amortization_operational_issues import (
    attach_operational_issues_to_amortization_result,
    build_operational_issues_from_amortization_result,
)
from app.application.ui.schemas import UiLastAmortizationAttempt, UiOperationalIssue
from app.application.use_cases.payment_validation_process_control import (
    update_process_control_row2,
)
from app.domain.ports.graph import GraphApiPort

logger = logging.getLogger(__name__)

CONTROL_COLUMN = "LastAmortizationAttemptJson"

FAILURE_OUTCOMES = frozenset({"requires_correction", "failed", "partial"})
SUCCESS_OUTCOMES = frozenset({"applied", "already_applied"})

AmortAttemptOutcome = Literal[
    "requires_correction", "failed", "partial", "applied", "already_applied"
]


def _collect_affected_payment_ids(
    result: dict[str, Any],
    issues: list[dict[str, Any]],
) -> list[str]:
    ids: list[str] = []
    seen: set[str] = set()
    for raw in issues:
        if not isinstance(raw, dict):
            continue
        loc = raw.get("location")
        pid = ""
        if isinstance(loc, dict):
            pid = str(loc.get("payment_id") or "").strip()
        if pid and pid not in seen:
            seen.add(pid)
            ids.append(pid)
    for item in result.get("items") or []:
        if not isinstance(item, dict):
            continue
        pid = str(item.get("id_pago") or "").strip()
        if not pid or pid in seen:
            continue
        status = str(item.get("application_status") or "").strip().upper()
        if item.get("error_code") or status in {"ERROR", "REVISION_MANUAL"}:
            seen.add(pid)
            ids.append(pid)
    return ids


def build_last_amortization_attempt_snapshot(
    result: dict[str, Any],
    *,
    attempt_id: str,
    outcome: str | None = None,
) -> UiLastAmortizationAttempt | None:
    """Construye snapshot persistible; None en éxito limpio o sin issues."""
    oc = str(outcome or result.get("outcome") or "").strip().lower()
    if oc in SUCCESS_OUTCOMES:
        return None
    if not oc:
        if result.get("can_apply") is False:
            oc = "requires_correction"
        elif str(result.get("status") or "").strip().lower() == "partial":
            oc = "partial"
        elif str(result.get("status") or "").strip().lower() == "failed":
            oc = "failed"
        else:
            return None
    if oc not in FAILURE_OUTCOMES:
        return None

    enriched = attach_operational_issues_to_amortization_result(dict(result))
    issues_raw = enriched.get("operational_issues")
    if not isinstance(issues_raw, list):
        issues_raw = build_operational_issues_from_amortization_result(enriched)
    issues_dicts = [i for i in issues_raw if isinstance(i, dict)]
    if not issues_dicts:
        return None

    issues = [UiOperationalIssue.model_validate(i) for i in issues_dicts]
    return UiLastAmortizationAttempt(
        attempt_id=attempt_id,
        outcome=oc,  # type: ignore[arg-type]
        created_at=now_colombia_iso(),
        operational_issues=issues,
        affected_payment_ids=_collect_affected_payment_ids(enriched, issues_dicts),
        user_message=str(enriched.get("user_message") or "").strip() or None,
        next_action=str(enriched.get("next_action") or "").strip() or None,
    )


def parse_last_amortization_attempt_json(
    raw: str | None,
) -> UiLastAmortizationAttempt | None:
    text = str(raw or "").strip()
    if not text:
        return None
    try:
        data = json.loads(text)
        if not isinstance(data, dict):
            return None
        return UiLastAmortizationAttempt.model_validate(data)
    except Exception:
        logger.warning("LastAmortizationAttemptJson inválido en Control")
        return None


async def persist_last_amortization_attempt(
    graph: GraphApiPort,
    *,
    site_id: str,
    drive_id: str,
    bank_code: str,
    attempt: UiLastAmortizationAttempt | None,
) -> None:
    """Escribe o limpia el snapshot JSON en Control (fila 2)."""
    bank = str(bank_code or "").strip()
    if not bank or not site_id or not drive_id:
        return
    value = attempt.model_dump_json() if attempt is not None else ""
    try:
        await update_process_control_row2(
            graph,
            site_id,
            drive_id,
            bank_code=bank,
            updates={
                CONTROL_COLUMN: value,
                "LastUpdatedAtProceso": now_colombia_iso(),
            },
        )
    except Exception as exc:
        logger.warning("No se pudo persistir last_amortization_attempt: %s", exc)


__all__ = [
    "CONTROL_COLUMN",
    "FAILURE_OUTCOMES",
    "SUCCESS_OUTCOMES",
    "build_last_amortization_attempt_snapshot",
    "parse_last_amortization_attempt_json",
    "persist_last_amortization_attempt",
]
