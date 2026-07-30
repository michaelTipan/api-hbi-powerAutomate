"""Puerto de enumeración de créditos para bootstrap técnico (fakes en 3A1)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

from app.domain.models.extract_index import ExtractIndexCandidate


@dataclass(slots=True)
class BootstrapCreditUnit:
    """Unidad de trabajo por crédito (datos locales / fake)."""

    client_identity: str
    credit_identity: str
    credit_folder_item_id: str
    credit_path: str
    candidates: list[ExtractIndexCandidate] = field(default_factory=list)
    opaque_cursor: str = ""


@runtime_checkable
class BootstrapScopePort(Protocol):
    """
    Enumera créditos del ámbito de campaña en orden estable.

    En 3A1 la implementación es fake/local; no Graph real.
    """

    async def list_credits(
        self,
        *,
        after_credit_key: str | None,
        limit: int | None = None,
    ) -> list[BootstrapCreditUnit]:
        """Créditos pendientes después del último confirmado (exclusive)."""
        ...
