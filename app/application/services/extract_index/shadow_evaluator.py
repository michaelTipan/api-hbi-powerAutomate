"""
Orquestador shadow desacoplado de Generate.

Nunca modifica el snapshot V2 oficial ni propaga excepciones del índice.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import date
from typing import Any

from app.application.config.extract_index_settings import (
    ExtractIndexMode,
    ExtractIndexSettings,
)
from app.application.services.extract_index.index_select_adapter import (
    IndexSelectAdapter,
    IndexSelectRequest,
)
from app.application.services.extract_index.shadow_models import (
    DivergenceType,
    OfficialV2Snapshot,
    ShadowComparisonRecord,
    ShadowEvaluationResult,
    ShadowOutcomeKind,
    ShadowSkipReason,
)
from app.application.services.extract_index.shadow_sampling import (
    ShadowSampleContext,
    is_credit_in_shadow_sample,
)
from app.domain.exceptions import (
    ExtractIndexDuplicateDocKeyError,
    ExtractIndexError,
    ExtractIndexSchemaError,
)
from app.domain.models.extract_index import ExtractIndexEnvironment

logger = logging.getLogger(__name__)


@dataclass
class ShadowJobBudget:
    """Presupuesto de créditos shadow por job (mutable, local al job)."""

    evaluated: int = 0
    skipped: int = 0
    divergences: int = 0
    errors_isolated: int = 0


def compare_v2_vs_index(
    *,
    credit_key: str,
    v2: OfficialV2Snapshot,
    index_item_id: str | None,
    index_fecha: date | None,
    index_source: str | None,
    index_reason: str | None,
    index_error: str | None,
    elapsed_ms: float,
    outcome: ShadowOutcomeKind,
) -> ShadowComparisonRecord:
    div = DivergenceType.NONE
    if index_error and not v2.error_code:
        div = DivergenceType.ERROR_VS_SUCCESS
    elif v2.error_code and not index_error:
        div = DivergenceType.ERROR_VS_SUCCESS
    else:
        id_diff = (v2.item_id or "") != (index_item_id or "")
        fecha_diff = v2.fecha_limite != index_fecha
        if id_diff and fecha_diff:
            div = DivergenceType.BOTH
        elif id_diff:
            div = DivergenceType.ITEM_ID
        elif fecha_diff:
            div = DivergenceType.FECHA_LIMITE
        elif (v2.source_location or "") != (index_source or "") and v2.item_id and index_item_id:
            div = DivergenceType.SOURCE_LOCATION

    final_outcome = outcome
    if div != DivergenceType.NONE and outcome == ShadowOutcomeKind.INDEX_SELECTED:
        final_outcome = ShadowOutcomeKind.INDEX_DIVERGENCE

    return ShadowComparisonRecord(
        credit_key=credit_key,
        item_id_v2=v2.item_id,
        item_id_index=index_item_id,
        fecha_limite_v2=v2.fecha_limite,
        fecha_limite_index=index_fecha,
        source_location_v2=v2.source_location,
        source_location_index=index_source,
        selection_reason_v2=v2.selection_reason,
        selection_reason_index=index_reason,
        divergence_type=div,
        elapsed_ms_index=elapsed_ms,
        index_error=index_error,
        outcome=final_outcome,
    )


class ShadowIndexEvaluator:
    """
    Evalúa el índice en paralelo lógico al V2 oficial.

    Contrato:
    - nunca modifica candidato/bytes/fecha/error V2;
    - convierte cualquier fallo del índice en ShadowEvaluationResult;
    - timeout propio vía asyncio.wait_for.
    """

    def __init__(
        self,
        *,
        settings: ExtractIndexSettings,
        adapter: IndexSelectAdapter,
        budget: ShadowJobBudget | None = None,
    ) -> None:
        self._settings = settings
        self._adapter = adapter
        self._budget = budget or ShadowJobBudget()

    @property
    def budget(self) -> ShadowJobBudget:
        return self._budget

    def _gate_skip(
        self,
        *,
        bank_code: str,
        process_date: date,
        credit_key: str,
        index_available: bool,
    ) -> ShadowEvaluationResult | None:
        if self._settings.mode != ExtractIndexMode.SHADOW:
            return ShadowEvaluationResult(
                outcome=ShadowOutcomeKind.SKIPPED,
                skip_reason=ShadowSkipReason.MODE_OFF,
            )

        banks = self._settings.shadow_allowed_banks
        if banks and bank_code.strip().lower() not in banks:
            self._budget.skipped += 1
            return ShadowEvaluationResult(
                outcome=ShadowOutcomeKind.SKIPPED,
                skip_reason=ShadowSkipReason.BANK_NOT_ALLOWED,
            )

        dates = self._settings.shadow_allowed_dates
        if dates and process_date.isoformat() not in dates:
            self._budget.skipped += 1
            return ShadowEvaluationResult(
                outcome=ShadowOutcomeKind.SKIPPED,
                skip_reason=ShadowSkipReason.DATE_NOT_ALLOWED,
            )

        if self._settings.shadow_max_credits is not None:
            if self._budget.evaluated >= self._settings.shadow_max_credits:
                self._budget.skipped += 1
                return ShadowEvaluationResult(
                    outcome=ShadowOutcomeKind.SKIPPED,
                    skip_reason=ShadowSkipReason.MAX_CREDITS_REACHED,
                )

        ctx = ShadowSampleContext(
            environment=self._settings.environment.value,
            bank_code=bank_code,
            process_date=process_date,
            credit_key=credit_key,
        )
        if not is_credit_in_shadow_sample(
            ctx, sample_pct=self._settings.shadow_sample_pct
        ):
            self._budget.skipped += 1
            return ShadowEvaluationResult(
                outcome=ShadowOutcomeKind.SKIPPED,
                skip_reason=ShadowSkipReason.CREDIT_OUT_OF_SAMPLE,
            )

        if not index_available:
            self._budget.skipped += 1
            return ShadowEvaluationResult(
                outcome=ShadowOutcomeKind.SKIPPED,
                skip_reason=ShadowSkipReason.INDEX_UNAVAILABLE,
            )
        return None

    async def evaluate(
        self,
        *,
        official_v2: OfficialV2Snapshot,
        request: IndexSelectRequest,
        bank_code: str,
        process_date: date,
        index_available: bool = True,
    ) -> ShadowEvaluationResult:
        """
        Ejecuta shadow. ``official_v2`` es solo lectura; no se muta.
        """
        # Copia defensiva de campos escalares (el caller no debe depender de mutación)
        v2 = OfficialV2Snapshot(
            credit_key=official_v2.credit_key,
            item_id=official_v2.item_id,
            fecha_limite=official_v2.fecha_limite,
            source_location=official_v2.source_location,
            selection_reason=official_v2.selection_reason,
            error_code=official_v2.error_code,
            relative_path=official_v2.relative_path,
        )

        skipped = self._gate_skip(
            bank_code=bank_code,
            process_date=process_date,
            credit_key=v2.credit_key,
            index_available=index_available,
        )
        if skipped is not None:
            return skipped

        self._budget.evaluated += 1
        timeout = self._settings.shadow_timeout_seconds

        try:
            result = await asyncio.wait_for(
                self._adapter.select(request),
                timeout=timeout,
            )
        except asyncio.TimeoutError:
            self._budget.errors_isolated += 1
            comparison = compare_v2_vs_index(
                credit_key=v2.credit_key,
                v2=v2,
                index_item_id=None,
                index_fecha=None,
                index_source=None,
                index_reason=None,
                index_error="index_timeout",
                elapsed_ms=timeout * 1000.0,
                outcome=ShadowOutcomeKind.INDEX_TIMEOUT,
            )
            return ShadowEvaluationResult(
                outcome=ShadowOutcomeKind.INDEX_TIMEOUT,
                comparison=comparison,
                isolated_error_type="TimeoutError",
                isolated_error_message=f"shadow timeout after {timeout}s",
                metrics={"elapsed_ms_index": timeout * 1000.0},
            )
        except (
            ExtractIndexSchemaError,
            ExtractIndexDuplicateDocKeyError,
            ExtractIndexError,
        ) as exc:
            return self._isolate_error(v2, exc, outcome=ShadowOutcomeKind.INDEX_UNAVAILABLE)
        except Exception as exc:  # noqa: BLE001 — aislamiento deliberado del shadow
            return self._isolate_error(v2, exc, outcome=ShadowOutcomeKind.INDEX_ERROR)

        snap = result.snapshot
        metrics = {
            "elapsed_ms_index": result.metrics.elapsed_ms,
            "pdf_downloads": result.metrics.pdf_downloads,
            "index_hits": result.metrics.index_hits,
            "fallback_required": result.metrics.fallback_required,
        }

        if snap.error_code == "index_empty":
            outcome = ShadowOutcomeKind.INDEX_UNAVAILABLE
        elif snap.error_code in ("index_insufficient", "index_drive_mismatch", "index_environment_mismatch"):
            outcome = ShadowOutcomeKind.INDEX_INSUFFICIENT
        elif snap.error_code == "index_parse_error":
            outcome = ShadowOutcomeKind.INDEX_PARSE_ERROR
        elif snap.fallback_required and snap.error_code:
            outcome = ShadowOutcomeKind.FALLBACK_REQUIRED
        elif snap.item_id:
            outcome = ShadowOutcomeKind.INDEX_SELECTED
        else:
            outcome = ShadowOutcomeKind.FALLBACK_REQUIRED

        comparison = compare_v2_vs_index(
            credit_key=v2.credit_key,
            v2=v2,
            index_item_id=snap.item_id,
            index_fecha=snap.fecha_limite,
            index_source=snap.source_location,
            index_reason=snap.selection_reason,
            index_error=snap.error_code,
            elapsed_ms=result.metrics.elapsed_ms,
            outcome=outcome,
        )
        if comparison.outcome == ShadowOutcomeKind.INDEX_DIVERGENCE:
            self._budget.divergences += 1
            outcome = ShadowOutcomeKind.INDEX_DIVERGENCE

        return ShadowEvaluationResult(
            outcome=outcome,
            comparison=comparison,
            metrics=metrics,
        )

    def _isolate_error(
        self,
        v2: OfficialV2Snapshot,
        exc: BaseException,
        *,
        outcome: ShadowOutcomeKind,
    ) -> ShadowEvaluationResult:
        self._budget.errors_isolated += 1
        logger.info(
            "shadow_index_isolated_error type=%s msg=%s credit=%s",
            type(exc).__name__,
            str(exc)[:300],
            v2.credit_key,
        )
        comparison = compare_v2_vs_index(
            credit_key=v2.credit_key,
            v2=v2,
            index_item_id=None,
            index_fecha=None,
            index_source=None,
            index_reason=None,
            index_error=f"{type(exc).__name__}:{exc}",
            elapsed_ms=0.0,
            outcome=outcome,
        )
        return ShadowEvaluationResult(
            outcome=outcome,
            comparison=comparison,
            isolated_error_type=type(exc).__name__,
            isolated_error_message=str(exc)[:500],
        )
