from fastapi import FastAPI

from app.adapters.primary.http.api_key_auth import install_api_key_auth
from app.adapters.primary.http.deps import get_graph_client, init_graph_client
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
from app.application.ui.feature_flags import get_ui_feature_flags
from app.logging_config import configure_logging


def _mount_operator_ui(app: FastAPI) -> None:
    """Monta router UI + SPA solo si UI_ENABLED efectivo. Reutiliza Graph existente."""
    flags = get_ui_feature_flags()
    if not flags.ui_enabled:
        return

    from app.adapters.primary.http.ui.auth import install_ui_auth
    from app.adapters.primary.http.ui.router_v1 import (
        configure_ui_router,
        router as ui_router,
    )
    from app.adapters.primary.http.ui.spa_static import mount_operator_spa
    from app.adapters.secondary.ui_sharepoint_read import UiSharePointReadAdapter
    from app.application.ui.ports import UiSharePointReadPort

    # Misma instancia que init_graph_client — sin segundo MsGraphClient.
    graph = get_graph_client()
    reader: UiSharePointReadPort = UiSharePointReadAdapter(graph)
    # Memoria PA mutable privada no se acopla en U2; JobManager + evidencia persistente.
    configure_ui_router(sharepoint_reader=reader)
    install_ui_auth(app)
    app.include_router(ui_router)
    mount_operator_spa(app)


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
    _mount_operator_ui(app)
    return app
