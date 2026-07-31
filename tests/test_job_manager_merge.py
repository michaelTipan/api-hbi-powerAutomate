"""Tests JobManager Merge: claim, evidencia, mutex compartido."""
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
    yield
    JobManager._instance = None


def test_merge_blocks_generate_and_notify() -> None:
    jm = get_job_manager()
    assert jm.try_start_merge() is True
    assert jm.try_start_generate() is False
    assert jm.try_start_finalize() is False
    assert jm.try_start_notify() is False
    assert jm.try_claim_merge_for_process("pk") == "busy"
    jm.finish_merge()
    assert jm.try_start_generate() is True
    jm.finish_generate()


def test_generate_blocks_merge() -> None:
    jm = get_job_manager()
    assert jm.try_start_generate() is True
    assert jm.try_claim_merge_for_process("pk-a") == "busy"
    jm.finish_generate()
    assert jm.try_claim_merge_for_process("pk-a") == "ok"
    jm.finish_merge()


def test_has_completed_merge_requires_consolidado_not_parcial() -> None:
    jm = get_job_manager()
    pk = "payment-validation|banco_bogota|2026-07-30|m1"
    jm._validation_jobs["j-partial"] = {
        "job_id": "j-partial",
        "type": "merge_composite_validado_pdfs",
        "status": "completed",
        "process_key": pk,
        "result": {
            "status": "ok",
            "process_key": pk,
            "process_control_estado": "MERGE_PARCIAL",
            "skipped_count": 2,
            "file_action": "partial",
        },
        "finished_at": "2026-07-31T01:00:00-05:00",
    }
    assert jm.has_completed_merge(pk) is False
    assert jm.try_claim_merge_for_process(pk) == "ok"
    jm.finish_merge()

    jm._validation_jobs["j-ok"] = {
        "job_id": "j-ok",
        "type": "merge_composite_validado_pdfs",
        "status": "completed",
        "process_key": pk,
        "result": {
            "status": "ok",
            "process_key": pk,
            "process_control_estado": "CONSOLIDADO",
            "already_merged": False,
            "skipped_count": 0,
            "file_action": "created",
        },
        "finished_at": "2026-07-31T02:00:00-05:00",
    }
    assert jm.has_completed_merge(pk) is True
    assert jm.try_claim_merge_for_process(pk) == "already_merged"
    assert jm.try_claim_merge_for_process(pk, force_rebuild=True) == "ok"
    jm.finish_merge()


def test_failed_and_interrupted_do_not_block_retry() -> None:
    jm = get_job_manager()
    pk = "payment-validation|banco_bogota|2026-07-30|m2"
    jm._validation_jobs["j-fail"] = {
        "job_id": "j-fail",
        "type": "merge_composite_validado_pdfs",
        "status": "failed",
        "process_key": pk,
        "error": {"type": "JobInterruptedByProcessRestart"},
        "result": None,
    }
    assert jm.has_completed_merge(pk) is False
    assert jm.try_claim_merge_for_process(pk) == "ok"
    jm.finish_merge()


def test_already_merged_flag_in_result_counts() -> None:
    jm = get_job_manager()
    pk = "payment-validation|banco_bogota|2026-07-30|m3"
    jm._validation_jobs["j-idem"] = {
        "job_id": "j-idem",
        "type": "merge_composite_validado_pdfs",
        "status": "completed",
        "process_key": pk,
        "result": {
            "status": "ok",
            "process_key": pk,
            "already_merged": True,
            "pdf_reused": True,
        },
        "finished_at": "2026-07-31T03:00:00-05:00",
    }
    assert jm.has_completed_merge(pk) is True
    hit = jm.find_successful_merge_by_process_key(pk)
    assert hit is not None
    assert hit["job_id"] == "j-idem"
