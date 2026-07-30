"""Relojes para presupuesto cooperativo de chunk."""

from __future__ import annotations

import time
from datetime import datetime, timezone


class SystemClock:
    def monotonic(self) -> float:
        return time.monotonic()

    def now(self) -> datetime:
        return datetime.now(timezone.utc)


class FakeClock:
    """Reloj inyectable para tests (avance manual)."""

    def __init__(
        self,
        *,
        start_monotonic: float = 0.0,
        start_now: datetime | None = None,
    ) -> None:
        self._mono = float(start_monotonic)
        self._now = start_now or datetime(2026, 7, 29, 12, 0, 0, tzinfo=timezone.utc)

    def monotonic(self) -> float:
        return self._mono

    def now(self) -> datetime:
        return self._now

    def advance(self, seconds: float) -> None:
        self._mono += float(seconds)
        # heartbeat avanza en paralelo (aproximación de test)
        from datetime import timedelta

        self._now = self._now + timedelta(seconds=float(seconds))
