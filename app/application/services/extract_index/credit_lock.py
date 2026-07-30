"""Lock lógico en memoria por CREDIT_KEY (fake/local; sin Redis)."""

from __future__ import annotations

import asyncio


class InMemoryCreditLock:
    """Implementación local de CreditLockPort para tests y motor técnico."""

    def __init__(self) -> None:
        self._holders: dict[str, str] = {}
        self._guard = asyncio.Lock()

    async def try_acquire(self, credit_key: str, *, owner: str) -> bool:
        async with self._guard:
            current = self._holders.get(credit_key)
            if current is None:
                self._holders[credit_key] = owner
                return True
            return current == owner

    async def release(self, credit_key: str, *, owner: str) -> None:
        async with self._guard:
            if self._holders.get(credit_key) == owner:
                del self._holders[credit_key]

    async def is_held(self, credit_key: str) -> bool:
        async with self._guard:
            return credit_key in self._holders

    async def holder(self, credit_key: str) -> str | None:
        async with self._guard:
            return self._holders.get(credit_key)
