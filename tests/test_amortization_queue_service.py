"""Tests AmortizationQueueService: UI (validar→aplicar) y facades PA.

Usa dobles/mocks para prepare/execute/run_* (no toca Graph real). El objetivo
es probar la orquestación (mutex, claim, finish, doble validación evitada,
mapeo de outcomes) — no la lógica financiera de los use cases, ya cubierta en
``test_amortization_fill_apply.py`` / ``test_amortization_fill_dry_run.py``.

Sigue el patrón del resto del repo: tests síncronos + ``asyncio.run`` (no hay
plugin ``pytest-asyncio`` instalado).
"""
from __future__ import annotations

import asyncio

import pytest
from fastapi import BackgroundTasks

from app.application.job_manager import JobManager, get_job_manager
from app.application.services import amortization_queue_service as svc_module
from app.application.services.amortization_queue_service import (
    AmortizationAlreadyAppliedError,
    AmortizationQueueBusyError,
    AmortizationQueueService,
)
from app.application.use_cases.amortization_application_plan import (
    AmortizationPreparedPlan,
)


class FakeGraph:
    """Doble mínimo: ningún método debería ejecutarse (todo mockeado)."""

    async def get(self, *a, **k):
        raise AssertionError("FakeGraph.get no debería llamarse en estos tests")

    async def get_bytes(self, *a, **k):
        raise AssertionError("FakeGraph.get_bytes no debería llamarse en estos tests")

    async def put_bytes(self, *a, **k):
        raise AssertionError("FakeGraph.put_bytes no debería llamarse en estos tests")

    async def post_json(self, *a, **k):
        raise AssertionError("FakeGraph.post_json no debería llamarse en estos tests")

    async def delete(self, *a, **k):
        raise AssertionError("FakeGraph.delete no debería llamarse en estos tests")


@pytest.fixture(autouse=True)
def _reset_jm(tmp_path, monkeypatch):
    # Aísla la persistencia a disco por test: JobManager reconcilia jobs
    # persistidos al reiniciar el singleton, y process_key genéricos ("pk-2",
    # "pk-3") no deben "contaminarse" entre tests ni entre corridas.
    monkeypatch.setenv("PAYMENT_VALIDATION_JOBS_DIR", str(tmp_path))
    JobManager._instance = None
    jm = get_job_manager()
    jm._validation_jobs.clear()
    jm._generate_active = False
    jm._finalize_active = False
    jm._notify_active = False
    jm._merge_active = False
    jm._amortization_active = False
    yield
    JobManager._instance = None


@pytest.fixture
def service() -> AmortizationQueueService:
    return AmortizationQueueService(get_job_manager())


async def _noop_try_record_step_event(*args, **kwargs):
    return {"execution_log_status": "DISABLED"}


@pytest.fixture(autouse=True)
def _disable_execution_log(monkeypatch):
    """Evita I/O de bitácora (flag-gated de por sí, pero blindamos el test)."""
    monkeypatch.setattr(
        svc_module, "try_record_step_event", _noop_try_record_step_event
    )


def _rejection_plan(
    *, process_key: str = "pk-1", bank_code: str = "banco_bogota"
) -> AmortizationPreparedPlan:
    return AmortizationPreparedPlan(
        can_apply=False,
        already_applied=False,
        rejection_kind="preflight",
        dry_run={"items": [{"id_pago": "P1"}], "summary": {"errors": 1}},
        resolved_bank_code=bank_code,
        resolved_process_key=process_key,
        rejection_result={
            "status": "preflight_failed",
            "mode": "prepare",
            "can_apply": False,
            "outcome": "requires_correction",
            "already_applied": False,
            "items": [{"id_pago": "P1"}],
            "bank_code": bank_code,
            "process_key": process_key,
            "error_code": "preflight_errors",
            "user_message": "Se encontraron datos que requieren corrección.",
        },
    )


def _applyable_plan(
    *, process_key: str = "pk-2", bank_code: str = "banco_bogota"
) -> AmortizationPreparedPlan:
    return AmortizationPreparedPlan(
        can_apply=True,
        already_applied=False,
        dry_run={"items": [{"id_pago": "P2"}], "summary": {"errors": 0}},
        resolved_bank_code=bank_code,
        resolved_process_key=process_key,
    )


def _already_applied_plan(
    *, process_key: str = "pk-3", bank_code: str = "banco_bogota"
) -> AmortizationPreparedPlan:
    return AmortizationPreparedPlan(
        can_apply=False,
        already_applied=True,
        rejection_kind="already_applied",
        resolved_bank_code=bank_code,
        resolved_process_key=process_key,
        already_applied_result={
            "status": "ok",
            "mode": "apply",
            "already_applied": True,
            "outcome": "already_applied",
            "bank_code": bank_code,
            "process_key": process_key,
            "apply_wrote_changes": False,
            "tables_uploaded_count": 0,
        },
    )


# ─── UI: can_apply=false → requires_correction, cero escrituras ─────────────


def test_ui_process_can_apply_false_never_calls_execute(monkeypatch, service):
    prepare_calls: list[dict] = []
    execute_calls: list[dict] = []

    async def fake_prepare(graph, **kwargs):
        prepare_calls.append(kwargs)
        return _rejection_plan()

    async def fake_execute(graph, plan, **kwargs):
        execute_calls.append(kwargs)
        raise AssertionError("execute_amortization_from_prepared NO debe llamarse")

    monkeypatch.setattr(svc_module, "prepare_amortization_application", fake_prepare)
    monkeypatch.setattr(svc_module, "execute_amortization_from_prepared", fake_execute)

    async def scenario():
        bt = BackgroundTasks()
        accepted = await service.enqueue_process_ui(
            graph=FakeGraph(),
            background_tasks=bt,
            bank_code="banco_bogota",
            process_key="pk-1",
        )
        assert accepted.status == "queued"
        await bt()
        return accepted

    accepted = asyncio.run(scenario())

    assert len(prepare_calls) == 1
    assert len(execute_calls) == 0

    job = service.job_manager.get_job(accepted.job_id)
    assert job["status"] == "completed"
    assert job["result"]["outcome"] == "requires_correction"
    assert job["result"]["can_apply"] is False
    assert job["result"]["items"] == [{"id_pago": "P1"}]
    # Mutex liberado tras completar (sin importar el resultado de negocio).
    assert service.job_manager.is_amortization_active() is False


# ─── UI: can_apply=true → prepara una vez, ejecuta una vez (sin doble validación) ──


def test_ui_process_can_apply_true_prepares_once_executes_once(monkeypatch, service):
    prepare_calls: list[dict] = []
    execute_calls: list[dict] = []

    async def fake_prepare(graph, **kwargs):
        prepare_calls.append(kwargs)
        return _applyable_plan()

    async def fake_execute(graph, plan, **kwargs):
        execute_calls.append({"plan": plan, **kwargs})
        return {
            "status": "ok",
            "mode": "apply",
            "outcome": "applied",
            "already_applied": False,
            "bank_code": plan.resolved_bank_code,
            "process_key": plan.resolved_process_key,
            "apply_wrote_changes": True,
            "tables_uploaded_count": 1,
        }

    monkeypatch.setattr(svc_module, "prepare_amortization_application", fake_prepare)
    monkeypatch.setattr(svc_module, "execute_amortization_from_prepared", fake_execute)

    async def scenario():
        bt = BackgroundTasks()
        accepted = await service.enqueue_process_ui(
            graph=FakeGraph(),
            background_tasks=bt,
            bank_code="banco_bogota",
            process_key="pk-2",
        )
        await bt()
        return accepted

    accepted = asyncio.run(scenario())

    assert len(prepare_calls) == 1
    assert len(execute_calls) == 1
    # El mismo plan preparado se pasa a execute: no se vuelve a correr un dry-run
    # completo (doble validación evitada por diseño, no solo por conteo de llamadas).
    assert execute_calls[0]["plan"].resolved_process_key == "pk-2"

    job = service.job_manager.get_job(accepted.job_id)
    assert job["status"] == "completed"
    assert job["result"]["outcome"] == "applied"
    assert job["result"]["apply_wrote_changes"] is True
    assert service.job_manager.is_amortization_active() is False


# ─── Busy: mutex compartido con Generate/Finalize/Notify/Merge ──────────────


def test_enqueue_process_ui_busy_when_mutation_active(service):
    service.job_manager.try_start_merge()

    async def scenario():
        with pytest.raises(AmortizationQueueBusyError):
            await service.enqueue_process_ui(
                graph=FakeGraph(),
                background_tasks=BackgroundTasks(),
                bank_code="banco_bogota",
                process_key="pk-busy",
            )

    asyncio.run(scenario())
    service.job_manager.finish_merge()


def test_enqueue_dry_run_pa_busy_when_mutation_active(service):
    service.job_manager.try_start_generate()

    async def scenario():
        with pytest.raises(AmortizationQueueBusyError):
            await service.enqueue_dry_run_pa(
                graph=FakeGraph(),
                background_tasks=BackgroundTasks(),
                bank_code="banco_bogota",
            )

    asyncio.run(scenario())
    service.job_manager.finish_generate()


def test_enqueue_apply_pa_busy_when_mutation_active(service):
    service.job_manager.try_start_notify()

    async def scenario():
        with pytest.raises(AmortizationQueueBusyError):
            await service.enqueue_apply_pa(
                graph=FakeGraph(),
                background_tasks=BackgroundTasks(),
                bank_code="banco_bogota",
            )

    asyncio.run(scenario())
    service.job_manager.finish_notify()


# ─── UI already_applied: raise (sin job nuevo) ──────────────────────────────


def test_enqueue_process_ui_raises_when_already_applied(service):
    pk = "pk-already"
    service.job_manager._validation_jobs["prior-job"] = {
        "job_id": "prior-job",
        "type": "amortization_process",
        "status": "completed",
        "process_key": pk,
        "result": {"status": "ok", "process_key": pk, "outcome": "applied"},
        "finished_at": "2026-07-31T01:00:00-05:00",
    }

    async def scenario():
        with pytest.raises(AmortizationAlreadyAppliedError) as excinfo:
            await service.enqueue_process_ui(
                graph=FakeGraph(),
                background_tasks=BackgroundTasks(),
                bank_code="banco_bogota",
                process_key=pk,
            )
        return excinfo.value

    err = asyncio.run(scenario())
    assert err.process_key == pk
    assert err.prior_job_id == "prior-job"
    # No debe adquirir el mutex al rechazar por already_applied.
    assert service.job_manager.is_amortization_active() is False


# ─── PA apply already_applied: reusa job previo (NO raise, como Merge PA) ──


def test_enqueue_apply_pa_reuses_prior_job_when_already_applied(service):
    pk = "pk-pa-already"
    service.job_manager._validation_jobs["prior-pa-job"] = {
        "job_id": "prior-pa-job",
        "type": "amortization_apply",
        "status": "completed",
        "process_key": pk,
        "result": {"status": "ok", "process_key": pk, "already_applied": True},
        "finished_at": "2026-07-31T02:00:00-05:00",
    }

    async def scenario():
        return await service.enqueue_apply_pa(
            graph=FakeGraph(),
            background_tasks=BackgroundTasks(),
            bank_code="banco_bogota",
            process_key=pk,
        )

    accepted = asyncio.run(scenario())
    assert accepted.reused_prior is True
    assert accepted.job_id == "prior-pa-job"
    assert accepted.status == "completed"
    assert service.job_manager.is_amortization_active() is False


# ─── PA dry-run: usa el mutex de amortización (serializa contra mutaciones) ──


def test_enqueue_dry_run_pa_uses_amortization_mutex(monkeypatch, service):
    lock_seen_active: list[bool] = []

    async def fake_dry_run(graph, **kwargs):
        # Mientras el dry-run corre, el mutex debe estar tomado.
        lock_seen_active.append(service.job_manager.is_amortization_active())
        return {"status": "ok", "mode": "dry_run", "can_apply": True, "items": []}

    monkeypatch.setattr(svc_module, "run_amortization_fill_dry_run", fake_dry_run)

    async def scenario():
        bt = BackgroundTasks()
        accepted = await service.enqueue_dry_run_pa(
            graph=FakeGraph(),
            background_tasks=bt,
            bank_code="banco_bogota",
            report_date_iso="2026-07-30",
        )
        # Tras encolar (antes de correr el background task) el lock sigue activo.
        assert service.job_manager.is_amortization_active() is True
        await bt()
        return accepted

    accepted = asyncio.run(scenario())
    assert lock_seen_active == [True]
    # Al terminar, finally libera el mutex.
    assert service.job_manager.is_amortization_active() is False

    job = service.job_manager.get_job(accepted.job_id)
    assert job["status"] == "completed"
    assert job["type"] == "amortization_dry_run"


def test_dry_run_pa_success_does_not_count_as_completed_amortization(
    monkeypatch, service
):
    """Regla de negocio: éxito de dry-run NUNCA cuenta como amortización aplicada."""
    pk = "pk-dry-not-applied"

    async def fake_dry_run(graph, **kwargs):
        return {
            "status": "ok",
            "mode": "dry_run",
            "can_apply": True,
            "process_key": pk,
            "items": [],
        }

    monkeypatch.setattr(svc_module, "run_amortization_fill_dry_run", fake_dry_run)

    async def scenario():
        bt = BackgroundTasks()
        await service.enqueue_dry_run_pa(
            graph=FakeGraph(),
            background_tasks=bt,
            bank_code="banco_bogota",
            process_key=pk,
        )
        await bt()

    asyncio.run(scenario())

    assert service.job_manager.has_completed_amortization(pk) is False
    # Confirma que un nuevo claim sigue disponible (no bloqueado por el dry-run).
    assert service.job_manager.try_claim_amortization_for_process(pk) == "ok"
    service.job_manager.finish_amortization()


# ─── Runner imports no explotan (NameError de infer_terminal_status_from_result) ──


def test_run_dry_run_pa_job_completes_without_nameerror(monkeypatch, service):
    async def fake_dry_run(graph, **kwargs):
        return {"status": "ok", "mode": "dry_run", "can_apply": True, "items": []}

    monkeypatch.setattr(svc_module, "run_amortization_fill_dry_run", fake_dry_run)

    job_id = "job-dry-direct"

    async def scenario():
        await service.job_manager.set_job(
            job_id,
            {"job_id": job_id, "type": "amortization_dry_run", "status": "queued"},
        )
        service.job_manager.try_start_amortization()
        await service._run_dry_run_pa_job(
            job_id,
            FakeGraph(),
            report_date_iso=None,
            merge_manifest_path=None,
            historical_file_path=None,
            bank_code="banco_bogota",
        )

    asyncio.run(scenario())
    job = service.job_manager.get_job(job_id)
    assert job["status"] == "completed"
    assert job["error"] is None
    assert service.job_manager.is_amortization_active() is False


def test_run_apply_pa_job_completes_without_nameerror(monkeypatch, service):
    async def fake_apply(graph, **kwargs):
        return {
            "status": "ok",
            "mode": "apply",
            "outcome": "applied",
            "already_applied": False,
            "apply_wrote_changes": True,
        }

    monkeypatch.setattr(svc_module, "run_amortization_fill_apply", fake_apply)

    job_id = "job-apply-direct"

    async def scenario():
        await service.job_manager.set_job(
            job_id,
            {"job_id": job_id, "type": "amortization_apply", "status": "queued"},
        )
        service.job_manager.try_start_amortization()
        await service._run_apply_pa_job(
            job_id,
            FakeGraph(),
            report_date_iso=None,
            merge_manifest_path=None,
            historical_file_path=None,
            bank_code="banco_bogota",
        )

    asyncio.run(scenario())
    job = service.job_manager.get_job(job_id)
    assert job["status"] == "completed"
    assert job["error"] is None
    assert job["result"]["outcome"] == "applied"
    assert service.job_manager.is_amortization_active() is False


# ─── UI already_applied desde prepare (no ejecuta apply) ────────────────────


def test_ui_process_already_applied_from_prepare_never_executes(monkeypatch, service):
    execute_calls: list[dict] = []

    async def fake_prepare(graph, **kwargs):
        return _already_applied_plan()

    async def fake_execute(graph, plan, **kwargs):
        execute_calls.append(kwargs)
        raise AssertionError("execute_amortization_from_prepared NO debe llamarse")

    monkeypatch.setattr(svc_module, "prepare_amortization_application", fake_prepare)
    monkeypatch.setattr(svc_module, "execute_amortization_from_prepared", fake_execute)

    async def scenario():
        bt = BackgroundTasks()
        accepted = await service.enqueue_process_ui(
            graph=FakeGraph(),
            background_tasks=bt,
            bank_code="banco_bogota",
            process_key="pk-3",
        )
        await bt()
        return accepted

    accepted = asyncio.run(scenario())

    assert len(execute_calls) == 0
    job = service.job_manager.get_job(accepted.job_id)
    assert job["status"] == "completed"
    assert job["result"]["outcome"] == "already_applied"
    assert service.job_manager.is_amortization_active() is False
