"""Cierre UI de NOTIFY_SENDING: incierto, sin éxito, sin retry de envío."""
from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.adapters.primary.http.deps import init_graph_client
from app.adapters.primary.http.ui.router_v1 import (
    configure_ui_router_for_tests,
    reset_ui_router_test_hooks,
)
from app.application.job_manager import JobManager, get_job_manager
from app.application.services.execution_log_hooks import infer_terminal_status_from_result
from app.application.services.generate_queue_service import reset_generate_queue_service_for_tests
from app.application.services.notify_queue_service import reset_notify_queue_service_for_tests
from app.application.ui.feature_flags import reset_ui_fail_closed_log_for_tests
from app.application.ui.job_read import JobReadResult
from app.application.ui.login_rate_limit import reset_login_rate_limiter_for_tests
from app.application.ui.notify_capabilities import (
    compute_notify_availability,
    control_indicates_already_notified,
    control_indicates_notify_mail_uncertain,
)
from app.application.ui.password_hash import hash_password
from app.application.ui.process_projection import (
    PaymentProcessProjectionService,
    ProjectionSources,
    TechnicalJobEvidence,
    derive_operational_status,
    derive_steps_from_control,
)
from app.application.ui.session_repository import (
    InMemorySessionRepository,
    set_session_repository_for_tests,
)
from app.application.use_cases.send_validar_extractos_notification import (
    NOTIFY_SENDING_STEP,
    _notify_sending_marker,
)
from tests.ui_fixtures import make_snap
from tests.ui_test_app import create_ui_test_app

ORIGIN = "https://testserver"
PROCESS_KEY = "payment-validation|banco_bogota|2026-07-30|sending-gap"
OTHER_KEY = "payment-validation|banco_bogota|2026-07-30|other-process"
SANDBOX_EMAIL = "notify-sandbox-only@example.invalid"
_REASON_SNIPPET = "Requiere verificación"


class _MockGraph:
    async def get(self, *args: object, **kwargs: object) -> dict[str, object]:
        return {}

    async def get_bytes(self, *args: object, **kwargs: object) -> bytes:
        return b""

    async def put_bytes(self, *args: object, **kwargs: object) -> dict[str, object]:
        return {}

    async def post_json(
        self, *args: object, **kwargs: object
    ) -> tuple[dict[str, object], int]:
        raise AssertionError("sendMail no debe ejecutarse en el hueco NOTIFY_SENDING")


@pytest.fixture(autouse=True)
def _clean(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PAYMENT_VALIDATION_JOBS_DIR", str(tmp_path / "jobs"))
    monkeypatch.setenv("UI_ENABLED", "true")
    monkeypatch.setenv("UI_WRITE_ENABLED", "true")
    monkeypatch.setenv("UI_NOTIFY_ENABLED", "true")
    monkeypatch.setenv("ACTIVE_ENVIRONMENT", "sandbox")
    monkeypatch.delenv("WEBSITE_INSTANCE_ID", raising=False)
    reset_ui_fail_closed_log_for_tests()
    reset_login_rate_limiter_for_tests()
    reset_ui_router_test_hooks()
    reset_notify_queue_service_for_tests()
    reset_generate_queue_service_for_tests()
    set_session_repository_for_tests(InMemorySessionRepository())
    jm = get_job_manager()
    jm._validation_jobs.clear()
    jm._generate_active = False
    jm._finalize_active = False
    jm._notify_active = False
    jm._jobs_dir = tmp_path / "jobs"
    jm._jobs_dir.mkdir(parents=True, exist_ok=True)
    yield
    reset_ui_router_test_hooks()
    reset_notify_queue_service_for_tests()
    jm._validation_jobs.clear()
    jm._generate_active = False
    jm._finalize_active = False
    jm._notify_active = False


def _sending_snap(**overrides: object):
    base = dict(
        estado_proceso="FINALIZADO",
        is_active=True,
        process_key=PROCESS_KEY,
        bank_code="banco_bogota",
        bank_name="Banco de Bogotá",
        historical_file_path="03 HISTORICO/hist.xlsx",
        email_pdf_path="",
        notify_idempotency_key=_notify_sending_marker(PROCESS_KEY),
        last_completed_step=NOTIFY_SENDING_STEP,
    )
    base.update(overrides)
    return make_snap(**base)


def _enable(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("UI_ENABLED", "true")
    monkeypatch.setenv("UI_WRITE_ENABLED", "true")
    monkeypatch.setenv("UI_NOTIFY_ENABLED", "true")
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
    monkeypatch.setenv("UI_NOTIFY_SANDBOX_TO", SANDBOX_EMAIL)


def _client(monkeypatch: pytest.MonkeyPatch, snap) -> tuple[TestClient, str]:
    _enable(monkeypatch)
    init_graph_client(_MockGraph())  # type: ignore[arg-type]
    configure_ui_router_for_tests(control_loader=lambda _bc: snap)
    client = TestClient(create_ui_test_app(), base_url=ORIGIN)
    assert (
        client.post(
            "/api/ui/v1/auth/login",
            json={"username": "operator", "password": "CorrectHorseBattery!"},
            headers={"Origin": ORIGIN},
        ).status_code
        == 200
    )
    csrf = client.get("/api/ui/v1/auth/csrf", headers={"Origin": ORIGIN}).json()[
        "csrf_token"
    ]
    return client, csrf


def _assert_uncertain_projection(snap, *, jobs=None) -> None:
    assert control_indicates_notify_mail_uncertain(snap) is True
    assert control_indicates_already_notified(snap) is False
    av = compute_notify_availability(
        write_allowed=True,
        notify_enabled=True,
        sandbox=True,
        mutation_active=False,
        snap=snap,
        expected_process_key=PROCESS_KEY,
    )
    assert av.allowed is False
    assert av.reason is not None
    assert _REASON_SNIPPET in av.reason
    assert "ya fue enviado" not in av.reason.lower()
    steps = derive_steps_from_control(snap, jobs=jobs)
    by = {s.name: s for s in steps}
    assert by["notify"].status == "requires_verification"
    assert by["notify"].status != "completed"
    assert by["notify"].status != "sync_pending"
    assert by["notify"].can_retry is False
    assert by["notify"].retry_action is None
    assert derive_operational_status(snap, steps) == "REQUIERE_VERIFICACION"
    detail = PaymentProcessProjectionService().project(
        ProjectionSources(snapshot=snap, jobs=jobs)
    )
    assert detail.operational_status == "REQUIERE_VERIFICACION"
    assert detail.available_actions["notify"].allowed is False
    assert _REASON_SNIPPET in (detail.available_actions["notify"].reason or "")
    assert not any(
        a.code in {"notify", "retry_notify"} and a.enabled for a in detail.next_actions
    )
    assert detail.operational_status != "PENDIENTE_NOTIFICACION"
    assert detail.operational_status != "SINCRONIZANDO"


def test_checkpoint_sending_without_persisted_job_is_uncertain() -> None:
    snap = _sending_snap()
    assert get_job_manager().has_completed_notify(PROCESS_KEY) is False
    _assert_uncertain_projection(snap)


def test_checkpoint_with_notify_mail_uncertain_job_is_not_success() -> None:
    snap = _sending_snap()
    jm = get_job_manager()
    asyncio.run(
        jm.set_job(
            "notify-uncertain",
            {
                "job_id": "notify-uncertain",
                "type": "notify_validar_extractos",
                "status": "completed",
                "process_key": PROCESS_KEY,
                "result": {
                    "status": "notify_mail_uncertain",
                    "process_key": PROCESS_KEY,
                    "merge_control_error_code": "notify_mail_uncertain",
                    "merge_control_warning": "notify_mail_uncertain",
                    "graph_sendmail_http_status": 0,
                },
            },
        )
    )
    assert jm.has_completed_notify(PROCESS_KEY) is False
    assert JobManager._notify_job_succeeded(jm.get_job("notify-uncertain") or {}) is False
    jobs = TechnicalJobEvidence(
        job_manager_by_type={
            "notify": JobReadResult(
                job_id="notify-uncertain",
                store="job_manager",
                payload=jm.get_job("notify-uncertain") or {},
            )
        }
    )
    _assert_uncertain_projection(snap, jobs=jobs)


def test_recycle_keeps_uncertain_and_does_not_treat_job_as_success(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    jobs_dir = tmp_path / "persist"
    jobs_dir.mkdir()
    monkeypatch.setenv("PAYMENT_VALIDATION_JOBS_DIR", str(jobs_dir))
    jm1 = JobManager()
    jm1._jobs_dir = jobs_dir
    jm1._validation_jobs.clear()
    asyncio.run(
        jm1.set_job(
            "persist-uncertain",
            {
                "job_id": "persist-uncertain",
                "type": "notify_validar_extractos",
                "status": "completed",
                "process_key": PROCESS_KEY,
                "finished_at": "2026-07-31T00:00:00Z",
                "result": {
                    "status": "ok",
                    "process_key": PROCESS_KEY,
                    "merge_control_error_code": "notify_mail_uncertain",
                    "graph_sendmail_http_status": 0,
                },
            },
        )
    )
    JobManager._instance = None
    jm2 = JobManager()
    jm2._jobs_dir = jobs_dir
    jm2._validation_jobs.clear()
    jm2._reconcile_persisted_jobs()
    assert jm2.has_completed_notify(PROCESS_KEY) is False
    JobManager._instance = None
    snap = _sending_snap()
    _assert_uncertain_projection(snap)


def test_cta_and_post_blocked_for_sending_checkpoint(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    snap = _sending_snap()
    client, csrf = _client(monkeypatch, snap)
    res = client.post(
        "/api/ui/v1/processes/notify",
        json={"bank_code": "banco_bogota", "process_key": PROCESS_KEY},
        headers={
            "Origin": ORIGIN,
            "Content-Type": "application/json",
            "X-CSRF-Token": csrf,
        },
    )
    assert res.status_code == 409
    body = res.json()["detail"]
    assert body["error_code"] == "notify_mail_uncertain"
    msg = (body.get("user_message") or "").lower()
    assert "verificación" in msg or "duplicados" in msg
    get_res = client.get(
        f"/api/ui/v1/processes/{PROCESS_KEY}",
        headers={"Origin": ORIGIN},
    )
    assert get_res.status_code == 200
    payload = get_res.json()
    assert payload["operational_status"] == "REQUIERE_VERIFICACION"
    assert payload["available_actions"]["notify"]["allowed"] is False
    notify_step = next(s for s in payload["steps"] if s["name"] == "notify")
    assert notify_step["status"] == "requires_verification"
    assert notify_step["can_retry"] is False


def test_sending_marker_of_other_process_does_not_block_current() -> None:
    snap = make_snap(
        estado_proceso="FINALIZADO",
        is_active=True,
        process_key=PROCESS_KEY,
        bank_code="banco_bogota",
        historical_file_path="03 HISTORICO/hist.xlsx",
        notify_idempotency_key=_notify_sending_marker(OTHER_KEY),
        last_completed_step="",
    )
    assert control_indicates_notify_mail_uncertain(snap) is False
    av = compute_notify_availability(
        write_allowed=True,
        notify_enabled=True,
        sandbox=True,
        mutation_active=False,
        snap=snap,
        expected_process_key=PROCESS_KEY,
    )
    assert av.allowed is True


def test_infer_terminal_notify_mail_uncertain_is_not_succeeded() -> None:
    assert (
        infer_terminal_status_from_result(
            {
                "status": "ok",
                "merge_control_error_code": "notify_mail_uncertain",
            }
        )
        == "BLOCKED"
    )
    assert (
        infer_terminal_status_from_result({"status": "notify_mail_uncertain"})
        == "BLOCKED"
    )


def test_last_completed_step_alone_is_uncertain() -> None:
    snap = _sending_snap(notify_idempotency_key="")
    assert snap.last_completed_step == NOTIFY_SENDING_STEP
    _assert_uncertain_projection(snap)
