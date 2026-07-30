from fastapi import FastAPI

from app.adapters.primary.http.api_key_auth import install_api_key_auth
from app.adapters.primary.http.deps import init_graph_client
from app.adapters.primary.http.extract_index_admin_wiring import (
    attach_extract_index_admin_router_state,
)
from app.adapters.primary.http.routers import (
    diagnostics,
    excel,
    extract_index_admin,
    graph,
    health,
    payment_validation,
    sharepoint,
)
from app.adapters.secondary.ms_graph_client import MsGraphClient
from app.logging_config import configure_logging


def create_app() -> FastAPI:
    configure_logging()
    app = FastAPI(title="Excel Parser API", version="2.0.0")
    # Auth HTTP opcional: solo activa si API_HTTP_KEY está definida en el entorno.
    install_api_key_auth(app)
    init_graph_client(MsGraphClient())
    app.include_router(health.router)
    app.include_router(excel.router)
    app.include_router(graph.router)
    app.include_router(diagnostics.router)
    app.include_router(sharepoint.router)
    app.include_router(payment_validation.router)
    # Extract-index admin (3A3): montado; wiring Graph lazy; gates + X-API-Key.
    attach_extract_index_admin_router_state(app)
    app.include_router(extract_index_admin.router)
    return app
