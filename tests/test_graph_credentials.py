"""Pruebas del proveedor de credenciales de Graph (sin secretos reales)."""

from __future__ import annotations

import pytest

from app.adapters.secondary import graph_credentials as gc
from app.adapters.secondary.ms_graph_client import MsGraphClient
from app.domain.exceptions import GraphConfigError


@pytest.fixture(autouse=True)
def _clean_credential_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in (
        gc.ENV_CREDENTIAL_SOURCE,
        gc.ENV_TENANT_ID,
        gc.ENV_CLIENT_ID,
        gc.ENV_CLIENT_SECRET,
        gc.ENV_KEY_VAULT_URI,
        gc.ENV_KEY_VAULT_CLIENT_ID_SECRET_NAME,
        gc.ENV_KEY_VAULT_CLIENT_SECRET_SECRET_NAME,
        gc.ENV_KEY_VAULT_TENANT_ID_SECRET_NAME,
    ):
        monkeypatch.delenv(key, raising=False)
    gc.reset_credentials_cache()
    yield
    gc.reset_credentials_cache()


def test_source_defaults_to_env() -> None:
    assert gc.resolve_credential_source() == gc.CREDENTIAL_SOURCE_ENV


def test_unknown_source_falls_back_to_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(gc.ENV_CREDENTIAL_SOURCE, "vault_raro")
    assert gc.resolve_credential_source() == gc.CREDENTIAL_SOURCE_ENV


def test_env_source_reads_the_three_variables(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(gc.ENV_TENANT_ID, "tenant")
    monkeypatch.setenv(gc.ENV_CLIENT_ID, "client")
    monkeypatch.setenv(gc.ENV_CLIENT_SECRET, "secret")
    credentials = gc.get_graph_credentials()
    assert credentials.tenant_id == "tenant"
    assert credentials.client_id == "client"
    assert credentials.client_secret == "secret"


def test_env_source_lists_missing_variables() -> None:
    with pytest.raises(GraphConfigError) as err:
        gc.get_graph_credentials()
    message = str(err.value)
    assert gc.ENV_TENANT_ID in message
    assert gc.ENV_CLIENT_ID in message
    assert gc.ENV_CLIENT_SECRET in message


def test_key_vault_source_requires_its_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(gc.ENV_CREDENTIAL_SOURCE, gc.CREDENTIAL_SOURCE_KEY_VAULT)
    with pytest.raises(GraphConfigError) as err:
        gc.get_graph_credentials()
    assert gc.ENV_KEY_VAULT_URI in str(err.value)


def test_key_vault_result_is_cached(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(gc.ENV_CREDENTIAL_SOURCE, gc.CREDENTIAL_SOURCE_KEY_VAULT)
    monkeypatch.setenv(gc.ENV_KEY_VAULT_URI, "https://vault.invalid/")
    monkeypatch.setenv(gc.ENV_KEY_VAULT_TENANT_ID_SECRET_NAME, "tenantid")
    monkeypatch.setenv(gc.ENV_KEY_VAULT_CLIENT_ID_SECRET_NAME, "clientid")
    monkeypatch.setenv(gc.ENV_KEY_VAULT_CLIENT_SECRET_SECRET_NAME, "secretid")

    calls: list[int] = []

    def _fake_read() -> gc.GraphCredentials:
        calls.append(1)
        return gc.GraphCredentials("t", "c", "s")

    monkeypatch.setattr(gc, "_read_key_vault_secrets", _fake_read)

    first = gc.get_graph_credentials()
    second = gc.get_graph_credentials()
    assert first == second
    assert len(calls) == 1


def test_describe_never_exposes_secret_values(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(gc.ENV_TENANT_ID, "tenant")
    monkeypatch.setenv(gc.ENV_CLIENT_ID, "client")
    monkeypatch.setenv(gc.ENV_CLIENT_SECRET, "super-secreto")
    described = repr(gc.describe_credential_config())
    assert "super-secreto" not in described
    assert "tenant" not in described


def test_client_construction_never_raises_without_credentials() -> None:
    """El arranque de la app no debe depender de que las credenciales existan."""
    client = MsGraphClient()
    assert client.base_url
    assert client.scope
