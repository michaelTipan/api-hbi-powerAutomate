"""Mapeo HTTP 423 Locked → error recuperable para la UI."""

from __future__ import annotations

from app.adapters.primary.http.ui.router_v1 import _map_review_http_errors
from app.application.ui.review_write import ReviewFileLockedError


def test_map_review_file_locked_returns_423() -> None:
    mapped = _map_review_http_errors(ReviewFileLockedError("Excel abierto"))
    assert mapped is not None
    assert mapped.status_code == 423
    detail = mapped.detail
    assert isinstance(detail, dict)
    assert detail["error_code"] == "sharepoint_file_locked"
    assert "bloqueado" in detail["user_message"].lower()
    assert "cierre" in detail["next_action"].lower()
