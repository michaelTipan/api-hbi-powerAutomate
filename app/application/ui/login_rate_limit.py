"""Rate limit en memoria para login UI (IP + username)."""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass


@dataclass
class RateLimitConfig:
    max_attempts: int = 5
    window_seconds: int = 900


class LoginRateLimiter:
    def __init__(self, config: RateLimitConfig | None = None) -> None:
        self._config = config or RateLimitConfig()
        self._lock = threading.Lock()
        # key -> list[timestamps]
        self._attempts: dict[str, list[float]] = {}

    def _key(self, *, ip: str, username: str) -> str:
        return f"{(ip or '').strip()}|{(username or '').strip().lower()}"

    def _prune_unlocked(self, now: float) -> None:
        window = self._config.window_seconds
        dead: list[str] = []
        for key, stamps in self._attempts.items():
            kept = [t for t in stamps if now - t < window]
            if kept:
                self._attempts[key] = kept
            else:
                dead.append(key)
        for key in dead:
            del self._attempts[key]

    def is_blocked(self, *, ip: str, username: str, now: float | None = None) -> bool:
        ts = time.time() if now is None else now
        with self._lock:
            self._prune_unlocked(ts)
            stamps = self._attempts.get(self._key(ip=ip, username=username), [])
            return len(stamps) >= self._config.max_attempts

    def register_failure(self, *, ip: str, username: str, now: float | None = None) -> None:
        ts = time.time() if now is None else now
        key = self._key(ip=ip, username=username)
        with self._lock:
            self._prune_unlocked(ts)
            stamps = self._attempts.setdefault(key, [])
            stamps.append(ts)

    def clear_success(self, *, ip: str, username: str) -> None:
        key = self._key(ip=ip, username=username)
        with self._lock:
            self._attempts.pop(key, None)

    def purge_expired(self, *, now: float | None = None) -> int:
        ts = time.time() if now is None else now
        with self._lock:
            before = len(self._attempts)
            self._prune_unlocked(ts)
            return before - len(self._attempts)

    def clear_for_tests(self) -> None:
        with self._lock:
            self._attempts.clear()


_limiter: LoginRateLimiter | None = None


def get_login_rate_limiter() -> LoginRateLimiter:
    global _limiter
    if _limiter is None:
        _limiter = LoginRateLimiter()
    return _limiter


def configure_login_rate_limiter(config: RateLimitConfig) -> LoginRateLimiter:
    global _limiter
    _limiter = LoginRateLimiter(config)
    return _limiter


def reset_login_rate_limiter_for_tests() -> None:
    global _limiter
    if _limiter is not None:
        _limiter.clear_for_tests()
    _limiter = None
