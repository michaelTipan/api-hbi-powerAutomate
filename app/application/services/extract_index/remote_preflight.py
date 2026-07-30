"""Preflight remoto sandbox: solo lectura (Fase 3A3)."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any

from app.application.config.extract_index_settings import (
    ExtractIndexMode,
    ExtractIndexSettings,
    get_extract_index_settings,
)
from app.application.services.extract_index.column_specs import (
    CONTROL_INDICE_COLUMNS,
    INDICE_EXTRACTOS_COLUMNS,
)
from app.application.services.extract_index.list_http import find_list_id_by_display_name
from app.application.services.extract_index.schema_validator import (
    fetch_list_columns,
    validate_columns_against_specs,
)
from app.application.sharepoint_resolution import (
    encode_graph_drive_path,
    resolve_sharepoint_from_env,
)
from app.domain.models.extract_index import ExtractIndexEnvironment
from app.domain.ports.graph import GraphApiPort


@dataclass
class MutationCounters:
    """Contadores de mutación / descargas durante el preflight."""

    list_item_writes: int = 0
    drive_mutations: int = 0
    pdf_downloads: int = 0
    campaigns_created: int = 0
    checkpoints_written: int = 0
    graph_gets: int = 0

    def as_dict(self) -> dict[str, int]:
        return {
            "list_item_writes": self.list_item_writes,
            "drive_mutations": self.drive_mutations,
            "pdf_downloads": self.pdf_downloads,
            "campaigns_created": self.campaigns_created,
            "checkpoints_written": self.checkpoints_written,
            "graph_gets": self.graph_gets,
        }


class ReadOnlyGraphProbe:
    """
    Proxy de GraphApiPort que solo permite GET/get_bytes y cuenta violaciones.
    No ejecuta escrituras: las rechaza y contabiliza.
    """

    def __init__(self, inner: GraphApiPort, counters: MutationCounters) -> None:
        self._inner = inner
        self.counters = counters
        self.blocked_writes: list[str] = []

    async def get(
        self, endpoint: str, params: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        self.counters.graph_gets += 1
        return await self._inner.get(endpoint, params)

    async def get_bytes(
        self, endpoint: str, params: dict[str, Any] | None = None
    ) -> bytes:
        # Preflight 3A3 no descarga PDFs para parseo
        self.counters.pdf_downloads += 1
        raise PermissionError("preflight_forbids_pdf_download")

    async def put_bytes(self, endpoint: str, content: bytes, **kwargs: Any) -> Any:
        self.counters.drive_mutations += 1
        self.blocked_writes.append(f"PUT {endpoint}")
        raise PermissionError("preflight_read_only")

    async def post_json(self, endpoint: str, body: dict[str, Any], **kwargs: Any) -> Any:
        path = endpoint.lower()
        if "/lists/" in path and "/items" in path:
            self.counters.list_item_writes += 1
        if "/drives/" in path:
            self.counters.drive_mutations += 1
        self.blocked_writes.append(f"POST {endpoint}")
        raise PermissionError("preflight_read_only")

    async def patch_json(self, endpoint: str, body: dict[str, Any], **kwargs: Any) -> Any:
        path = endpoint.lower()
        if "/lists/" in path:
            self.counters.list_item_writes += 1
        if "/drives/" in path:
            self.counters.drive_mutations += 1
        self.blocked_writes.append(f"PATCH {endpoint}")
        raise PermissionError("preflight_read_only")

    async def delete(self, endpoint: str, **kwargs: Any) -> Any:
        path = endpoint.lower()
        if "/lists/" in path:
            self.counters.list_item_writes += 1
        if "/drives/" in path:
            self.counters.drive_mutations += 1
        self.blocked_writes.append(f"DELETE {endpoint}")
        raise PermissionError("preflight_read_only")


@dataclass
class RemotePreflightReport:
    ok: bool
    environment: str
    mode: str
    bootstrap_enabled: bool
    site_id: str = ""
    drive_id: str = ""
    clients_base_path: str = ""
    production_path_used: bool = False
    indice: dict[str, Any] = field(default_factory=dict)
    control: dict[str, Any] = field(default_factory=dict)
    sample_clients: list[dict[str, Any]] = field(default_factory=list)
    issues: list[str] = field(default_factory=list)
    mutation_counters: dict[str, int] = field(default_factory=dict)
    blocked_writes: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "environment": self.environment,
            "mode": self.mode,
            "bootstrap_enabled": self.bootstrap_enabled,
            "site_id": self.site_id,
            "drive_id": self.drive_id,
            "clients_base_path": self.clients_base_path,
            "production_path_used": self.production_path_used,
            "indice": self.indice,
            "control": self.control,
            "sample_clients": self.sample_clients,
            "issues": self.issues,
            "mutation_counters": self.mutation_counters,
            "blocked_writes": self.blocked_writes,
            "campaigns_created": 0,
            "checkpoints_written": 0,
        }


_PROD_CLIENTS_MARKERS = (
    # Marcadores genéricos (evitar nombres numerados hardcodeados en fuente).
    "INFORMACION CREDITOS CLIENTES",
)


def _looks_like_production_clients_path(path: str) -> bool:
    """
    Heurística: ruta de clientes productiva si menciona la carpeta madre
    de créditos y no incluye el marcador de pruebas del overlay.
    """
    normalized = (path or "").replace("\\", "/").upper()
    sandbox_marker = (
        os.getenv("EXTRACT_INDEX_SANDBOX_PATH_MARKER") or "COMWARE PRUEBAS"
    ).strip().upper()
    if sandbox_marker and sandbox_marker in normalized:
        return False
    for marker in _PROD_CLIENTS_MARKERS:
        if marker.upper() in normalized:
            # La raíz productiva suele ser …/INFORMACION CREDITOS-CLIENTES/<carpeta prod>
            # sin el marcador de pruebas.
            return True
    return False


async def run_remote_sandbox_preflight(
    graph: GraphApiPort,
    *,
    settings: ExtractIndexSettings | None = None,
    sample_client_limit: int = 3,
) -> RemotePreflightReport:
    """
    Preflight remoto estrictamente RO.

    No crea campañas, no escribe listas, no muta drives, no parsea PDFs.
    """
    cfg = settings or get_extract_index_settings()
    counters = MutationCounters()
    probe = ReadOnlyGraphProbe(graph, counters)
    issues: list[str] = []

    if cfg.environment != ExtractIndexEnvironment.SANDBOX:
        issues.append("environment_not_sandbox")
    if cfg.mode != ExtractIndexMode.OFF:
        issues.append("extract_index_mode_must_be_off")
    if not cfg.bootstrap_enabled:
        issues.append("bootstrap_disabled")

    clients_path = (os.getenv("GRAPH_CLIENTS_BASE_PATH") or "").strip()
    production_used = _looks_like_production_clients_path(clients_path)
    if production_used:
        issues.append("production_clients_path_detected")
    if not clients_path:
        issues.append("missing_clients_base_path")

    report = RemotePreflightReport(
        ok=False,
        environment=cfg.environment.value,
        mode=cfg.mode.value,
        bootstrap_enabled=cfg.bootstrap_enabled,
        clients_base_path=clients_path,
        production_path_used=production_used,
    )

    try:
        ctx = await resolve_sharepoint_from_env(probe)
    except Exception as exc:  # noqa: BLE001
        issues.append(f"resolve_sharepoint:{type(exc).__name__}")
        report.issues = issues
        report.mutation_counters = counters.as_dict()
        report.blocked_writes = list(probe.blocked_writes)
        return report

    site_id = str(ctx.get("site_id") or "")
    drive_id = str(ctx.get("drive_id") or "")
    report.site_id = site_id
    report.drive_id = drive_id
    if not site_id or not drive_id:
        issues.append("missing_site_or_drive")

    # Localizar listas + validar columnas (solo GET)
    for label, display, specs in (
        ("indice", cfg.indice_list_display_name, INDICE_EXTRACTOS_COLUMNS),
        ("control", cfg.control_list_display_name, CONTROL_INDICE_COLUMNS),
    ):
        entry: dict[str, Any] = {"display_name": display}
        try:
            list_id = await find_list_id_by_display_name(
                probe, site_id=site_id, display_name=display
            )
            entry["list_id"] = list_id
            columns = await fetch_list_columns(probe, site_id=site_id, list_id=list_id)
            validation = validate_columns_against_specs(
                list_display_name=display,
                list_id=list_id,
                columns=columns,
                specs=specs,
            )
            entry["schema_ok"] = validation.ok
            entry["issues"] = [
                {"code": i.code, "message": i.message, "column": i.column_internal_name}
                for i in validation.issues
            ]
            if not validation.ok:
                issues.append(f"{label}_schema_incompatible")
        except Exception as exc:  # noqa: BLE001
            entry["schema_ok"] = False
            entry["error"] = f"{type(exc).__name__}:{str(exc)[:200]}"
            issues.append(f"{label}_locate_or_schema_failed")
        if label == "indice":
            report.indice = entry
        else:
            report.control = entry

    # Muestra pequeña de clientes (metadata hijos de la raíz sandbox)
    if clients_path and site_id and drive_id and not production_used:
        try:
            encoded = encode_graph_drive_path(clients_path)
            children = await probe.get(
                f"/sites/{site_id}/drives/{drive_id}/root:/{encoded}:/children"
                f"?$select=id,name,folder,file&$top={max(1, sample_client_limit)}"
            )
            for item in (children.get("value") or [])[:sample_client_limit]:
                report.sample_clients.append(
                    {
                        "id": str(item.get("id") or ""),
                        "name": str(item.get("name") or ""),
                        "is_folder": bool(item.get("folder")),
                    }
                )
        except Exception as exc:  # noqa: BLE001
            issues.append(f"sample_clients_failed:{type(exc).__name__}")

    # Garantías fail-closed del propio probe
    if counters.list_item_writes or counters.drive_mutations or counters.pdf_downloads:
        issues.append("unexpected_mutations_or_downloads")

    report.issues = issues
    report.mutation_counters = counters.as_dict()
    report.blocked_writes = list(probe.blocked_writes)
    report.ok = len(issues) == 0
    return report
