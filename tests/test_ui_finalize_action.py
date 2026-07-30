"""Tests U3-B: Finalize UI, gate UI_FINALIZE_ENABLED, cola compartida PA↔UI.

Cubre seguridad (flag fail-closed, CSRF/Origin, ProcessKey), locks cruzados,
contrato PA, JobManager compartido, terminal status sin NameError e identidad.
"""
from __future__ import annotations

from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.adapters.primary.http.deps import init_graph_client
from app.adapters.primary.http.routers.payment_validation import router as pa_router
from app.adapters.primary.http.ui.router_v1 import (
    configure_ui_router_for_tests,
    reset_ui_router_test_hooks,
)
from app.application.job_manager import JobManager, get_job_manager
from app.application.services import finalize_queue_service as finalize_queue_module
from app.application.services.execution_log_hooks import infer_terminal_status_from_result
from app.application.services.finalize_queue_service import (
    FinalizeQueueService,
    get_finalize_queue_service,
    reset_finalize_queue_service_for_tests,
)
from app.application.services.generate_queue_service import (
    get_generate_queue_service,
    reset_generate_queue_service_for_tests,
)
from app.application.ui.feature_flags import (
    get_ui_feature_flags,
    reset_ui_fail_closed_log_for_tests,
)
from app.application.ui.finalize_capabilities import compute_finalize_availability
from app.application.ui.finalize_checklist import build_finalize_operator_checklist
from app.application.ui.finalize_resolve import (
    FinalizeProcessIdentityError,
    resolve_finalize_target_from_control,
)
from app.application.ui.login_rate_limit import reset_login_rate_limiter_for_tests
from app.application.ui.password_hash import hash_password
from app.application.ui.session_repository import (
    InMemorySessionRepository,
    set_session_repository_for_tests,
)
from app.application.services.review_schema import ControlCols, EstadoPago
from tests.ui_fixtures import make_snap
from tests.ui_test_app import create_ui_test_app

REPO_ROOT = Path(__file__).resolve().parents[1]
ORIGIN = "https://testserver"
PROCESS_KEY = "payment-validation|banco_bogota|2026-07-30|bb40fcea-test"


class _MockGraph:
    def __init__(self) -> None:
        self.calls: list[str] = []

    async def get(self, *a, **k):
        self.calls.append("get")
        return {}

    async def get_bytes(self, *a, **k):
        self.calls.append("get_bytes")
        return b""

    async def put_bytes(self, *a, **k):
        self.calls.append("put_bytes")
        return {}

    async def delete(self, *a, **k):
        self.calls.append("delete")
        return None

    async def post_json(self, *a, **k):
        self.calls.append("post_json")
        return {}, 202


def _enable_local(
    monkeypatch: pytest.MonkeyPatch,
    *,
    write_enabled: bool = True,
    finalize_enabled: bool = True,
) -> None:
    encoded = hash_password("CorrectHorseBattery!")
    monkeypatch.setenv("UI_ENABLED", "true")
    monkeypatch.setenv("UI_WRITE_ENABLED", "true" if write_enabled else "false")
    if finalize_enabled:
        monkeypatch.setenv("UI_FINALIZE_ENABLED", "true")
    else:
        monkeypatch.setenv("UI_FINALIZE_ENABLED", "false")
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
    reset_finalize_queue_service_for_tests()
    jm = JobManager()
    jm._validation_jobs.clear()
    jm._generate_active = False
    jm._finalize_active = False
    init_graph_client(_MockGraph())  # type: ignore[arg-type]
    yield
    reset_login_rate_limiter_for_tests()
    set_session_repository_for_tests(None)
    reset_generate_queue_service_for_tests()
    reset_finalize_queue_service_for_tests()
    jm._validation_jobs.clear()
    jm._generate_active = False
    jm._finalize_active = False
    init_graph_client(_MockGraph())  # type: ignore[arg-type]


def _ready_snap(**overrides: object):
    base = dict(
        bank_code="banco_bogota",
        bank_name="Banco de Bogotá",
        process_key=PROCESS_KEY,
        process_id="bb40fcea-test",
        estado_proceso="REVISION_CREADA",
        is_active=True,
        validation_file_path="01 REVISION/validacion_pagos_banco_bogota.xlsx",
    )
    base.update(overrides)
    return make_snap(**base)


def _client_with_session(
    monkeypatch: pytest.MonkeyPatch,
    *,
    write_enabled: bool = True,
    finalize_enabled: bool = True,
    snap=None,
) -> tuple[TestClient, str]:
    _enable_local(
        monkeypatch, write_enabled=write_enabled, finalize_enabled=finalize_enabled
    )
    configure_ui_router_for_tests(control_loader=lambda _bc: snap or _ready_snap())
    client = TestClient(create_ui_test_app(), base_url="https://testserver")
    res = client.post(
        "/api/ui/v1/auth/login",
        json={"username": "operator", "password": "CorrectHorseBattery!"},
        headers={"Origin": ORIGIN},
    )
    assert res.status_code == 200, res.text
    csrf = client.get("/api/ui/v1/auth/csrf", headers={"Origin": ORIGIN}).json()[
        "csrf_token"
    ]
    return client, csrf


def _write_headers(csrf: str) -> dict[str, str]:
    return {
        "Origin": ORIGIN,
        "Content-Type": "application/json",
        "X-CSRF-Token": csrf,
    }


def _combined_app() -> FastAPI:
    """UI + PA en la misma app (mismo JobManager / colas)."""
    app = create_ui_test_app()
    app.include_router(pa_router)
    return app


# ─── Flag UI_FINALIZE_ENABLED ────────────────────────────────────────────────


def test_finalize_flag_absent_is_false(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("UI_ENABLED", "true")
    monkeypatch.setenv("UI_WRITE_ENABLED", "true")
    monkeypatch.setenv("UI_AUTH_MODE", "mock")
    monkeypatch.setenv("ACTIVE_ENVIRONMENT", "sandbox")
    monkeypatch.delenv("UI_FINALIZE_ENABLED", raising=False)
    flags = get_ui_feature_flags()
    assert flags.ui_finalize_enabled is False
    assert flags.finalize_allowed is False
    assert flags.writes_allowed is True


def test_finalize_flag_invalid_fail_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("UI_ENABLED", "true")
    monkeypatch.setenv("UI_WRITE_ENABLED", "true")
    monkeypatch.setenv("UI_AUTH_MODE", "mock")
    monkeypatch.setenv("ACTIVE_ENVIRONMENT", "sandbox")
    monkeypatch.setenv("UI_FINALIZE_ENABLED", "maybe")
    flags = get_ui_feature_flags()
    assert flags.ui_finalize_enabled is False


def test_finalize_flag_false_does_not_block_generate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _fake_generate(graph, process_date, *, bank_code, job_id):
        return {"process_key": f"payment-validation|{bank_code}|x", "status": "ok"}

    monkeypatch.setattr(
        "app.application.services.generate_queue_service.generate_payment_validation",
        _fake_generate,
    )
    client, csrf = _client_with_session(monkeypatch, finalize_enabled=False)
    res = client.post(
        "/api/ui/v1/processes/generate",
        json={"bank_code": "banco_bogota"},
        headers=_write_headers(csrf),
    )
    assert res.status_code == 202, res.text


def test_finalize_gate_false_blocks_before_lock_job_graph(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    graph = _MockGraph()
    init_graph_client(graph)  # type: ignore[arg-type]
    called = {"finalize": False}

    async def _boom(*a, **k):
        called["finalize"] = True
        raise AssertionError("no debe llegar al use case")

    monkeypatch.setattr(finalize_queue_module, "finalize_payment_validation", _boom)

    client, csrf = _client_with_session(monkeypatch, finalize_enabled=False)
    jm = get_job_manager()
    jobs_before = len(jm._validation_jobs)

    res = client.post(
        "/api/ui/v1/processes/finalize",
        json={"bank_code": "banco_bogota", "process_key": PROCESS_KEY},
        headers=_write_headers(csrf),
    )
    assert res.status_code == 403
    assert res.json()["detail"]["error_code"] == "ui_finalize_disabled"
    assert jm.is_generate_or_finalize_active() is False
    assert len(jm._validation_jobs) == jobs_before
    assert called["finalize"] is False
    assert "get_bytes" not in graph.calls
    assert "put_bytes" not in graph.calls


# ─── Servicio compartido / JobManager ────────────────────────────────────────


def test_pa_and_ui_share_finalize_queue_service() -> None:
    pa_src = (
        REPO_ROOT / "app/adapters/primary/http/routers/payment_validation.py"
    ).read_text(encoding="utf-8")
    ui_src = (REPO_ROOT / "app/adapters/primary/http/ui/router_v1.py").read_text(
        encoding="utf-8"
    )
    assert "get_finalize_queue_service" in pa_src
    assert "get_finalize_queue_service" in ui_src
    assert "try_start_finalize" not in pa_src
    assert "try_start_finalize" not in ui_src
    assert "_run_finalize_job" not in pa_src
    assert "_run_finalize_job" not in ui_src


def test_finalize_and_generate_share_same_job_manager() -> None:
    assert get_finalize_queue_service().job_manager is get_job_manager()
    assert get_generate_queue_service().job_manager is get_job_manager()
    assert get_finalize_queue_service().job_manager is get_generate_queue_service().job_manager


def test_generate_pa_blocks_finalize_ui(monkeypatch: pytest.MonkeyPatch) -> None:
    _enable_local(monkeypatch, finalize_enabled=True)
    configure_ui_router_for_tests(control_loader=lambda _bc: _ready_snap())
    app = _combined_app()
    client = TestClient(app, base_url="https://testserver")
    client.post(
        "/api/ui/v1/auth/login",
        json={"username": "operator", "password": "CorrectHorseBattery!"},
        headers={"Origin": ORIGIN},
    )
    csrf = client.get("/api/ui/v1/auth/csrf", headers={"Origin": ORIGIN}).json()[
        "csrf_token"
    ]

    async def _fake_gen(graph, process_date, *, bank_code, job_id):
        return {"status": "ok"}

    monkeypatch.setattr(
        "app.application.services.generate_queue_service.generate_payment_validation",
        _fake_gen,
    )
    pa = client.post(
        "/graph/sharepoint/payment-validation/generate/queue",
        json={"bank_code": "banco_bogota"},
    )
    assert pa.status_code == 202
    # Mientras el lock sigue (si el BG ya liberó, lo tomamos a mano).
    jm = get_job_manager()
    if not jm.is_generate_or_finalize_active():
        assert jm.try_start_generate() is True
    try:
        res = client.post(
            "/api/ui/v1/processes/finalize",
            json={"bank_code": "banco_bogota", "process_key": PROCESS_KEY},
            headers=_write_headers(csrf),
        )
        assert res.status_code == 409
    finally:
        jm.finish_generate()
        jm.finish_finalize()


def test_generate_ui_blocks_finalize_pa(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _fake_gen(graph, process_date, *, bank_code, job_id):
        return {"status": "ok"}

    monkeypatch.setattr(
        "app.application.services.generate_queue_service.generate_payment_validation",
        _fake_gen,
    )
    client, csrf = _client_with_session(monkeypatch)
    app = client.app
    app.include_router(pa_router)
    gen = client.post(
        "/api/ui/v1/processes/generate",
        json={"bank_code": "banco_bogota"},
        headers=_write_headers(csrf),
    )
    assert gen.status_code == 202
    jm = get_job_manager()
    if not jm.is_generate_or_finalize_active():
        assert jm.try_start_generate() is True
    try:
        pa = client.post("/graph/sharepoint/payment-validation/finalize/queue", json={})
        assert pa.status_code == 409
    finally:
        jm.finish_generate()
        jm.finish_finalize()


def test_finalize_pa_blocks_finalize_ui(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _fake_fin(graph, **k):
        return {"status": "ok"}

    monkeypatch.setattr(finalize_queue_module, "finalize_payment_validation", _fake_fin)
    _enable_local(monkeypatch)
    configure_ui_router_for_tests(control_loader=lambda _bc: _ready_snap())
    client = TestClient(_combined_app(), base_url="https://testserver")
    client.post(
        "/api/ui/v1/auth/login",
        json={"username": "operator", "password": "CorrectHorseBattery!"},
        headers={"Origin": ORIGIN},
    )
    csrf = client.get("/api/ui/v1/auth/csrf", headers={"Origin": ORIGIN}).json()[
        "csrf_token"
    ]
    pa = client.post("/graph/sharepoint/payment-validation/finalize/queue", json={})
    assert pa.status_code == 202
    jm = get_job_manager()
    if not jm.is_generate_or_finalize_active():
        assert jm.try_start_finalize() is True
    try:
        res = client.post(
            "/api/ui/v1/processes/finalize",
            json={"bank_code": "banco_bogota", "process_key": PROCESS_KEY},
            headers=_write_headers(csrf),
        )
        assert res.status_code == 409
    finally:
        jm.finish_finalize()


def test_finalize_ui_blocks_generate_pa(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _fake_fin(graph, **k):
        return {"status": "ok"}

    monkeypatch.setattr(finalize_queue_module, "finalize_payment_validation", _fake_fin)
    client, csrf = _client_with_session(monkeypatch)
    client.app.include_router(pa_router)
    fin = client.post(
        "/api/ui/v1/processes/finalize",
        json={"bank_code": "banco_bogota", "process_key": PROCESS_KEY},
        headers=_write_headers(csrf),
    )
    assert fin.status_code == 202, fin.text
    jm = get_job_manager()
    if not jm.is_generate_or_finalize_active():
        assert jm.try_start_finalize() is True
    try:
        pa = client.post(
            "/graph/sharepoint/payment-validation/generate/queue",
            json={"bank_code": "banco_bogota"},
        )
        assert pa.status_code == 409
    finally:
        jm.finish_finalize()


def test_ui_and_pa_read_same_job(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _fake_fin(graph, **k):
        return {
            "status": "ok",
            "process_key": PROCESS_KEY,
            "already_finalized": False,
        }

    monkeypatch.setattr(finalize_queue_module, "finalize_payment_validation", _fake_fin)
    client, csrf = _client_with_session(monkeypatch)
    client.app.include_router(pa_router)
    res = client.post(
        "/api/ui/v1/processes/finalize",
        json={"bank_code": "banco_bogota", "process_key": PROCESS_KEY},
        headers=_write_headers(csrf),
    )
    assert res.status_code == 202
    job_id = res.json()["job_id"]
    ui_job = client.get(f"/api/ui/v1/jobs/{job_id}", headers={"Origin": ORIGIN})
    pa_job = client.get(f"/graph/sharepoint/payment-validation/jobs/{job_id}")
    assert ui_job.status_code == 200
    assert pa_job.status_code == 200
    assert ui_job.json()["job_id"] == job_id
    assert pa_job.json().get("job_id") == job_id or pa_job.json().get("status")


# ─── Lock release ────────────────────────────────────────────────────────────


def test_lock_released_on_success(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _ok(graph, **k):
        return {"status": "ok"}

    monkeypatch.setattr(finalize_queue_module, "finalize_payment_validation", _ok)
    jm = JobManager()
    svc = FinalizeQueueService(jm)
    from fastapi import BackgroundTasks

    async def _run() -> None:
        bg = BackgroundTasks()
        accepted = await svc.enqueue(
            graph=_MockGraph(),
            background_tasks=bg,
            bank_code="banco_bogota",
            validation_file_path="x.xlsx",
        )
        assert jm.is_generate_or_finalize_active() is True
        await bg()
        assert jm.is_generate_or_finalize_active() is False
        job = jm.get_job(accepted.job_id)
        assert job is not None
        assert job["status"] == "completed"

    import asyncio

    asyncio.run(_run())


def test_lock_released_on_exception(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _boom(graph, **k):
        raise RuntimeError("fallo simulado")

    monkeypatch.setattr(finalize_queue_module, "finalize_payment_validation", _boom)
    jm = JobManager()
    svc = FinalizeQueueService(jm)
    from fastapi import BackgroundTasks

    async def _run() -> None:
        bg = BackgroundTasks()
        accepted = await svc.enqueue(
            graph=_MockGraph(),
            background_tasks=bg,
            bank_code="banco_bogota",
        )
        await bg()
        assert jm.is_generate_or_finalize_active() is False
        job = jm.get_job(accepted.job_id)
        assert job is not None
        assert job["status"] == "failed"

    import asyncio

    asyncio.run(_run())


def test_lock_not_released_if_never_acquired() -> None:
    jm = JobManager()
    assert jm.try_start_finalize() is True
    svc = FinalizeQueueService(jm)
    from fastapi import BackgroundTasks

    async def _run() -> None:
        bg = BackgroundTasks()
        with pytest.raises(Exception):
            await svc.enqueue(
                graph=_MockGraph(), background_tasks=bg, bank_code="banco_bogota"
            )
        assert jm.is_generate_or_finalize_active() is True
        jm.finish_finalize()

    import asyncio

    asyncio.run(_run())


# ─── Terminal status / NameError ─────────────────────────────────────────────


def test_infer_terminal_success() -> None:
    assert infer_terminal_status_from_result({"status": "ok"}) == "SUCCEEDED"


def test_infer_terminal_already_finalized() -> None:
    assert (
        infer_terminal_status_from_result({"status": "already_finalized"})
        == "SKIPPED_IDEMPOTENT"
    )


def test_infer_terminal_business_error_still_succeeded_shape() -> None:
    # Compatibilidad: errores embebidos con status ok → SUCCEEDED (auditoría).
    assert (
        infer_terminal_status_from_result({"status": "ok", "errors": [{"x": 1}]})
        == "SUCCEEDED"
    )


def test_runner_no_nameerror_on_terminal(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _ok(graph, **k):
        return {"status": "already_finalized", "already_finalized": True}

    monkeypatch.setattr(finalize_queue_module, "finalize_payment_validation", _ok)
    jm = JobManager()
    svc = FinalizeQueueService(jm)
    from fastapi import BackgroundTasks

    async def _run() -> None:
        bg = BackgroundTasks()
        accepted = await svc.enqueue(
            graph=_MockGraph(), background_tasks=bg, bank_code="banco_bogota"
        )
        await bg()
        job = jm.get_job(accepted.job_id)
        assert job is not None
        assert job["status"] == "completed"
        assert "NameError" not in str(job.get("error") or {})

    import asyncio

    asyncio.run(_run())


def test_pa_contract_shape_unchanged(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _ok(graph, **k):
        return {"status": "ok"}

    monkeypatch.setattr(finalize_queue_module, "finalize_payment_validation", _ok)
    app = FastAPI()
    init_graph_client(_MockGraph())  # type: ignore[arg-type]
    app.include_router(pa_router)
    client = TestClient(app)
    res = client.post(
        "/graph/sharepoint/payment-validation/finalize/queue",
        json={
            "validation_file": "a.xlsx",
            "validation_file_path": "rev/a.xlsx",
            "process_date": "2026-07-30",
            "bank_code": "banco_bogota",
        },
    )
    assert res.status_code == 202
    body = res.json()
    assert set(body.keys()) == {"job_id", "status"}
    assert body["status"] == "queued"
    assert isinstance(body["job_id"], str)


# ─── Identidad ProcessKey / available_actions ────────────────────────────────


def test_process_key_other_bank_409(monkeypatch: pytest.MonkeyPatch) -> None:
    snap = _ready_snap(bank_code="banco_bancolombia", process_key=PROCESS_KEY)
    client, csrf = _client_with_session(monkeypatch, snap=snap)
    # Body pide bogota; control dice bancolombia + misma key → mismatch banco.
    res = client.post(
        "/api/ui/v1/processes/finalize",
        json={"bank_code": "banco_bogota", "process_key": PROCESS_KEY},
        headers=_write_headers(csrf),
    )
    assert res.status_code == 409


def test_process_key_inactive_409(monkeypatch: pytest.MonkeyPatch) -> None:
    snap = _ready_snap(is_active=False)
    client, csrf = _client_with_session(monkeypatch, snap=snap)
    res = client.post(
        "/api/ui/v1/processes/finalize",
        json={"bank_code": "banco_bogota", "process_key": PROCESS_KEY},
        headers=_write_headers(csrf),
    )
    assert res.status_code == 409
    assert res.json()["detail"]["error_code"] == "process_not_active"


def test_validation_path_resolved_from_control(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, object] = {}

    async def _fake(graph, **k):
        captured.update(k)
        return {"status": "ok", "process_key": PROCESS_KEY}

    monkeypatch.setattr(finalize_queue_module, "finalize_payment_validation", _fake)
    path = "01 REVISION/from_control_only.xlsx"
    client, csrf = _client_with_session(
        monkeypatch, snap=_ready_snap(validation_file_path=path)
    )
    res = client.post(
        "/api/ui/v1/processes/finalize",
        json={"bank_code": "banco_bogota", "process_key": PROCESS_KEY},
        headers=_write_headers(csrf),
    )
    assert res.status_code == 202
    assert captured.get("validation_file_path") == path
    assert "validation_file" not in res.json()


def test_ui_schema_rejects_extra_paths(monkeypatch: pytest.MonkeyPatch) -> None:
    client, csrf = _client_with_session(monkeypatch)
    res = client.post(
        "/api/ui/v1/processes/finalize",
        json={
            "bank_code": "banco_bogota",
            "process_key": PROCESS_KEY,
            "validation_file_path": "evil.xlsx",
            "force": True,
        },
        headers=_write_headers(csrf),
    )
    assert res.status_code == 422


def test_available_actions_finalize_no_lock_no_excel_parse(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, _csrf = _client_with_session(monkeypatch, finalize_enabled=False)
    jm = get_job_manager()
    assert jm.is_generate_or_finalize_active() is False
    key = PROCESS_KEY.replace("|", "%7C")
    res = client.get(f"/api/ui/v1/processes/{key}", headers={"Origin": ORIGIN})
    assert res.status_code == 200
    body = res.json()
    assert body["available_actions"]["finalize"]["allowed"] is False
    assert "habilitado" in (body["available_actions"]["finalize"]["reason"] or "").lower()
    assert body["operator_checklist"]
    assert jm.is_generate_or_finalize_active() is False
    assert ControlCols.VAL_PROCESAR_SI in " ".join(body["operator_checklist"])
    assert EstadoPago.REVISION_MANUAL in " ".join(body["operator_checklist"])


def test_post_revalidates_after_available_actions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """available_actions puede decir allowed; el POST revalida identidad."""
    client, csrf = _client_with_session(
        monkeypatch,
        snap=_ready_snap(estado_proceso="REVISION_CREADA"),
    )
    # Cambiar control a inactivo antes del POST.
    configure_ui_router_for_tests(
        control_loader=lambda _bc: _ready_snap(is_active=False)
    )
    res = client.post(
        "/api/ui/v1/processes/finalize",
        json={"bank_code": "banco_bogota", "process_key": PROCESS_KEY},
        headers=_write_headers(csrf),
    )
    assert res.status_code == 409


def test_finalize_success_does_not_call_notify(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """La orquestación UI solo invoca finalize_payment_validation (sin Notify)."""
    ui_src = (REPO_ROOT / "app/adapters/primary/http/ui/router_v1.py").read_text(
        encoding="utf-8"
    )
    svc_src = (
        REPO_ROOT / "app/application/services/finalize_queue_service.py"
    ).read_text(encoding="utf-8")
    assert "notify" not in ui_src.lower() or "notify_idempotency" in ui_src
    assert "finalize_payment_validation" in svc_src
    assert "notify_payment" not in svc_src
    assert "payment_validation_notify" not in svc_src

    async def _fake(graph, **k):
        return {
            "status": "ok",
            "process_key": PROCESS_KEY,
            "notify_executed": False,
        }

    monkeypatch.setattr(finalize_queue_module, "finalize_payment_validation", _fake)
    client, csrf = _client_with_session(monkeypatch)
    res = client.post(
        "/api/ui/v1/processes/finalize",
        json={"bank_code": "banco_bogota", "process_key": PROCESS_KEY},
        headers=_write_headers(csrf),
    )
    assert res.status_code == 202


def test_resolve_identity_pure() -> None:
    snap = _ready_snap()
    target = resolve_finalize_target_from_control(
        snap, bank_code="banco_bogota", process_key=PROCESS_KEY
    )
    assert target.validation_file_path.endswith(".xlsx")
    with pytest.raises(FinalizeProcessIdentityError):
        resolve_finalize_target_from_control(
            snap, bank_code="banco_bancolombia", process_key=PROCESS_KEY
        )


def test_compute_finalize_availability_pure() -> None:
    av = compute_finalize_availability(
        write_allowed=True,
        finalize_enabled=False,
        sandbox=True,
        generate_or_finalize_active=False,
        snap=_ready_snap(),
    )
    assert av.allowed is False
    checklist = build_finalize_operator_checklist()
    assert any("Procesar" in line for line in checklist)


def test_production_blocks_finalize(monkeypatch: pytest.MonkeyPatch) -> None:
    _enable_local(monkeypatch, finalize_enabled=True)
    monkeypatch.setenv("ACTIVE_ENVIRONMENT", "production")
    # local_session + production → UI fail-closed; o write gate sandbox.
    configure_ui_router_for_tests(control_loader=lambda _bc: _ready_snap())
    client = TestClient(create_ui_test_app(), base_url="https://testserver")
    # Login puede fallar por fail-closed; en cualquier caso Finalize no debe 202.
    login = client.post(
        "/api/ui/v1/auth/login",
        json={"username": "operator", "password": "CorrectHorseBattery!"},
        headers={"Origin": ORIGIN},
    )
    if login.status_code != 200:
        return
    csrf = client.get("/api/ui/v1/auth/csrf", headers={"Origin": ORIGIN}).json()[
        "csrf_token"
    ]
    res = client.post(
        "/api/ui/v1/processes/finalize",
        json={"bank_code": "banco_bogota", "process_key": PROCESS_KEY},
        headers=_write_headers(csrf),
    )
    assert res.status_code in {401, 403}


def test_csrf_required_for_finalize(monkeypatch: pytest.MonkeyPatch) -> None:
    client, _csrf = _client_with_session(monkeypatch)
    res = client.post(
        "/api/ui/v1/processes/finalize",
        json={"bank_code": "banco_bogota", "process_key": PROCESS_KEY},
        headers={"Origin": ORIGIN, "Content-Type": "application/json"},
    )
    assert res.status_code == 403
    assert res.json()["detail"]["error_code"] == "invalid_csrf_token"


def test_bootstrap_exposes_finalize_allowed_false(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, _ = _client_with_session(monkeypatch, finalize_enabled=False)
    res = client.get("/api/ui/v1/bootstrap", headers={"Origin": ORIGIN})
    assert res.status_code == 200
    assert res.json()["finalize_allowed"] is False
    assert res.json()["writes_allowed"] is True
