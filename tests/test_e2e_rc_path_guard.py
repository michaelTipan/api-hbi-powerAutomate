"""Guarda fail-closed de paths sandbox E2E."""
from __future__ import annotations

import pytest

from scripts.e2e_rc.path_guard import (
    AUTHORIZED_CLIENTS_BASE,
    assert_runtime_clients_base,
    assert_sandbox_mutable_path,
)


def test_allows_sandbox_root_and_child() -> None:
    assert assert_sandbox_mutable_path(AUTHORIZED_CLIENTS_BASE) == AUTHORIZED_CLIENTS_BASE.strip("/")
    child = f"{AUTHORIZED_CLIENTS_BASE}/01 CARGA TRANSACCIONES BANCO/BANCO_BOGOTA.xlsx"
    assert "PRUEBAS" in assert_sandbox_mutable_path(child)


def test_rejects_production_clients_base() -> None:
    with pytest.raises(RuntimeError, match="path_guard"):
        assert_sandbox_mutable_path("INFORMACION CREDITOS-CLIENTES/ACME SA")


def test_rejects_dotdot() -> None:
    with pytest.raises(RuntimeError, match="path_guard"):
        assert_sandbox_mutable_path(f"{AUTHORIZED_CLIENTS_BASE}/../secreto")


def test_runtime_base_must_match() -> None:
    assert_runtime_clients_base(AUTHORIZED_CLIENTS_BASE)
    with pytest.raises(RuntimeError, match="path_guard_runtime_mismatch"):
        assert_runtime_clients_base("INFORMACION CREDITOS-CLIENTES")
