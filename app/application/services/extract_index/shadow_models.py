"""DTOs del camino shadow del índice (nunca mutan el resultado V2 oficial)."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from enum import Enum
from typing import Any


class ShadowOutcomeKind(str, Enum):
    """Resultados explícitos de la evaluación shadow."""

    SKIPPED = "skipped"
    INDEX_SELECTED = "index_selected"
    INDEX_UNAVAILABLE = "index_unavailable"
    INDEX_INSUFFICIENT = "index_insufficient"
    INDEX_PARSE_ERROR = "index_parse_error"
    INDEX_DIVERGENCE = "index_divergence"
    INDEX_TIMEOUT = "index_timeout"
    FALLBACK_REQUIRED = "fallback_required"
    INDEX_ERROR = "index_error"


class ShadowSkipReason(str, Enum):
    MODE_OFF = "mode_off"
    CREDIT_OUT_OF_SAMPLE = "credit_out_of_sample"
    BANK_NOT_ALLOWED = "bank_not_allowed"
    DATE_NOT_ALLOWED = "date_not_allowed"
    MAX_CREDITS_REACHED = "max_credits_reached"
    INDEX_UNAVAILABLE = "index_unavailable"
    TIME_BUDGET_EXHAUSTED = "time_budget_exhausted"


class DivergenceType(str, Enum):
    NONE = "none"
    ITEM_ID = "item_id"
    FECHA_LIMITE = "fecha_limite"
    BOTH = "both"
    ERROR_VS_SUCCESS = "error_vs_success"
    SOURCE_LOCATION = "source_location"


@dataclass(frozen=True, slots=True)
class OfficialV2Snapshot:
    """Copia inmutable del resultado oficial V2 (entrada al shadow)."""

    credit_key: str
    item_id: str | None
    fecha_limite: date | None
    source_location: str | None
    selection_reason: str | None
    error_code: str | None
    relative_path: str | None = None


@dataclass(frozen=True, slots=True)
class IndexSelectionSnapshot:
    """Resultado del camino índice (solo observación)."""

    item_id: str | None = None
    fecha_limite: date | None = None
    source_location: str | None = None
    selection_reason: str | None = None
    error_code: str | None = None
    relative_path: str | None = None
    fallback_required: bool = False


@dataclass(frozen=True, slots=True)
class ShadowComparisonRecord:
    """Registro comparable V2 vs índice para métricas/logs."""

    credit_key: str
    item_id_v2: str | None
    item_id_index: str | None
    fecha_limite_v2: date | None
    fecha_limite_index: date | None
    source_location_v2: str | None
    source_location_index: str | None
    selection_reason_v2: str | None
    selection_reason_index: str | None
    divergence_type: DivergenceType
    elapsed_ms_index: float
    index_error: str | None = None
    outcome: ShadowOutcomeKind = ShadowOutcomeKind.INDEX_SELECTED


@dataclass(frozen=True, slots=True)
class ShadowEvaluationResult:
    """
    Resultado del orquestador shadow.

    Garantías: no modifica V2; nunca propaga excepciones del índice.
    """

    outcome: ShadowOutcomeKind
    comparison: ShadowComparisonRecord | None = None
    skip_reason: ShadowSkipReason | None = None
    isolated_error_type: str | None = None
    isolated_error_message: str | None = None
    metrics: dict[str, Any] = field(default_factory=dict)

    @property
    def official_v2_untouched(self) -> bool:
        """Contrato explícito para tests: el shadow no es fuente oficial."""
        return True
