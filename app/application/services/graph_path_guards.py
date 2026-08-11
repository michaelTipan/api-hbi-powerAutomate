"""Guards genéricos de rutas Graph (documentos vs listas)."""

from __future__ import annotations

import re

_DRIVE_MUTATION_RE = re.compile(
    r"(^|/)?drives/[^/]+/(root:|items/)",
    re.IGNORECASE,
)


def is_drive_document_path(endpoint: str) -> bool:
    """True si el endpoint apunta a driveItems / contenido documental."""
    path = endpoint.split("?", 1)[0]
    if "/lists/" in path.lower():
        return False
    return bool(_DRIVE_MUTATION_RE.search(path))
