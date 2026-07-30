"""Parseo de ``UI_ALLOWED_ORIGINS`` (orígenes exactos permitidos para escrituras UI).

Formato: lista separada por comas de orígenes exactos, por ejemplo
``https://app-hbiauto-prod-001.azurewebsites.net,https://otro-host``.

Fail-closed: si ``UI_ALLOWED_ORIGINS`` está definida pero queda vacía o sin ningún
origen válido tras el parseo, ``resolve_allowed_origins()`` devuelve una lista
vacía (``valid=False``). Como el chequeo de Origin usa comparación exacta contra
esa lista, el resultado natural es que **ningún** origen se acepte: mejor negar
todo que aceptar de más cuando la configuración está rota.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from urllib.parse import urlparse

ENV_UI_ALLOWED_ORIGINS = "UI_ALLOWED_ORIGINS"


def _normalize_origin(raw: str) -> str | None:
    """Normaliza a ``scheme://netloc`` exacto. ``None`` si no es un origen válido."""
    value = (raw or "").strip()
    if not value:
        return None
    try:
        parsed = urlparse(value)
    except ValueError:
        return None
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return None
    # Solo scheme + netloc: sin path/query/fragment (un Origin real nunca los trae,
    # pero si alguien configura mal la env var no queremos aceptarlos "por accidente").
    if parsed.path not in ("", "/") or parsed.query or parsed.fragment:
        return None
    return f"{parsed.scheme}://{parsed.netloc}"


@dataclass(frozen=True)
class AllowedOriginsConfig:
    origins: frozenset[str]
    # True si la env var estaba presente (aunque su contenido sea inválido/vacío).
    configured: bool
    # True si quedó al menos un origen válido tras el parseo.
    valid: bool


def resolve_allowed_origins() -> AllowedOriginsConfig:
    raw = os.getenv(ENV_UI_ALLOWED_ORIGINS)
    if raw is None:
        return AllowedOriginsConfig(origins=frozenset(), configured=False, valid=False)
    stripped = raw.strip()
    if not stripped:
        return AllowedOriginsConfig(origins=frozenset(), configured=True, valid=False)
    origins: set[str] = set()
    for part in stripped.split(","):
        normalized = _normalize_origin(part)
        if normalized:
            origins.add(normalized)
    return AllowedOriginsConfig(
        origins=frozenset(origins),
        configured=True,
        valid=bool(origins),
    )


def is_origin_allowed(origin: str, cfg: AllowedOriginsConfig | None = None) -> bool:
    """Comparación exacta tras normalizar. Sin startswith/subdominios."""
    if not origin:
        return False
    resolved = cfg if cfg is not None else resolve_allowed_origins()
    normalized = _normalize_origin(origin)
    if normalized is None:
        return False
    return normalized in resolved.origins
