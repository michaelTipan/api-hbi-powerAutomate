"""Repositorio de sesiones UI opacas (abstracción + memoria)."""
from __future__ import annotations

import hashlib
import secrets
import threading
import time
from dataclasses import dataclass
from typing import Protocol


SESSION_TOKEN_BYTES = 32


@dataclass
class SessionRecord:
    """Registro en almacén: nunca guarda el token en claro."""

    token_hash: str
    username: str
    role: str
    created_at: float
    last_activity_at: float
    expires_at: float
    csrf_token: str
    auth_mode: str = "local_session"


def hash_session_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def mint_session_token() -> str:
    return secrets.token_urlsafe(SESSION_TOKEN_BYTES)


def mint_csrf_token() -> str:
    return secrets.token_urlsafe(32)


class SessionRepository(Protocol):
    def create(self, record: SessionRecord) -> None: ...

    def get_by_token_hash(self, token_hash: str) -> SessionRecord | None: ...

    def touch(self, token_hash: str, *, last_activity_at: float, expires_at: float) -> bool: ...

    def delete(self, token_hash: str) -> bool: ...

    def delete_by_username(self, username: str) -> int: ...

    def purge_expired(self, *, now: float | None = None) -> int: ...


class InMemorySessionRepository:
    """Sesiones en memoria del proceso (1 worker). Reinicio invalida todo."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._by_hash: dict[str, SessionRecord] = {}

    def create(self, record: SessionRecord) -> None:
        with self._lock:
            self._by_hash[record.token_hash] = record

    def get_by_token_hash(self, token_hash: str) -> SessionRecord | None:
        with self._lock:
            return self._by_hash.get(token_hash)

    def touch(self, token_hash: str, *, last_activity_at: float, expires_at: float) -> bool:
        with self._lock:
            rec = self._by_hash.get(token_hash)
            if rec is None:
                return False
            rec.last_activity_at = last_activity_at
            rec.expires_at = expires_at
            return True

    def delete(self, token_hash: str) -> bool:
        with self._lock:
            return self._by_hash.pop(token_hash, None) is not None

    def delete_by_username(self, username: str) -> int:
        with self._lock:
            victims = [
                h for h, r in self._by_hash.items() if r.username == username
            ]
            for h in victims:
                del self._by_hash[h]
            return len(victims)

    def purge_expired(self, *, now: float | None = None) -> int:
        ts = time.time() if now is None else now
        with self._lock:
            victims = [h for h, r in self._by_hash.items() if r.expires_at <= ts]
            for h in victims:
                del self._by_hash[h]
            return len(victims)

    def clear_for_tests(self) -> None:
        with self._lock:
            self._by_hash.clear()


_default_repo: InMemorySessionRepository | None = None


def get_session_repository() -> InMemorySessionRepository:
    global _default_repo
    if _default_repo is None:
        _default_repo = InMemorySessionRepository()
    return _default_repo


def set_session_repository_for_tests(repo: InMemorySessionRepository | None) -> None:
    global _default_repo
    _default_repo = repo
