"""Generate con la configuración real de sitio (hostname/path) y Control local.

Sin mocks de ``announce_control_generate_failed``: el fallo técnico tras anunciar
GENERANDO debe dejar el Control en ERROR_GENERATE a través de la cola real.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from urllib.parse import unquote

import pytest
from fastapi import BackgroundTasks

from app.application.job_manager import JobManager
from app.application.services.generate_queue_service import GenerateQueueService
from app.application.use_cases.payment_validation_process_control import (
    read_process_control_snapshot,
    update_process_control_row2,
)
from tests.bank_upload_scenarios import PROCESS_DATE, build_bank_excel
from tests.test_cancel_process_control import MockGraphClientCancel

BANK = "banco_bogota"


class RealConfigGraph(MockGraphClientCancel):
    """Graph falso que resuelve el sitio por hostname/path (sin búsqueda de texto)."""

    def __init__(self) -> None:
        super().__init__()
        self.fail_clients_listing = False

    async def get(self, endpoint: str, params=None):
        if endpoint == "/sites":
            raise AssertionError("no debe buscar el sitio por texto")
        if endpoint.startswith("/sites/contoso.sharepoint.com:"):
            return {"id": "dummy_site"}
        if self.fail_clients_listing and endpoint.endswith(":/children"):
            path = unquote(endpoint.split("/root:/", 1)[1].rsplit(":/children", 1)[0])
            if path == "clientes":
                raise RuntimeError("graph_timeout")
        return await super().get(endpoint, params=params)


def set_real_config_env(monkeypatch: pytest.MonkeyPatch, store_dir: Path) -> None:
    for key in ("GRAPH_SHAREPOINT_SITE_SEARCH", "GRAPH_SHAREPOINT_DRIVE_NAME"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("GRAPH_OPERATIONS_SITE_HOSTNAME", "contoso.sharepoint.com")
    monkeypatch.setenv("GRAPH_OPERATIONS_SITE_PATH", "sites/HBI")
    monkeypatch.setenv("GRAPH_OPERATIONS_DRIVE_NAME", "DRIVE")
    monkeypatch.setenv("GRAPH_PAYMENT_VALIDATION_REVIEW_PATH", "revision")
    monkeypatch.setenv("GRAPH_CLIENTS_BASE_PATH", "clientes")
    monkeypatch.setenv("GRAPH_VALIDATION_FILE_PREFIX", "val")
    monkeypatch.setenv("GRAPH_BANK_PAYMENTS_FILE_PATH", "banco.xlsx")
    monkeypatch.setenv("GRAPH_BANK_PAYMENTS_FILE_PATH_BANCOLOMBIA", "banco.xlsx")
    monkeypatch.setenv("ACTIVE_ENVIRONMENT", "sandbox")
    monkeypatch.setenv("PROCESS_CONTROL_STORE", "local")
    monkeypatch.setenv("PAYMENT_VALIDATION_CONTROL_STORE_DIR", str(store_dir))


@pytest.fixture
def fresh_job_manager(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    monkeypatch.setenv("PAYMENT_VALIDATION_JOBS_DIR", str(tmp_path / "jobs"))
    JobManager._instance = None
    yield JobManager()
    JobManager._instance = None


def run_queue(graph, jm: JobManager, *, force_regenerate: bool = False) -> str:
    async def _run() -> str:
        svc = GenerateQueueService(jm)
        bg = BackgroundTasks()
        accepted = await svc.enqueue(
            graph=graph,
            background_tasks=bg,
            bank_code=BANK,
            process_date=PROCESS_DATE,
            trigger_source="web_ui",
            force_regenerate=force_regenerate,
        )
        await bg()
        return accepted.job_id

    return asyncio.run(_run())


def control_estado(graph) -> tuple[str, bool]:
    snap = asyncio.run(read_process_control_snapshot(graph, "s", "d", bank_code=BANK))
    return snap.estado_proceso, snap.is_active


def test_technical_failure_after_generando_leaves_error_generate(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, fresh_job_manager: JobManager
) -> None:
    set_real_config_env(monkeypatch, tmp_path / "control")
    graph = RealConfigGraph()
    graph.downloaded_files["banco.xlsx"] = build_bank_excel()
    graph.fail_clients_listing = True

    job_id = run_queue(graph, fresh_job_manager)

    job = fresh_job_manager.get_job(job_id)
    assert job["status"] == "failed"
    assert job["error"]["message"] == "graph_timeout"
    estado, active = control_estado(graph)
    assert estado == "ERROR_GENERATE"
    assert active is True
    assert fresh_job_manager.is_generate_or_finalize_active() is False


def test_failure_before_announcing_keeps_previous_control(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, fresh_job_manager: JobManager
) -> None:
    set_real_config_env(monkeypatch, tmp_path / "control")
    graph = RealConfigGraph()
    graph.downloaded_files["banco.xlsx"] = build_bank_excel()
    asyncio.run(
        update_process_control_row2(
            graph,
            "s",
            "d",
            bank_code=BANK,
            updates={
                "EstadoProceso": "REVISION_CREADA",
                "IsActive": True,
                "ProcessKey": "payment-validation|banco_bogota|2025-12-30|old12345",
                "ValidationFilePath": "revision/val_old12345.xlsx",
            },
        )
    )
    graph.downloaded_files["revision/val_old12345.xlsx"] = b"x"

    job_id = run_queue(graph, fresh_job_manager)

    job = fresh_job_manager.get_job(job_id)
    assert job["status"] == "failed"
    assert job["error"]["message"].startswith("active_process_exists|")
    assert control_estado(graph) == ("REVISION_CREADA", True)
