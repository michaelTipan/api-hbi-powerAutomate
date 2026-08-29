"""App FastAPI aislada para tests de UI (auth + router)."""
from __future__ import annotations

from unittest.mock import MagicMock

from fastapi import FastAPI

from app.adapters.primary.http.deps import init_graph_client
from app.adapters.primary.http.ui.auth import install_ui_auth
from app.adapters.primary.http.ui.router_v1 import router as ui_router
from app.adapters.secondary.ms_graph_client import MsGraphClient


def create_ui_test_app(*, install_auth: bool = True) -> FastAPI:
    init_graph_client(MagicMock(spec=MsGraphClient))
    app = FastAPI(title="HBI UI Test App", version="u2-test")
    if install_auth:
        install_ui_auth(app)
    app.include_router(ui_router)
    return app
