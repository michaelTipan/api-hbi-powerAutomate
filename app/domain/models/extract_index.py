"""Modelos del índice de extractos (caché derivada en SharePoint Lists)."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from enum import Enum
from typing import Any


class ExtractIndexEnvironment(str, Enum):
    """Ambiente lógico de filas del índice (no mezclar)."""

    SANDBOX = "sandbox"
    PRODUCTION = "production"


class ParseStatus(str, Enum):
    """Estado de parseo de un candidato PDF."""

    PENDING = "pending"
    OK = "ok"
    ERROR = "error"
    SKIPPED = "skipped"


class CampaignStatus(str, Enum):
    """Estado de una campaña de bootstrap (control)."""

    IDLE = "idle"
    RUNNING = "running"
    PAUSED = "paused"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass(frozen=True, slots=True)
class CreditKey:
    """Identidad de carpeta de crédito en el índice."""

    environment: ExtractIndexEnvironment
    drive_id: str
    credit_folder_item_id: str

    def as_string(self) -> str:
        return f"{self.environment.value}|{self.drive_id}|{self.credit_folder_item_id}"


@dataclass(frozen=True, slots=True)
class DocKey:
    """Identidad documental de un PDF candidato."""

    environment: ExtractIndexEnvironment
    drive_id: str
    item_id: str

    def as_string(self) -> str:
        return f"{self.environment.value}|{self.drive_id}|{self.item_id}"


@dataclass(slots=True)
class ExtractIndexCandidate:
    """Fila lógica de INDICE_EXTRACTOS (un PDF candidato V2)."""

    environment: ExtractIndexEnvironment
    credit_key: CreditKey
    doc_key: DocKey
    drive_id: str
    item_id: str
    credit_folder_item_id: str
    name: str = ""
    path: str = ""
    ubicacion: str = ""
    ctag: str = ""
    etag: str = ""
    size: int | None = None
    parse_status: ParseStatus = ParseStatus.PENDING
    parser_version: str = ""
    fecha_limite: date | None = None
    content_hash: str = ""
    eliminado: bool = False
    parse_error: str = ""
    ultima_revision: datetime | None = None
    list_item_id: str | None = None
    extra_fields: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class BootstrapControlRecord:
    """Fila lógica de CONTROL_INDICE_EXTRACTOS."""

    environment: ExtractIndexEnvironment
    campaign_id: str
    status: CampaignStatus = CampaignStatus.IDLE
    chunk_id: str = ""
    checkpoint: str = ""
    current_client: str = ""
    current_credit: str = ""
    heartbeat: datetime | None = None
    continuation_required: bool = False
    paused: bool = False
    cancellation_requested: bool = False
    completed: bool = False
    error_summary: str = ""
    totals_json: str = ""
    list_item_id: str | None = None
    extra_fields: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class SchemaColumnSpec:
    """Columna esperada en una lista técnica (nombre interno Graph)."""

    internal_name: str
    display_name: str
    column_type: str
    required: bool = True
    must_be_indexed: bool = False


@dataclass(slots=True)
class SchemaValidationIssue:
    """Diferencia detectada; no se corrige automáticamente."""

    code: str
    message: str
    column_internal_name: str = ""
    severity: str = "error"


@dataclass(slots=True)
class SchemaValidationResult:
    """Resultado de validar esquema de lista existente."""

    list_display_name: str
    list_id: str
    ok: bool
    issues: list[SchemaValidationIssue] = field(default_factory=list)

    @property
    def errors(self) -> list[SchemaValidationIssue]:
        return [i for i in self.issues if i.severity == "error"]
