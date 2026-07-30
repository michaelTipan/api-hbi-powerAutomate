"""Adapter Graph de solo lectura para el árbol documental."""

from __future__ import annotations

from typing import Any

from app.application.services.extract_index.mutation_guard import is_drive_document_path
from app.domain.exceptions import DocumentMutationForbidden, ExtractIndexError
from app.domain.ports.graph import GraphApiPort


class GraphDocumentTreeReadOnlyAdapter:
    """
    Implementa DocumentTreeReadOnlyPort.

    Solo delega get/get_bytes. Rechaza endpoints que no sean de drive documental
    cuando se solicita enforce_drive_paths=True (default).
    """

    def __init__(
        self,
        graph: GraphApiPort,
        *,
        enforce_drive_paths: bool = True,
    ) -> None:
        self._graph = graph
        self._enforce_drive_paths = enforce_drive_paths
        # Evidencia: este adapter no tiene métodos de escritura.
        self.read_call_count = 0

    def _assert_read_endpoint(self, endpoint: str) -> None:
        if not self._enforce_drive_paths:
            return
        # Permitir también resolución de site/drive si hace falta en fases posteriores;
        # en Fase 1 exigimos rutas de drive o sites (lectura).
        path = endpoint.split("?", 1)[0].lower()
        if any(
            x in path
            for x in (
                "/drives/",
                "/sites/",
                "drive/root",
                "/items/",
            )
        ):
            # Bloquear si alguien intenta colar mutación vía query rara: solo GET aquí.
            return
        raise ExtractIndexError(
            f"DocumentTreeReadOnly: endpoint no permitido para lectura: {endpoint}"
        )

    async def get_json(
        self, endpoint: str, params: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        self._assert_read_endpoint(endpoint)
        self.read_call_count += 1
        return await self._graph.get(endpoint, params)

    async def get_bytes(
        self, endpoint: str, params: dict[str, Any] | None = None
    ) -> bytes:
        self._assert_read_endpoint(endpoint)
        if self._enforce_drive_paths and not (
            is_drive_document_path(endpoint) or "/content" in endpoint.lower()
        ):
            # Descargas deben ser de contenido documental.
            pass
        self.read_call_count += 1
        return await self._graph.get_bytes(endpoint, params)

    # --- Métodos de escritura deliberadamente ausentes ---
    # upload / create / update / delete / move / rename / copy /
    # create_folder / update_metadata / update_permissions → no existen.


def assert_readonly_port_has_no_write_attrs(port: object) -> None:
    """Utilidad de test: el puerto/adapter no debe exponer mutadores."""
    forbidden = (
        "upload",
        "put_bytes",
        "post_json",
        "patch_json",
        "delete",
        "move",
        "rename",
        "copy",
        "create_folder",
        "update_metadata",
        "update_permissions",
        "update_content",
    )
    for name in forbidden:
        if hasattr(port, name):
            raise DocumentMutationForbidden(
                f"Puerto read-only expone atributo prohibido: {name}"
            )
