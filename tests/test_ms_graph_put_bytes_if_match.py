"""Adapter Graph real: If-Match en PUT."""

from __future__ import annotations

import asyncio

import httpx

from app.adapters.secondary.ms_graph_client import MsGraphClient


def test_put_bytes_sends_if_match_http_header(monkeypatch):
    captured: dict[str, object] = {}

    class _Resp:
        status_code = 200

        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict:
            return {"id": "ok"}

    class _Client:
        def __init__(self, *a, **k) -> None:
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return None

        async def put(self, url, headers=None, content=None):
            captured["url"] = url
            captured["headers"] = dict(headers or {})
            captured["content"] = content
            return _Resp()

    monkeypatch.setattr(httpx, "AsyncClient", _Client)

    client = MsGraphClient()

    async def _token() -> str:
        return "token-test"

    monkeypatch.setattr(client, "_get_access_token", _token)
    asyncio.run(client.put_bytes("/drives/x/root:/f.xlsx:/content", b"abc", if_match='"etag-9"'))
    headers = captured["headers"]
    assert isinstance(headers, dict)
    assert headers.get("If-Match") == '"etag-9"'
    assert headers.get("Authorization") == "Bearer token-test"


def test_put_bytes_omits_if_match_when_absent(monkeypatch):
    captured: dict[str, object] = {}

    class _Resp:
        status_code = 200

        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict:
            return {}

    class _Client:
        def __init__(self, *a, **k) -> None:
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return None

        async def put(self, url, headers=None, content=None):
            captured["headers"] = dict(headers or {})
            return _Resp()

    monkeypatch.setattr(httpx, "AsyncClient", _Client)
    client = MsGraphClient()

    async def _token() -> str:
        return "t"

    monkeypatch.setattr(client, "_get_access_token", _token)
    asyncio.run(client.put_bytes("/x", b"z"))
    headers = captured["headers"]
    assert isinstance(headers, dict)
    assert "If-Match" not in headers
