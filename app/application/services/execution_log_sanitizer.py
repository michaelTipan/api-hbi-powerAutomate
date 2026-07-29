"""Sanitización de payloads para la bitácora de ejecución (sin secretos ni binarios)."""

from __future__ import annotations

from typing import Any

_DENYLIST_KEYS = frozenset(
    {
        "authorization",
        "access_token",
        "client_secret",
        "password",
        "api_key",
        "api_http_key",
        "excel_base64",
        "pdf_base64",
        "cookie",
        "x-api-key",
    }
)

_MAX_STRING = 4000


def sanitize_for_execution_log(obj: Any, *, max_string: int = _MAX_STRING) -> Any:
    """
    Copia superficial segura para JSON de auditoría.
    Elimina claves sensibles y trunca strings largos.
    """
    if obj is None or isinstance(obj, (bool, int, float)):
        return obj
    if isinstance(obj, str):
        if len(obj) <= max_string:
            return obj
        return obj[: max_string - 3] + "..."
    if isinstance(obj, bytes):
        return f"<bytes:{len(obj)}>"
    if isinstance(obj, dict):
        out: dict[str, Any] = {}
        for key, value in obj.items():
            key_s = str(key)
            if key_s.casefold() in _DENYLIST_KEYS or key_s.upper().startswith("GRAPH_"):
                out[key_s] = "<redacted>"
                continue
            out[key_s] = sanitize_for_execution_log(value, max_string=max_string)
        return out
    if isinstance(obj, (list, tuple)):
        return [sanitize_for_execution_log(item, max_string=max_string) for item in obj]
    return sanitize_for_execution_log(str(obj), max_string=max_string)
