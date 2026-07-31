"""Tests U3-D: Procesar amortización desde la UI (capa API; sin SPA)."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.adapters.primary.http.deps import init_graph_client
from app.adapters.primary.http.ui.router_v1 import (
    configure_ui_router_for_tests,
    reset_ui_router_test_hooks,
)
from app.application.job_manager import get_job_manager
from app.application.services import amortization_queue_service as amortization_queue_module
from app.application.services.amortization_queue_service import (
    AmortizationQueueAccepted,
    reset_amortization_queue_service_for_tests,
)
from app.application.services.generate_queue_service import (
    reset_generate_queue_service_for_tests,
)
from app.application.services.merge_queue_service import (
    reset_merge_queue_service_for_tests,
)
from app.application.ui.amortization_capabilities import (
    compute_amortization_availability,
)
from app.application.ui.amortization_readiness import AmortizationReadiness
from app.application.ui.feature_flags import (
    get_ui_feature_flags,
    reset_ui_fail_closed_log_for_tests,
)
from app.application.ui.login_rate_limit import reset_login_rate_limiter_for_tests
from app.application.ui.password_hash import hash_password
from app.application.ui.session_repository import (
    InMemorySessionRepository,
    set_session_repository_for_tests,
)
from tests.ui_fixtures import make_snap
from tests.ui_test_app import create_ui_test_app

ORIGIN = "https://testserver"
PROCESS_KEY = "payment-validation|banco_bogota|2026-07-30|amortization-test"


class _MockGraph:
    def __init__(self) -> None:
        self.calls: list[str] = []

    async def get(self, *args: object, **kwargs: object) -> dict[str, object]:
        self.calls.append("get")
        return {}

    async def get_bytes(self, *args: object, **kwargs: object) -> bytes:
        self.calls.append("get_bytes")
        return b""

    async def put_bytes(self, *args: object, **kwargs: object) -> dict[str, object]:
        self.calls.append("put_bytes")
        return {}

    async def post_json(
        self, *args: object, **kwargs: object
    ) -> tuple[dict[str, object], int]:
        self.calls.append("post_json")
        return {}, 202


def _enable_local(
    monkeypatch: pytest.MonkeyPatch,
    *,
    amortization_enabled: bool = True,
) -> None:
    monkeypatch.setenv("UI_ENABLED", "true")
    monkeypatch.setenv("UI_WRITE_ENABLED", "true")
    monkeypatch.setenv(
        "UI_AMORTIZATION_ENABLED", "true" if amortization_enabled else "false"
    )
    monkeypatch.setenv("UI_AUTH_MODE", "local_session")
    monkeypatch.setenv("ACTIVE_ENVIRONMENT", "sandbox")
    monkeypatch.setenv("UI_LOCAL_USERNAME", "operator")
    monkeypatch.setenv("UI_LOCAL_PASSWORD_HASH", hash_password("CorrectHorseBattery!"))
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
    reset_merge_queue_service_for_tests()
    reset_amortization_queue_service_for_tests()
    jm = get_job_manager()
    jm._validation_jobs.clear()
    jm._generate_active = False
    jm._finalize_active = False
    jm._notify_active = False
    jm._merge_active = False
    jm._amortization_active = False
    try:
        if jm._jobs_dir.is_dir():
            for path in jm._jobs_dir.glob("*.json"):
                path.unlink(missing_ok=True)
    except OSError:
        pass
    init_graph_client(_MockGraph())  # type: ignore[arg-type]
    yield
    reset_login_rate_limiter_for_tests()
    set_session_repository_for_tests(None)
    reset_generate_queue_service_for_tests()
    reset_merge_queue_service_for_tests()
    reset_amortization_queue_service_for_tests()
    jm._validation_jobs.clear()
    jm._generate_active = False
    jm._finalize_active = False
    jm._notify_active = False
    jm._merge_active = False
    jm._amortization_active = False


def _ready_snap(**overrides: object):
    base = {
        "bank_code": "banco_bogota",
        "bank_name": "Banco de Bogotá",
        "process_key": PROCESS_KEY,
        "process_id": "amortization-test",
        "estado_proceso": "CONSOLIDADO",
        "is_active": True,
        "historical_file_path": "02 HISTORICO/historico_banco_bogota.xlsx",
        "merge_manifest_path": "01 TRAZABILIDAD/merge_manifest.json",
    }
    base.update(overrides)
    return make_snap(**base)


def _client_with_session(
    monkeypatch: pytest.MonkeyPatch,
    *,
    amortization_enabled: bool = True,
    snap=None,
) -> tuple[TestClient, str]:
    _enable_local(monkeypatch, amortization_enabled=amortization_enabled)
    configure_ui_router_for_tests(control_loader=lambda _bc: snap or _ready_snap())
    client = TestClient(create_ui_test_app(), base_url=ORIGIN)
    login = client.post(
        "/api/ui/v1/auth/login",
        json={"username": "operator", "password": "CorrectHorseBattery!"},
        headers={"Origin": ORIGIN},
    )
    assert login.status_code == 200, login.text
    csrf = client.get("/api/ui/v1/auth/csrf", headers={"Origin": ORIGIN}).json()[
        "csrf_token"
    ]
    return client, csrf


def _headers(csrf: str, *, origin: str = ORIGIN) -> dict[str, str]:
    return {
        "Origin": origin,
        "Content-Type": "application/json",
        "X-CSRF-Token": csrf,
    }


def _ready_readiness() -> AmortizationReadiness:
    return AmortizationReadiness(
        status="ready",
        can_start=True,
        expected_items=2,
        ready_items=2,
        checked_at="2026-07-31T00:00:00-05:00",
        user_message="La información está disponible para iniciar la validación y aplicación.",
        next_action="Puede procesar la amortización desde la UI.",
    )


# ─── Flag ────────────────────────────────────────────────────────────────────


def test_amortization_flag_absent_or_invalid_is_false(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("UI_ENABLED", "true")
    monkeypatch.setenv("UI_WRITE_ENABLED", "true")
    monkeypatch.setenv("UI_AUTH_MODE", "mock")
    monkeypatch.setenv("ACTIVE_ENVIRONMENT", "sandbox")
    monkeypatch.delenv("UI_AMORTIZATION_ENABLED", raising=False)
    assert get_ui_feature_flags().ui_amortization_enabled is False
    monkeypatch.setenv("UI_AMORTIZATION_ENABLED", "invalid")
    assert get_ui_feature_flags().ui_amortization_enabled is False


def test_amortization_flag_false_blocks_before_lock(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    graph = _MockGraph()
    init_graph_client(graph)  # type: ignore[arg-type]
    called: list[str] = []

    async def _no_enqueue(*_a: object, **_k: object) -> AmortizationQueueAccepted:
        called.append("enqueue")
        raise AssertionError("enqueue no debe ejecutarse con flag false")

    async def _no_readiness(*_a: object, **_k: object) -> AmortizationReadiness:
        called.append("readiness")
        raise AssertionError("readiness no debe evaluarse con flag false")

    monkeypatch.setattr(
        amortization_queue_module.AmortizationQueueService,
        "enqueue_process_ui",
        _no_enqueue,
    )
    monkeypatch.setattr(
        "app.adapters.primary.http.ui.router_v1.assess_amortization_readiness",
        _no_readiness,
    )
    client, csrf = _client_with_session(monkeypatch, amortization_enabled=False)
    jm = get_job_manager()
    res = client.post(
        "/api/ui/v1/processes/amortization",
        json={"bank_code": "banco_bogota", "process_key": PROCESS_KEY},
        headers=_headers(csrf),
    )
    assert res.status_code == 403
    assert res.json()["detail"]["error_code"] == "ui_amortization_disabled"
    assert not called
    assert not jm.is_amortization_active()
    assert not jm._validation_jobs


def test_bootstrap_exposes_amortization_allowed_false_by_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _enable_local(monkeypatch, amortization_enabled=False)
    client = TestClient(create_ui_test_app(), base_url=ORIGIN)
    res = client.get("/api/ui/v1/bootstrap", headers={"Origin": ORIGIN})
    assert res.status_code == 200
    assert res.json()["amortization_allowed"] is False


def test_bootstrap_exposes_amortization_allowed_true_when_enabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _enable_local(monkeypatch, amortization_enabled=True)
    client = TestClient(create_ui_test_app(), base_url=ORIGIN)
    res = client.get("/api/ui/v1/bootstrap", headers={"Origin": ORIGIN})
    assert res.status_code == 200
    assert res.json()["amortization_allowed"] is True


# ─── Auth / CSRF / Origin ────────────────────────────────────────────────────


def test_amortization_without_session_returns_401(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _enable_local(monkeypatch)
    configure_ui_router_for_tests(control_loader=lambda _bc: _ready_snap())
    client = TestClient(create_ui_test_app(), base_url=ORIGIN)
    res = client.post(
        "/api/ui/v1/processes/amortization",
        json={"bank_code": "banco_bogota", "process_key": PROCESS_KEY},
        headers={"Origin": ORIGIN, "Content-Type": "application/json"},
    )
    assert res.status_code == 401
    assert res.json()["error_code"] == "missing_or_invalid_session"


def test_amortization_invalid_origin_returns_403(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, csrf = _client_with_session(monkeypatch)
    res = client.post(
        "/api/ui/v1/processes/amortization",
        json={"bank_code": "banco_bogota", "process_key": PROCESS_KEY},
        headers=_headers(csrf, origin="https://evil.example"),
    )
    assert res.status_code == 403
    assert res.json()["detail"]["error_code"] == "invalid_origin"


def test_csrf_required_for_amortization(monkeypatch: pytest.MonkeyPatch) -> None:
    client, _csrf = _client_with_session(monkeypatch)
    res = client.post(
        "/api/ui/v1/processes/amortization",
        json={"bank_code": "banco_bogota", "process_key": PROCESS_KEY},
        headers={"Origin": ORIGIN, "Content-Type": "application/json"},
    )
    assert res.status_code == 403
    assert res.json()["detail"]["error_code"] == "invalid_csrf_token"


# ─── Body / schema ───────────────────────────────────────────────────────────


def test_amortization_schema_rejects_extra_fields(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, csrf = _client_with_session(monkeypatch)
    res = client.post(
        "/api/ui/v1/processes/amortization",
        json={
            "bank_code": "banco_bogota",
            "process_key": PROCESS_KEY,
            "force": True,
            "merge_manifest_path": "x/y.json",
            "dry_run": True,
        },
        headers=_headers(csrf),
    )
    assert res.status_code == 422


# ─── Concurrencia / identidad ────────────────────────────────────────────────


def test_amortization_busy_returns_409(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _ready(*_a: object, **_k: object) -> AmortizationReadiness:
        return _ready_readiness()

    monkeypatch.setattr(
        "app.adapters.primary.http.ui.router_v1.assess_amortization_readiness", _ready
    )
    client, csrf = _client_with_session(monkeypatch)
    jm = get_job_manager()
    jm._merge_active = True
    res = client.post(
        "/api/ui/v1/processes/amortization",
        json={"bank_code": "banco_bogota", "process_key": PROCESS_KEY},
        headers=_headers(csrf),
    )
    assert res.status_code == 409
    assert res.json()["detail"]["error_code"] == "amortization_busy"


def test_amortization_already_applied_returns_409(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    snap = _ready_snap(
        estado_proceso="AMORTIZACION_APLICADA",
        apply_idempotency_key=PROCESS_KEY,
    )
    client, csrf = _client_with_session(monkeypatch, snap=snap)
    res = client.post(
        "/api/ui/v1/processes/amortization",
        json={"bank_code": "banco_bogota", "process_key": PROCESS_KEY},
        headers=_headers(csrf),
    )
    assert res.status_code == 409
    assert res.json()["detail"]["error_code"] == "already_applied"


def test_amortization_process_key_mismatch_returns_409(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    snap = _ready_snap(process_key="payment-validation|banco_bogota|2026-07-30|other")
    client, csrf = _client_with_session(monkeypatch, snap=snap)
    res = client.post(
        "/api/ui/v1/processes/amortization",
        json={"bank_code": "banco_bogota", "process_key": PROCESS_KEY},
        headers=_headers(csrf),
    )
    assert res.status_code == 409
    assert res.json()["detail"]["error_code"] == "process_key_mismatch"


def test_amortization_not_ready_returns_409(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _incomplete(*_a: object, **_k: object) -> AmortizationReadiness:
        return AmortizationReadiness(
            status="incomplete",
            can_start=False,
            user_message="Faltan soportes o el manifiesto de consolidación está incompleto.",
            next_action="Complete la consolidación de soportes antes de procesar la amortización.",
        )

    monkeypatch.setattr(
        "app.adapters.primary.http.ui.router_v1.assess_amortization_readiness",
        _incomplete,
    )
    client, csrf = _client_with_session(monkeypatch)
    res = client.post(
        "/api/ui/v1/processes/amortization",
        json={"bank_code": "banco_bogota", "process_key": PROCESS_KEY},
        headers=_headers(csrf),
    )
    assert res.status_code == 409
    assert res.json()["detail"]["error_code"] == "not_ready_for_amortization"


# ─── Happy path ──────────────────────────────────────────────────────────────


def test_amortization_happy_path_enqueue_mocked(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    async def _ready(*_a: object, **_k: object) -> AmortizationReadiness:
        return _ready_readiness()

    async def _fake_enqueue(
        self: object, **kwargs: object
    ) -> AmortizationQueueAccepted:
        captured.update(kwargs)
        return AmortizationQueueAccepted(
            job_id="amortization-job-1",
            bank_code="banco_bogota",
            process_key=PROCESS_KEY,
            status="queued",
        )

    monkeypatch.setattr(
        "app.adapters.primary.http.ui.router_v1.assess_amortization_readiness", _ready
    )
    monkeypatch.setattr(
        amortization_queue_module.AmortizationQueueService,
        "enqueue_process_ui",
        _fake_enqueue,
    )
    client, csrf = _client_with_session(monkeypatch)
    res = client.post(
        "/api/ui/v1/processes/amortization",
        json={"bank_code": "banco_bogota", "process_key": PROCESS_KEY},
        headers=_headers(csrf),
    )
    assert res.status_code == 202, res.text
    body = res.json()
    assert body["accepted"] is True
    assert body["action"] == "amortization"
    assert body["job_id"] == "amortization-job-1"
    assert body["process_key"] == PROCESS_KEY
    assert body["poll_url"] == "/api/ui/v1/jobs/amortization-job-1"
    assert captured.get("bank_code") == "banco_bogota"
    assert captured.get("process_key") == PROCESS_KEY
    assert captured.get("trigger_source") == "web_ui"


# ─── available_actions ───────────────────────────────────────────────────────


def test_available_actions_amortization_ready(monkeypatch: pytest.MonkeyPatch) -> None:
    """compute_amortization_availability(): pura, allowed=True cuando todo está listo."""
    av = compute_amortization_availability(
        write_allowed=True,
        amortization_enabled=True,
        sandbox=True,
        mutation_active=False,
        snap=_ready_snap(),
        expected_process_key=PROCESS_KEY,
        readiness_status="ready",
    )
    assert av.allowed is True
    assert av.reason is None


def test_available_actions_amortization_merge_parcial_blocked() -> None:
    av = compute_amortization_availability(
        write_allowed=True,
        amortization_enabled=True,
        sandbox=True,
        mutation_active=False,
        snap=_ready_snap(estado_proceso="MERGE_PARCIAL"),
        expected_process_key=PROCESS_KEY,
        readiness_status="ready",
    )
    assert av.allowed is False


def test_available_actions_no_dry_run_or_apply_keys(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """La UI solo expone la acción "amortization"; nunca dry_run/apply sueltos."""
    client, _csrf = _client_with_session(monkeypatch, amortization_enabled=False)
    key = PROCESS_KEY.replace("|", "%7C")
    res = client.get(f"/api/ui/v1/processes/{key}", headers={"Origin": ORIGIN})
    assert res.status_code == 200
    body = res.json()
    assert "amortization" in body["available_actions"]
    assert "dry_run" not in body["available_actions"]
    assert "apply" not in body["available_actions"]
