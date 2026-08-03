"""
Contrato estable de errores de negocio para jobs HTTP y proyección UI.

Centraliza el parseo de códigos (ValueError / ExcelWriteGuardError) y la
resolución de mensajes operativos en español.
"""

from __future__ import annotations

import json
import re
from typing import Any

from app.application.job_status_enrichment import resolve_business_error_for_job
from app.application.services.excel_write_guard import ExcelWriteGuardError


def parse_business_error_message(message: str) -> tuple[str, dict[str, Any]]:
    """Extrae código estable y metadatos opcionales de un mensaje de excepción."""
    raw = (message or "").strip()
    if not raw:
        return "unknown_error", {}
    if "|" not in raw:
        return raw, {}

    code, rest = raw.split("|", 1)
    code = code.strip()
    rest = rest.strip()
    if not rest:
        return code, {}

    try:
        parsed = json.loads(rest)
        if isinstance(parsed, dict):
            return code, parsed
    except json.JSONDecodeError:
        pass

    details: dict[str, Any] = {}
    for part in rest.split(","):
        part = part.strip()
        if not part or "=" not in part:
            continue
        key, value = part.split("=", 1)
        key = key.strip()
        value = value.strip()
        if key:
            details[key] = _coerce_detail_value(value)
    return code, details


def _coerce_detail_value(value: str) -> Any:
    if re.fullmatch(r"-?\d+", value):
        try:
            return int(value)
        except ValueError:
            return value
    if re.fullmatch(r"-?\d+\.\d+", value):
        try:
            return float(value)
        except ValueError:
            return value
    return value


def exception_to_business_error(
    job_type: str,
    exc: BaseException,
) -> tuple[str, dict[str, Any]]:
    """Normaliza una excepción de job a (código, payload enriquecido)."""
    if isinstance(exc, ExcelWriteGuardError):
        message = str(exc)
        code = exc.error_code
        details = dict(exc.details)
    else:
        message = str(exc)
        code, details = parse_business_error_message(message)

    payload = resolve_business_error_for_job(
        job_type,
        message=message,
        exc_type=type(exc).__name__,
    )
    payload.setdefault("error_code", code)
    if details:
        payload["details"] = details
        if details.get("excel_row") is not None:
            payload["excel_row"] = details.get("excel_row")
        if details.get("field"):
            payload["field"] = details.get("field")
        if details.get("id_pago"):
            payload["payment_id"] = str(details.get("id_pago"))
    return str(payload.get("error_code") or code), payload


def job_error_storage_dict(
    job_type: str,
    exc: BaseException,
) -> dict[str, Any]:
    """Documento ``error`` persistido en JobManager."""
    _, payload = exception_to_business_error(job_type, exc)
    return {
        "type": type(exc).__name__,
        "message": str(exc),
        "error_code": payload.get("error_code"),
        "technical_message": payload.get("technical_message") or str(exc),
        "user_message": payload.get("user_message"),
        "next_action": payload.get("next_action"),
        "severity": payload.get("severity", "error"),
        "details": payload.get("details"),
        "excel_row": payload.get("excel_row"),
        "field": payload.get("field"),
        "payment_id": payload.get("payment_id"),
    }
