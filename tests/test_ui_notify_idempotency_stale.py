"""Regresión incidente U3-C1: segundo Notify tras éxito con control stale.

Reproduce: Notify #1 completed → proyección/control aún FINALIZADO → segundo POST
no debe crear job ni sendMail ni PDF.
"""
from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import BackgroundTasks
from fastapi.testclient import TestClient

from app.adapters.primary.http.deps import init_graph_client
from app.adapters.primary.http.routers.sharepoint import router as sharepoint_router
from app.adapters.primary.http.ui.router_v1 import (
    configure_ui_router_for_tests,
    reset_ui_router_test_hooks,
)
from app.application.job_manager import JobManager, get_job_manager
from app.application.services import notify_queue_service as notify_queue_module
from app.application.services.generate_queue_service import reset_generate_queue_service_for_tests
from app.application.services.notify_queue_service import (
    NotifyAlreadyNotifiedError,
    NotifyQueueBusyError,
    NotifyQueueService,
    get_notify_queue_service,
    reset_notify_queue_service_for_tests,
)
from app.application.ui.feature_flags import reset_ui_fail_closed_log_for_tests
from app.application.ui.login_rate_limit import reset_login_rate_limiter_for_tests
from app.application.ui.notify_capabilities import compute_notify_availability
from app.application.ui.password_hash import hash_password
from app.application.ui.session_repository import (
    InMemorySessionRepository,
    set_session_repository_for_tests,
)
from tests.ui_fixtures import make_snap
from tests.ui_test_app import create_ui_test_app

ORIGIN = "https://testserver"
PROCESS_KEY = "payment-validation|banco_bogota|2026-07-30|stale-incident"
OTHER_KEY = "payment-validation|banco_bogota|2026-07-30|other-process"
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


@pytest.fixture(autouse=True)
def _clean_notify_state(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PAYMENT_VALIDATION_JOBS_DIR", str(tmp_path / "jobs"))
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


def _ready_snap(**overrides: object):
    base = dict(
        estado_proceso="FINALIZADO",
        is_active=True,
        process_key=PROCESS_KEY,
        bank_code="banco_bogota",
        bank_name="Banco de Bogotá",
        historical_file_path="03 HISTORICO/hist.xlsx",
        email_pdf_path="",
        notify_idempotency_key="",
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
    monkeypatch.delenv("UI_NOTIFY_SANDBOX_CC", raising=False)


def _client(monkeypatch: pytest.MonkeyPatch, snap=_ready_snap()) -> tuple[TestClient, str]:
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


def _headers(csrf: str) -> dict[str, str]:
    return {
        "Origin": ORIGIN,
        "Content-Type": "application/json",
        "X-CSRF-Token": csrf,
    }


def _success_result(**overrides: object) -> SimpleNamespace:
    base = dict(
        report_date="2026-07-30",
        historico_excel_path="03 HISTORICO/hist.xlsx",
        historical_file_path="03 HISTORICO/hist.xlsx",
        historical_file_source="explicit",
        rows_included=1,
        subject="Prueba",
        attachments_count=0,
        graph_sendmail_http_status=202,
        mail_sender="sender@example.invalid",
        mail_to=SANDBOX_EMAIL,
        merge_control_error_code=None,
        bank_code="banco_bogota",
        bank_name="Banco de Bogotá",
        process_key=PROCESS_KEY,
        email_pdf_path="04 CORREOS ENVIADOS/ABONOS.pdf",
        email_pdf_error=None,
        merge_control_updated=True,
        merge_control_file_path="control.xlsx",
        merge_control_status="PENDIENTE_ASIENTOS",
        merge_control_warning=None,
        bank_email_label="BANCO BOGOTA",
        bank_code_source="control",
        process_control_file_path="control.xlsx",
        process_control_estado="PENDIENTE_ASIENTOS",
        payment_groups_included=1,
        abono_groups_included=0,
        abono_credit_rows_included=0,
        extracts_attached_count=0,
        extracts_not_required_count=0,
        movement_groups_included=1,
    )
    base.update(overrides)
    return SimpleNamespace(**base)


def test_incident_stale_control_second_post_already_notified(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Incidente exacto: control stale FINALIZADO + JM completed → 409, 0 segundo send."""
    send_calls = 0

    async def _fake_send(graph: object, **kwargs: object) -> SimpleNamespace:
        nonlocal send_calls
        send_calls += 1
        return _success_result()

    monkeypatch.setattr(
        notify_queue_module, "send_validar_extractos_notification_email", _fake_send
    )

    # Control permanece FINALIZADO (stale) en toda la prueba.
    stale = _ready_snap(estado_proceso="FINALIZADO")
    client, csrf = _client(monkeypatch, snap=stale)

    first = client.post(
        "/api/ui/v1/processes/notify",
        json={"bank_code": "banco_bogota", "process_key": PROCESS_KEY},
        headers=_headers(csrf),
    )
    assert first.status_code == 202, first.text
    job_id = first.json()["job_id"]

    # Ejecutar background del TestClient no corre add_task automáticamente en todos
    # los casos; forzar vía servicio si el job quedó queued.
    jm = get_job_manager()
    job = jm.get_job(job_id)
    assert job is not None
    if job["status"] == "queued":
        # El TestClient suele ejecutar tasks; si no, marcar completed como el incidente.
        asyncio.run(
            jm.set_job(
                job_id,
                {
                    "status": "completed",
                    "process_key": PROCESS_KEY,
                    "type": "notify_validar_extractos",
                    "finished_at": "2026-07-31T00:00:00-05:00",
                    "result": {
                        "status": "ok",
                        "process_key": PROCESS_KEY,
                        "graph_sendmail_http_status": 202,
                        "email_pdf_path": "04 CORREOS ENVIADOS/ABONOS.pdf",
                        "merge_control_status": "PENDIENTE_ASIENTOS",
                    },
                    "error": None,
                },
            )
        )
        jm.finish_notify()
        send_calls = 1  # simula el envío del job #1

    # Esperar a completed real si el runner corrió.
    for _ in range(50):
        job = jm.get_job(job_id)
        assert job is not None
        if job["status"] in ("completed", "failed"):
            break
        asyncio.run(asyncio.sleep(0.02))
    job = jm.get_job(job_id)
    assert job is not None
    if job["status"] == "completed" and send_calls == 0:
        # runner ejecutó fake_send
        pass
    assert jm.has_completed_notify(PROCESS_KEY) is True

    # Proyección con control stale: Notify bloqueado por evidencia JM.
    av = compute_notify_availability(
        write_allowed=True,
        notify_enabled=True,
        sandbox=True,
        sandbox_recipients_configured=True,
        mutation_active=False,
        snap=stale,
        expected_process_key=PROCESS_KEY,
    )
    assert av.allowed is False
    assert "ya fue enviado" in (av.reason or "").lower()

    jobs_before = len(jm._validation_jobs)
    second = client.post(
        "/api/ui/v1/processes/notify",
        json={"bank_code": "banco_bogota", "process_key": PROCESS_KEY},
        headers=_headers(csrf),
    )
    assert second.status_code == 409, second.text
    assert second.json()["detail"]["error_code"] == "already_notified"
    assert "ya fue enviado" in second.json()["detail"]["user_message"].lower()
    assert len(jm._validation_jobs) == jobs_before
    # No segundo sendMail (send_calls no crece tras el 409).
    assert send_calls <= 1


def test_failed_notify_allows_retry(monkeypatch: pytest.MonkeyPatch) -> None:
    jm = get_job_manager()
    asyncio.run(
        jm.set_job(
            "failed-notify-1",
            {
                "job_id": "failed-notify-1",
                "type": "notify_validar_extractos",
                "status": "failed",
                "process_key": PROCESS_KEY,
                "result": None,
                "error": {"type": "ValueError", "message": "boom"},
            },
        )
    )
    assert jm.has_completed_notify(PROCESS_KEY) is False
    av = compute_notify_availability(
        write_allowed=True,
        notify_enabled=True,
        sandbox=True,
        sandbox_recipients_configured=True,
        mutation_active=False,
        snap=_ready_snap(),
        expected_process_key=PROCESS_KEY,
    )
    assert av.allowed is True


def test_other_process_key_not_blocked(monkeypatch: pytest.MonkeyPatch) -> None:
    jm = get_job_manager()
    asyncio.run(
        jm.set_job(
            "ok-other",
            {
                "job_id": "ok-other",
                "type": "notify_validar_extractos",
                "status": "completed",
                "process_key": OTHER_KEY,
                "finished_at": "2026-07-31T00:00:00Z",
                "result": {"status": "ok", "process_key": OTHER_KEY},
            },
        )
    )
    assert jm.has_completed_notify(OTHER_KEY) is True
    assert jm.has_completed_notify(PROCESS_KEY) is False
    av = compute_notify_availability(
        write_allowed=True,
        notify_enabled=True,
        sandbox=True,
        sandbox_recipients_configured=True,
        mutation_active=False,
        snap=_ready_snap(),
        expected_process_key=PROCESS_KEY,
    )
    assert av.allowed is True


def test_stale_notify_key_from_previous_process_allows_notify() -> None:
    """U4-RC: NotifyIdempotencyKey de un lote anterior no bloquea el nuevo ProcessKey."""
    from app.application.ui.notify_capabilities import control_indicates_already_notified
    from app.application.ui.process_projection import (
        derive_operational_status,
        derive_steps_from_control,
    )

    snap = _ready_snap(
        estado_proceso="FINALIZADO",
        process_key=PROCESS_KEY,
        notify_idempotency_key=OTHER_KEY,
        email_pdf_path="04 CORREOS/old.pdf",
        merge_idempotency_key=OTHER_KEY,
        merge_manifest_path="manifest_old.json",
    )
    assert control_indicates_already_notified(snap) is False
    av = compute_notify_availability(
        write_allowed=True,
        notify_enabled=True,
        sandbox=True,
        sandbox_recipients_configured=True,
        mutation_active=False,
        snap=snap,
        expected_process_key=PROCESS_KEY,
    )
    assert av.allowed is True
    steps = derive_steps_from_control(snap)
    by_name = {s.name: s for s in steps}
    assert by_name["notify"].status == "not_started"
    assert by_name["merge"].status != "completed"
    assert derive_operational_status(snap, steps) == "PENDIENTE_NOTIFICACION"


def test_running_notify_is_busy_not_already(monkeypatch: pytest.MonkeyPatch) -> None:
    service = NotifyQueueService(get_job_manager())

    async def _run() -> None:
        first = await service.enqueue(
            graph=_MockGraph(),
            background_tasks=BackgroundTasks(),
            process_key=PROCESS_KEY,
            bank_code="banco_bogota",
        )
        assert first.status == "queued"
        with pytest.raises(NotifyQueueBusyError):
            await service.enqueue(
                graph=_MockGraph(),
                background_tasks=BackgroundTasks(),
                process_key=PROCESS_KEY,
                bank_code="banco_bogota",
            )

    try:
        asyncio.run(_run())
    finally:
        get_job_manager().finish_notify()


def test_control_pendiente_asientos_blocks(monkeypatch: pytest.MonkeyPatch) -> None:
    snap = _ready_snap(
        estado_proceso="PENDIENTE_ASIENTOS",
        email_pdf_path="04 CORREOS/x.pdf",
        notify_idempotency_key=PROCESS_KEY,
    )
    av = compute_notify_availability(
        write_allowed=True,
        notify_enabled=True,
        sandbox=True,
        sandbox_recipients_configured=True,
        mutation_active=False,
        snap=snap,
        expected_process_key=PROCESS_KEY,
    )
    assert av.allowed is False
    client, csrf = _client(monkeypatch, snap=snap)
    res = client.post(
        "/api/ui/v1/processes/notify",
        json={"bank_code": "banco_bogota", "process_key": PROCESS_KEY},
        headers=_headers(csrf),
    )
    assert res.status_code == 409
    assert res.json()["detail"]["error_code"] == "already_notified"


def test_notify_idempotency_key_blocks_even_if_estado_finalizado(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    snap = _ready_snap(
        estado_proceso="FINALIZADO",
        email_pdf_path="04 CORREOS/x.pdf",
        notify_idempotency_key=PROCESS_KEY,
    )
    av = compute_notify_availability(
        write_allowed=True,
        notify_enabled=True,
        sandbox=True,
        sandbox_recipients_configured=True,
        mutation_active=False,
        snap=snap,
        expected_process_key=PROCESS_KEY,
    )
    assert av.allowed is False


def test_recycle_preserves_completed_notify_evidence(
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
            "persist-ok",
            {
                "job_id": "persist-ok",
                "type": "notify_validar_extractos",
                "status": "completed",
                "process_key": PROCESS_KEY,
                "finished_at": "2026-07-31T00:00:00Z",
                "result": {
                    "status": "ok",
                    "process_key": PROCESS_KEY,
                    "graph_sendmail_http_status": 202,
                },
            },
        )
    )
    # Simular recycle: nueva instancia leyendo disco.
    JobManager._instance = None
    jm2 = JobManager()
    jm2._jobs_dir = jobs_dir
    jm2._validation_jobs.clear()
    jm2._reconcile_persisted_jobs()
    assert jm2.has_completed_notify(PROCESS_KEY) is True
    JobManager._instance = None


def test_pa_and_ui_share_already_notified(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _fake_send(graph: object, **kwargs: object) -> SimpleNamespace:
        return _success_result()

    monkeypatch.setattr(
        notify_queue_module, "send_validar_extractos_notification_email", _fake_send
    )
    service = get_notify_queue_service()

    async def _seed() -> None:
        tasks = BackgroundTasks()
        accepted = await service.enqueue(
            graph=_MockGraph(),
            background_tasks=tasks,
            process_key=PROCESS_KEY,
            bank_code="banco_bogota",
            trigger_source="web_ui",
        )
        await tasks()
        assert service.job_manager.has_completed_notify(PROCESS_KEY)

    asyncio.run(_seed())

    client, csrf = _client(monkeypatch)
    client.app.include_router(sharepoint_router)
    ui = client.post(
        "/api/ui/v1/processes/notify",
        json={"bank_code": "banco_bogota", "process_key": PROCESS_KEY},
        headers=_headers(csrf),
    )
    assert ui.status_code == 409
    assert ui.json()["detail"]["error_code"] == "already_notified"

    # PA con bank_code: resuelve process_key y también bloquea.
    async def _pa() -> None:
        with pytest.raises(NotifyAlreadyNotifiedError):
            await service.enqueue(
                graph=_MockGraph(),
                background_tasks=BackgroundTasks(),
                bank_code="banco_bogota",
                process_key=PROCESS_KEY,
                trigger_source="power_automate",
            )

    asyncio.run(_pa())


def test_completed_notify_does_not_block_generate_finalize_flags(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    jm = get_job_manager()
    asyncio.run(
        jm.set_job(
            "ok-1",
            {
                "job_id": "ok-1",
                "type": "notify_validar_extractos",
                "status": "completed",
                "process_key": PROCESS_KEY,
                "result": {"status": "ok", "process_key": PROCESS_KEY},
            },
        )
    )
    assert jm.is_generate_or_finalize_active() is False
    assert jm.try_start_generate() is True
    jm.finish_generate()
    assert jm.try_start_finalize() is True
    jm.finish_finalize()
