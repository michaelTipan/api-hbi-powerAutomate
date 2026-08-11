"""Fail-closed: mutaciones Graph solo bajo la raíz sandbox PRUEBAS autorizada."""
from __future__ import annotations

import re
from pathlib import PurePosixPath

AUTHORIZED_CLIENTS_BASE = (
    "INFORMACION CREDITOS-CLIENTES/"
    "03 COMWARE PRUEBAS- INFORMACION CREDITOS CLIENTES"
)

_FORBIDDEN_MARKERS = (
    "02 COMWARE AUTOMATIZACION",
    "INFORMACION CREDITOS-CLIENTES/INFORMACION",  # clients reales sin PRUEBAS
)


def normalize_graph_path(path: str) -> str:
    text = (path or "").replace("\\", "/").strip()
    text = re.sub(r"/+", "/", text)
    return text.strip("/")


def assert_sandbox_mutable_path(path: str) -> str:
    """Valida que ``path`` esté bajo la raíz PRUEBAS. Raise RuntimeError si no."""
    norm = normalize_graph_path(path)
    base = normalize_graph_path(AUTHORIZED_CLIENTS_BASE)
    if not norm:
        raise RuntimeError("path_guard_empty")
    lower = norm.lower()
    for marker in _FORBIDDEN_MARKERS:
        if normalize_graph_path(marker).lower() in lower and "pruebas" not in lower:
            raise RuntimeError(f"path_guard_forbidden_marker:{marker}")
    if "pruebas" not in lower:
        raise RuntimeError("path_guard_missing_pruebas")
    if not (norm == base or norm.startswith(base + "/")):
        raise RuntimeError(f"path_guard_outside_sandbox:{norm}")
    # Evitar escape vía ..
    parts = PurePosixPath(norm).parts
    if ".." in parts:
        raise RuntimeError("path_guard_dotdot")
    return norm


def assert_runtime_clients_base(runtime_base: str) -> str:
    """Compara GRAPH_CLIENTS_BASE_PATH efectivo del worker con el autorizado."""
    norm = normalize_graph_path(runtime_base)
    expected = normalize_graph_path(AUTHORIZED_CLIENTS_BASE)
    if norm != expected:
        raise RuntimeError(
            f"path_guard_runtime_mismatch: got={norm!r} expected={expected!r}"
        )
    return norm
