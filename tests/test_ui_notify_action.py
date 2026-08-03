"""Tests U3-C1: Notify desde UI con gate sandbox y cola compartida PA↔UI."""
from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import BackgroundTasks, FastAPI, HTTPException, Request
from fastapi.testclient import TestClient

from app.adapters.primary.http.deps import init_graph_client
from app.adapters.primary.http.routers.payment_validation import router as pa_router
from app.adapters.primary.http.routers.sharepoint import router as sharepoint_router
from app.adapters.primary.http.ui import write_deps as write_deps_module
from app.adapters.primary.http.ui.router_v1 import (
    configure_ui_router_for_tests,
    reset_ui_router_test_hooks,
)
from app.adapters.primary.http.ui.write_deps import require_write_access
from app.application.job_manager import JobManager, get_job_manager
from app.application.services import notify_queue_service as notify_queue_module
from app.application.services.generate_queue_service import reset_generate_queue_service_for_tests
from app.application.services.notify_queue_service import (
    NotifyQueueService,
    get_notify_queue_service,
    reset_notify_queue_service_for_tests,
)
from app.application.ui.feature_flags import (
    get_ui_feature_flags,
    reset_ui_fail_closed_log_for_tests,
)
from app.application.ui.login_rate_limit import reset_login_rate_limiter_for_tests
from app.application.ui.local_auth import AuthenticatedLocalUser
from app.application.ui.password_hash import hash_password
from app.application.ui.session_repository import (
    InMemorySessionRepository,
    set_session_repository_for_tests,
)
from tests.ui_fixtures import make_snap
from tests.ui_test_app import create_ui_test_app

REPO_ROOT = Path(__file__).resolve().parents[1]
ORIGIN = "https://testserver"
PROCESS_KEY = "payment-validation|banco_bogota|2026-07-30|notify-test"
SANDBOX_EMAIL = "notify-sandbox-only@example.invalid"


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
    notify_enabled: bool = True,
    sandbox_to: str | None = SANDBOX_EMAIL,
) -> None:
    monkeypatch.setenv("UI_ENABLED", "true")
    monkeypatch.setenv("UI_WRITE_ENABLED", "true")
    monkeypatch.setenv("UI_NOTIFY_ENABLED", "true" if notify_enabled else "false")
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
    if sandbox_to is None:
        monkeypatch.delenv("UI_NOTIFY_SANDBOX_TO", raising=False)
    else:
        monkeypatch.setenv("UI_NOTIFY_SANDBOX_TO", sandbox_to)
    monkeypatch.delenv("UI_NOTIFY_SANDBOX_CC", raising=False)
    monkeypatch.delenv("WEBSITE_INSTANCE_ID", raising=False)
    monkeypatch.delenv("WEBSITE_SITE_NAME", raising=False)


@pytest.fixture(autouse=True)
def _cleanup() -> None:
    reset_ui_router_test_hooks()
    reset_ui_fail_closed_log_for_tests()
    reset_login_rate_limiter_for_tests()
    set_session_repository_for_tests(InMemorySessionRepository())
    reset_generate_queue_service_for_tests()
    reset_notify_queue_service_for_tests()
    jm = get_job_manager()
    jm._validation_jobs.clear()
    jm._generate_active = False
    jm._finalize_active = False
    jm._notify_active = False
    jm._merge_active = False
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
    reset_notify_queue_service_for_tests()
    jm._validation_jobs.clear()
    jm._generate_active = False
    jm._finalize_active = False
    jm._notify_active = False
    jm._merge_active = False
    try:
        if jm._jobs_dir.is_dir():
            for path in jm._jobs_dir.glob("*.json"):
                path.unlink(missing_ok=True)
    except OSError:
        pass


def _ready_snap(**overrides: object):
    base = {
        "bank_code": "banco_bogota",
        "bank_name": "Banco de Bogotá",
        "process_key": PROCESS_KEY,
        "process_id": "notify-test",
        "estado_proceso": "FINALIZADO",
        "is_active": True,
        "historical_file_path": "02 HISTORICO/historico_banco_bogota.xlsx",
    }
    base.update(overrides)
    return make_snap(**base)


def _client_with_session(
    monkeypatch: pytest.MonkeyPatch,
    *,
    notify_enabled: bool = True,
    sandbox_to: str | None = SANDBOX_EMAIL,
    snap=None,
) -> tuple[TestClient, str]:
    _enable_local(
        monkeypatch, notify_enabled=notify_enabled, sandbox_to=sandbox_to
    )
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


def _combined_app() -> FastAPI:
    app = create_ui_test_app()
    app.include_router(pa_router)
    app.include_router(sharepoint_router)
    return app


def _notify_result(*, already_notified: bool = False) -> SimpleNamespace:
    return SimpleNamespace(
        report_date="2026-07-30",
        historico_excel_path="02 HISTORICO/historico.xlsx",
        historical_file_path="02 HISTORICO/historico.xlsx",
        historical_file_source="explicit",
        rows_included=1,
        subject="Prueba",
        attachments_count=0,
        graph_sendmail_http_status=202,
        mail_sender="sender@example.invalid",
        mail_to=SANDBOX_EMAIL,
        merge_control_error_code="already_notified" if already_notified else None,
        bank_code="banco_bogota",
        bank_name="Banco de Bogotá",
        process_key=PROCESS_KEY,
        email_pdf_path=None,
        email_pdf_error=None,
        merge_control_updated=False,
        merge_control_file_path=None,
        merge_control_status=None,
        merge_control_warning=None,
        bank_email_label="",
        bank_code_source="control",
        process_control_file_path="control.xlsx",
        process_control_estado="FINALIZADO",
        payment_groups_included=0,
        abono_groups_included=0,
        abono_credit_rows_included=0,
        extracts_attached_count=0,
        extracts_not_required_count=0,
        movement_groups_included=0,
    )


def test_notify_flag_absent_or_invalid_is_false(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("UI_ENABLED", "true")
    monkeypatch.setenv("UI_WRITE_ENABLED", "true")
    monkeypatch.setenv("UI_AUTH_MODE", "mock")
    monkeypatch.setenv("ACTIVE_ENVIRONMENT", "sandbox")
    monkeypatch.delenv("UI_NOTIFY_ENABLED", raising=False)
    assert get_ui_feature_flags().ui_notify_enabled is False
    monkeypatch.setenv("UI_NOTIFY_ENABLED", "invalid")
    assert get_ui_feature_flags().ui_notify_enabled is False


def test_notify_flag_false_does_not_block_generate_or_finalize(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _enable_local(monkeypatch, notify_enabled=False)
    flags = get_ui_feature_flags()
    assert flags.writes_allowed is True
    assert flags.notify_allowed is False


def test_notify_without_sandbox_to_env_still_accepts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """UI_NOTIFY_SANDBOX_TO vacío ya no bloquea: destinatarios vienen de CORREOS.xlsx."""
    captured: dict[str, object] = {}

    async def _fake_send(graph: object, **kwargs: object) -> SimpleNamespace:
        captured.update(kwargs)
        return _notify_result()

    monkeypatch.setattr(
        notify_queue_module, "send_validar_extractos_notification_email", _fake_send
    )
    client, csrf = _client_with_session(monkeypatch, sandbox_to=None)
    res = client.post(
        "/api/ui/v1/processes/notify",
        json={"bank_code": "banco_bogota", "process_key": PROCESS_KEY},
        headers=_headers(csrf),
    )
    assert res.status_code == 202, res.text
    assert captured.get("to_override") in (None, "")
    assert captured.get("cc_override") in (None, "")


def test_notify_flag_false_blocks_before_lock_job_graph(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    graph = _MockGraph()
    init_graph_client(graph)  # type: ignore[arg-type]
    client, csrf = _client_with_session(monkeypatch, notify_enabled=False)
    jm = get_job_manager()
    res = client.post(
        "/api/ui/v1/processes/notify",
        json={"bank_code": "banco_bogota", "process_key": PROCESS_KEY},
        headers=_headers(csrf),
    )
    assert res.status_code == 403
    assert res.json()["detail"]["error_code"] == "ui_notify_disabled"
    assert not jm.is_notify_active()
    assert not jm._validation_jobs
    assert not graph.calls


def test_ui_notify_uses_correos_path_without_to_override_and_sanitizes_poll(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    async def _fake_send(graph: object, **kwargs: object) -> SimpleNamespace:
        captured.update(kwargs)
        return _notify_result()

    monkeypatch.setattr(
        notify_queue_module, "send_validar_extractos_notification_email", _fake_send
    )
    # Aunque el env TO exista (legacy), la UI no lo inyecta.
    client, csrf = _client_with_session(monkeypatch, sandbox_to=SANDBOX_EMAIL)
    res = client.post(
        "/api/ui/v1/processes/notify",
        json={"bank_code": "banco_bogota", "process_key": PROCESS_KEY},
        headers=_headers(csrf),
    )
    assert res.status_code == 202, res.text
    assert captured.get("to_override") in (None, "")
    assert captured.get("cc_override") in (None, "")
    job = client.get(f"/api/ui/v1/jobs/{res.json()['job_id']}", headers={"Origin": ORIGIN})
    assert job.status_code == 200
    assert job.json()["status"] == "completed"
    assert "mail_to" not in (job.json()["result_summary"] or {})


def test_notify_schema_rejects_client_recipients(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, csrf = _client_with_session(monkeypatch)
    res = client.post(
        "/api/ui/v1/processes/notify",
        json={
            "bank_code": "banco_bogota",
            "process_key": PROCESS_KEY,
            "to": "real@example.com",
            "cc": "real@example.com",
        },
        headers=_headers(csrf),
    )
    assert res.status_code == 422


def test_spa_source_has_no_sandbox_test_email() -> None:
    for path in (REPO_ROOT / "frontend" / "src").rglob("*.[tj]s*"):
        assert SANDBOX_EMAIL not in path.read_text(encoding="utf-8")


def test_notify_requires_session_csrf_and_origin(monkeypatch: pytest.MonkeyPatch) -> None:
    _enable_local(monkeypatch)
    configure_ui_router_for_tests(control_loader=lambda _bc: _ready_snap())
    client = TestClient(create_ui_test_app(), base_url=ORIGIN)
    payload = {"bank_code": "banco_bogota", "process_key": PROCESS_KEY}
    assert client.post("/api/ui/v1/processes/notify", json=payload).status_code == 401
    assert (
        client.post(
            "/api/ui/v1/processes/notify",
            json=payload,
            headers={"X-API-Key": "not-a-session", "Origin": ORIGIN},
        ).status_code
        == 401
    )
    client, csrf = _client_with_session(monkeypatch)
    assert (
        client.post(
            "/api/ui/v1/processes/notify",
            json=payload,
            headers={"Origin": ORIGIN, "Content-Type": "application/json"},
        ).status_code
        == 403
    )
    assert client.post(
        "/api/ui/v1/processes/notify", json=payload, headers=_headers(csrf, origin="")
    ).status_code == 403
    assert client.post(
        "/api/ui/v1/processes/notify",
        json=payload,
        headers=_headers(csrf, origin="https://wrong.example"),
    ).status_code == 403


def test_production_allows_notify_write_gate(monkeypatch: pytest.MonkeyPatch) -> None:
    """production + write flags: require_write_access ya no rechaza por ambiente."""
    _enable_local(monkeypatch)
    monkeypatch.setenv("ACTIVE_ENVIRONMENT", "production")
    monkeypatch.setattr(write_deps_module, "validate_csrf_header", lambda _r, _u: True)
    user = AuthenticatedLocalUser(
        username="operator",
        role="operator",
        auth_mode="local_session",
        expires_at=9999999999,
        token_hash="test-token",
    )
    request = Request(
        {
            "type": "http",
            "method": "POST",
            "scheme": "https",
            "path": "/api/ui/v1/processes/notify",
            "headers": [
                (b"origin", ORIGIN.encode()),
                (b"content-type", b"application/json"),
                (b"x-csrf-token", b"test-csrf"),
            ],
            "server": ("testserver", 443),
        }
    )
    request.state.ui_local_user = user
    got = require_write_access(request)
    assert got.username == "operator"


def test_pa_and_ui_share_notify_service_and_job_manager() -> None:
    pa_src = (REPO_ROOT / "app/adapters/primary/http/routers/sharepoint.py").read_text(
        encoding="utf-8"
    )
    ui_src = (REPO_ROOT / "app/adapters/primary/http/ui/router_v1.py").read_text(
        encoding="utf-8"
    )
    assert "get_notify_queue_service" in pa_src
    assert "get_notify_queue_service" in ui_src
    assert get_notify_queue_service().job_manager is get_job_manager()


def test_pa_contract_and_poll_use_job_manager(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _fake_send(graph: object, **kwargs: object) -> SimpleNamespace:
        return _notify_result()

    monkeypatch.setattr(
        notify_queue_module, "send_validar_extractos_notification_email", _fake_send
    )
    app = FastAPI()
    app.include_router(sharepoint_router)
    client = TestClient(app)
    res = client.post(
        "/graph/sharepoint/notify-validar-extractos-email",
        json={"bank_code": "banco_bogota", "historical_file_path": "hist.xlsx"},
    )
    assert res.status_code == 202
    assert set(res.json()) == {
        "status",
        "job_id",
        "estimated_processing_seconds",
        "message",
    }
    poll = client.get(
        f"/graph/sharepoint/notify-validar-extractos-email/jobs/{res.json()['job_id']}"
    )
    assert poll.status_code == 200
    assert get_job_manager().get_job(res.json()["job_id"]) is not None


def test_reconcile_marks_orphan_notify_job_failed(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("PAYMENT_VALIDATION_JOBS_DIR", str(tmp_path))
    job_path = tmp_path / "orphan-notify.json"
    job_path.write_text(
        '{"job_id":"orphan-notify","status":"running","type":"notify_validar_extractos"}',
        encoding="utf-8",
    )
    jm = JobManager()
    jm._jobs_dir = tmp_path
    jm._validation_jobs.clear()
    jm._reconcile_persisted_jobs()
    job = jm.get_job("orphan-notify")
    assert job is not None
    assert job["status"] == "failed"
    assert job["error"]["type"] == "JobInterruptedByProcessRestart"


def test_notify_double_click_creates_one_job() -> None:
    service = NotifyQueueService(JobManager())

    async def _run() -> None:
        first = await service.enqueue(
            graph=_MockGraph(),
            background_tasks=BackgroundTasks(),
            trigger_source="web_ui",
        )
        with pytest.raises(notify_queue_module.NotifyQueueBusyError):
            await service.enqueue(
                graph=_MockGraph(),
                background_tasks=BackgroundTasks(),
                trigger_source="web_ui",
            )
        assert len(service.job_manager._validation_jobs) == 1
        assert service.job_manager.get_job(first.job_id) is not None

    try:
        asyncio.run(_run())
    finally:
        service.job_manager.finish_notify()


def test_notify_locks_pa_ui_generate_and_finalize(monkeypatch: pytest.MonkeyPatch) -> None:
    client, csrf = _client_with_session(monkeypatch)
    client.app.include_router(sharepoint_router)
    jm = get_job_manager()
    assert jm.try_start_notify()
    try:
        ui = client.post(
            "/api/ui/v1/processes/notify",
            json={"bank_code": "banco_bogota", "process_key": PROCESS_KEY},
            headers=_headers(csrf),
        )
        pa = client.post("/graph/sharepoint/notify-validar-extractos-email", json={})
        assert ui.status_code == 409
        assert pa.status_code == 409
        assert jm.try_start_generate() is False
        assert jm.try_start_finalize() is False
    finally:
        jm.finish_notify()


def test_notify_rejects_wrong_process_or_missing_historical(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, csrf = _client_with_session(monkeypatch)
    wrong = client.post(
        "/api/ui/v1/processes/notify",
        json={"bank_code": "banco_bogota", "process_key": PROCESS_KEY.replace("notify", "other")},
        headers=_headers(csrf),
    )
    assert wrong.status_code == 409
    configure_ui_router_for_tests(
        control_loader=lambda _bc: _ready_snap(historical_file_path="")
    )
    missing = client.post(
        "/api/ui/v1/processes/notify",
        json={"bank_code": "banco_bogota", "process_key": PROCESS_KEY},
        headers=_headers(csrf),
    )
    assert missing.status_code == 409
    assert missing.json()["detail"]["error_code"] == "missing_historical_file_path"


def test_notify_service_only_invokes_notify_use_case() -> None:
    source = (
        REPO_ROOT / "app/application/services/notify_queue_service.py"
    ).read_text(encoding="utf-8").lower()
    for forbidden in (
        "finalize_payment_validation",
        "merge_composite_validado_pdfs",
        "dry_run",
        "apply_",
    ):
        assert forbidden not in source


def test_already_notified_completes_without_second_send(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = 0

    async def _fake_send(graph: object, **kwargs: object) -> SimpleNamespace:
        nonlocal calls
        calls += 1
        return _notify_result(already_notified=True)

    monkeypatch.setattr(
        notify_queue_module, "send_validar_extractos_notification_email", _fake_send
    )
    service = NotifyQueueService(JobManager())

    async def _run() -> None:
        first_tasks = BackgroundTasks()
        first = await service.enqueue(
            graph=_MockGraph(),
            background_tasks=first_tasks,
            process_key=PROCESS_KEY,
            bank_code="banco_bogota",
        )
        await first_tasks()
        first_job = service.job_manager.get_job(first.job_id)
        assert first_job is not None
        assert first_job["status"] == "completed"
        assert first_job["result"]["merge_control_error_code"] == "already_notified"
        assert service.job_manager.has_completed_notify(PROCESS_KEY) is True

        with pytest.raises(notify_queue_module.NotifyAlreadyNotifiedError):
            await service.enqueue(
                graph=_MockGraph(),
                background_tasks=BackgroundTasks(),
                process_key=PROCESS_KEY,
                bank_code="banco_bogota",
            )

    asyncio.run(_run())
    assert calls == 1
