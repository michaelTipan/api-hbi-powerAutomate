"""Prueba de mecanismo: trabajo sync en el event loop impide atender GET /jobs.

Reproduce la causa raíz del 502 en Azure (1 worker gunicorn+uvicorn):
Generate corre como BackgroundTask en el mismo loop; openpyxl/PDF sync
congelan el loop y el gateway responde 502 al poll mientras el job sigue OK.
"""
from __future__ import annotations

import asyncio
import time


def test_sync_work_in_async_task_starves_concurrent_job_poll() -> None:
    """Sin to_thread, el trabajo sync de Generate corre antes que GET /jobs."""

    async def _run() -> None:
        markers: list[str] = []

        async def fake_generate_sync_excel() -> None:
            markers.append("generate_enter")
            # Equivalente a openpyxl.Workbook()/save() dentro de generate async.
            time.sleep(0.2)
            markers.append("generate_done")

        async def fake_get_jobs() -> None:
            markers.append("jobs_ok")

        t0 = time.perf_counter()
        await asyncio.gather(
            asyncio.create_task(fake_generate_sync_excel()),
            asyncio.create_task(fake_get_jobs()),
        )
        elapsed = time.perf_counter() - t0

        assert markers == ["generate_enter", "generate_done", "jobs_ok"]
        assert elapsed >= 0.15

    asyncio.run(_run())


def test_to_thread_keeps_job_poll_responsive() -> None:
    """Con to_thread, GET /jobs responde mientras Excel/PDF corren fuera del loop."""

    async def _run() -> None:
        markers: list[str] = []

        async def fake_generate_offloaded() -> None:
            markers.append("generate_enter")
            await asyncio.to_thread(time.sleep, 0.2)
            markers.append("generate_done")

        async def fake_get_jobs() -> None:
            await asyncio.sleep(0.01)
            markers.append("jobs_ok")

        t0 = time.perf_counter()
        await asyncio.gather(
            asyncio.create_task(fake_generate_offloaded()),
            asyncio.create_task(fake_get_jobs()),
        )
        elapsed = time.perf_counter() - t0

        assert markers[0] == "generate_enter"
        assert "jobs_ok" in markers
        assert markers.index("jobs_ok") < markers.index("generate_done")
        assert elapsed >= 0.15

    asyncio.run(_run())
