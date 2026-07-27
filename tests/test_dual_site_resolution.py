"""
Resolución de los dos sitios de SharePoint y exclusión de carpetas de automatización.

Verifica que el mecanismo histórico de búsqueda por texto siga funcionando cuando las
variables nuevas no están definidas, para no romper el ambiente de pruebas.
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from app.application.config.payment_validation_settings import (
    is_excluded_client_folder,
    resolve_client_folder_exclusions,
)
from app.application.sharepoint_resolution import (
    ENV_ACCOUNTING_DRIVE_NAME,
    ENV_ACCOUNTING_SITE_HOSTNAME,
    ENV_ACCOUNTING_SITE_PATH,
    ENV_OPERATIONS_SITE_HOSTNAME,
    ENV_OPERATIONS_SITE_PATH,
    accounting_site_is_configured,
    operations_site_is_configured,
    require_operations_site_config,
    resolve_accounting_context,
    resolve_sharepoint_path,
)
from app.domain.exceptions import GraphConfigError

OPERATIONS_HOST = "gecolsacat.sharepoint.com"
OPERATIONS_PATH = "sites/OperacionesHBICapital"
ACCOUNTING_PATH = "sites/HBICapitalContabilidad"


class _SitesGraph:
    """Simula /sites?search=, /sites/{host}:/{path} y /sites/{id}/drives."""

    def __init__(self, drives: list[str] | None = None) -> None:
        self.requests: list[str] = []
        self.drives = drives if drives is not None else ["Documentos"]

    async def get(self, endpoint: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        self.requests.append(endpoint)
        if endpoint.endswith("/drives"):
            return {
                "value": [
                    {"id": f"drive-{i}", "name": name} for i, name in enumerate(self.drives)
                ]
            }
        if endpoint == "/sites":
            return {"value": [{"id": "site-by-search", "name": "PRUEBAS"}]}
        return {"id": f"site::{endpoint.split(':/', 1)[-1]}"}


@pytest.fixture(autouse=True)
def _clean_site_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in (
        ENV_OPERATIONS_SITE_HOSTNAME,
        ENV_OPERATIONS_SITE_PATH,
        ENV_ACCOUNTING_SITE_HOSTNAME,
        ENV_ACCOUNTING_SITE_PATH,
        ENV_ACCOUNTING_DRIVE_NAME,
        "GRAPH_OPERATIONS_DRIVE_NAME",
    ):
        monkeypatch.delenv(key, raising=False)


def test_search_is_used_when_new_variables_are_absent() -> None:
    graph = _SitesGraph()
    context = asyncio.run(resolve_sharepoint_path(graph, "PRUEBAS", "Documentos", "carpeta/a"))
    assert context["site_id"] == "site-by-search"
    assert graph.requests[0] == "/sites"


def test_hostname_and_path_take_priority(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(ENV_OPERATIONS_SITE_HOSTNAME, OPERATIONS_HOST)
    monkeypatch.setenv(ENV_OPERATIONS_SITE_PATH, OPERATIONS_PATH)
    graph = _SitesGraph()
    context = asyncio.run(resolve_sharepoint_path(graph, "IGNORADO", "Documentos", "carpeta/a"))
    assert context["site_id"] == f"site::{OPERATIONS_PATH}"
    assert graph.requests[0] == f"/sites/{OPERATIONS_HOST}:/{OPERATIONS_PATH}"


def test_operations_config_accepts_either_mechanism(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("GRAPH_SHAREPOINT_SITE_SEARCH", raising=False)
    assert not operations_site_is_configured()
    with pytest.raises(GraphConfigError):
        require_operations_site_config()

    monkeypatch.setenv(ENV_OPERATIONS_SITE_HOSTNAME, OPERATIONS_HOST)
    monkeypatch.setenv(ENV_OPERATIONS_SITE_PATH, OPERATIONS_PATH)
    assert operations_site_is_configured()
    require_operations_site_config()


def test_drive_name_mismatch_lists_available_libraries() -> None:
    graph = _SitesGraph(drives=["Documentos compartidos"])
    with pytest.raises(GraphConfigError) as err:
        asyncio.run(resolve_sharepoint_path(graph, "PRUEBAS", "Documentos", "carpeta/a"))
    assert "Documentos compartidos" in str(err.value)


def test_drive_name_matches_ignoring_case() -> None:
    graph = _SitesGraph(drives=["documentos"])
    context = asyncio.run(resolve_sharepoint_path(graph, "PRUEBAS", "Documentos", "carpeta/a"))
    assert context["drive_id"] == "drive-0"


def test_accounting_is_disabled_until_configured() -> None:
    assert not accounting_site_is_configured()
    graph = _SitesGraph()
    with pytest.raises(GraphConfigError):
        asyncio.run(resolve_accounting_context(graph))


def test_accounting_context_resolves_when_configured(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(ENV_ACCOUNTING_SITE_HOSTNAME, OPERATIONS_HOST)
    monkeypatch.setenv(ENV_ACCOUNTING_SITE_PATH, ACCOUNTING_PATH)
    monkeypatch.setenv(ENV_ACCOUNTING_DRIVE_NAME, "Documentos")
    assert accounting_site_is_configured()

    graph = _SitesGraph()
    context = asyncio.run(resolve_accounting_context(graph))
    assert context["site_id"] == f"site::{ACCOUNTING_PATH}"
    assert context["drive_id"] == "drive-0"


def test_automation_folders_are_excluded_from_clients(monkeypatch: pytest.MonkeyPatch) -> None:
    clients_base = "INFORMACION CREDITOS-CLIENTES"
    monkeypatch.setenv(
        "PAYMENT_VALIDATION_BASE_FOLDER",
        f"{clients_base}/01 VALIDACION PAGOS",
    )
    monkeypatch.setenv(
        "GRAPH_BANK_PAYMENTS_FILE_PATH",
        f"{clients_base}/00 CARGA TRANSACCIONES BANCO/BANCO_BOGOTA.xlsx",
    )
    monkeypatch.setenv(
        "GRAPH_BANK_PAYMENTS_FILE_PATH_BANCOLOMBIA",
        f"{clients_base}/00 CARGA TRANSACCIONES BANCO/BANCO_BANCOLOMBIA.xlsx",
    )

    exclusions = resolve_client_folder_exclusions(clients_base)
    assert "01 VALIDACION PAGOS" in exclusions
    assert "00 CARGA TRANSACCIONES BANCO" in exclusions

    assert is_excluded_client_folder("01 VALIDACION PAGOS", exclusions)
    assert is_excluded_client_folder("00 carga  transacciones banco", exclusions)
    assert not is_excluded_client_folder("AGREGADOS GUAYURIBA", exclusions)
    assert not is_excluded_client_folder("A&M CONSTRUCOL", exclusions)


def test_extra_exclusions_can_be_added_by_env(monkeypatch: pytest.MonkeyPatch) -> None:
    clients_base = "INFORMACION CREDITOS-CLIENTES"
    monkeypatch.setenv(
        "GRAPH_CLIENTS_EXCLUDED_FOLDERS",
        "02 COMWARE AUTOMATIZACION - INFORMACION CREDITOS CLIENTES, PLANTILLAS",
    )
    exclusions = resolve_client_folder_exclusions(clients_base)
    assert is_excluded_client_folder("PLANTILLAS", exclusions)
    assert is_excluded_client_folder(
        "02 COMWARE AUTOMATIZACION - INFORMACION CREDITOS CLIENTES", exclusions
    )


def test_exclusions_are_empty_without_clients_base() -> None:
    assert resolve_client_folder_exclusions("") == frozenset()
