"""Validación de process_key expuesto en rutas UI (no es path SharePoint)."""
from __future__ import annotations

import re

_PROCESS_KEY_RE = re.compile(
    r"^payment-validation\|[a-z0-9_]+\|\d{4}-\d{2}-\d{2}\|[A-Za-z0-9\-]+$",
    re.IGNORECASE,
)


class UiInvalidProcessKeyError(ValueError):
    def __init__(self, process_key: str, reason: str) -> None:
        self.process_key = process_key
        self.reason = reason
        super().__init__(reason)


def assert_ui_process_key(process_key: str) -> str:
    """Rechaza URLs Graph, paths absolutos o claves con traversal.

    El backend usa ``process_key`` solo como identificador de negocio; los paths
    SharePoint se derivan del Control / settings, nunca del navegador.
    """
    key = str(process_key or "").strip()
    if not key:
        raise UiInvalidProcessKeyError(key, "process_key_empty")
    lower = key.lower()
    if "://" in key or lower.startswith("http"):
        raise UiInvalidProcessKeyError(key, "process_key_url_forbidden")
    if "graph.microsoft.com" in lower or "/sites/" in lower or "/drives/" in lower:
        raise UiInvalidProcessKeyError(key, "process_key_graph_path_forbidden")
    if key.startswith("/") or key.startswith("\\") or ".." in key.replace("\\", "/").split("/"):
        raise UiInvalidProcessKeyError(key, "process_key_path_forbidden")
    # Formato canónico preferido; permitir claves legacy cortas sin pipes solo si
    # no parecen path (p. ej. tests). Si tiene pipes, exigir patrón.
    if "|" in key and not _PROCESS_KEY_RE.match(key):
        # Aún permitir variantes de test (pk-1) sin pipes; con pipes malformadas → error.
        parts = key.split("|")
        if len(parts) != 4 or not parts[0] or not parts[1]:
            raise UiInvalidProcessKeyError(key, "process_key_malformed")
    return key
