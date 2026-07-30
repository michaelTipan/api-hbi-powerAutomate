"""
Hook de integración shadow → Generate (Fase 2B2).

No decide el resultado oficial. Solo logs/métricas internas.
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from datetime import date
from typing import Any

from app.application.config.extract_index_settings import (
    ExtractIndexMode,
    ExtractIndexSettings,
    get_extract_index_settings,
)
from app.application.services.extract_index.extract_selection_v2 import (
    EXTRACT_SOURCE_EXTRACTOS,
)
from app.application.services.extract_index.index_select_adapter import IndexSelectRequest
from app.application.services.extract_index.keys import build_credit_key
from app.application.services.extract_index.reconcile import LiveFileMetadata
from app.application.services.extract_index.shadow_evaluator import (
    ShadowIndexEvaluator,
    ShadowJobBudget,
)
from app.application.services.extract_index.shadow_models import (
    OfficialV2Snapshot,
    ShadowOutcomeKind,
    ShadowSkipReason,
)
from app.domain.models.extract_index import ExtractIndexEnvironment

logger = logging.getLogger(__name__)


@dataclass
class GenerateShadowJobContext:
    """Contexto local al job Generate (no global de proceso)."""

    settings: ExtractIndexSettings
    budget: ShadowJobBudget = field(default_factory=ShadowJobBudget)
    evaluated_credit_keys: set[str] = field(default_factory=set)
    shadow_elapsed_seconds: float = 0.0
    run_id: str = ""
    job_id: str = ""


def new_generate_shadow_job_context(
    *,
    job_id: str | None,
    run_id: str | None = None,
    settings: ExtractIndexSettings | None = None,
) -> GenerateShadowJobContext | None:
    """Crea contexto solo si mode=shadow; off → None (cero efecto)."""
    cfg = settings or get_extract_index_settings()
    if cfg.mode != ExtractIndexMode.SHADOW:
        return None
    return GenerateShadowJobContext(
        settings=cfg,
        budget=ShadowJobBudget(),
        run_id=str(run_id or job_id or ""),
        job_id=str(job_id or ""),
    )


def _live_from_pool(pool: list[dict[str, Any]]) -> list[LiveFileMetadata]:
    lives: list[LiveFileMetadata] = []
    for cand in pool:
        item = cand.get("item") if isinstance(cand.get("item"), dict) else {}
        if not isinstance(item, dict):
            continue
        iid = str(item.get("id") or "")
        if not iid:
            continue
        lives.append(
            LiveFileMetadata(
                item_id=iid,
                name=str(cand.get("name") or item.get("name") or ""),
                path=str(cand.get("relative_path") or ""),
                ctag=str(item.get("cTag") or item.get("ctag") or ""),
                etag=str(item.get("eTag") or item.get("etag") or ""),
                size=_as_int(item.get("size")),
                source_location=str(cand.get("source_location") or ""),
            )
        )
    return lives


def _as_int(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _extractos_children_from_pool(pool: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for cand in pool:
        if str(cand.get("source_location") or "") != EXTRACT_SOURCE_EXTRACTOS:
            continue
        item = cand.get("item")
        if isinstance(item, dict):
            out.append(item)
    return out


def _log_shadow_result(
    *,
    ctx: GenerateShadowJobContext,
    bank_code: str,
    process_date: date,
    credit_key: str,
    skipped_reason: str | None,
    outcome: str | None,
    comparison: Any,
    isolated_error_type: str | None,
    elapsed_ms: float,
) -> None:
    payload: dict[str, Any] = {
        "event": "extract_index_shadow",
        "run_id": ctx.run_id,
        "job_id": ctx.job_id,
        "environment": ctx.settings.environment.value,
        "bank_code": bank_code,
        "process_date": process_date.isoformat(),
        "credit_key": credit_key,
        "skipped_reason": skipped_reason,
        "outcome": outcome,
        "elapsed_ms": round(elapsed_ms, 3),
        "isolated_error_type": isolated_error_type,
    }
    if comparison is not None:
        payload.update(
            {
                "item_id_v2": comparison.item_id_v2,
                "item_id_index": comparison.item_id_index,
                "fecha_limite_v2": (
                    comparison.fecha_limite_v2.isoformat()
                    if comparison.fecha_limite_v2
                    else None
                ),
                "fecha_limite_index": (
                    comparison.fecha_limite_index.isoformat()
                    if comparison.fecha_limite_index
                    else None
                ),
                "divergence_type": comparison.divergence_type.value,
            }
        )
    logger.info("extract_index_shadow %s", payload)


async def maybe_evaluate_shadow_after_v2(
    *,
    evaluator: ShadowIndexEvaluator | None,
    job_ctx: GenerateShadowJobContext | None,
    bank_code: str,
    process_date: date,
    drive_id: str,
    credit_folder_item_id: str,
    credit_path: str,
    credit_folder_items: list[dict[str, Any]],
    pool: list[dict[str, Any]],
    statement_item: dict[str, Any] | None,
    fecha_limite_pdf: date | None,
    sel_err: str | None,
    selected: dict[str, Any] | None,
) -> None:
    """
    Único punto de cableado shadow.

    No modifica argumentos de V2. No propaga errores de índice.
    Re-lanza CancelledError / KeyboardInterrupt / SystemExit.
    """
    if job_ctx is None:
        return
    if job_ctx.settings.mode != ExtractIndexMode.SHADOW:
        return

    try:
        env = job_ctx.settings.environment
        credit_key = build_credit_key(
            environment=env,
            drive_id=drive_id,
            credit_folder_item_id=credit_folder_item_id or "unknown",
        ).as_string()
    except Exception:
        logger.info(
            "extract_index_shadow skipped_reason=credit_key_invalid job_id=%s",
            job_ctx.job_id,
        )
        return

    if credit_key in job_ctx.evaluated_credit_keys:
        _log_shadow_result(
            ctx=job_ctx,
            bank_code=bank_code,
            process_date=process_date,
            credit_key=credit_key,
            skipped_reason=ShadowSkipReason.ALREADY_EVALUATED.value,
            outcome=ShadowOutcomeKind.SKIPPED.value,
            comparison=None,
            isolated_error_type=None,
            elapsed_ms=0.0,
        )
        job_ctx.budget.skipped += 1
        return

    if job_ctx.shadow_elapsed_seconds >= job_ctx.settings.shadow_total_budget_seconds:
        _log_shadow_result(
            ctx=job_ctx,
            bank_code=bank_code,
            process_date=process_date,
            credit_key=credit_key,
            skipped_reason=ShadowSkipReason.JOB_BUDGET_EXHAUSTED.value,
            outcome=ShadowOutcomeKind.SKIPPED.value,
            comparison=None,
            isolated_error_type=None,
            elapsed_ms=0.0,
        )
        job_ctx.budget.skipped += 1
        return

    if evaluator is None:
        job_ctx.evaluated_credit_keys.add(credit_key)
        _log_shadow_result(
            ctx=job_ctx,
            bank_code=bank_code,
            process_date=process_date,
            credit_key=credit_key,
            skipped_reason=ShadowSkipReason.EVALUATOR_UNAVAILABLE.value,
            outcome=ShadowOutcomeKind.SKIPPED.value,
            comparison=None,
            isolated_error_type=None,
            elapsed_ms=0.0,
        )
        job_ctx.budget.skipped += 1
        return

    # Asegurar que el evaluador comparta el mismo budget del job
    evaluator._budget = job_ctx.budget  # noqa: SLF001 — inyección de presupuesto del job
    evaluator._settings = job_ctx.settings  # noqa: SLF001

    item_id = None
    if isinstance(statement_item, dict):
        item_id = str(statement_item.get("id") or "") or None
    source = None
    rel = None
    reason = None
    if isinstance(selected, dict):
        source = str(selected.get("source_location") or "") or None
        rel = str(selected.get("relative_path") or "") or None
        reason = "max_fecha_limite" if not sel_err else None

    official = OfficialV2Snapshot(
        credit_key=credit_key,
        item_id=item_id,
        fecha_limite=fecha_limite_pdf,
        source_location=source,
        selection_reason=reason,
        error_code=sel_err,
        relative_path=rel,
    )

    request = IndexSelectRequest(
        environment=env if isinstance(env, ExtractIndexEnvironment) else ExtractIndexEnvironment.SANDBOX,
        drive_id=drive_id,
        credit_key=credit_key,
        credit_path=credit_path,
        credit_folder_items=credit_folder_items,
        extractos_children=_extractos_children_from_pool(pool) or None,
        live_files=_live_from_pool(pool),
        content_endpoint_builder=lambda path: path,
        parser_version="v1",
    )

    job_ctx.evaluated_credit_keys.add(credit_key)
    started = time.perf_counter()
    try:
        result = await evaluator.evaluate(
            official_v2=official,
            request=request,
            bank_code=bank_code,
            process_date=process_date,
            index_available=True,
        )
    except asyncio.CancelledError:
        raise
    except (KeyboardInterrupt, SystemExit):
        raise
    except Exception as exc:  # aislamiento de último recurso del hook
        elapsed = (time.perf_counter() - started) * 1000.0
        job_ctx.shadow_elapsed_seconds += elapsed / 1000.0
        _log_shadow_result(
            ctx=job_ctx,
            bank_code=bank_code,
            process_date=process_date,
            credit_key=credit_key,
            skipped_reason=None,
            outcome=ShadowOutcomeKind.INDEX_ERROR.value,
            comparison=None,
            isolated_error_type=type(exc).__name__,
            elapsed_ms=elapsed,
        )
        return

    elapsed = (time.perf_counter() - started) * 1000.0
    job_ctx.shadow_elapsed_seconds += elapsed / 1000.0
    skip = result.skip_reason.value if result.skip_reason else None
    _log_shadow_result(
        ctx=job_ctx,
        bank_code=bank_code,
        process_date=process_date,
        credit_key=credit_key,
        skipped_reason=skip,
        outcome=result.outcome.value,
        comparison=result.comparison,
        isolated_error_type=result.isolated_error_type,
        elapsed_ms=elapsed,
    )
