"""Puerto de reloj inyectable (presupuesto cooperativo de chunk)."""

from __future__ import annotations

from datetime import datetime
from typing import Protocol, runtime_checkable


@runtime_checkable
class ClockPort(Protocol):
    def monotonic(self) -> float:
        """Segundos monotónicos (presupuesto de chunk)."""
        ...

    def now(self) -> datetime:
        """Marca de tiempo para heartbeat."""
        ...
