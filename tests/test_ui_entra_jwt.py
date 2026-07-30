"""Tests U2: JWT Entra con JWKS local (sin red)."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.adapters.primary.http.ui.router_v1 import reset_ui_router_test_hooks
from app.application.ui.entra_jwt import (
    EntraTokenError,
    reset_jwks_clients_for_tests,
    set_jwks_client_factory_for_tests,
    validate_entra_access_token,
)
from tests.ui_entra_jwt_helpers import (
    ALT_PRIVATE,
    AUDIENCE,
    ISSUER,
    TENANT,
    install_entra_env,
    install_fake_jwks,
    mint_token,
)
from tests.ui_test_app import create_ui_test_app


@pytest.fixture(autouse=True)
def _reset_auth() -> None:
    reset_ui_router_test_hooks()
    reset_jwks_clients_for_tests()
    set_jwks_client_factory_for_tests(None)
    yield
    reset_jwks_clients_for_tests()
    set_jwks_client_factory_for_tests(None)


def _client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setenv("UI_ENABLED", "true")
    monkeypatch.setenv("UI_AUTH_MODE", "entra")
    monkeypatch.setenv("ACTIVE_ENVIRONMENT", "sandbox")
    install_entra_env(monkeypatch)
    install_fake_jwks()
    return TestClient(create_ui_test_app())


def test_valid_signature_ok(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _client(monkeypatch)
    token = mint_token()
    res = client.get(
        "/api/ui/v1/environment",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert res.status_code == 200
    assert res.json()["environment"] == "sandbox"


def test_invalid_signature(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _client(monkeypatch)
    token = mint_token(private=ALT_PRIVATE)
    res = client.get(
        "/api/ui/v1/environment",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert res.status_code == 401
    assert res.json()["error_code"] == "invalid_signature"


def test_wrong_issuer(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _client(monkeypatch)
    token = mint_token(iss="https://login.microsoftonline.com/other/v2.0")
    res = client.get(
        "/api/ui/v1/environment",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert res.status_code == 401
    assert res.json()["error_code"] == "invalid_issuer"


def test_wrong_audience(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _client(monkeypatch)
    token = mint_token(aud="api://other")
    res = client.get(
        "/api/ui/v1/environment",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert res.status_code == 401
    assert res.json()["error_code"] == "invalid_audience"


def test_wrong_tenant(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _client(monkeypatch)
    token = mint_token(tid="00000000-0000-0000-0000-000000000099")
    res = client.get(
        "/api/ui/v1/environment",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert res.status_code == 401
    assert res.json()["error_code"] == "invalid_tenant"


def test_expired_token(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _client(monkeypatch)
    token = mint_token(exp_offset=-120, nbf_offset=-600)
    res = client.get(
        "/api/ui/v1/environment",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert res.status_code == 401
    assert res.json()["error_code"] == "token_expired"


def test_insufficient_role(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _client(monkeypatch)
    token = mint_token(roles=["Other.Role"])
    res = client.get(
        "/api/ui/v1/environment",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert res.status_code == 403
    assert res.json()["error_code"] == "insufficient_scope_or_role"


def test_scope_alternative_ok(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("UI_ENABLED", "true")
    monkeypatch.setenv("UI_AUTH_MODE", "entra")
    monkeypatch.setenv("ACTIVE_ENVIRONMENT", "sandbox")
    install_entra_env(
        monkeypatch,
        UI_ENTRA_REQUIRED_ROLES="",
        UI_ENTRA_REQUIRED_SCOPES="access_as_user",
    )
    install_fake_jwks()
    client = TestClient(create_ui_test_app())
    token = mint_token(roles=[], scp="access_as_user openid")
    res = client.get(
        "/api/ui/v1/environment",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert res.status_code == 200


def test_jwks_unavailable_fail_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("UI_ENABLED", "true")
    monkeypatch.setenv("UI_AUTH_MODE", "entra")
    monkeypatch.setenv("ACTIVE_ENVIRONMENT", "sandbox")
    install_entra_env(monkeypatch)
    install_fake_jwks(fail=True)
    client = TestClient(create_ui_test_app())
    token = mint_token()
    res = client.get(
        "/api/ui/v1/environment",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert res.status_code == 401
    assert res.json()["error_code"] == "jwks_unavailable"


def test_validate_direct_claims(monkeypatch: pytest.MonkeyPatch) -> None:
    install_entra_env(monkeypatch)
    install_fake_jwks()
    payload = validate_entra_access_token(mint_token())
    assert payload["tid"] == TENANT
    assert payload["aud"] == AUDIENCE
    assert payload["iss"] == ISSUER


def test_validate_rejects_without_network_default(monkeypatch: pytest.MonkeyPatch) -> None:
    """Sin factory: PyJWKClient fallaría a red; con URI local fake sigue fail-closed."""
    install_entra_env(monkeypatch)
    install_fake_jwks(fail=True)
    with pytest.raises(EntraTokenError) as exc:
        validate_entra_access_token(mint_token())
    assert exc.value.error_code == "jwks_unavailable"
