"""Puertos de repositorio para listas técnicas del índice."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from app.domain.models.extract_index import (
    BootstrapControlRecord,
    DocKey,
    ExtractIndexCandidate,
    ExtractIndexEnvironment,
    SchemaValidationResult,
)


@runtime_checkable
class ExtractIndexRepository(Protocol):
    """CRUD de ítems en INDICE_EXTRACTOS (nunca create_list)."""

    async def validate_schema(self) -> SchemaValidationResult: ...

    async def find_by_credit_key(
        self, *, environment: ExtractIndexEnvironment, credit_key: str
    ) -> list[ExtractIndexCandidate]: ...

    async def find_by_doc_key(
        self, *, environment: ExtractIndexEnvironment, doc_key: str
    ) -> list[ExtractIndexCandidate]: ...

    async def upsert_by_doc_key(
        self, candidate: ExtractIndexCandidate
    ) -> ExtractIndexCandidate: ...

    async def report_duplicate_doc_keys(
        self, *, environment: ExtractIndexEnvironment
    ) -> list[DocKey]: ...


@runtime_checkable
class BootstrapControlRepository(Protocol):
    """CRUD de ítems en CONTROL_INDICE_EXTRACTOS (nunca create_list)."""

    async def validate_schema(self) -> SchemaValidationResult: ...

    async def get_by_campaign_id(
        self, *, environment: ExtractIndexEnvironment, campaign_id: str
    ) -> BootstrapControlRecord | None: ...

    async def upsert_by_campaign_id(
        self, record: BootstrapControlRecord
    ) -> BootstrapControlRecord: ...
