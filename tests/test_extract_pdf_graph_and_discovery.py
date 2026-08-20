"""Reintentos Graph en descarga de extractos y discovery de créditos."""
from __future__ import annotations

import asyncio

import httpx
import pytest

from app.application.services.extract_pdf_graph import (
    get_graph_bytes_with_retry,
    graph_download_error_detail,
    is_transient_graph_download_error,
)
from app.application.use_cases.payment_validation_generate import (
    _is_asientos_contables_cred_folder,
    _is_infra_folder,
    _looks_like_standard_credit_folder,
)


def test_asientos_contables_cred_folder_is_infra_not_credit_unit() -> None:
    assert _is_asientos_contables_cred_folder("ASIENTOS CONTABLES CRED 248")
    assert _is_infra_folder("ASIENTOS CONTABLES CRED 248")
    # El nombre contiene «248» (looks_like_standard), pero infra lo omite antes.
    assert _looks_like_standard_credit_folder("ASIENTOS CONTABLES CRED 248")


def test_credito_folder_still_operational() -> None:
    assert not _is_infra_folder("CREDITO # 248 VIGENTE")
    assert _looks_like_standard_credit_folder("CREDITO # 248 VIGENTE")


def test_graph_download_retries_transient_then_succeeds() -> None:
    calls = {"n": 0}
    payload = b"%PDF-1.4 ok"

    class _Client:
        async def get_bytes(self, _endpoint: str) -> bytes:
            calls["n"] += 1
            if calls["n"] < 3:
                req = httpx.Request("GET", "https://graph.example/content")
                resp = httpx.Response(503, request=req)
                raise httpx.HTTPStatusError("503", request=req, response=resp)
            return payload

    out = asyncio.run(get_graph_bytes_with_retry(_Client(), "/sites/x/content"))
    assert out == payload
    assert calls["n"] == 3


def test_graph_download_does_not_retry_permanent_404() -> None:
    calls = {"n": 0}

    class _Client:
        async def get_bytes(self, _endpoint: str) -> bytes:
            calls["n"] += 1
            req = httpx.Request("GET", "https://graph.example/content")
            resp = httpx.Response(404, request=req)
            raise httpx.HTTPStatusError("404", request=req, response=resp)

    with pytest.raises(httpx.HTTPStatusError):
        asyncio.run(get_graph_bytes_with_retry(_Client(), "/x"))
    assert calls["n"] == 1


def test_transient_error_classifier() -> None:
    req = httpx.Request("GET", "https://graph.example/content")
    exc_503 = httpx.HTTPStatusError("503", request=req, response=httpx.Response(503, request=req))
    exc_404 = httpx.HTTPStatusError("404", request=req, response=httpx.Response(404, request=req))
    assert is_transient_graph_download_error(exc_503)
    assert not is_transient_graph_download_error(exc_404)
    assert graph_download_error_detail(exc_503) == "HTTP 503"
