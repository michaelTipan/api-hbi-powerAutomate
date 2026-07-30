"""Tests U3-A: POST /api/ui/v1/processes/generate y GET /api/ui/v1/banks.

Cubre: identidad de JobManager entre PA y UI, reutilización de
GenerateQueueService (sin duplicar cableado ni tocar helpers privados de PA),
available_actions sin efectos de lock, y los caminos 202/409/422 del endpoint.
"""
from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.adapters.primary.http.deps import init_graph_client
from app.adapters.primary.http.ui.router_v1 import reset_ui_router_test_hooks
from app.application.job_manager import JobManager, get_job_manager
from app.application.services import generate_queue_service as generate_queue_service_module
from app.application.services.generate_queue_service import (
    get_generate_queue_service,
    reset_generate_queue_service_for_tests,
)
from app.application.ui.feature_flags import reset_ui_fail_closed_log_for_tests
from app.application.ui.login_rate_limit import reset_login_rate_limiter_for_tests
from app.application.ui.password_hash import hash_password
from app.application.ui.session_repository import (
    InMemorySessionRepository,
    set_session_repository_for_tests,
)
from tests.ui_test_app import create_ui_test_app

REPO_ROOT = Path(__file__).resolve().parents[1]
ORIGIN = "https://testserver"


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


def _enable_local(monkeypatch: pytest.MonkeyPatch, *, write_enabled: bool = True) -> None:
    encoded = hash_password("CorrectHorseBattery!")
    monkeypatch.setenv("UI_ENABLED", "true")
    monkeypatch.setenv("UI_WRITE_ENABLED", "true" if write_enabled else "false")
    monkeypatch.setenv("UI_AUTH_MODE", "local_session")
    monkeypatch.setenv("ACTIVE_ENVIRONMENT", "sandbox")
    monkeypatch.setenv("UI_LOCAL_USERNAME", "operator")
    monkeypatch.setenv("UI_LOCAL_PASSWORD_HASH", encoded)
    monkeypatch.setenv("UI_LOCAL_ROLE", "operator")
    monkeypatch.setenv("UI_SESSION_TTL_MINUTES", "480")
    monkeypatch.setenv("UI_SESSION_IDLE_MINUTES", "60")
    monkeypatch.setenv("UI_LOGIN_MAX_ATTEMPTS", "5")
    monkeypatch.setenv("UI_LOGIN_WINDOW_SECONDS", "900")
    monkeypatch.setenv("UI_COOKIE_SECURE", "true")
    monkeypatch.setenv("UI_COOKIE_HTTPONLY", "true")
    monkeypatch.setenv("UI_COOKIE_SAMESITE", "strict")
    monkeypatch.setenv("UI_ALLOWED_ORIGINS", ORIGIN)
    monkeypatch.delenv("WEBSITE_INSTANCE_ID", raising=False)
    monkeypatch.delenv("WEBSITE_SITE_NAME", raising=False)


@pytest.fixture(autouse=True)
def _cleanup() -> None:
    reset_ui_router_test_hooks()
    reset_ui_fail_closed_log_for_tests()
    reset_login_rate_limiter_for_tests()
    set_session_repository_for_tests(InMemorySessionRepository())
    reset_generate_queue_service_for_tests()
    jm = JobManager()
    jm._validation_jobs.clear()
    jm._generate_active = False
    jm._finalize_active = False
    init_graph_client(_MockGraph())  # type: ignore[arg-type]
    yield
    reset_login_rate_limiter_for_tests()
    set_session_repository_for_tests(None)
    reset_generate_queue_service_for_tests()
    jm._validation_jobs.clear()
    jm._generate_active = False
    jm._finalize_active = False
    init_graph_client(_MockGraph())  # type: ignore[arg-type]


def _client_with_session(monkeypatch: pytest.MonkeyPatch, *, write_enabled: bool = True) -> tuple[TestClient, str]:
    _enable_local(monkeypatch, write_enabled=write_enabled)
    client = TestClient(create_ui_test_app(), base_url="https://testserver")
    res = client.post(
        "/api/ui/v1/auth/login",
        json={"username": "operator", "password": "CorrectHorseBattery!"},
        headers={"Origin": ORIGIN},
    )
    assert res.status_code == 200, res.text
    csrf = client.get("/api/ui/v1/auth/csrf", headers={"Origin": ORIGIN}).json()["csrf_token"]
    return client, csrf


def _generate_headers(csrf: str) -> dict[str, str]:
    return {
        "Origin": ORIGIN,
        "Content-Type": "application/json",
        "X-CSRF-Token": csrf,
    }


# ─── Identidad / no-duplicación de cableado PA↔UI ──────────────────────────


def test_pa_ui_share_same_job_manager_identity() -> None:
    assert get_job_manager() is JobManager()
    svc = get_generate_queue_service()
    assert svc.job_manager is get_job_manager()


def test_both_routers_use_generate_queue_service() -> None:
    pa_src = (REPO_ROOT / "app/adapters/primary/http/routers/payment_validation.py").read_text(
        encoding="utf-8"
    )
    ui_src = (REPO_ROOT / "app/adapters/primary/http/ui/router_v1.py").read_text(encoding="utf-8")
    assert "get_generate_queue_service" in pa_src
    assert "get_generate_queue_service" in ui_src
    assert "from app.application.services.generate_queue_service import" in pa_src
    assert "from app.application.services.generate_queue_service import" in ui_src
    # Generate/Finalize delegan en colas compartidas. Cancel (PA) sí usa
    # try_start_generate como mutex propio; la UI no debe usarlo.
    assert "try_start_generate" not in ui_src
    # El único try_start_generate del router PA debe vivir en cancel-active-process.
    assert pa_src.count("try_start_generate") == 1
    assert "cancel-active-process" in pa_src


def test_ui_does_not_import_payment_validation_private_helpers() -> None:
    ui_src = (REPO_ROOT / "app/adapters/primary/http/ui/router_v1.py").read_text(encoding="utf-8")
    # No importa el router PA (ni ninguno de sus helpers privados de cola);
    # solo casos de uso compartidos (payment_validation_process_control /
    # generate_queue_service), que no viven en el router PA.
    assert "adapters.primary.http.routers" not in ui_src
    assert "_run_generate_job" not in ui_src
    assert "_run_finalize_job" not in ui_src
    assert "_run_amortization" not in ui_src


# ─── available_actions / GET /banks ─────────────────────────────────────────


def test_available_actions_no_side_effects_on_locks(monkeypatch: pytest.MonkeyPatch) -> None:
    client, _csrf = _client_with_session(monkeypatch)
    jm = get_job_manager()
    assert jm.is_generate_or_finalize_active() is False

    first = client.get("/api/ui/v1/banks", headers={"Origin": ORIGIN})
    assert first.status_code == 200
    second = client.get("/api/ui/v1/banks", headers={"Origin": ORIGIN})
    assert second.status_code == 200

    # GET /banks es de solo lectura: el lock nunca quedó tomado.
    assert jm.is_generate_or_finalize_active() is False
    assert jm.try_start_generate() is True
    jm.finish_generate()

    bodies = {item["bank_code"]: item for item in first.json()}
    assert set(bodies) == {"banco_bogota", "banco_bancolombia"}
    for item in bodies.values():
        assert item["available_actions"]["generate"]["allowed"] is True


def test_available_actions_reflect_write_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    client, _csrf = _client_with_session(monkeypatch, write_enabled=False)
    res = client.get("/api/ui/v1/banks", headers={"Origin": ORIGIN})
    assert res.status_code == 200
    for item in res.json():
        assert item["available_actions"]["generate"]["allowed"] is False
        assert item["available_actions"]["generate"]["reason"]


def test_available_actions_reflect_active_lock(monkeypatch: pytest.MonkeyPatch) -> None:
    client, _csrf = _client_with_session(monkeypatch)
    jm = get_job_manager()
    assert jm.try_start_generate() is True
    try:
        res = client.get("/api/ui/v1/banks", headers={"Origin": ORIGIN})
        assert res.status_code == 200
        for item in res.json():
            assert item["available_actions"]["generate"]["allowed"] is False
    finally:
        jm.finish_generate()


# ─── POST /processes/generate ───────────────────────────────────────────────


def test_generate_accepted_returns_202_without_process_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _fake_generate(graph, process_date, *, bank_code, job_id):
        return {"process_key": f"payment-validation|{bank_code}|x", "status": "ok"}

    monkeypatch.setattr(
        generate_queue_service_module, "generate_payment_validation", _fake_generate
    )

    client, csrf = _client_with_session(monkeypatch)
    res = client.post(
        "/api/ui/v1/processes/generate",
        json={"bank_code": "banco_bogota"},
        headers=_generate_headers(csrf),
    )
    assert res.status_code == 202, res.text
    body = res.json()
    assert body["accepted"] is True
    assert body["action"] == "generate"
    assert body["bank_code"] == "banco_bogota"
    assert body["status"] == "queued"
    assert body["job_id"]
    assert body["poll_url"] == f"/api/ui/v1/jobs/{body['job_id']}"
    assert "process_key" not in body

    # El job quedó registrado en el JobManager compartido con auditoría web_ui.
    job = get_job_manager().get_job(body["job_id"])
    assert job is not None
    assert job.get("trigger_source") == "web_ui"
    assert job.get("requested_by") == "operator"
    assert job.get("ui_request_id")


def test_generate_409_when_lock_held(monkeypatch: pytest.MonkeyPatch) -> None:
    client, csrf = _client_with_session(monkeypatch)
    jm = get_job_manager()
    assert jm.try_start_generate() is True
    try:
        res = client.post(
            "/api/ui/v1/processes/generate",
            json={"bank_code": "banco_bogota"},
            headers=_generate_headers(csrf),
        )
        assert res.status_code == 409
        assert res.json()["detail"]["error_code"] == "generate_busy"
    finally:
        jm.finish_generate()


def test_generate_invalid_bank_code_returns_422(monkeypatch: pytest.MonkeyPatch) -> None:
    client, csrf = _client_with_session(monkeypatch)
    res = client.post(
        "/api/ui/v1/processes/generate",
        json={"bank_code": "banco_inventado"},
        headers=_generate_headers(csrf),
    )
    assert res.status_code == 422


def test_pa_generate_lock_blocks_ui_generate(monkeypatch: pytest.MonkeyPatch) -> None:
    """PA activo (lock tomado directamente en JobManager) → UI recibe 409."""
    client, csrf = _client_with_session(monkeypatch)
    jm = get_job_manager()
    assert jm.try_start_generate() is True  # simula queue_generate de PA en curso
    try:
        res = client.post(
            "/api/ui/v1/processes/generate",
            json={"bank_code": "banco_bancolombia"},
            headers=_generate_headers(csrf),
        )
        assert res.status_code == 409
    finally:
        jm.finish_generate()
