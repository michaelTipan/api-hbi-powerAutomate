from __future__ import annotations

import os
from pathlib import Path

import pytest

from app.application.ui.legacy_paths import (
    LEGACY_SANDBOX_TREE_MARKER,
    collect_legacy_path_fields,
    is_legacy_sandbox_path,
)
from app.application.ui.process_projection import PaymentProcessProjectionService, ProjectionSources
from tests.ui_fixtures import make_snap


def test_no_productive_module_imports_appservice_graph_http() -> None:
    root = Path(__file__).resolve().parents[1]
    offenders: list[str] = []
    for path in (root / "app").rglob("*.py"):
        text = path.read_text(encoding="utf-8", errors="replace")
        if "ui_appservice_graph_http" in text or "AppServiceGraphHttp" in text:
            offenders.append(str(path.relative_to(root)))
    assert offenders == []


def test_app_factory_does_not_mention_appservice_graph() -> None:
    root = Path(__file__).resolve().parents[1]
    candidates = [
        root / "app_factory.py",
        root / "app" / "adapters" / "primary" / "http" / "app_factory.py",
    ]
    found = [p for p in candidates if p.is_file()]
    assert found, "app_factory.py no encontrado"
    for path in found:
        text = path.read_text(encoding="utf-8", errors="replace")
        assert "AppServiceGraphHttp" not in text
        assert "ui_appservice_graph_http" not in text


def test_appservice_graph_requires_smoke_flag(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("UI_SHAREPOINT_SMOKE", raising=False)
    import sys

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from scripts.support.ui_appservice_graph_http import AppServiceGraphHttp

    with pytest.raises(RuntimeError, match="UI_SHAREPOINT_SMOKE"):
        AppServiceGraphHttp(base_url="https://example.invalid", api_key="x")


def test_appservice_graph_rejects_absolute_endpoint(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("UI_SHAREPOINT_SMOKE", "1")
    import sys

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from scripts.support.ui_appservice_graph_http import AppServiceGraphHttp

    client = AppServiceGraphHttp(base_url="https://example.invalid", api_key="x")
    with pytest.raises(ValueError, match="absolute|host|relative"):
        # sync helper
        client._reject_absolute("https://graph.microsoft.com/v1.0/me")
    assert "api_key" not in repr(client)
    assert "***" in repr(client)


def test_legacy_sandbox_path_detection() -> None:
    legacy = (
        f"INFORMACION CREDITOS-CLIENTES/{LEGACY_SANDBOX_TREE_MARKER}/"
        "02 VALIDACION PAGOS/01 REVISION/a.xlsx"
    )
    current = (
        "INFORMACION CREDITOS-CLIENTES/03 COMWARE PRUEBAS- INFORMACION CREDITOS CLIENTES/"
        "02 VALIDACION PAGOS/01 REVISION/a.xlsx"
    )
    assert is_legacy_sandbox_path(legacy)
    assert not is_legacy_sandbox_path(current)
    fields = collect_legacy_path_fields(
        {"validation_file_path": legacy, "historical_file_path": current}
    )
    assert fields == ("validation_file_path",)


def test_projection_warns_on_legacy_paths_without_breaking() -> None:
    legacy = (
        f"INFORMACION CREDITOS-CLIENTES/{LEGACY_SANDBOX_TREE_MARKER}/"
        "02 VALIDACION PAGOS/03 HISTORICO/cartera.xlsx"
    )
    snap = make_snap(
        estado_proceso="PENDIENTE_ASIENTOS",
        historical_file_path=legacy,
        validation_file_path=legacy.replace("03 HISTORICO", "01 REVISION").replace(
            "cartera.xlsx", "validacion.xlsx"
        ),
        notify_idempotency_key="pk",
        email_pdf_path="",
    )
    detail = PaymentProcessProjectionService().project(ProjectionSources(snapshot=snap))
    assert detail.process_key
    codes = {e.error_code for e in detail.errors}
    assert "legacy_sandbox_path" in codes
    warn = next(e for e in detail.errors if e.error_code == "legacy_sandbox_path")
    assert warn.severity == "warning"
