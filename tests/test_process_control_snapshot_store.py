"""read/update de Control con fake Graph + store en temp dir."""

from __future__ import annotations

import asyncio
from pathlib import Path
from urllib.parse import unquote

import pytest

from app.application.use_cases.payment_validation_process_control import (
    read_process_control_record,
    read_process_control_snapshot,
    update_process_control_row2,
)
from app.application.use_cases.setup_merge_control_workbook import (
    _build_process_control_workbook_bytes,
)


class _FakeGraph:
    def __init__(self, files: dict[str, bytes]) -> None:
        self.files = dict(files)
        self.get_calls = 0
        self.put_calls = 0

    def _path(self, endpoint: str) -> str:
        return unquote(endpoint.split("/root:/", 1)[1].rsplit(":/content", 1)[0]).strip("/")

    async def get_bytes(self, endpoint: str, params=None) -> bytes:
        self.get_calls += 1
        path = self._path(endpoint)
        if path not in self.files:
            raise FileNotFoundError(path)
        return self.files[path]

    async def put_bytes(self, endpoint: str, content: bytes, content_type: str = "", if_match=None):
        self.put_calls += 1
        self.files[self._path(endpoint)] = content
        return {}


def _workbook() -> bytes:
    return _build_process_control_workbook_bytes("banco_bogota", "Banco de Bogotá")


def _rel_path() -> str:
    from app.application.use_cases.payment_validation_process_control import (
        resolve_process_control_path_for_bank,
    )

    return resolve_process_control_path_for_bank("banco_bogota").strip().strip("/")


@pytest.fixture
def graph() -> _FakeGraph:
    return _FakeGraph({_rel_path(): _workbook()})


def test_excel_mode_always_hits_graph(graph: _FakeGraph, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PROCESS_CONTROL_STORE", "excel")
    monkeypatch.setenv("ACTIVE_ENVIRONMENT", "sandbox")

    async def _run() -> None:
        snap1 = await read_process_control_snapshot(
            graph, "site", "drive", bank_code="banco_bogota"
        )
        snap2 = await read_process_control_snapshot(
            graph, "site", "drive", bank_code="banco_bogota"
        )
        assert snap1.estado_proceso
        assert snap2.bank_code == "banco_bogota"
        assert graph.get_calls == 2
        assert graph.put_calls == 0

    asyncio.run(_run())


def test_dual_bootstraps_once_then_reads_disk(
    graph: _FakeGraph, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("PROCESS_CONTROL_STORE", "dual")
    monkeypatch.setenv("ACTIVE_ENVIRONMENT", "sandbox")

    async def _run() -> None:
        rec1 = await read_process_control_record(
            graph, "site", "drive", bank_code="banco_bogota"
        )
        assert rec1.source == "excel"
        first_gets = graph.get_calls
        rec2 = await read_process_control_record(
            graph, "site", "drive", bank_code="banco_bogota"
        )
        assert rec2.source == "disk"
        assert graph.get_calls == first_gets

    asyncio.run(_run())


def test_dual_update_writes_excel_and_disk(
    graph: _FakeGraph, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("PROCESS_CONTROL_STORE", "dual")
    monkeypatch.setenv("ACTIVE_ENVIRONMENT", "sandbox")

    async def _run() -> None:
        await update_process_control_row2(
            graph,
            "site",
            "drive",
            bank_code="banco_bogota",
            updates={"EstadoProceso": "REVISION_CREADA", "GenerateJobId": "job-gen-1"},
        )
        assert graph.put_calls == 1
        rec = await read_process_control_record(
            graph, "site", "drive", bank_code="banco_bogota"
        )
        assert rec.source == "disk"
        assert rec.snapshot.estado_proceso == "REVISION_CREADA"
        assert rec.cells.get("GenerateJobId") == "job-gen-1"
        # Lectura posterior no vuelve a Graph.
        gets_after_update_read = graph.get_calls
        snap = await read_process_control_snapshot(
            graph, "site", "drive", bank_code="banco_bogota"
        )
        assert snap.estado_proceso == "REVISION_CREADA"
        assert graph.get_calls == gets_after_update_read

    asyncio.run(_run())


def test_local_update_skips_excel_put(
    graph: _FakeGraph, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("PROCESS_CONTROL_STORE", "local")
    monkeypatch.setenv("ACTIVE_ENVIRONMENT", "sandbox")

    async def _run() -> None:
        await update_process_control_row2(
            graph,
            "site",
            "drive",
            bank_code="banco_bogota",
            updates={"EstadoProceso": "FINALIZADO"},
        )
        assert graph.put_calls == 0
        rec = await read_process_control_record(
            graph, "site", "drive", bank_code="banco_bogota"
        )
        assert rec.source == "disk"
        assert rec.snapshot.estado_proceso == "FINALIZADO"

    asyncio.run(_run())


def test_disk_write_failure_does_not_raise(
    graph: _FakeGraph, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("PROCESS_CONTROL_STORE", "dual")
    monkeypatch.setenv("ACTIVE_ENVIRONMENT", "sandbox")
    blocker = tmp_path / "not_a_dir"
    blocker.write_text("x", encoding="utf-8")
    monkeypatch.setenv("PAYMENT_VALIDATION_CONTROL_STORE_DIR", str(blocker))

    async def _run() -> None:
        await update_process_control_row2(
            graph,
            "site",
            "drive",
            bank_code="banco_bogota",
            updates={"EstadoProceso": "GENERANDO"},
        )
        assert graph.put_calls == 1

    asyncio.run(_run())
