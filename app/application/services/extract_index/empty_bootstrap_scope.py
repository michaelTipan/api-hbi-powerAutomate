"""Scope vacío para wiring admin cuando no se procesan chunks (3A3)."""

from __future__ import annotations

from app.domain.ports.bootstrap_scope import BootstrapCreditUnit


class EmptyBootstrapScope:
    """No enumera créditos: impide procesar chunks reales por accidente."""

    async def list_credits(
        self,
        *,
        after_credit_key: str | None,
        limit: int | None = None,
    ) -> list[BootstrapCreditUnit]:
        return []
