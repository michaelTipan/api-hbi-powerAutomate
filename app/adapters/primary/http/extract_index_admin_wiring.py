"""Montaje lazy del admin extract-index (Fase 3A3 / integración)."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from fastapi import FastAPI, HTTPException, Request

from app.adapters.primary.http.deps import get_graph_client
from app.adapters.primary.http.extract_index_admin_deps import ExtractIndexAdminState
from app.application.config.extract_index_settings import get_extract_index_settings
from app.application.services.extract_index.bootstrap_wiring import (
    compose_bootstrap_wiring_from_graph,
)
from app.application.services.extract_index.empty_bootstrap_scope import EmptyBootstrapScope
from app.application.services.extract_index.list_http import find_list_id_by_display_name
from app.application.sharepoint_resolution import resolve_sharepoint_from_env

logger = logging.getLogger(__name__)


def attach_extract_index_admin_router_state(app: FastAPI) -> None:
    """
    Inicializa el slot de estado. El wiring Graph se resuelve en la primera
    petición admin (lazy) para no tumbar el arranque si las listas faltan.
    """
    app.state.extract_index_admin = None
    app.state.extract_index_admin_init_lock = asyncio.Lock()
    app.state.extract_index_admin_init_error = None


async def ensure_extract_index_admin_state(request: Request) -> ExtractIndexAdminState:
    existing = getattr(request.app.state, "extract_index_admin", None)
    if isinstance(existing, ExtractIndexAdminState):
        return existing

    lock = getattr(request.app.state, "extract_index_admin_init_lock", None)
    if lock is None:
        raise HTTPException(
            status_code=503,
            detail={
                "code": "extract_index_admin_not_wired",
                "message": "Estado admin no inicializado en app_factory.",
            },
        )

    async with lock:
        existing = getattr(request.app.state, "extract_index_admin", None)
        if isinstance(existing, ExtractIndexAdminState):
            return existing

        prev_err = getattr(request.app.state, "extract_index_admin_init_error", None)
        if prev_err:
            raise HTTPException(
                status_code=503,
                detail={
                    "code": "extract_index_admin_init_failed",
                    "message": str(prev_err)[:400],
                },
            )

        try:
            state = await _build_admin_state()
        except Exception as exc:  # noqa: BLE001
            request.app.state.extract_index_admin_init_error = (
                f"{type(exc).__name__}:{exc}"
            )
            logger.exception("extract_index_admin wiring failed")
            raise HTTPException(
                status_code=503,
                detail={
                    "code": "extract_index_admin_init_failed",
                    "message": f"{type(exc).__name__}:{str(exc)[:300]}",
                },
            ) from exc

        request.app.state.extract_index_admin = state
        return state


async def _build_admin_state() -> ExtractIndexAdminState:
    settings = get_extract_index_settings()
    graph = get_graph_client()
    ctx = await resolve_sharepoint_from_env(graph)
    site_id = str(ctx["site_id"])
    indice_id = await find_list_id_by_display_name(
        graph, site_id=site_id, display_name=settings.indice_list_display_name
    )
    control_id = await find_list_id_by_display_name(
        graph, site_id=site_id, display_name=settings.control_list_display_name
    )
    wiring = compose_bootstrap_wiring_from_graph(
        graph,
        site_id=site_id,
        indice_list_id=indice_id,
        control_list_id=control_id,
        scope=EmptyBootstrapScope(),
        settings=settings,
        require_schema=False,
    )
    # Adjuntar ids resueltos para diagnóstico (sin secretos)
    wiring_extra: dict[str, Any] = {
        "site_id": site_id,
        "drive_id": str(ctx.get("drive_id") or ""),
        "indice_list_id": indice_id,
        "control_list_id": control_id,
    }
    # Guardar en settings vía atributo dinámico del wiring.lists ya tiene ids
    _ = wiring_extra
    return ExtractIndexAdminState(wiring=wiring)
