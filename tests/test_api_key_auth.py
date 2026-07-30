"""Auth HTTP por X-API-Key: aditiva, no rompe el comportamiento sin API_HTTP_KEY."""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.adapters.primary.http.api_key_auth import (
    ENV_API_HTTP_KEY,
    is_public_path,
    keys_match,
)
from app.adapters.primary.http.app_factory import create_app
from app.adapters.primary.http.deps import init_graph_client


class _MockGraph:
    async def get(self, *a, **k):
        return {}

    async def get_bytes(self, *a, **k):
        return b""

    async def put_bytes(self, *a, **k):
        return {}

    async def delete(self, *a, **k):
        return None

    async def post_json(self, *a, **k):
        return {}, 202


def test_keys_match_constant_time() -> None:
    assert keys_match(presented="abc", expected="abc") is True
    assert keys_match(presented="abc", expected="abd") is False
    assert keys_match(presented="", expected="abc") is False


def test_health_is_public_path() -> None:
    assert is_public_path("/health") is True
    assert is_public_path("/health/") is True
    assert is_public_path("/app") is True
    assert is_public_path("/app/processes/x") is True
    assert is_public_path("/api/ui/v1/bootstrap") is True
    assert is_public_path("/api/ui") is False
    assert is_public_path("/graph/diagnostics") is False
    assert is_public_path("/graph/sharepoint/payment-validation/generate/queue") is False


def test_without_env_key_existing_behaviour_unchanged(monkeypatch) -> None:
    monkeypatch.delenv(ENV_API_HTTP_KEY, raising=False)
    init_graph_client(_MockGraph())
    client = TestClient(create_app(), raise_server_exceptions=False)
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"
    # Ruta de negocio también accesible sin key (modo compat / tests).
    r2 = client.get("/graph/diagnostics")
    assert r2.status_code != 401


def test_with_env_key_health_stays_open(monkeypatch) -> None:
    monkeypatch.setenv(ENV_API_HTTP_KEY, "test-secret-key-001")
    init_graph_client(_MockGraph())
    client = TestClient(create_app(), raise_server_exceptions=False)
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_with_env_key_missing_header_returns_401(monkeypatch) -> None:
    monkeypatch.setenv(ENV_API_HTTP_KEY, "test-secret-key-001")
    init_graph_client(_MockGraph())
    client = TestClient(create_app(), raise_server_exceptions=False)
    r = client.get("/graph/diagnostics")
    assert r.status_code == 401
    body = r.json()
    assert body["detail"] == "missing_api_key"


def test_with_env_key_wrong_header_returns_401(monkeypatch) -> None:
    monkeypatch.setenv(ENV_API_HTTP_KEY, "test-secret-key-001")
    init_graph_client(_MockGraph())
    client = TestClient(create_app(), raise_server_exceptions=False)
    r = client.get("/graph/diagnostics", headers={"X-API-Key": "wrong"})
    assert r.status_code == 401
    assert r.json()["detail"] == "invalid_api_key"


def test_with_env_key_valid_header_allows_request(monkeypatch) -> None:
    monkeypatch.setenv(ENV_API_HTTP_KEY, "test-secret-key-001")
    init_graph_client(_MockGraph())
    client = TestClient(create_app(), raise_server_exceptions=False)
    r = client.get(
        "/graph/diagnostics",
        headers={"X-API-Key": "test-secret-key-001"},
    )
    assert r.status_code != 401
    # Puede ser 200 u otro código de negocio; lo importante es que no rechace auth.
    assert r.status_code < 500 or r.status_code == 200
