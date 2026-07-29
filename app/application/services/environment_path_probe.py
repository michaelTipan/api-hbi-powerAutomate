"""
Sondeo **solo lectura** de las rutas SharePoint configuradas por entorno.

Sirve para validar un `.env` recién desplegado (sandbox o producción) sin escribir,
crear ni mover nada: cada comprobación es un `GET` de metadatos del `driveItem`.

No contiene lógica financiera. Enumera los destinos que el flujo necesita y reporta
si cada uno existe y si es carpeta o archivo.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import date
from typing import Any

from app.application.config.payment_validation_settings import (
    BANK_CODE_BANCOLOMBIA,
    BANK_CODE_BOGOTA,
    get_payment_validation_paths,
    list_payment_banks,
    resolve_correos_xlsx_path,
    resolve_execution_run_logs_folder_path,
    resolve_followup_workbook_path,
    resolve_ibr_workbook_path,
    resolve_merge_output_folder_path,
)
from app.application.services.accounting_destination import (
    build_accounting_month_segments,
    resolve_accounting_bank_folder_name,
)
from app.application.sharepoint_resolution import (
    accounting_site_is_configured,
    encode_graph_drive_path,
    resolve_accounting_context,
    resolve_sharepoint_from_env,
)
from app.domain.ports.graph import GraphApiPort

KIND_FOLDER = "folder"
KIND_FILE = "file"

SCOPE_OPERATIONS = "operations"
SCOPE_ACCOUNTING = "accounting"

STATUS_OK = "ok"
STATUS_MISSING = "missing"
STATUS_KIND_MISMATCH = "kind_mismatch"
STATUS_ERROR = "error"

FOLLOWUP_ADELANTADOS_FILENAME = "pagos_adelantados.xlsx"


@dataclass(frozen=True)
class ProbeTarget:
    """Destino configurado que el flujo espera encontrar en SharePoint."""

    name: str
    kind: str
    path: str
    scope: str
    required: bool
    note: str = ""


def _clients_base_path() -> str:
    return os.getenv("GRAPH_CLIENTS_BASE_PATH", "").strip().strip("/")


def build_operations_probe_targets() -> tuple[ProbeTarget, ...]:
    """Rutas del sitio de Operaciones derivadas del `.env` activo."""
    paths = get_payment_validation_paths()
    targets: list[ProbeTarget] = [
        ProbeTarget(
            name="clients_base",
            kind=KIND_FOLDER,
            path=_clients_base_path(),
            scope=SCOPE_OPERATIONS,
            required=True,
            note="GRAPH_CLIENTS_BASE_PATH: raíz de carpetas de clientes.",
        ),
        ProbeTarget(
            name="payment_validation_base",
            kind=KIND_FOLDER,
            path=paths.base_folder,
            scope=SCOPE_OPERATIONS,
            required=True,
        ),
        ProbeTarget(
            name="control",
            kind=KIND_FOLDER,
            path=paths.control,
            scope=SCOPE_OPERATIONS,
            required=True,
            note="control_proceso_* y libros de seguimiento.",
        ),
        ProbeTarget(
            name="review",
            kind=KIND_FOLDER,
            path=paths.review,
            scope=SCOPE_OPERATIONS,
            required=True,
        ),
        ProbeTarget(
            name="historical",
            kind=KIND_FOLDER,
            path=paths.historical,
            scope=SCOPE_OPERATIONS,
            required=True,
        ),
        ProbeTarget(
            name="logs_manifests",
            kind=KIND_FOLDER,
            path=paths.logs,
            scope=SCOPE_OPERATIONS,
            required=True,
        ),
        ProbeTarget(
            name="email_sent",
            kind=KIND_FOLDER,
            path=paths.email,
            scope=SCOPE_OPERATIONS,
            required=True,
        ),
        ProbeTarget(
            name="execution_logs",
            kind=KIND_FOLDER,
            path=resolve_execution_run_logs_folder_path(),
            scope=SCOPE_OPERATIONS,
            required=True,
        ),
    ]

    # La carpeta de consolidados en Operaciones solo se usa cuando Contabilidad no
    # está configurada: con Contabilidad activa, Merge nunca escribe aquí.
    if not accounting_site_is_configured():
        targets.append(
            ProbeTarget(
                name="merge_output_operations",
                kind=KIND_FOLDER,
                path=resolve_merge_output_folder_path(),
                scope=SCOPE_OPERATIONS,
                required=True,
                note="Destino del PDF consolidado mientras Contabilidad esté apagada.",
            )
        )

    for bank in list_payment_banks():
        targets.append(
            ProbeTarget(
                name=f"bank_input_{bank.bank_code}",
                kind=KIND_FILE,
                path=bank.input_file_path,
                scope=SCOPE_OPERATIONS,
                required=True,
            )
        )
        targets.append(
            ProbeTarget(
                name=f"bank_control_{bank.bank_code}",
                kind=KIND_FILE,
                path=bank.control_file_path,
                scope=SCOPE_OPERATIONS,
                required=True,
            )
        )

    targets.append(
        ProbeTarget(
            name="correos_xlsx",
            kind=KIND_FILE,
            path=resolve_correos_xlsx_path(),
            scope=SCOPE_OPERATIONS,
            required=True,
        )
    )
    targets.append(
        ProbeTarget(
            name="ibr_diario_xlsx",
            kind=KIND_FILE,
            path=resolve_ibr_workbook_path(),
            scope=SCOPE_OPERATIONS,
            required=True,
        )
    )
    targets.append(
        ProbeTarget(
            name="pagos_adelantados_xlsx",
            kind=KIND_FILE,
            path=resolve_followup_workbook_path(FOLLOWUP_ADELANTADOS_FILENAME),
            scope=SCOPE_OPERATIONS,
            required=False,
            note="Lo crea el endpoint de setup de seguimiento si aún no existe.",
        )
    )
    return tuple(targets)


def build_accounting_probe_targets(report_date: date) -> tuple[ProbeTarget, ...]:
    """
    Cadena de carpetas del sitio de Contabilidad para la fecha indicada.

    Año, ``TESORERIA {año}`` y el mes los crea Merge si faltan, así que se reportan
    como informativos. La carpeta del banco **no** se crea nunca: es obligatoria.
    """
    year, tesoreria, month = build_accounting_month_segments(report_date)
    year_path = year
    tesoreria_path = f"{year}/{tesoreria}"
    month_path = f"{tesoreria_path}/{month}"

    targets: list[ProbeTarget] = [
        ProbeTarget(
            name="accounting_year",
            kind=KIND_FOLDER,
            path=year_path,
            scope=SCOPE_ACCOUNTING,
            required=False,
            note="Merge la crea si falta.",
        ),
        ProbeTarget(
            name="accounting_tesoreria",
            kind=KIND_FOLDER,
            path=tesoreria_path,
            scope=SCOPE_ACCOUNTING,
            required=False,
            note="Merge la crea si falta.",
        ),
        ProbeTarget(
            name="accounting_month",
            kind=KIND_FOLDER,
            path=month_path,
            scope=SCOPE_ACCOUNTING,
            required=False,
            note="Merge la crea si falta.",
        ),
    ]

    for bank_code in (BANK_CODE_BOGOTA, BANK_CODE_BANCOLOMBIA):
        bank_folder = resolve_accounting_bank_folder_name(bank_code)
        targets.append(
            ProbeTarget(
                name=f"accounting_bank_folder_{bank_code}",
                kind=KIND_FOLDER,
                path=f"{month_path}/{bank_folder}",
                scope=SCOPE_ACCOUNTING,
                required=True,
                note="Merge no la crea: debe existir el mes en curso.",
            )
        )
    return tuple(targets)


def _status_code_of(exc: Exception) -> int | None:
    response = getattr(exc, "response", None)
    status = getattr(response, "status_code", None)
    return int(status) if isinstance(status, int) else None


async def _probe_one(
    graph: GraphApiPort,
    site_id: str,
    drive_id: str,
    target: ProbeTarget,
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "name": target.name,
        "scope": target.scope,
        "kind_expected": target.kind,
        "path": target.path,
        "required": target.required,
    }
    if target.note:
        result["note"] = target.note

    if not target.path:
        result["status"] = STATUS_ERROR
        result["detail"] = "Ruta vacía en la configuración."
        return result

    endpoint = f"/sites/{site_id}/drives/{drive_id}/root:/{encode_graph_drive_path(target.path)}"
    try:
        item = await graph.get(endpoint)
    except Exception as exc:
        status_code = _status_code_of(exc)
        result["status"] = STATUS_MISSING if status_code == 404 else STATUS_ERROR
        result["http_status"] = status_code
        result["detail"] = str(exc)[:300]
        return result

    actual_kind = KIND_FOLDER if "folder" in item else KIND_FILE
    result["kind_actual"] = actual_kind
    result["status"] = STATUS_OK if actual_kind == target.kind else STATUS_KIND_MISMATCH
    web_url = item.get("webUrl")
    if isinstance(web_url, str) and web_url:
        result["web_url"] = web_url
    return result


def _summarize(checks: list[dict[str, Any]]) -> dict[str, Any]:
    required_failures = [
        c["name"]
        for c in checks
        if c.get("required") and c.get("status") != STATUS_OK
    ]
    optional_failures = [
        c["name"]
        for c in checks
        if not c.get("required") and c.get("status") != STATUS_OK
    ]
    return {
        "checked": len(checks),
        "ok": sum(1 for c in checks if c.get("status") == STATUS_OK),
        "required_failures": required_failures,
        "optional_missing": optional_failures,
    }


async def probe_environment_paths(
    graph: GraphApiPort,
    report_date: date,
) -> dict[str, Any]:
    """
    Comprueba todas las rutas del `.env` activo con peticiones `GET` únicamente.

    Nunca crea, modifica ni mueve elementos: es seguro ejecutarlo en producción.
    """
    payload: dict[str, Any] = {
        "read_only": True,
        "active_environment": os.getenv("ACTIVE_ENVIRONMENT", "").strip() or "(no definido)",
        "report_date": report_date.isoformat(),
        "accounting_configured": accounting_site_is_configured(),
        "clients_excluded_folders": [
            name.strip()
            for name in (os.getenv("GRAPH_CLIENTS_EXCLUDED_FOLDERS", "") or "").split(",")
            if name.strip()
        ],
    }

    checks: list[dict[str, Any]] = []

    try:
        operations = await resolve_sharepoint_from_env(graph)
    except Exception as exc:
        payload["status"] = "error"
        payload["operations_site"] = {
            "status": STATUS_ERROR,
            "error_type": exc.__class__.__name__,
            "detail": str(exc)[:600],
        }
        return payload

    payload["operations_site"] = {
        "status": STATUS_OK,
        "site_id": operations["site_id"],
        "drive_id": operations["drive_id"],
    }
    for target in build_operations_probe_targets():
        checks.append(
            await _probe_one(graph, operations["site_id"], operations["drive_id"], target)
        )

    if accounting_site_is_configured():
        try:
            accounting = await resolve_accounting_context(graph)
        except Exception as exc:
            payload["accounting_site"] = {
                "status": STATUS_ERROR,
                "error_type": exc.__class__.__name__,
                "detail": str(exc)[:600],
            }
            accounting = None
        else:
            payload["accounting_site"] = {
                "status": STATUS_OK,
                "site_id": accounting["site_id"],
                "drive_id": accounting["drive_id"],
            }
        if accounting:
            for target in build_accounting_probe_targets(report_date):
                checks.append(
                    await _probe_one(
                        graph, accounting["site_id"], accounting["drive_id"], target
                    )
                )
    else:
        payload["accounting_site"] = {
            "status": "disabled",
            "detail": "Contabilidad apagada: el consolidado se queda en Operaciones.",
        }

    payload["checks"] = checks
    payload["summary"] = _summarize(checks)
    accounting_status = payload["accounting_site"].get("status")
    healthy = (
        not payload["summary"]["required_failures"]
        and accounting_status in (STATUS_OK, "disabled")
    )
    payload["status"] = STATUS_OK if healthy else "degraded"
    return payload


__all__ = [
    "KIND_FILE",
    "KIND_FOLDER",
    "ProbeTarget",
    "SCOPE_ACCOUNTING",
    "SCOPE_OPERATIONS",
    "STATUS_ERROR",
    "STATUS_KIND_MISMATCH",
    "STATUS_MISSING",
    "STATUS_OK",
    "build_accounting_probe_targets",
    "build_operations_probe_targets",
    "probe_environment_paths",
]
