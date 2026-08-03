"""Validación de overlays sandbox-ui-* y production-ui-enabled."""

from __future__ import annotations

from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
OVERLAY_DIR = REPO / "config" / "environments"


def _parse_env(path: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        out[k.strip()] = v
    return out


@pytest.mark.parametrize(
    "name,writes",
    [
        ("sandbox-ui-readonly.env", False),
        ("sandbox-ui-enabled.env", True),
    ],
)
def test_sandbox_ui_overlays_safe_paths(name: str, writes: bool) -> None:
    data = _parse_env(OVERLAY_DIR / name)
    assert data["ACTIVE_ENVIRONMENT"] == "sandbox"
    assert "PRUEBAS" in data["GRAPH_CLIENTS_BASE_PATH"]
    assert data["GRAPH_CLIENTS_BASE_PATH"] != "INFORMACION CREDITOS-CLIENTES"
    assert data.get("GRAPH_ACCOUNTING_SITE_HOSTNAME", "") == ""
    assert data.get("GRAPH_ACCOUNTING_SITE_PATH", "") == ""
    assert data["UI_ENABLED"] == "true"
    assert data["UI_AUTH_MODE"] == "local_session"
    assert data["EXTRACT_INDEX_MODE"] == "off"
    if writes:
        assert data["UI_WRITE_ENABLED"] == "true"
        assert data["UI_FINALIZE_ENABLED"] == "true"
        assert data["UI_NOTIFY_ENABLED"] == "true"
        assert data["UI_MERGE_ENABLED"] == "true"
        assert data["UI_AMORTIZATION_ENABLED"] == "true"
    else:
        assert data["UI_WRITE_ENABLED"] == "false"
        assert data["UI_FINALIZE_ENABLED"] == "false"
        assert data["UI_NOTIFY_ENABLED"] == "false"
        assert data["UI_MERGE_ENABLED"] == "false"
        assert data["UI_AMORTIZATION_ENABLED"] == "false"


def test_production_ui_enabled_overlay() -> None:
    data = _parse_env(OVERLAY_DIR / "production-ui-enabled.env")
    assert data["ACTIVE_ENVIRONMENT"] == "production"
    assert data["ENV_READY"] == "true"
    assert data["GRAPH_CLIENTS_BASE_PATH"] == "INFORMACION CREDITOS-CLIENTES"
    assert "PRUEBAS" not in data["GRAPH_CLIENTS_BASE_PATH"]
    assert "PRUEBAS" in data["GRAPH_CLIENTS_EXCLUDED_FOLDERS"]
    assert data["ACCOUNTING_FOLDER_SMOKE_ENABLED"] == "false"
    assert data["UI_ENABLED"] == "true"
    assert data["UI_WRITE_ENABLED"] == "true"
    assert data["UI_FINALIZE_ENABLED"] == "true"
    assert data["UI_NOTIFY_ENABLED"] == "true"
    assert data["UI_MERGE_ENABLED"] == "true"
    assert data["UI_AMORTIZATION_ENABLED"] == "true"
    assert data["UI_REVIEW_EDIT_ENABLED"] == "true"
    assert data["UI_ASIENTOS_UPLOAD_ENABLED"] == "true"
    assert data["UI_AUTH_MODE"] == "local_session"
    assert data["UI_COOKIE_SECURE"] == "true"
    assert "PAYMENT_VALIDATION_ASIENTOS_FOLDER" in data.get("UNSET_KEYS", "")
