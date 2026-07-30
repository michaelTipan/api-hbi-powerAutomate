from __future__ import annotations

import asyncio
from typing import Any

import pytest

from app.adapters.secondary.ui_sharepoint_read import UiSharePointReadAdapter
from app.application.ui.download_limits import UiDownloadTooLargeError
from app.application.ui.graph_endpoint import UiGraphEndpointError, assert_relative_graph_endpoint
from app.application.ui.path_guard import UiAllowedRoots, UiPathEscapeError
from app.application.ui.ports import UiSharePointReadPort
from app.application.ui.read_cache import UiReadCache


_BANNED = (
    "upload",
    "put_bytes",
    "create_folder",
    "delete",
    "move",
    "rename",
    "copy",
    "patch_json",
    "post_json",
    "send_mail",
    "replace_content",
)


class _FakeHttp:
    def __init__(self) -> None:
        self.calls: list[str] = []

    async def get(self, endpoint: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        self.calls.append(endpoint)
        assert_relative_graph_endpoint(endpoint)
        return {
            "id": "item-1",
            "name": "file.xlsx",
            "webUrl": "https://contoso.sharepoint.com/sites/x/file.xlsx",
            "eTag": '"etag-1"',
            "cTag": '"ctag-1"',
            "size": 10,
            "lastModifiedDateTime": "2026-07-29T12:00:00Z",
        }

    async def get_bytes(self, endpoint: str, params: dict[str, Any] | None = None) -> bytes:
        self.calls.append(endpoint)
        assert_relative_graph_endpoint(endpoint)
        return b"0123456789"


def test_adapter_has_no_mutating_methods() -> None:
    for name in _BANNED:
        assert not hasattr(UiSharePointReadAdapter, name)


def test_port_protocol_only_exposes_read_ops() -> None:
    required = {
        "read_process_control",
        "get_item_meta",
        "download_bytes",
        "get_web_url",
        "read_merge_manifest_summary",
        "adelantados_meta",
    }
    for name in required:
        assert hasattr(UiSharePointReadPort, name)
    for name in _BANNED:
        assert name not in required
        assert not hasattr(UiSharePointReadPort, name)


def test_download_bytes_always_path_guarded(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ACTIVE_ENVIRONMENT", "sandbox")
    roots = UiAllowedRoots(environment="sandbox", roots=("base/sandbox",))
    http = _FakeHttp()
    adapter = UiSharePointReadAdapter(
        http,
        cache=UiReadCache(ttl_seconds=60),
        allowed_roots=roots,
        site_search="Operaciones",
        drive_name="Documentos",
        max_download_bytes=1024,
    )

    async def _fake_resolve(http_client, site_search, drive_name, relative_path):
        return {"site_id": "site-A", "drive_id": "drive-A", "item_path": relative_path}

    monkeypatch.setattr(
        "app.adapters.secondary.ui_sharepoint_read.resolve_sharepoint_path",
        _fake_resolve,
    )

    with pytest.raises(UiPathEscapeError):
        asyncio.run(adapter.download_bytes("../outside.xlsx"))

    content = asyncio.run(adapter.download_bytes("base/sandbox/file.xlsx"))
    assert content.content == b"0123456789"
    assert all(not c.startswith("http") for c in http.calls)


def test_download_bytes_enforces_size_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ACTIVE_ENVIRONMENT", "sandbox")
    roots = UiAllowedRoots(environment="sandbox", roots=("base/sandbox",))
    http = _FakeHttp()
    adapter = UiSharePointReadAdapter(
        http,
        cache=UiReadCache(ttl_seconds=60),
        allowed_roots=roots,
        max_download_bytes=5,
    )

    async def _fake_resolve(http_client, site_search, drive_name, relative_path):
        return {"site_id": "site-A", "drive_id": "drive-A"}

    monkeypatch.setattr(
        "app.adapters.secondary.ui_sharepoint_read.resolve_sharepoint_path",
        _fake_resolve,
    )
    with pytest.raises(UiDownloadTooLargeError):
        asyncio.run(adapter.download_bytes("base/sandbox/file.xlsx"))


def test_adapter_rejects_absolute_graph_endpoint_helper() -> None:
    with pytest.raises(UiGraphEndpointError):
        assert_relative_graph_endpoint("https://graph.microsoft.com/v1.0/me")
