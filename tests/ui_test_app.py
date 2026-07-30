"""App FastAPI aislada para tests de UI (no usa create_app / app_factory)."""
from __future__ import annotations

from fastapi import FastAPI

from app.adapters.primary.http.ui.auth import install_ui_auth
from app.adapters.primary.http.ui.router_v1 import router as ui_router


def create_ui_test_app(*, install_auth: bool = True) -> FastAPI:
    app = FastAPI(title="HBI UI Test App", version="u1-test")
    if install_auth:
        install_ui_auth(app)
    app.include_router(ui_router)
    return app
