"""Readiness de Amortización (solo lectura): completitud declarada del manifest.

No adquiere mutex, no escribe control, no ejecuta dry-run financiero completo
ni parsea PDFs masivamente (eso ocurre en ``prepare_amortization_application``
al confirmar la acción). Solo valida ProcessKey/IsActive/estado y el resumen
del manifest de Merge ya generado.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Any, Protocol

from app.application.job_manager import get_job_manager
from app.application.services.colombia_time import now_colombia_iso
from app.application.services.merge_group_validation import MANIFEST_STATUS_COMPLETE
from app.application.services.merge_manifest_gate import (
    assess_manifest_completeness,
    count_expected_credit_events,
)
from app.application.ui.amortization_capabilities import (
    control_indicates_already_applied,
)
from app.application.sharepoint_resolution import resolve_sharepoint_from_env
from app.application.use_cases.payment_validation_process_control import (
    ProcessControlSnapshot,
)
from app.application.use_cases.validate_payment_report import _graph_download_by_path

logger = logging.getLogger(__name__)

_MSG_ALREADY = "La amortización de este proceso ya fue aplicada anteriormente."
_MSG_INCOMPLETE = (
    "Faltan asientos contables o el manifiesto de consolidación está incompleto."
)
_MSG_UNKNOWN = (
    "No se pudo verificar si la información está lista para amortizar. "
    "Actualice e intente nuevamente."
)
_MSG_READY = "La información está disponible para iniciar la validación y aplicación."
_NEXT_LOAD = (
    "Complete la consolidación de asientos contables antes de procesar la amortización."
)
_NEXT_RETRY = "Actualice el detalle del proceso e intente nuevamente."
_NEXT_START = "Puede procesar la amortización desde la UI."
_NEXT_DONE = "Consulte las tablas de amortización actualizadas."


class GraphLike(Protocol):
    async def get(self, *a: Any, **k: Any) -> Any: ...
    async def get_bytes(self, *a: Any, **k: Any) -> Any: ...


@dataclass
class AmortizationReadiness:
    status: str  # ready|incomplete|unknown|already_applied
    can_start: bool = False
    expected_items: int = 0
    ready_items: int = 0
    missing_items: list[dict[str, Any]] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    checked_at: str = ""
    user_message: str = ""
    next_action: str = ""


def _now() -> str:
    return now_colombia_iso()


def _result(
    status: str,
    *,
    expected: int = 0,
    ready: int = 0,
    missing_items: list[dict[str, Any]] | None = None,
    warnings: list[str] | None = None,
    user_message: str,
    next_action: str,
) -> AmortizationReadiness:
    return AmortizationReadiness(
        status=status,
        can_start=status == "ready",
        expected_items=expected,
        ready_items=ready,
        missing_items=list(missing_items or []),
        warnings=list(warnings or []),
        checked_at=_now(),
        user_message=user_message,
        next_action=next_action,
    )


async def assess_amortization_readiness(
    graph: GraphLike,
    snap: ProcessControlSnapshot,
    bank_code: str,
) -> AmortizationReadiness:
    """Evalúa livianamente si hay insumos suficientes para procesar amortización."""
    pk = (snap.process_key or "").strip()
    if control_indicates_already_applied(snap) or (
        pk and get_job_manager().has_completed_amortization(pk)
    ):
        return _result(
            "already_applied",
            user_message=_MSG_ALREADY,
            next_action=_NEXT_DONE,
        )

    if not pk or not snap.is_active:
        return _result(
            "incomplete",
            user_message=_MSG_INCOMPLETE,
            next_action=_NEXT_LOAD,
        )

    manifest_rel = (snap.merge_manifest_path or "").strip().strip("/")
    historico = (snap.historical_file_path or "").strip().strip("/")
    if not manifest_rel or not historico:
        return _result(
            "incomplete",
            user_message=_MSG_INCOMPLETE,
            next_action=_NEXT_LOAD,
        )

    try:
        ctx = await resolve_sharepoint_from_env(graph)
        site_id = str(ctx["site_id"])
        drive_id = str(ctx["drive_id"])
        manifest_raw = await _graph_download_by_path(
            graph, site_id, drive_id, manifest_rel
        )
        manifest_doc = json.loads(manifest_raw.decode("utf-8"))
    except Exception:
        logger.info(
            "amortization_readiness: fallo lectura manifest bank=%s",
            bank_code,
            exc_info=True,
        )
        return _result(
            "unknown",
            user_message=_MSG_UNKNOWN,
            next_action=_NEXT_RETRY,
        )

    assessment = assess_manifest_completeness(manifest_doc)
    expected = count_expected_credit_events(manifest_doc)
    missing_items: list[dict[str, Any]] = [
        dict(g) for g in (assessment.get("incomplete_groups") or []) if isinstance(g, dict)
    ]
    missing_items.extend(
        dict(i) for i in (assessment.get("output_issues") or []) if isinstance(i, dict)
    )
    warnings: list[str] = []
    if assessment["manifest_status"] != MANIFEST_STATUS_COMPLETE:
        warnings.append(f"manifest_status={assessment['manifest_status']}")

    is_complete = (
        assessment["manifest_status"] == MANIFEST_STATUS_COMPLETE
        and bool(assessment["eligible_for_dry_run"])
        and assessment["incomplete_groups_count"] == 0
    )
    if not is_complete:
        return _result(
            "incomplete",
            expected=expected,
            ready=max(0, expected - len(missing_items)),
            missing_items=missing_items,
            warnings=warnings,
            user_message=_MSG_INCOMPLETE,
            next_action=_NEXT_LOAD,
        )

    return _result(
        "ready",
        expected=expected,
        ready=expected,
        missing_items=[],
        warnings=warnings,
        user_message=_MSG_READY,
        next_action=_NEXT_START,
    )
