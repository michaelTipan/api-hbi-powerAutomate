"""Caché temporal de lecturas UI (no es fuente de verdad).

Clave obligatoria: environment + site_id + drive_id + relative_path (+ kind).
El eTag se valida aparte. Solo valores de negocio (bytes/meta/resúmenes);
nunca tokens ni credenciales.
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, Generic, TypeVar

T = TypeVar("T")


@dataclass
class _Entry(Generic[T]):
    etag: str | None
    value: T
    expires_at: float
    environment: str


def build_cache_key(
    *,
    environment: str,
    site_id: str,
    drive_id: str,
    relative_path: str,
    kind: str,
) -> str:
    """Clave que separa ambientes y drives; evita reutilización cruzada."""
    env = (environment or "").strip().lower() or "unknown"
    site = (site_id or "").strip() or "_"
    drive = (drive_id or "").strip() or "_"
    path = (relative_path or "").replace("\\", "/").strip().strip("/")
    kind_n = (kind or "raw").strip().lower()
    return f"{env}|{site}|{drive}|{kind_n}|{path}"


class UiReadCache:
    """TTL corto en memoria para evitar re-descargas en polling.

    - No persiste a disco.
    - No almacena tokens / headers / secretos.
    - Cambio de ``ACTIVE_ENVIRONMENT`` → ``clear()`` desde el adaptador.
    """

    def __init__(self, *, ttl_seconds: float = 30.0) -> None:
        self._ttl = max(1.0, float(ttl_seconds))
        self._store: dict[str, _Entry[Any]] = {}
        self._bound_environment: str | None = None

    @property
    def bound_environment(self) -> str | None:
        return self._bound_environment

    def bind_environment(self, environment: str) -> None:
        """Asocia la caché a un ambiente; si cambia, invalida todo."""
        env = (environment or "").strip().lower()
        if self._bound_environment is None:
            self._bound_environment = env
            return
        if self._bound_environment != env:
            self.clear()
            self._bound_environment = env

    def get(self, key: str, *, etag: str | None = None) -> Any | None:
        hit = self._store.get(key)
        if hit is None:
            return None
        if hit.expires_at < time.monotonic():
            self._store.pop(key, None)
            return None
        if etag is not None and hit.etag is not None and hit.etag != etag:
            return None
        return hit.value

    def put(
        self,
        key: str,
        value: Any,
        *,
        etag: str | None = None,
        environment: str | None = None,
    ) -> None:
        env = (environment or self._bound_environment or "unknown").strip().lower()
        self._store[key] = _Entry(
            etag=etag,
            value=value,
            expires_at=time.monotonic() + self._ttl,
            environment=env,
        )

    def invalidate(self, key: str) -> None:
        self._store.pop(key, None)

    def clear(self) -> None:
        self._store.clear()
