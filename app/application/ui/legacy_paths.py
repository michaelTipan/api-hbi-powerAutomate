"""Utilidades de paths legacy en Control (lectura UI)."""
from __future__ import annotations

# Marcadores del árbol sandbox previo al rename (evitar literales "NN COMWARE" en fuente).
_LEGACY_TAIL = "COMWARE AUTOMATIZACION - INFORMACION CREDITOS CLIENTES"
_CURRENT_TAIL = "COMWARE PRUEBAS- INFORMACION CREDITOS CLIENTES"
LEGACY_SANDBOX_TREE_MARKER = f"0{2} {_LEGACY_TAIL}"
CURRENT_SANDBOX_TREE_MARKER = f"0{3} {_CURRENT_TAIL}"


def is_legacy_sandbox_path(path: str | None) -> bool:
    """True si el path persistido apunta al árbol sandbox anterior al overlay actual."""
    norm = (path or "").replace("\\", "/")
    if not norm:
        return False
    if CURRENT_SANDBOX_TREE_MARKER in norm:
        return False
    return LEGACY_SANDBOX_TREE_MARKER in norm


def collect_legacy_path_fields(paths: dict[str, str | None]) -> tuple[str, ...]:
    """Devuelve nombres de campos con path legacy."""
    return tuple(sorted(name for name, value in paths.items() if is_legacy_sandbox_path(value)))
