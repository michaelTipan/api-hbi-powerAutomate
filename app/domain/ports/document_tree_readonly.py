"""Puerto documental de solo lectura (árbol Documentos / driveItems)."""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class DocumentTreeReadOnlyPort(Protocol):
    """
    Acceso estrictamente de lectura al árbol documental.

    No expone upload, create, update, delete, move, rename, copy,
    create_folder, update_metadata ni update_permissions.
    """

    async def get_json(
        self, endpoint: str, params: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        """GET JSON (listados / metadata de driveItems)."""

    async def get_bytes(
        self, endpoint: str, params: dict[str, Any] | None = None
    ) -> bytes:
        """GET bytes (descarga de contenido, p. ej. PDF)."""
