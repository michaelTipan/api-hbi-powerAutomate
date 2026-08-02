"""Tests de bitácora de ejecución (flag off = sin efectos; flat day + archivo por step)."""

from __future__ import annotations

import json
from datetime import date
from typing import Any

import pytest

from app.application.services.execution_log_sanitizer import sanitize_for_execution_log
from app.application.services.execution_run_log import (
    build_execution_log_relative_path,
    filename_result_token,
    initialize_execution_log,
    record_execution_event,
    recompute_summary,
    should_reuse_execution_id,
)


def test_sanitize_redacts_secrets_and_truncates():
    payload = {
        "client_secret": "super-secret",
        "authorization": "Bearer xyz",
        "ok": "value",
        "long": "x" * 5000,
    }
    out = sanitize_for_execution_log(payload)
    assert out["client_secret"] == "<redacted>"
    assert out["authorization"] == "<redacted>"
    assert out["ok"] == "value"
    assert out["long"].endswith("...")
    assert len(out["long"]) <= 4000


def test_build_path_dated_hierarchy_with_step_and_result(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv(
        "PAYMENT_VALIDATION_BASE_FOLDER",
        "INFORMACION CREDITOS-CLIENTES/01 VALIDACION PAGOS",
    )
    monkeypatch.delenv("GRAPH_EXECUTION_RUN_LOGS_PATH", raising=False)
    monkeypatch.delenv("PAYMENT_VALIDATION_EXECUTION_LOGS_FOLDER", raising=False)
    from datetime import datetime
    from zoneinfo import ZoneInfo

    when = datetime(2026, 7, 28, 19, 15, 30, tzinfo=ZoneInfo("America/Bogota"))
    path = build_execution_log_relative_path(
        bank_code="banco_bogota",
        day=date(2026, 7, 28),
        execution_id="a81f2c9e-1111-2222-3333-444444444444",
        step="GENERATE",
        result="FAILED",
        when=when,
    )
    norm = path.replace("\\", "/")
    assert "/06 LOGS/2026/07/2026-07-28/" in norm
    assert "lote_" not in norm
    assert norm.endswith(
        "execution_log_banco_bogota_20260728_191530_generate_FAILED_a81f2c9e.json"
    )


def test_filename_result_token_mapping():
    assert filename_result_token("QUEUED") == "STARTED"
    assert filename_result_token("STARTED") == "STARTED"
    assert filename_result_token("SUCCEEDED") == "SUCCEEDED"
    assert filename_result_token("SKIPPED_IDEMPOTENT") == "SUCCEEDED"
    assert filename_result_token("FAILED") == "FAILED"
    assert filename_result_token("BLOCKED") == "FAILED"
    assert filename_result_token("PARTIAL") == "PARTIAL"
    assert filename_result_token("REQUEST_REJECTED") == "REJECTED"


def test_should_reuse_execution_id_rules():
    assert should_reuse_execution_id(
        existing_execution_id="e1", is_active=True, estado_proceso="REVISION_CREADA"
    )
    assert should_reuse_execution_id(
        existing_execution_id="e1", is_active=False, estado_proceso="VACIO"
    )
    assert should_reuse_execution_id(
        existing_execution_id="e1", is_active=False, estado_proceso="ERROR_GENERATE"
    )
    assert not should_reuse_execution_id(
        existing_execution_id="e1",
        is_active=False,
        estado_proceso="AMORTIZACION_APLICADA",
    )
    assert not should_reuse_execution_id(
        existing_execution_id="", is_active=False, estado_proceso="VACIO"
    )


def test_recompute_summary_waiting_after_generate():
    events = [
        {"step": "GENERATE", "status": "STARTED", "attempt": 1},
        {"step": "GENERATE", "status": "SUCCEEDED", "attempt": 1},
    ]
    summary = recompute_summary(events)
    assert summary["overall_status"] == "WAITING_FOR_NEXT_STEP"
    assert summary["next_expected_step"] == "FINALIZE"
    assert summary["waiting_for"] == "SECRETARY_REVIEW"


def test_recompute_summary_succeeded_only_after_apply():
    events = [
        {"step": "GENERATE", "status": "SUCCEEDED", "attempt": 1},
        {"step": "FINALIZE", "status": "SUCCEEDED", "attempt": 1},
        {"step": "NOTIFY", "status": "SUCCEEDED", "attempt": 1},
        {"step": "MERGE", "status": "SUCCEEDED", "attempt": 1},
        {"step": "DRY_RUN", "status": "SUCCEEDED", "attempt": 1},
        {"step": "APPLY", "status": "SUCCEEDED", "attempt": 1},
    ]
    summary = recompute_summary(events)
    assert summary["overall_status"] == "SUCCEEDED"


def test_flag_off_initialize_is_noop(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("EXECUTION_RUN_LOG_ENABLED", raising=False)

    class _Graph:
        async def put_bytes(self, *a: Any, **k: Any) -> dict[str, Any]:
            raise AssertionError("no debe escribir con flag off")

        async def get(self, *a: Any, **k: Any) -> dict[str, Any]:
            raise AssertionError("no debe leer con flag off")

        async def get_bytes(self, *a: Any, **k: Any) -> bytes:
            raise AssertionError("no")

        async def post_json(self, *a: Any, **k: Any) -> tuple[dict[str, Any], int]:
            raise AssertionError("no")

    import asyncio

    out = asyncio.run(
        initialize_execution_log(
            _Graph(),  # type: ignore[arg-type]
            "site",
            "drive",
            execution_id="e1",
            bank_code="banco_bogota",
            process_date=date(2026, 7, 28),
            job_id="j1",
        )
    )
    assert out["execution_log_status"] == "DISABLED"


def test_initialize_and_record_terminal_creates_separate_files(
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setenv("EXECUTION_RUN_LOG_ENABLED", "true")
    monkeypatch.setenv("PAYMENT_VALIDATION_BASE_FOLDER", "base")
    store: dict[str, bytes] = {}

    class _Graph:
        async def post_json(self, endpoint: str, body: dict[str, Any]) -> tuple[dict[str, Any], int]:
            return {}, 201

        async def put_bytes(
            self,
            endpoint: str,
            content: bytes,
            content_type: str = "application/octet-stream",
            if_match: str | None = None,
        ) -> dict[str, Any]:
            store[endpoint] = content
            return {"eTag": '"1"'}

        async def get(self, endpoint: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
            return {"eTag": '"1"'}

        async def get_bytes(self, endpoint: str, params: dict[str, Any] | None = None) -> bytes:
            if endpoint not in store:
                raise FileNotFoundError(endpoint)
            return store[endpoint]

    import asyncio

    async def _run() -> None:
        g = _Graph()
        init = await initialize_execution_log(
            g,  # type: ignore[arg-type]
            "s",
            "d",
            execution_id="aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
            bank_code="banco_bogota",
            process_date=date(2026, 7, 28),
            job_id="job-1",
        )
        assert init["execution_log_status"] == "OK"
        assert "2026-07-28" in init["execution_log_path"]
        assert "lote_" not in init["execution_log_path"]
        assert "_generate_STARTED_" in init["execution_log_path"].replace("\\", "/")

        started = await record_execution_event(
            g,  # type: ignore[arg-type]
            "s",
            "d",
            execution_id=init["execution_id"],
            execution_log_path=init["execution_log_path"],
            step="GENERATE",
            status="STARTED",
            job_id="job-1",
            bank_code="banco_bogota",
        )
        assert started["execution_log_status"] == "OK"
        assert "_generate_STARTED_" in started["execution_log_path"].replace("\\", "/")

        failed = await record_execution_event(
            g,  # type: ignore[arg-type]
            "s",
            "d",
            execution_id=init["execution_id"],
            execution_log_path=started["execution_log_path"],
            step="GENERATE",
            status="FAILED",
            job_id="job-1",
            bank_code="banco_bogota",
            error={"error_code": "review_folder_not_empty"},
        )
        assert failed["execution_log_status"] == "OK"
        assert "_generate_FAILED_" in failed["execution_log_path"].replace("\\", "/")
        assert failed["execution_log_path"] != started["execution_log_path"]
        # Conserva el STARTED y crea el FAILED
        assert len(store) >= 2
        failed_docs = [
            json.loads(content.decode("utf-8"))
            for content in store.values()
            if b'"status": "FAILED"' in content
        ]
        assert failed_docs
        doc = failed_docs[-1]
        assert doc["execution_id"] == "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
        statuses = [e["status"] for e in doc["events"]]
        assert "FAILED" in statuses

    asyncio.run(_run())
