from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.adapters.primary.http.ui.router_v1 import (
    configure_ui_router_for_tests,
    reset_ui_router_test_hooks,
)
from app.application.job_manager import JobManager
from tests.ui_fixtures import make_snap
from tests.ui_test_app import create_ui_test_app

AUTH = {"Authorization": "Bearer mock-user"}


@pytest.fixture(autouse=True)
def _env(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("UI_ENABLED", "true")
    monkeypatch.setenv("UI_WRITE_ENABLED", "false")
    monkeypatch.setenv("UI_AUTH_MODE", "mock")
    monkeypatch.setenv("ACTIVE_ENVIRONMENT", "sandbox")
    reset_ui_router_test_hooks()
    yield
    reset_ui_router_test_hooks()


def test_list_and_get_process() -> None:
    snap = make_snap()
    configure_ui_router_for_tests(control_loader=lambda bc: snap)
    client = TestClient(create_ui_test_app())

    listed = client.get("/api/ui/v1/processes", headers=AUTH)
    assert listed.status_code == 200
    body = listed.json()
    assert body["environment"] == "sandbox"
    assert len(body["items"]) >= 1
    assert body["items"][0]["process_key"] == snap.process_key
    assert body["items"][0]["operational_status"] == "EN_REVISION"

    detail = client.get(
        f"/api/ui/v1/processes/{snap.process_key}",
        headers=AUTH,
    )
    assert detail.status_code == 200
    d = detail.json()
    assert d["files"]["validation_file_path"]
    assert any(l["rel"] == "review_excel" for l in d["links"])
    assert [s["name"] for s in d["steps"]] == [
        "generate",
        "review",
        "finalize",
        "notify",
        "merge",
        "dry_run",
        "apply",
    ]
    assert d["trigger_source"] is None


def test_process_not_found() -> None:
    configure_ui_router_for_tests(
        control_loader=lambda bc: make_snap(process_key="other", estado_proceso="VACIO")
    )
    client = TestClient(create_ui_test_app())
    res = client.get(
        "/api/ui/v1/processes/payment-validation|banco_bogota|2026-01-01|x",
        headers=AUTH,
    )
    assert res.status_code == 404
    assert res.json()["detail"]["error_code"] == "process_not_found"


def test_get_job_from_job_manager() -> None:
    import asyncio

    jm = JobManager()
    job_id = "ui-test-job-001"

    async def _seed() -> None:
        await jm.set_job(
            job_id,
            {
                "job_id": job_id,
                "type": "generate",
                "status": "completed",
                "queued_at": "t0",
                "result": {"process_key": "pk", "bank_code": "banco_bogota"},
            },
        )

    asyncio.run(_seed())
    client = TestClient(create_ui_test_app())
    res = client.get(f"/api/ui/v1/jobs/{job_id}", headers=AUTH)
    assert res.status_code == 200
    body = res.json()
    assert body["store"] == "job_manager"
    assert body["type"] == "generate"
    assert body["environment"] == "sandbox"


def test_get_job_finalize_failed_attaches_expanded_issues() -> None:
    """El modal de la SPA necesita error.issues, no solo el conteo genérico."""
    import asyncio
    import json

    jm = JobManager()
    job_id = "ui-test-finalize-multi-001"
    message = "multiple_review_errors|" + json.dumps(
        {
            "issues": [
                {
                    "error_code": "validar_requires_positive_total",
                    "excel_row": 6,
                    "sheet": "Aplicacion_Pagos",
                    "field": "Total aplicado",
                    "credito": "CREDITO # 265",
                    "cliente": "EQUINORTE",
                },
                {
                    "error_code": "empty_estado_pago",
                    "excel_row": 4,
                    "sheet": "Aplicacion_Pagos",
                    "field": "Estado Pago",
                    "id_pago": "ID2",
                },
            ],
            "count": 2,
        },
        ensure_ascii=False,
    )

    async def _seed() -> None:
        await jm.set_job(
            job_id,
            {
                "job_id": job_id,
                "type": "finalize",
                "status": "failed",
                "queued_at": "t0",
                "error": {
                    "type": "ValueError",
                    "message": message,
                    "error_code": "multiple_review_errors",
                },
            },
        )

    asyncio.run(_seed())
    client = TestClient(create_ui_test_app())
    res = client.get(f"/api/ui/v1/jobs/{job_id}", headers=AUTH)
    assert res.status_code == 200
    body = res.json()
    issues = (body.get("error") or {}).get("issues") or []
    assert len(issues) == 2
    assert "total aplicado" in (issues[0].get("user_message") or "").lower()
    assert issues[0].get("location", {}).get("row") == 6
    assert "Estado Pago" in (issues[1].get("user_message") or "")


def test_get_job_completed_exposes_artifact_urls_in_result_summary() -> None:
    """Modales de éxito: histórico/soporte (Finalize) y Excel de revisión (Generate)."""
    import asyncio

    jm = JobManager()

    async def _seed() -> None:
        await jm.set_job(
            "ui-test-finalize-ok-urls",
            {
                "job_id": "ui-test-finalize-ok-urls",
                "type": "finalize",
                "status": "completed",
                "queued_at": "t0",
                "result": {
                    "process_key": "pk-f",
                    "historical_file_path": "hist/h.xlsx",
                    "historical_file_url": "https://sp.example/hist.xlsx",
                    "secretary_file_path": "hist/s.xlsx",
                    "secretary_file_url": "https://sp.example/sec.xlsx",
                    "secret_token": "must-not-leak",
                },
            },
        )
        await jm.set_job(
            "ui-test-generate-ok-urls",
            {
                "job_id": "ui-test-generate-ok-urls",
                "type": "generate",
                "status": "completed",
                "queued_at": "t0",
                "result": {
                    "process_key": "pk-g",
                    "validation_file_path": "rev/r.xlsx",
                    "validation_file_url": "https://sp.example/review.xlsx",
                },
            },
        )

    asyncio.run(_seed())
    client = TestClient(create_ui_test_app())

    finalize = client.get("/api/ui/v1/jobs/ui-test-finalize-ok-urls", headers=AUTH).json()
    summary_f = finalize.get("result_summary") or {}
    assert summary_f.get("historical_file_url") == "https://sp.example/hist.xlsx"
    assert summary_f.get("secretary_file_url") == "https://sp.example/sec.xlsx"
    assert "secret_token" not in summary_f

    generate = client.get("/api/ui/v1/jobs/ui-test-generate-ok-urls", headers=AUTH).json()
    summary_g = generate.get("result_summary") or {}
    assert summary_g.get("validation_file_url") == "https://sp.example/review.xlsx"
    assert summary_g.get("validation_file_path") == "rev/r.xlsx"


def test_no_mutation_routes_registered() -> None:
    # /processes/generate es U3-A (existe, gateado por write_deps); el resto de
    # mutaciones (finalize/notify/merge) siguen sin exponerse en la UI.
    client = TestClient(create_ui_test_app())
    for path in (
        "/api/ui/v1/processes/pk/finalize",
        "/api/ui/v1/processes/pk/notify",
        "/api/ui/v1/processes/pk/merge",
    ):
        res = client.post(path, headers=AUTH, json={})
        assert res.status_code in {404, 405}


def test_rejects_client_supplied_sharepoint_path_query() -> None:
    configure_ui_router_for_tests(control_loader=lambda bc: make_snap())
    client = TestClient(create_ui_test_app())
    res = client.get(
        "/api/ui/v1/processes",
        headers=AUTH,
        params={"path": "secret/folder/file.xlsx"},
    )
    assert res.status_code == 400
    assert res.json()["detail"]["error_code"] == "client_path_forbidden"


def test_rejects_graph_url_as_process_key() -> None:
    configure_ui_router_for_tests(control_loader=lambda bc: make_snap())
    client = TestClient(create_ui_test_app())
    res = client.get(
        "/api/ui/v1/processes/https://graph.microsoft.com/v1.0/sites/x",
        headers=AUTH,
    )
    assert res.status_code == 422
    assert res.json()["detail"]["error_code"] == "invalid_process_key"
