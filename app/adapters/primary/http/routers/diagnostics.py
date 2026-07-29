"""
Diagnóstico de configuración en tiempo de ejecución.

Pensado para operar el despliegue sin acceso a los logs del App Service: permite
comprobar desde Insomnia o Power Automate qué fuente de credenciales está activa, si
Microsoft Graph responde y si los dos sitios de SharePoint se resuelven.

Nunca devuelve valores de secretos: solo nombres de configuración y resultados de
comprobación. Siempre responde 200 para que el detalle del fallo sea legible.
"""

from __future__ import annotations

import os
from datetime import date
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.adapters.primary.http.deps import GraphClientDep
from app.adapters.secondary.graph_credentials import describe_credential_config
from app.application.config.payment_validation_settings import (
    BANK_CODE_BOGOTA,
    get_payment_validation_paths,
    list_payment_banks,
)
from app.application.services.accounting_destination import (
    AccountingDestinationError,
    AccountingDestinationResolver,
    build_accounting_month_segments,
    resolve_accounting_bank_folder_name,
)
from app.application.services.colombia_time import today_colombia_iso
from app.application.services.environment_path_probe import probe_environment_paths
from app.application.services.sharepoint_list_capability_probe import (
    probe_existing_lists_item_crud,
)
from app.application.sharepoint_resolution import (
    accounting_site_is_configured,
    describe_sharepoint_config,
    encode_graph_drive_path,
    resolve_accounting_context,
    resolve_sharepoint_from_env,
)

router = APIRouter(prefix="/graph", tags=["diagnostics"])

ENV_ACCOUNTING_FOLDER_SMOKE = "ACCOUNTING_FOLDER_SMOKE_ENABLED"
ENV_LIST_CAPABILITY_PROBE = "SHAREPOINT_LIST_CAPABILITY_PROBE_ENABLED"

# PDF mínimo válido solo para la prueba de humo de Contabilidad.
_TINY_PDF = (
    b"%PDF-1.4\n"
    b"1 0 obj<< /Type /Catalog /Pages 2 0 R >>endobj\n"
    b"2 0 obj<< /Type /Pages /Kids [3 0 R] /Count 1 >>endobj\n"
    b"3 0 obj<< /Type /Page /Parent 2 0 R /MediaBox [0 0 200 200] >>endobj\n"
    b"xref\n0 4\n0000000000 65535 f \n0000000009 00000 n \n"
    b"0000000058 00000 n \n0000000115 00000 n \n"
    b"trailer<< /Size 4 /Root 1 0 R >>\nstartxref\n190\n%%EOF\n"
)


class AccountingFolderSmokeRequest(BaseModel):
    """Cuerpo opcional para la prueba de cadena de carpetas en Contabilidad."""

    report_date: str = Field(
        default="2027-07-28",
        description="Fecha bancaria simulada (YYYY-MM-DD).",
    )
    bank_code: str = Field(default=BANK_CODE_BOGOTA)
    upload_pdf: bool = Field(
        default=True,
        description="Si true, crea la carpeta del banco si falta y sube un PDF de humo.",
    )


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


@router.get("/diagnostics/paths-probe")
async def graph_paths_probe(
    graph: GraphClientDep,
    report_date: str | None = None,
) -> dict[str, Any]:
    """
    Verifica **solo con GET** que todas las rutas del `.env` activo existan.

    Seguro en producción: no crea, mueve ni modifica nada. ``report_date``
    (YYYY-MM-DD) elige el mes contable a comprobar; por defecto, hoy en Colombia.
    """
    raw = (report_date or "").strip()
    if raw:
        try:
            target_date = date.fromisoformat(raw)
        except ValueError as exc:
            raise HTTPException(
                status_code=400,
                detail="report_date debe tener formato YYYY-MM-DD.",
            ) from exc
    else:
        target_date = date.fromisoformat(today_colombia_iso())

    return await probe_environment_paths(graph, target_date)


def _list_capability_probe_enabled() -> bool:
    return (os.getenv(ENV_LIST_CAPABILITY_PROBE) or "").strip().casefold() in {
        "1",
        "true",
        "yes",
        "on",
    }


@router.post("/diagnostics/list-capability-probe")
async def sharepoint_list_capability_probe(graph: GraphClientDep) -> dict[str, Any]:
    """
    Prueba de capacidad sobre ``INDICE_EXTRACTOS`` y ``CONTROL_INDICE_EXTRACTOS``.

    Localiza las listas (creadas a mano), crea un ítem temporal, lo lee y lo borra.
    No intenta crear el contenedor de lista.

    Requiere ``SHAREPOINT_LIST_CAPABILITY_PROBE_ENABLED=true``.
    """
    if not _list_capability_probe_enabled():
        raise HTTPException(
            status_code=403,
            detail=(
                f"{ENV_LIST_CAPABILITY_PROBE} no está activo; "
                "habilítelo solo para la prueba de capacidad de Listas."
            ),
        )
    return await probe_existing_lists_item_crud(graph)


def _smoke_enabled() -> bool:
    return (os.getenv(ENV_ACCOUNTING_FOLDER_SMOKE) or "").strip().casefold() in {
        "1",
        "true",
        "yes",
        "on",
    }


@router.post("/diagnostics/accounting-folder-smoke")
async def accounting_folder_smoke(
    graph: GraphClientDep,
    body: AccountingFolderSmokeRequest | None = None,
) -> dict[str, Any]:
    """
    Prueba de humo: crea año / TESORERIA {año} / mes en Contabilidad (misma regla que Merge).

    Solo responde si ``ACCOUNTING_FOLDER_SMOKE_ENABLED`` está activo. La carpeta del banco
    no se crea en Merge real; aquí solo se crea si ``upload_pdf`` es true y aún no existe.
    """
    if not _smoke_enabled():
        raise HTTPException(
            status_code=403,
            detail=(
                f"{ENV_ACCOUNTING_FOLDER_SMOKE} no está activo; "
                "habilítelo solo para la prueba de Contabilidad."
            ),
        )
    if not accounting_site_is_configured():
        raise HTTPException(
            status_code=400,
            detail="Sitio de Contabilidad no configurado (GRAPH_ACCOUNTING_SITE_*).",
        )

    request = body or AccountingFolderSmokeRequest()
    try:
        target = date.fromisoformat(request.report_date.strip())
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail=f"report_date inválida: {request.report_date!r}",
        ) from exc

    bank_code = request.bank_code.strip() or BANK_CODE_BOGOTA
    year, tesoreria, month = build_accounting_month_segments(target)
    bank_folder = resolve_accounting_bank_folder_name(bank_code)

    try:
        ctx = await resolve_accounting_context(graph)
        resolver = AccountingDestinationResolver(graph, ctx["site_id"], ctx["drive_id"])

        actual_year = await resolver._ensure_folder("", year)
        actual_tesoreria = await resolver._ensure_folder(actual_year, tesoreria)
        tesoreria_path = f"{actual_year}/{actual_tesoreria}"
        actual_month = await resolver._ensure_folder(tesoreria_path, month)
        month_path = f"{tesoreria_path}/{actual_month}"

        bank_created = False
        bank_path: str | None = None
        pdf_path: str | None = None
        try:
            actual_bank = await resolver._require_folder(month_path, bank_folder, bank_code)
            bank_path = f"{month_path}/{actual_bank}"
        except AccountingDestinationError as exc:
            if not request.upload_pdf or exc.code != "accounting_bank_folder_not_found":
                raise
            await resolver._create_folder(month_path, bank_folder)
            bank_created = True
            bank_path = f"{month_path}/{bank_folder}"

        if request.upload_pdf and bank_path:
            pdf_name = (
                f"PRUEBA_consolidado_merge_{target.isoformat()}_{bank_code}.pdf"
            )
            pdf_path = f"{bank_path}/{pdf_name}"
            endpoint = (
                f"/sites/{ctx['site_id']}/drives/{ctx['drive_id']}"
                f"/root:/{encode_graph_drive_path(pdf_path)}:/content"
            )
            await graph.put_bytes(endpoint, _TINY_PDF, content_type="application/pdf")
    except AccountingDestinationError as exc:
        return {
            "status": "error",
            "error_code": exc.code,
            "detail": exc.message,
            "report_date": target.isoformat(),
            "segments": {"year": year, "tesoreria": tesoreria, "month": month},
        }
    except Exception as exc:
        return _failure(exc)

    return {
        "status": "ok",
        "report_date": target.isoformat(),
        "bank_code": bank_code,
        "segments": {"year": year, "tesoreria": tesoreria, "month": month},
        "month_path": month_path,
        "bank_path": bank_path,
        "bank_folder_created_for_smoke": bank_created,
        "pdf_path": pdf_path,
        "note": (
            "Cadena creada con la misma lógica que Merge. "
            "Puede borrar manualmente la carpeta del año de prueba en Contabilidad."
        ),
    }
