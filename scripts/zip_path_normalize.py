"""Normalización de paths de entradas ZIP (siempre '/')."""
from __future__ import annotations


def normalize_zip_entry_path(name: str) -> str:
    """Unifica separadores Windows/POSIX para validar el paquete Azure."""
    normalized = (name or "").replace("\\", "/")
    while normalized.startswith("./"):
        normalized = normalized[2:]
    return normalized.lstrip("/")
