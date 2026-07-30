from __future__ import annotations

import pytest

from app.application.ui.download_limits import (
    UiDownloadTooLargeError,
    assert_download_size_allowed,
)
from app.application.ui.graph_endpoint import (
    UiGraphEndpointError,
    assert_relative_graph_endpoint,
)
from app.application.ui.process_key import (
    UiInvalidProcessKeyError,
    assert_ui_process_key,
)
from app.application.ui.read_cache import UiReadCache, build_cache_key


def test_cache_key_includes_env_site_drive_path() -> None:
    key = build_cache_key(
        environment="sandbox",
        site_id="site-1",
        drive_id="drive-1",
        relative_path="base/file.xlsx",
        kind="bytes",
    )
    assert key == "sandbox|site-1|drive-1|bytes|base/file.xlsx"


def test_cache_separated_by_environment() -> None:
    cache = UiReadCache(ttl_seconds=60)
    k_sb = build_cache_key(
        environment="sandbox",
        site_id="s",
        drive_id="d",
        relative_path="a.xlsx",
        kind="bytes",
    )
    k_pr = build_cache_key(
        environment="production",
        site_id="s",
        drive_id="d",
        relative_path="a.xlsx",
        kind="bytes",
    )
    cache.put(k_sb, b"sandbox-bytes", etag='"1"', environment="sandbox")
    cache.put(k_pr, b"prod-bytes", etag='"1"', environment="production")
    assert cache.get(k_sb, etag='"1"') == b"sandbox-bytes"
    assert cache.get(k_pr, etag='"1"') == b"prod-bytes"
    assert k_sb != k_pr


def test_cache_bind_environment_clears_on_switch() -> None:
    cache = UiReadCache(ttl_seconds=60)
    cache.bind_environment("sandbox")
    key = build_cache_key(
        environment="sandbox",
        site_id="s",
        drive_id="d",
        relative_path="a.xlsx",
        kind="meta",
    )
    cache.put(key, {"x": 1}, etag='"e"', environment="sandbox")
    assert cache.get(key, etag='"e"') == {"x": 1}
    cache.bind_environment("production")
    assert cache.get(key, etag='"e"') is None


def test_cache_etag_mismatch_miss() -> None:
    cache = UiReadCache(ttl_seconds=60)
    key = build_cache_key(
        environment="sandbox",
        site_id="s",
        drive_id="d",
        relative_path="a.xlsx",
        kind="bytes",
    )
    cache.put(key, b"old", etag='"v1"', environment="sandbox")
    assert cache.get(key, etag='"v2"') is None


def test_graph_endpoint_rejects_absolute_urls() -> None:
    with pytest.raises(UiGraphEndpointError) as exc:
        assert_relative_graph_endpoint("https://graph.microsoft.com/v1.0/sites/x")
    assert exc.value.reason == "graph_absolute_url_forbidden"


def test_graph_endpoint_allows_relative() -> None:
    ep = assert_relative_graph_endpoint("/sites/abc/drives/def/root:/folder/file.xlsx")
    assert ep.startswith("/sites/")


def test_download_size_limit() -> None:
    with pytest.raises(UiDownloadTooLargeError):
        assert_download_size_allowed("a.xlsx", 100, limit=50)


def test_process_key_rejects_graph_url() -> None:
    with pytest.raises(UiInvalidProcessKeyError):
        assert_ui_process_key("https://graph.microsoft.com/v1.0/me")
    with pytest.raises(UiInvalidProcessKeyError):
        assert_ui_process_key("/sites/xxx/drives/yyy/root:/secret")


def test_process_key_accepts_canonical() -> None:
    key = "payment-validation|banco_bancolombia|2026-07-29|abc-123"
    assert assert_ui_process_key(key) == key
