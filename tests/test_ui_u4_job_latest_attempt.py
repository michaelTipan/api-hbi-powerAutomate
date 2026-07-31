"""U4-A: JobManager.find_latest_job_by_process_and_types + parseo seguro."""
from __future__ import annotations

import asyncio

import pytest

from app.application.job_manager import get_job_manager
from app.application.ui.job_stage_types import STAGE_JOB_TYPES
from app.application.ui.last_attempt import parse_finalize_error_details


@pytest.fixture()
def jm(tmp_path, monkeypatch: pytest.MonkeyPatch):
    import app.application.job_manager as jm_mod

    monkeypatch.setattr(jm_mod, "_jobs_dir", lambda: tmp_path / "jobs")
    (tmp_path / "jobs").mkdir(parents=True, exist_ok=True)
    manager = get_job_manager()
    manager._validation_jobs.clear()
    yield manager
    manager._validation_jobs.clear()


def test_find_latest_by_process_ignores_other_key(jm) -> None:
    pk = "payment-validation|banco_bogota|2026-07-30|aaa"
    other = "payment-validation|banco_bogota|2026-07-30|bbb"

    async def _seed() -> None:
        await jm.set_job(
            "j-old",
            {
                "job_id": "j-old",
                "type": "finalize",
                "status": "failed",
                "process_key": pk,
                "finished_at": "2026-07-31T10:00:00-05:00",
            },
        )
        await jm.set_job(
            "j-other",
            {
                "job_id": "j-other",
                "type": "finalize",
                "status": "failed",
                "process_key": other,
                "finished_at": "2026-07-31T12:00:00-05:00",
            },
        )
        await jm.set_job(
            "j-new",
            {
                "job_id": "j-new",
                "type": "finalize",
                "status": "failed",
                "process_key": pk,
                "finished_at": "2026-07-31T11:00:00-05:00",
            },
        )

    asyncio.run(_seed())
    latest = jm.find_latest_job_by_process_and_types(pk, STAGE_JOB_TYPES["finalize"])
    assert latest is not None
    assert latest["job_id"] == "j-new"


def test_find_latest_does_not_treat_old_as_active(jm) -> None:
    pk = "payment-validation|banco_bancolombia|2026-07-29|abc-123"

    async def _seed() -> None:
        await jm.set_job(
            "j-done",
            {
                "job_id": "j-done",
                "type": "finalize",
                "status": "failed",
                "process_key": pk,
                "finished_at": "2026-07-31T09:00:00-05:00",
            },
        )

    asyncio.run(_seed())
    latest = jm.find_latest_job_by_process_and_types(
        pk, ("finalize",), statuses=("queued", "running")
    )
    assert latest is None
    terminal = jm.find_latest_job_by_process_and_types(pk, ("finalize",))
    assert terminal is not None
    assert terminal["status"] == "failed"


def test_parse_valid_codigo_json() -> None:
    parsed = parse_finalize_error_details(
        {
            "error": {
                "message": (
                    'invalid_estado_pago|{"excel_row":8,"field":"Estado Pago",'
                    '"value_found":"PAGADO","sheet":"Distribucion_Pagos"}'
                ),
                "user_message": "msg",
                "next_action": "next",
            }
        }
    )
    assert parsed["error_code"] == "invalid_estado_pago"
    assert parsed["details"]["excel_row"] == 8
    assert parsed["details"]["field"] == "Estado Pago"


def test_parse_corrupt_json_keeps_code_without_crash() -> None:
    parsed = parse_finalize_error_details(
        {
            "error": {
                "message": "invalid_estado_pago|{not-json",
                "user_message": "Mensaje general seguro",
                "next_action": "Corrija y reintente",
            }
        }
    )
    assert parsed["error_code"] == "invalid_estado_pago"
    assert parsed["details"] == {}
    assert parsed["user_message"] == "Mensaje general seguro"
