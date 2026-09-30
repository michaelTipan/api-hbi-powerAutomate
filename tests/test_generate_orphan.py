"""Salida desde un GENERANDO huérfano (job muerto tras anunciar progreso)."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from app.application.job_manager import JobManager
from app.application.services.generate_orphan import is_orphan_generating
from app.application.ui.path_guard import UiAllowedRoots
from app.application.ui.process_query import UiProcessQueryService
from app.application.use_cases.payment_validation_cancel import (
    cancel_active_payment_validation,
)
from app.application.use_cases.payment_validation_process_control import (
    read_process_control_snapshot,
    update_process_control_row2,
)
from tests.fakes.ui_sharepoint_fake import FakeUiSharePointRead, make_fake_control
from tests.test_generate_control_real_config import (
    BANK,
    RealConfigGraph,
    build_bank_excel,
    fresh_job_manager,  # noqa: F401 — fixture
    run_queue,
    set_real_config_env,
)
from tests.ui_fixtures import make_snap

NOW = datetime(2026, 9, 30, 15, 0, tzinfo=timezone.utc)
OLD_KEY = "payment-validation|banco_bogota|2025-12-20|old12345"


class _Jobs:
    def __init__(self, jobs: dict[str, dict] | None = None, *, locked: bool = False) -> None:
        self.jobs = jobs or {}
        self.locked = locked

    def get_job(self, job_id: str):
        return self.jobs.get(job_id)

    def is_generate_or_finalize_active(self) -> bool:
        return self.locked


def _iso(dt: datetime) -> str:
    return dt.isoformat()


# ─── Regla pura ──────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "job,expected",
    [
        ({"status": "failed"}, True),
        ({"status": "cancelled"}, True),
        (None, True),
        ({"status": "running", "heartbeat_at": _iso(NOW - timedelta(minutes=11))}, True),
        ({"status": "queued", "updated_at": _iso(NOW - timedelta(minutes=30))}, True),
        ({"status": "running", "heartbeat_at": _iso(NOW - timedelta(minutes=2))}, False),
        (
            {
                "status": "running",
                "heartbeat_at": _iso(NOW - timedelta(minutes=1)),
                "updated_at": _iso(NOW - timedelta(hours=2)),
            },
            False,
        ),
        ({"status": "running"}, False),
        ({"status": "completed"}, False),
    ],
)
def test_orphan_rule_by_job_state(job, expected):
    jm = _Jobs({"g1": job} if job is not None else {})
    assert is_orphan_generating("GENERANDO", "g1", job_manager=jm, now=NOW) is expected


def test_orphan_rule_requires_generando_and_free_lock():
    dead = _Jobs({"g1": {"status": "failed"}})
    assert is_orphan_generating("ERROR_GENERATE", "g1", job_manager=dead, now=NOW) is False
    assert is_orphan_generating("REVISION_CREADA", "g1", job_manager=dead, now=NOW) is False
    locked = _Jobs({"g1": {"status": "failed"}}, locked=True)
    assert is_orphan_generating("GENERANDO", "g1", job_manager=locked, now=NOW) is False
    assert (
        is_orphan_generating(
            "GENERANDO", "g1", job_manager=locked, now=NOW, check_generate_lock=False
        )
        is True
    )


def test_orphan_rule_never_flags_the_current_job():
    jm = _Jobs({})
    assert is_orphan_generating("GENERANDO", "", job_manager=jm, now=NOW) is True
    assert (
        is_orphan_generating(
            "GENERANDO", "me", job_manager=jm, now=NOW, check_generate_lock=False, current_job_id="me"
        )
        is False
    )


# ─── Proyección: igual que ERROR_GENERATE ────────────────────────────────────

ROOT = "INFORMACION CREDITOS-CLIENTES/03 COMWARE PRUEBAS- INFORMACION CREDITOS CLIENTES"
CONTROL_PATH = f"{ROOT}/02 VALIDACION PAGOS/90 ACCESO RESTRINGIDO/03 CONTROL TECNICO/control.xlsx"


@pytest.fixture
def ui_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("UI_ENABLED", "true")
    monkeypatch.setenv("UI_WRITE_ENABLED", "true")
    monkeypatch.setenv("ACTIVE_ENVIRONMENT", "sandbox")


def _project(estado: str, generate_job_id: str | None):
    snap = make_snap(
        control_file_path=CONTROL_PATH,
        estado_proceso=estado,
        validation_file_path="",
        process_key="payment-validation|banco_bancolombia|2026-09-30|abc-123",
    )
    fake = FakeUiSharePointRead(
        roots=UiAllowedRoots(environment="sandbox", roots=(ROOT,)),
        controls={
            "banco_bancolombia": make_fake_control(snap, generate_job_id=generate_job_id)
        },
    )
    return asyncio.run(UiProcessQueryService(fake).project_bank("banco_bancolombia"))


def _visible(detail) -> dict:
    return {
        "operational_status": detail.operational_status,
        "operational_title": detail.operational_title,
        "operational_message": detail.operational_message,
        "control_estado_proceso": detail.control_estado_proceso,
        "steps": [(s.name, s.status, s.retry_action) for s in detail.steps],
        "actions": {k: v.allowed for k, v in detail.available_actions.items()},
        "next_actions": [(a.code, a.enabled) for a in detail.next_actions],
        "errors": [(e.stage, e.error_code) for e in detail.errors],
        "active_job": detail.active_job,
    }


def _seed_job(jm: JobManager, job_id: str, payload: dict) -> None:
    asyncio.run(
        jm.set_job(job_id, {"job_id": job_id, "type": "generate", "bank_code": "banco_bancolombia", **payload})
    )


def test_projection_orphan_matches_error_generate(ui_env, fresh_job_manager):
    _seed_job(fresh_job_manager, "dead", {"status": "failed", "error": {"message": "boom"}})
    orphan = _project("GENERANDO", "dead")
    reference = _project("ERROR_GENERATE", "dead")

    assert orphan.operational_status == "ERROR_RECUPERABLE"
    generate = next(s for s in orphan.steps if s.name == "generate")
    assert (generate.status, generate.retry_action) == ("failed_retryable", "retry_generate")
    assert orphan.available_actions["cancel_lote"].allowed is True
    assert orphan.available_actions["regenerate"].allowed is True
    assert _visible(orphan) == _visible(reference)


def test_projection_stale_running_job_is_orphan(ui_env, fresh_job_manager):
    stale = _iso(datetime.now(timezone.utc) - timedelta(minutes=45))
    _seed_job(
        fresh_job_manager,
        "stale",
        {"status": "running", "heartbeat_at": stale, "updated_at": stale},
    )
    detail = _project("GENERANDO", "stale")
    assert detail.operational_status == "ERROR_RECUPERABLE"
    assert detail.active_job is None


def test_projection_live_generate_keeps_generando(ui_env, fresh_job_manager):
    fresh = _iso(datetime.now(timezone.utc))
    _seed_job(
        fresh_job_manager,
        "live",
        {"status": "running", "heartbeat_at": fresh, "updated_at": fresh},
    )
    detail = _project("GENERANDO", "live")
    assert detail.operational_status == "GENERANDO"
    assert detail.control_estado_proceso == "GENERANDO"
    assert detail.available_actions["cancel_lote"].allowed is False


def test_projection_generate_lock_active_keeps_generando(ui_env, fresh_job_manager):
    _seed_job(fresh_job_manager, "dead", {"status": "failed"})
    assert fresh_job_manager.try_start_generate()
    try:
        detail = _project("GENERANDO", "dead")
    finally:
        fresh_job_manager.finish_generate()
    assert detail.operational_status == "GENERANDO"


# ─── Iniciar / Regenerar / Cancelar sobre el Control real (store local) ──────


def _seed_generando(graph, job_id: str) -> None:
    asyncio.run(
        update_process_control_row2(
            graph,
            "s",
            "d",
            bank_code=BANK,
            updates={
                "EstadoProceso": "GENERANDO",
                "IsActive": True,
                "ProcessKey": OLD_KEY,
                "GenerateJobId": job_id,
                "ValidationFilePath": "",
            },
        )
    )


def _estado(graph) -> str:
    return asyncio.run(read_process_control_snapshot(graph, "s", "d", bank_code=BANK)).estado_proceso


def _seed_bogota_job(jm: JobManager, job_id: str, payload: dict) -> None:
    asyncio.run(jm.set_job(job_id, {"job_id": job_id, "type": "generate", "bank_code": BANK, **payload}))


@pytest.fixture
def real_graph(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    set_real_config_env(monkeypatch, tmp_path / "control")
    graph = RealConfigGraph()
    graph.downloaded_files["banco.xlsx"] = build_bank_excel()
    return graph


@pytest.mark.parametrize("force_regenerate", [False, True])
def test_iniciar_and_regenerar_recover_orphan(real_graph, fresh_job_manager, force_regenerate):
    _seed_bogota_job(fresh_job_manager, "dead", {"status": "failed"})
    _seed_generando(real_graph, "dead")

    job_id = run_queue(real_graph, fresh_job_manager, force_regenerate=force_regenerate)

    job = fresh_job_manager.get_job(job_id)
    assert job["status"] == "completed", job.get("error")
    assert _estado(real_graph) == "REVISION_CREADA"


def test_iniciar_with_live_generate_still_blocks(real_graph, fresh_job_manager):
    fresh = _iso(datetime.now(timezone.utc))
    _seed_bogota_job(
        fresh_job_manager, "live", {"status": "running", "heartbeat_at": fresh, "updated_at": fresh}
    )
    _seed_generando(real_graph, "live")

    job_id = run_queue(real_graph, fresh_job_manager)

    job = fresh_job_manager.get_job(job_id)
    assert job["status"] == "failed"
    assert job["error"]["message"] == f"active_process_exists|{OLD_KEY}|GENERANDO"
    # El fallo de este intento no pisa el GENERANDO del job vivo.
    assert _estado(real_graph) == "GENERANDO"


def test_cancel_orphan_generando(real_graph, fresh_job_manager):
    _seed_bogota_job(fresh_job_manager, "dead", {"status": "failed"})
    _seed_generando(real_graph, "dead")

    result = asyncio.run(cancel_active_payment_validation(real_graph, bank_code=BANK))

    assert result["process_control_estado"] == "CANCELADO"
    assert result["estado_antes"] == "GENERANDO"
    assert _estado(real_graph) == "CANCELADO"


def test_cancel_orphan_generando_auto_detected(real_graph, fresh_job_manager):
    _seed_generando(real_graph, "")

    result = asyncio.run(cancel_active_payment_validation(real_graph))

    assert result["bank_code"] == BANK
    assert _estado(real_graph) == "CANCELADO"


def test_cancel_live_generando_is_rejected(real_graph, fresh_job_manager):
    fresh = _iso(datetime.now(timezone.utc))
    _seed_bogota_job(
        fresh_job_manager, "live", {"status": "running", "heartbeat_at": fresh, "updated_at": fresh}
    )
    _seed_generando(real_graph, "live")

    with pytest.raises(ValueError, match=r"^cancel_not_allowed\|GENERANDO\|"):
        asyncio.run(cancel_active_payment_validation(real_graph, bank_code=BANK))
    assert _estado(real_graph) == "GENERANDO"
