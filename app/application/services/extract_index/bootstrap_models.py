"""Modelos del motor bootstrap técnico (Fase 3A1; sin HTTP/Graph real)."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any

from app.domain.models.extract_index import CampaignStatus, ExtractIndexEnvironment

BOOTSTRAP_PARSER_VERSION = "v1"
BOOTSTRAP_SCHEMA_VERSION = "v1"


@dataclass(frozen=True, slots=True)
class CampaignScopeKey:
    """Clave estable de ámbito: no dos campañas activas equivalentes."""

    environment: ExtractIndexEnvironment
    drive_id: str
    root_identity: str
    parser_version: str = BOOTSTRAP_PARSER_VERSION
    schema_version: str = BOOTSTRAP_SCHEMA_VERSION

    def as_campaign_id(self) -> str:
        return "|".join(
            (
                self.environment.value,
                self.drive_id,
                self.root_identity,
                self.parser_version,
                self.schema_version,
            )
        )


@dataclass(slots=True)
class BootstrapCheckpoint:
    """Checkpoint por crédito confirmado (no solo contador)."""

    environment: ExtractIndexEnvironment
    drive_id: str
    last_confirmed_client: str = ""
    last_confirmed_credit: str = ""
    last_confirmed_credit_key: str = ""
    opaque_cursor: str = ""
    parser_version: str = BOOTSTRAP_PARSER_VERSION
    schema_version: str = BOOTSTRAP_SCHEMA_VERSION

    def to_json(self) -> str:
        payload = {
            "environment": self.environment.value,
            "drive_id": self.drive_id,
            "last_confirmed_client": self.last_confirmed_client,
            "last_confirmed_credit": self.last_confirmed_credit,
            "last_confirmed_credit_key": self.last_confirmed_credit_key,
            "opaque_cursor": self.opaque_cursor,
            "parser_version": self.parser_version,
            "schema_version": self.schema_version,
        }
        return json.dumps(payload, ensure_ascii=False, sort_keys=True)

    @classmethod
    def from_json(cls, raw: str) -> BootstrapCheckpoint | None:
        if not raw or not str(raw).strip():
            return None
        data = json.loads(raw)
        env_raw = str(data.get("environment") or "sandbox").lower()
        env = (
            ExtractIndexEnvironment.PRODUCTION
            if env_raw == "production"
            else ExtractIndexEnvironment.SANDBOX
        )
        return cls(
            environment=env,
            drive_id=str(data.get("drive_id") or ""),
            last_confirmed_client=str(data.get("last_confirmed_client") or ""),
            last_confirmed_credit=str(data.get("last_confirmed_credit") or ""),
            last_confirmed_credit_key=str(data.get("last_confirmed_credit_key") or ""),
            opaque_cursor=str(data.get("opaque_cursor") or ""),
            parser_version=str(data.get("parser_version") or BOOTSTRAP_PARSER_VERSION),
            schema_version=str(data.get("schema_version") or BOOTSTRAP_SCHEMA_VERSION),
        )


@dataclass(slots=True)
class CampaignTotals:
    """Métricas de campaña persistidas en TOTALS_JSON."""

    drive_id: str = ""
    root_identity: str = ""
    parser_version: str = BOOTSTRAP_PARSER_VERSION
    schema_version: str = BOOTSTRAP_SCHEMA_VERSION
    security_violation: bool = False
    credits_processed: int = 0
    credits_skipped_locked: int = 0
    credits_failed: int = 0
    credits_parse_error: int = 0
    upserts_ok: int = 0
    chunks_run: int = 0
    last_error: str = ""
    call_order_trace: list[str] = field(default_factory=list)

    def to_json(self) -> str:
        return json.dumps(asdict(self), ensure_ascii=False, sort_keys=True)

    @classmethod
    def from_json(cls, raw: str) -> CampaignTotals:
        if not raw or not str(raw).strip():
            return cls()
        data = json.loads(raw)
        return cls(
            drive_id=str(data.get("drive_id") or ""),
            root_identity=str(data.get("root_identity") or ""),
            parser_version=str(data.get("parser_version") or BOOTSTRAP_PARSER_VERSION),
            schema_version=str(data.get("schema_version") or BOOTSTRAP_SCHEMA_VERSION),
            security_violation=bool(data.get("security_violation")),
            credits_processed=int(data.get("credits_processed") or 0),
            credits_skipped_locked=int(data.get("credits_skipped_locked") or 0),
            credits_failed=int(data.get("credits_failed") or 0),
            credits_parse_error=int(data.get("credits_parse_error") or 0),
            upserts_ok=int(data.get("upserts_ok") or 0),
            chunks_run=int(data.get("chunks_run") or 0),
            last_error=str(data.get("last_error") or ""),
            call_order_trace=list(data.get("call_order_trace") or []),
        )


class ChunkStopReason(str, Enum):
    COMPLETED = "completed"
    MAX_CREDITS = "max_credits"
    MAX_SECONDS = "max_seconds"
    PAUSED = "paused"
    CANCELLED = "cancelled"
    SECURITY_VIOLATION = "security_violation"
    UPSERT_FAILURE = "upsert_failure"
    CHECKPOINT_FAILURE = "checkpoint_failure"
    EMPTY = "empty"
    LOCK_CONTENTION = "lock_contention"


@dataclass(slots=True)
class ChunkResult:
    campaign_id: str
    chunk_id: str
    status: CampaignStatus
    stop_reason: ChunkStopReason
    continuation_required: bool
    credits_attempted: int = 0
    credits_confirmed: int = 0
    credits_skipped_locked: int = 0
    elapsed_seconds: float = 0.0
    security_violation: bool = False
    error_summary: str = ""
    call_order: list[str] = field(default_factory=list)
    heartbeat: datetime | None = None


@dataclass(slots=True)
class LogicalPreflightResult:
    ok: bool
    issues: list[str] = field(default_factory=list)
    capabilities: dict[str, Any] = field(default_factory=dict)
