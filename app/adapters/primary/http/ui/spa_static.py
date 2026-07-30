"""Montaje SPA operador bajo /app (fallback React; no intercepta /api|/graph|/health)."""
from __future__ import annotations

import logging
import os
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse, RedirectResponse
from starlette.staticfiles import StaticFiles

logger = logging.getLogger(__name__)


def resolve_operator_ui_static_dir() -> Path | None:
    """Directorio con index.html (paquete Azure: app/static/operator-ui)."""
    override = (os.getenv("UI_STATIC_DIR") or "").strip()
    if override:
        path = Path(override)
        if (path / "index.html").is_file():
            return path.resolve()
        logger.warning("UI_STATIC_DIR sin index.html: %s", override)
        return None

    # spa_static → …/app/adapters/primary/http/ui → parents[4] = app/
    packaged = Path(__file__).resolve().parents[4] / "static" / "operator-ui"
    if (packaged / "index.html").is_file():
        return packaged
    return None


def mount_operator_spa(app: FastAPI, static_dir: Path | None = None) -> bool:
    """Registra /app → /app/, assets y fallback SPA. False si no hay dist."""
    root = static_dir or resolve_operator_ui_static_dir()
    if root is None:
        logger.warning(
            "UI habilitada pero sin estáticos en app/static/operator-ui "
            "(ni UI_STATIC_DIR). SPA no montada."
        )
        return False

    index = root / "index.html"
    assets = root / "assets"

    @app.get("/app", include_in_schema=False)
    async def redirect_app_slash() -> RedirectResponse:
        return RedirectResponse(url="/app/", status_code=307)

    if assets.is_dir():
        app.mount(
            "/app/assets",
            StaticFiles(directory=str(assets)),
            name="operator-ui-assets",
        )

    @app.get("/app/", include_in_schema=False)
    @app.get("/app/{full_path:path}", include_in_schema=False)
    async def spa_fallback(full_path: str = "") -> FileResponse:
        # Nunca debe capturar /api, /graph, /health (prefijo distinto).
        candidate = (root / full_path).resolve() if full_path else index
        try:
            candidate.relative_to(root.resolve())
        except ValueError:
            return FileResponse(index)
        if candidate.is_file():
            return FileResponse(candidate)
        return FileResponse(index)

    logger.info("Operator SPA montada desde %s", root)
    return True
