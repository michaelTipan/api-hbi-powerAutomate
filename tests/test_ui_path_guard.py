from __future__ import annotations

import pytest

from app.application.ui.path_guard import (
    UiAllowedRoots,
    UiPathEscapeError,
    assert_path_allowed,
    collect_allowed_roots_from_env,
)


def test_path_guard_rejects_traversal() -> None:
    roots = UiAllowedRoots(environment="sandbox", roots=("base/sandbox",))
    with pytest.raises(UiPathEscapeError):
        assert_path_allowed("base/sandbox/../secret", roots=roots)


def test_path_guard_rejects_outside_root() -> None:
    roots = UiAllowedRoots(environment="sandbox", roots=("base/sandbox",))
    with pytest.raises(UiPathEscapeError) as exc:
        assert_path_allowed("other/tree/file.xlsx", roots=roots)
    assert exc.value.reason == "path_outside_environment_roots"


def test_path_guard_allows_under_root() -> None:
    roots = UiAllowedRoots(environment="sandbox", roots=("base/sandbox",))
    assert (
        assert_path_allowed("base/sandbox/02 VALIDACION/01 REVISION/a.xlsx", roots=roots)
        == "base/sandbox/02 VALIDACION/01 REVISION/a.xlsx"
    )


def test_collect_roots_from_overlay(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ACTIVE_ENVIRONMENT", "sandbox")
    monkeypatch.setenv(
        "GRAPH_CLIENTS_BASE_PATH",
        "INFORMACION CREDITOS-CLIENTES/03 COMWARE PRUEBAS- INFORMACION CREDITOS CLIENTES",
    )
    monkeypatch.setenv(
        "PAYMENT_VALIDATION_BASE_FOLDER",
        "INFORMACION CREDITOS-CLIENTES/03 COMWARE PRUEBAS- INFORMACION CREDITOS CLIENTES/02 VALIDACION PAGOS",
    )
    bundle = collect_allowed_roots_from_env()
    assert bundle.environment == "sandbox"
    assert any("03 COMWARE PRUEBAS" in r for r in bundle.roots)
