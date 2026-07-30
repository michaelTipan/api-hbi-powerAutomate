"""Puerto de lock lógico por crédito (bootstrap vs Generate)."""

from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class CreditLockPort(Protocol):
    """
    Lock cooperativo por CREDIT_KEY.

    Generate tiene prioridad lógica: si el lock está ocupado, bootstrap
    omite el crédito; nunca fuerza ni roba el lock.
    """

    async def try_acquire(self, credit_key: str, *, owner: str) -> bool:
        """True si se adquirió; False si ya está ocupado."""
        ...

    async def release(self, credit_key: str, *, owner: str) -> None:
        """Libera solo si el owner coincide."""
        ...

    async def is_held(self, credit_key: str) -> bool:
        ...

    async def holder(self, credit_key: str) -> str | None:
        ...
