"""Puertos de lectura estricta para la UI operativa (U1.5).

La proyección depende de ``UiSharePointReadPort``, nunca de ``GraphApiPort``
completo (que incluye put/post/patch/delete).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

from app.application.use_cases.payment_validation_process_control import (
    ProcessControlSnapshot,
)


@dataclass(frozen=True)
class UiDriveItemMeta:
    """Metadata sanitizada de un ítem SharePoint (sin tokens ni headers)."""

    path: str
    name: str | None = None
    web_url: str | None = None
    etag: str | None = None
    ctag: str | None = None
    size: int | None = None
    last_modified: str | None = None
    exists: bool = True


@dataclass(frozen=True)
class UiFileContent:
    """Contenido binario acotado a lectura (tests / parse local)."""

    path: str
    content: bytes
    etag: str | None = None
    content_type: str | None = None


@dataclass(frozen=True)
class UiControlReadResult:
    """Control por banco + job ids técnicos si existen en el Excel."""

    snapshot: ProcessControlSnapshot
    meta: UiDriveItemMeta
    generate_job_id: str | None = None
    finalize_job_id: str | None = None
    notify_job_id: str | None = None
    merge_job_id: str | None = None
    apply_job_id: str | None = None
    dry_run_job_id: str | None = None


@dataclass(frozen=True)
class UiManifestOutputRef:
    """PDF consolidado operativo leído desde ``outputs[]`` del manifest Merge."""

    path: str
    credito: str | None = None
    id_pago: str | None = None
    web_url: str | None = None


@dataclass(frozen=True)
class UiManifestSummary:
    """Resumen de manifest Merge sin volcar el JSON completo al cliente."""

    path: str
    exists: bool
    etag: str | None = None
    status: str | None = None
    incomplete_group_count: int = 0
    complete_group_count: int = 0
    eligible_for_dry_run: bool | None = None
    # Primer PDF consolidado del manifest (compat / atajo).
    primary_output_path: str | None = None
    # Todos los PDFs operativos de ``outputs[]`` (uno por grupo consolidado).
    output_pdfs: tuple[UiManifestOutputRef, ...] = field(default_factory=tuple)
    raw_keys: tuple[str, ...] = field(default_factory=tuple)


@runtime_checkable
class UiGraphHttpReadPort(Protocol):
    """HTTP Graph mínimo: solo GET. Sin put/post/patch/delete.

    ``endpoint`` debe ser un path relativo construido en servidor
    (p. ej. ``/sites/{id}/drives/{id}/root:/...``). El adaptador UI valida
    con ``assert_relative_graph_endpoint``: el navegador nunca suministra
    URLs Graph absolutas ni host ``graph.microsoft.com``.
    """

    async def get(self, endpoint: str, params: dict[str, Any] | None = None) -> dict[str, Any]: ...

    async def get_bytes(self, endpoint: str, params: dict[str, Any] | None = None) -> bytes: ...


@runtime_checkable
class UiSharePointReadPort(Protocol):
    """Puerto SharePoint de solo lectura para la UI.

    Paths relativos se derivan de ``bank_code`` / Control / settings del
    ambiente activo. Toda descarga pasa por ``assert_path_allowed``.
    No hay operación que acepte URL Graph del cliente.
    """

    async def read_process_control(self, bank_code: str) -> UiControlReadResult: ...

    async def get_item_meta(self, relative_path: str) -> UiDriveItemMeta: ...

    async def download_bytes(self, relative_path: str) -> UiFileContent: ...

    async def get_web_url(self, relative_path: str) -> str | None: ...

    async def read_merge_manifest_summary(self, relative_path: str) -> UiManifestSummary: ...

    async def adelantados_meta(self) -> UiDriveItemMeta | None: ...
