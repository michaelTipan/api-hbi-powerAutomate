"""Tests JobManager Amortization: claim, evidencia, mutex compartido."""
from __future__ import annotations

import pytest

from app.application.job_manager import JobManager, get_job_manager


@pytest.fixture(autouse=True)
def _reset_jm() -> None:
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


def test_amortization_blocks_generate_finalize_notify_merge() -> None:
    jm = get_job_manager()
    assert jm.try_start_amortization() is True
    assert jm.try_start_generate() is False
    assert jm.try_start_finalize() is False
    assert jm.try_start_notify() is False
    assert jm.try_start_merge() is False
    assert jm.try_claim_amortization_for_process("pk") == "busy"
    jm.finish_amortization()
    assert jm.try_start_generate() is True
    jm.finish_generate()


def test_generate_merge_notify_block_amortization() -> None:
    jm = get_job_manager()
    assert jm.try_start_generate() is True
    assert jm.try_claim_amortization_for_process("pk-a") == "busy"
    jm.finish_generate()

    assert jm.try_start_merge() is True
    assert jm.try_claim_amortization_for_process("pk-a") == "busy"
    jm.finish_merge()

    assert jm.try_start_notify() is True
    assert jm.try_claim_amortization_for_process("pk-a") == "busy"
    jm.finish_notify()

    assert jm.try_claim_amortization_for_process("pk-a") == "ok"
    jm.finish_amortization()


def test_double_claim_amortization_is_busy() -> None:
    jm = get_job_manager()
    assert jm.try_claim_amortization_for_process("pk-double") == "ok"
    assert jm.try_claim_amortization_for_process("pk-double") == "busy"
    assert jm.is_amortization_active() is True
    jm.finish_amortization()
    assert jm.is_amortization_active() is False


def test_already_applied_when_completed_amortization_process_outcome_applied() -> None:
    jm = get_job_manager()
    pk = "payment-validation|banco_bogota|2026-07-30|a1"
    jm._validation_jobs["j-applied"] = {
        "job_id": "j-applied",
        "type": "amortization_process",
        "status": "completed",
        "process_key": pk,
        "result": {
            "status": "ok",
            "process_key": pk,
            "outcome": "applied",
        },
        "finished_at": "2026-07-31T01:00:00-05:00",
    }
    assert jm.has_completed_amortization(pk) is True
    assert jm.try_claim_amortization_for_process(pk) == "already_applied"


def test_already_applied_flag_in_result_counts() -> None:
    jm = get_job_manager()
    pk = "payment-validation|banco_bogota|2026-07-30|a2"
    jm._validation_jobs["j-idem"] = {
        "job_id": "j-idem",
        "type": "amortization_apply",
        "status": "completed",
        "process_key": pk,
        "result": {
            "status": "ok",
            "process_key": pk,
            "already_applied": True,
        },
        "finished_at": "2026-07-31T02:00:00-05:00",
    }
    assert jm.has_completed_amortization(pk) is True
    hit = jm.find_successful_amortization_by_process_key(pk)
    assert hit is not None
    assert hit["job_id"] == "j-idem"


def test_dry_run_completed_does_not_count_as_success() -> None:
    jm = get_job_manager()
    pk = "payment-validation|banco_bogota|2026-07-30|a3"
    jm._validation_jobs["j-dry"] = {
        "job_id": "j-dry",
        "type": "amortization_dry_run",
        "status": "completed",
        "process_key": pk,
        "result": {
            "status": "ok",
            "process_key": pk,
            "outcome": "applied",
            "already_applied": True,
            "process_control_estado": "AMORTIZACION_APLICADA",
        },
        "finished_at": "2026-07-31T03:00:00-05:00",
    }
    assert jm.has_completed_amortization(pk) is False
    assert jm.try_claim_amortization_for_process(pk) == "ok"
    jm.finish_amortization()


def test_requires_correction_does_not_count() -> None:
    jm = get_job_manager()
    pk = "payment-validation|banco_bogota|2026-07-30|a4"
    jm._validation_jobs["j-req-corr"] = {
        "job_id": "j-req-corr",
        "type": "amortization_apply",
        "status": "completed",
        "process_key": pk,
        "result": {
            "status": "ok",
            "process_key": pk,
            "outcome": "requires_correction",
        },
        "finished_at": "2026-07-31T04:00:00-05:00",
    }
    assert jm.has_completed_amortization(pk) is False
    assert jm.try_claim_amortization_for_process(pk) == "ok"
    jm.finish_amortization()


def test_input_changed_requires_retry_does_not_count() -> None:
    jm = get_job_manager()
    pk = "payment-validation|banco_bogota|2026-07-30|a5"
    jm._validation_jobs["j-input-changed"] = {
        "job_id": "j-input-changed",
        "type": "amortization_process",
        "status": "completed",
        "process_key": pk,
        "result": {
            "status": "ok",
            "process_key": pk,
            "outcome": "input_changed_requires_retry",
        },
        "finished_at": "2026-07-31T05:00:00-05:00",
    }
    assert jm.has_completed_amortization(pk) is False
    assert jm.try_claim_amortization_for_process(pk) == "ok"
    jm.finish_amortization()


def test_partial_outcome_does_not_count() -> None:
    jm = get_job_manager()
    pk = "payment-validation|banco_bogota|2026-07-30|a6"
    jm._validation_jobs["j-partial"] = {
        "job_id": "j-partial",
        "type": "amortization_apply",
        "status": "completed",
        "process_key": pk,
        "result": {
            "status": "ok",
            "process_key": pk,
            "outcome": "partial",
        },
        "finished_at": "2026-07-31T06:00:00-05:00",
    }
    assert jm.has_completed_amortization(pk) is False


def test_amortizacion_parcial_estado_does_not_count() -> None:
    jm = get_job_manager()
    pk = "payment-validation|banco_bogota|2026-07-30|a7"
    jm._validation_jobs["j-parcial"] = {
        "job_id": "j-parcial",
        "type": "amortization_apply",
        "status": "completed",
        "process_key": pk,
        "result": {
            "status": "partial",
            "process_key": pk,
            "process_control_estado": "AMORTIZACION_PARCIAL",
        },
        "finished_at": "2026-07-31T07:00:00-05:00",
    }
    assert jm.has_completed_amortization(pk) is False
    assert jm.try_claim_amortization_for_process(pk) == "ok"
    jm.finish_amortization()


def test_error_apply_estado_does_not_count() -> None:
    jm = get_job_manager()
    pk = "payment-validation|banco_bogota|2026-07-30|a8"
    jm._validation_jobs["j-error"] = {
        "job_id": "j-error",
        "type": "amortization_apply",
        "status": "completed",
        "process_key": pk,
        "result": {
            "status": "failed",
            "process_key": pk,
            "process_control_estado": "ERROR_APPLY",
        },
        "finished_at": "2026-07-31T08:00:00-05:00",
    }
    assert jm.has_completed_amortization(pk) is False


def test_amortizacion_aplicada_estado_counts_when_status_not_partial() -> None:
    jm = get_job_manager()
    pk = "payment-validation|banco_bogota|2026-07-30|a9"
    jm._validation_jobs["j-aplicada"] = {
        "job_id": "j-aplicada",
        "type": "amortization_apply",
        "status": "completed",
        "process_key": pk,
        "result": {
            "status": "ok",
            "process_key": pk,
            "process_control_estado": "AMORTIZACION_APLICADA",
        },
        "finished_at": "2026-07-31T09:00:00-05:00",
    }
    assert jm.has_completed_amortization(pk) is True
    assert jm.try_claim_amortization_for_process(pk) == "already_applied"


def test_can_apply_false_outcome_without_already_applied_does_not_count() -> None:
    jm = get_job_manager()
    pk = "payment-validation|banco_bogota|2026-07-30|a10"
    jm._validation_jobs["j-cannot"] = {
        "job_id": "j-cannot",
        "type": "amortization_apply",
        "status": "completed",
        "process_key": pk,
        "result": {
            "status": "ok",
            "process_key": pk,
            "can_apply": False,
            "already_applied": False,
        },
        "finished_at": "2026-07-31T10:00:00-05:00",
    }
    assert jm.has_completed_amortization(pk) is False


def test_failed_status_does_not_block_retry() -> None:
    jm = get_job_manager()
    pk = "payment-validation|banco_bogota|2026-07-30|a11"
    jm._validation_jobs["j-fail"] = {
        "job_id": "j-fail",
        "type": "amortization_apply",
        "status": "failed",
        "process_key": pk,
        "error": {"type": "JobInterruptedByProcessRestart"},
        "result": None,
    }
    assert jm.has_completed_amortization(pk) is False
    assert jm.try_claim_amortization_for_process(pk) == "ok"
    jm.finish_amortization()


def test_finish_amortization_releases_lock() -> None:
    jm = get_job_manager()
    assert jm.try_start_amortization() is True
    assert jm.is_amortization_active() is True
    jm.finish_amortization()
    assert jm.is_amortization_active() is False
    assert jm.try_start_merge() is True
    jm.finish_merge()


def test_any_mutation_active_includes_amortization() -> None:
    jm = get_job_manager()
    assert jm.is_generate_or_finalize_active() is False
    jm._amortization_active = True
    assert jm.is_generate_or_finalize_active() is True
    jm._amortization_active = False
    assert jm.is_generate_or_finalize_active() is False
