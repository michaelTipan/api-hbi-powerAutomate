"""Graph DELETE: reintentos ante 423 Locked."""

from __future__ import annotations

import asyncio

import httpx
import pytest

from app.adapters.secondary.ms_graph_client import MsGraphClient


def test_delete_succeeds_on_second_attempt_after_423(monkeypatch):
    calls: list[int] = []

    class _Resp:
        def __init__(self, status_code: int) -> None:
            self.status_code = status_code
            self.text = ""
            self.request = httpx.Request("DELETE", "https://graph.test/x")

        def raise_for_status(self) -> None:
            if self.status_code >= 400:
                raise httpx.HTTPStatusError(
                    "err",
                    request=self.request,
                    response=self,
                )

    class _Client:
        def __init__(self, *a, **k) -> None:
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return None

        async def delete(self, url, headers=None):
            calls.append(1)
            if len(calls) == 1:
                return _Resp(423)
            return _Resp(204)

    sleeps: list[float] = []

    async def _fake_sleep(delay: float) -> None:
        sleeps.append(delay)

    monkeypatch.setattr(httpx, "AsyncClient", _Client)
    monkeypatch.setattr(asyncio, "sleep", _fake_sleep)
    monkeypatch.setenv("GRAPH_DELETE_MAX_RETRIES", "4")
    monkeypatch.setenv("GRAPH_DELETE_RETRY_BASE_SECONDS", "2.5")

    client = MsGraphClient()

    async def _token() -> str:
        return "token-test"

    monkeypatch.setattr(client, "_get_access_token", _token)
    asyncio.run(client.delete("/drives/x/root:/f.xlsx:"))
    assert len(calls) == 2
    assert len(sleeps) == 1


def test_delete_raises_after_max_423_retries(monkeypatch):
    calls: list[int] = []

    class _Resp:
        status_code = 423
        text = "Locked"
        request = httpx.Request("DELETE", "https://graph.test/x")

    class _Client:
        def __init__(self, *a, **k) -> None:
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return None

        async def delete(self, url, headers=None):
            calls.append(1)
            return _Resp()

    monkeypatch.setattr(httpx, "AsyncClient", _Client)
    monkeypatch.setenv("GRAPH_DELETE_MAX_RETRIES", "3")

    client = MsGraphClient()

    async def _token() -> str:
        return "t"

    async def _no_sleep(_delay: float) -> None:
        return None

    monkeypatch.setattr(client, "_get_access_token", _token)
    monkeypatch.setattr(asyncio, "sleep", _no_sleep)

    with pytest.raises(httpx.HTTPStatusError) as exc:
        asyncio.run(client.delete("/x"))
    assert exc.value.response.status_code == 423
    assert len(calls) == 3
