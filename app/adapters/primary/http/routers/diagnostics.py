"""
Diagnóstico de configuración en tiempo de ejecución.

Pensado para operar el despliegue sin acceso a los logs del App Service: permite
comprobar desde Insomnia o Power Automate qué fuente de credenciales está activa, si
Microsoft Graph responde y si los dos sitios de SharePoint se resuelven.

Nunca devuelve valores de secretos: solo nombres de configuración y resultados de
comprobación. Siempre responde 200 para que el detalle del fallo sea legible.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter

from app.adapters.primary.http.deps import GraphClientDep
from app.adapters.secondary.graph_credentials import describe_credential_config
from app.application.config.payment_validation_settings import (
    get_payment_validation_paths,
    list_payment_banks,
)
from app.application.sharepoint_resolution import (
    accounting_site_is_configured,
    describe_sharepoint_config,
    resolve_accounting_context,
    resolve_sharepoint_from_env,
)

router = APIRouter(prefix="/graph", tags=["diagnostics"])


def _failure(exc: Exception) -> dict[str, str]:
    return {"status": "error", "error_type": exc.__class__.__name__, "detail": str(exc)[:600]}


async def _check_token(graph: GraphClientDep) -> dict[str, Any]:
    try:
        token = await graph._get_access_token()
    except Exception as exc:
        return _failure(exc)
    return {"status": "ok", "token_length": len(token)}


async def _check_operations(graph: GraphClientDep) -> dict[str, Any]:
    try:
        context = await resolve_sharepoint_from_env(graph)
    except Exception as exc:
        return _failure(exc)
    return {
        "status": "ok",
        "site_id": context["site_id"],
        "drive_id": context["drive_id"],
        "probe_path": context["file_path"],
    }


async def _check_accounting(graph: GraphClientDep) -> dict[str, Any]:
    if not accounting_site_is_configured():
        return {
            "status": "disabled",
            "detail": (
                "El sitio de Contabilidad no está configurado; el PDF consolidado se "
                "guarda en Operaciones."
            ),
        }
    try:
        context = await resolve_accounting_context(graph)
    except Exception as exc:
        return _failure(exc)
    return {"status": "ok", "site_id": context["site_id"], "drive_id": context["drive_id"]}


def _describe_paths() -> dict[str, Any]:
    try:
        paths = get_payment_validation_paths()
    except Exception as exc:
        return _failure(exc)
    return {
        "status": "ok",
        "base_folder": paths.base_folder,
        "control": paths.control,
        "review": paths.review,
        "historical": paths.historical,
        "logs": paths.logs,
        "email": paths.email,
        "asientos": paths.asientos,
    }


def _describe_banks() -> dict[str, Any]:
    try:
        banks = list_payment_banks()
    except Exception as exc:
        return _failure(exc)
    return {
        "status": "ok",
        "banks": [
            {
                "bank_code": bank.bank_code,
                "input_file_path": bank.input_file_path,
                "control_file_path": bank.control_file_path,
            }
            for bank in banks
        ],
    }


@router.get("/diagnostics")
async def graph_diagnostics(graph: GraphClientDep) -> dict[str, Any]:
    """Comprobación de configuración de extremo a extremo, sin exponer secretos."""
    credentials = describe_credential_config()
    token = await _check_token(graph)
    operations = await _check_operations(graph)
    accounting = await _check_accounting(graph)
    paths = _describe_paths()
    banks = _describe_banks()

    checks = (token, operations, paths, banks)
    healthy = all(check.get("status") == "ok" for check in checks) and accounting.get(
        "status"
    ) in ("ok", "disabled")

    return {
        "status": "ok" if healthy else "degraded",
        "credentials": credentials,
        "graph_token": token,
        "sharepoint_config": describe_sharepoint_config(),
        "operations_site": operations,
        "accounting_site": accounting,
        "payment_validation_paths": paths,
        "banks": banks,
    }
