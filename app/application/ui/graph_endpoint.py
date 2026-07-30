"""Validación de endpoints Graph relativos (solo construidos en servidor)."""
from __future__ import annotations


class UiGraphEndpointError(ValueError):
    """El cliente o un caller intentó pasar una URL Graph absoluta / inválida."""

    def __init__(self, endpoint: str, reason: str) -> None:
        self.endpoint = endpoint
        self.reason = reason
        super().__init__(reason)


def assert_relative_graph_endpoint(endpoint: str) -> str:
    """Fail-closed: solo paths relativos tipo ``/sites/.../drives/...``.

    Prohibido: ``https://graph.microsoft.com/...``, URLs arbitrarias del navegador,
    esquemas ``http(s)://``, o strings sin ``/`` inicial.
    """
    raw = str(endpoint or "").strip()
    if not raw:
        raise UiGraphEndpointError(raw, "graph_endpoint_empty")
    lower = raw.lower()
    if lower.startswith("http://") or lower.startswith("https://"):
        raise UiGraphEndpointError(raw, "graph_absolute_url_forbidden")
    if "://" in raw:
        raise UiGraphEndpointError(raw, "graph_absolute_url_forbidden")
    if "graph.microsoft.com" in lower:
        raise UiGraphEndpointError(raw, "graph_host_forbidden")
    if not raw.startswith("/"):
        raise UiGraphEndpointError(raw, "graph_endpoint_must_be_relative")
    if ".." in raw.split("/"):
        raise UiGraphEndpointError(raw, "graph_endpoint_traversal_forbidden")
    return raw
