"""Fakes locales para bootstrap técnico 3A1 (cero Graph real)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.domain.exceptions import DocumentMutationForbidden, ExtractIndexDuplicateDocKeyError
from app.domain.models.extract_index import (
    BootstrapControlRecord,
    DocKey,
    ExtractIndexCandidate,
    ExtractIndexEnvironment,
    SchemaValidationResult,
)
from app.domain.ports.bootstrap_scope import BootstrapCreditUnit


@dataclass
class InMemoryExtractIndexRepository:
    """Repositorio índice en memoria (idempotente por DOC_KEY)."""

    items: dict[str, ExtractIndexCandidate] = field(default_factory=dict)
    upsert_calls: list[str] = field(default_factory=list)
    fail_next_upsert: bool = False
    document_mutations: int = 0

    async def validate_schema(self) -> SchemaValidationResult:
        return SchemaValidationResult(
            list_display_name="INDICE_EXTRACTOS", list_id="mem-indice", ok=True
        )

    async def find_by_credit_key(
        self, *, environment: ExtractIndexEnvironment, credit_key: str
    ) -> list[ExtractIndexCandidate]:
        return [
            c
            for c in self.items.values()
            if c.environment == environment and c.credit_key.as_string() == credit_key
        ]

    async def find_by_doc_key(
        self, *, environment: ExtractIndexEnvironment, doc_key: str
    ) -> list[ExtractIndexCandidate]:
        return [
            c
            for c in self.items.values()
            if c.environment == environment and c.doc_key.as_string() == doc_key
        ]

    async def upsert_by_doc_key(
        self, candidate: ExtractIndexCandidate
    ) -> ExtractIndexCandidate:
        if self.fail_next_upsert:
            self.fail_next_upsert = False
            raise ExtractIndexDuplicateDocKeyError("upsert_failed_simulated")
        key = candidate.doc_key.as_string()
        self.upsert_calls.append(key)
        existing = self.items.get(key)
        if existing is not None:
            candidate.list_item_id = existing.list_item_id or f"item-{len(self.items)}"
        else:
            candidate.list_item_id = f"item-{len(self.items) + 1}"
        self.items[key] = candidate
        return candidate

    async def report_duplicate_doc_keys(
        self, *, environment: ExtractIndexEnvironment
    ) -> list[DocKey]:
        return []


@dataclass
class InMemoryBootstrapControlRepository:
    """Control de campaña en memoria."""

    by_key: dict[tuple[str, str], BootstrapControlRecord] = field(default_factory=dict)
    fail_next_upsert: bool = False

    async def validate_schema(self) -> SchemaValidationResult:
        return SchemaValidationResult(
            list_display_name="CONTROL_INDICE_EXTRACTOS",
            list_id="mem-control",
            ok=True,
        )

    async def get_by_campaign_id(
        self, *, environment: ExtractIndexEnvironment, campaign_id: str
    ) -> BootstrapControlRecord | None:
        return self.by_key.get((environment.value, campaign_id))

    async def upsert_by_campaign_id(
        self, record: BootstrapControlRecord
    ) -> BootstrapControlRecord:
        if self.fail_next_upsert:
            self.fail_next_upsert = False
            raise RuntimeError("control_upsert_failed")
        key = (record.environment.value, record.campaign_id)
        existing = self.by_key.get(key)
        if existing and existing.list_item_id:
            record.list_item_id = existing.list_item_id
        else:
            record.list_item_id = record.list_item_id or f"ctrl-{len(self.by_key) + 1}"
        # Guardar copia superficial de campos relevantes
        self.by_key[key] = record
        return record


@dataclass
class FakeBootstrapScope:
    """Cola ordenada de créditos locales."""

    units: list[BootstrapCreditUnit] = field(default_factory=list)

    async def list_credits(
        self,
        *,
        after_credit_key: str | None,
        limit: int | None = None,
    ) -> list[BootstrapCreditUnit]:
        start = 0
        if after_credit_key:
            for i, u in enumerate(self.units):
                ck = (
                    u.candidates[0].credit_key.as_string()
                    if u.candidates
                    else u.credit_folder_item_id
                )
                if ck == after_credit_key:
                    start = i + 1
                    break
        out = self.units[start:]
        if limit is not None:
            out = out[: max(0, int(limit))]
        return out


@dataclass
class FakeReadonlyDocumentTree:
    """DocumentTreeReadOnlyPort fake; cualquier escritura → DocumentMutationForbidden."""

    gets: list[str] = field(default_factory=list)
    raise_on_get: Exception | None = None

    async def get_json(
        self, endpoint: str, params: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        self.gets.append(endpoint)
        if self.raise_on_get is not None:
            raise self.raise_on_get
        return {"id": "ok", "endpoint": endpoint}

    async def get_bytes(
        self, endpoint: str, params: dict[str, Any] | None = None
    ) -> bytes:
        self.gets.append(endpoint)
        return b"%PDF-fake"

    async def post_json(self, endpoint: str, body: dict[str, Any]) -> Any:
        raise DocumentMutationForbidden(f"document mutation forbidden: POST {endpoint}")

    async def put_bytes(self, endpoint: str, content: bytes) -> Any:
        raise DocumentMutationForbidden(f"document mutation forbidden: PUT {endpoint}")

    async def patch_json(self, endpoint: str, body: dict[str, Any]) -> Any:
        raise DocumentMutationForbidden(f"document mutation forbidden: PATCH {endpoint}")

    async def delete(self, endpoint: str) -> Any:
        raise DocumentMutationForbidden(f"document mutation forbidden: DELETE {endpoint}")
