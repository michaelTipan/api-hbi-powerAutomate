"""Límites de tamaño para descargas UI (fail-closed)."""
from __future__ import annotations

import os


class UiDownloadTooLargeError(ValueError):
    """Contenido SharePoint supera el tope de lectura UI."""

    def __init__(self, path: str, size: int, limit: int) -> None:
        self.path = path
        self.size = size
        self.limit = limit
        super().__init__(f"download_too_large path={path} size={size} limit={limit}")


def ui_max_download_bytes() -> int:
    """Tope por defecto 15 MiB; configurable vía ``UI_SHAREPOINT_MAX_DOWNLOAD_BYTES``."""
    raw = (os.getenv("UI_SHAREPOINT_MAX_DOWNLOAD_BYTES") or "").strip()
    if not raw:
        return 15 * 1024 * 1024
    try:
        value = int(raw)
    except ValueError:
        return 15 * 1024 * 1024
    return max(1024, value)


def assert_download_size_allowed(path: str, size: int | None, *, limit: int | None = None) -> None:
    cap = limit if limit is not None else ui_max_download_bytes()
    if size is None:
        return
    if int(size) > int(cap):
        raise UiDownloadTooLargeError(path, int(size), int(cap))
