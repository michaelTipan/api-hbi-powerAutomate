"""Cancelar de forma segura un proceso sin escrituras financieras.

La cancelación conserva toda la evidencia irreversible y solo borra artefactos
reversibles cuya identidad esté ligada inequívocamente al ``ProcessId``. Nunca
revierte tablas de amortización: ante cualquier evidencia de Apply, el proceso
queda en su flujo normal de recuperación.
"""

from __future__ import annotations

import logging
import os
import json
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Any

import httpx

from app.application.config.payment_validation_settings import (
    BANK_CODE_BANCOLOMBIA,
    BANK_CODE_BOGOTA,
    get_payment_validation_paths,
    resolve_bank_display_name,
    validate_bank_code,
)
from app.application.sharepoint_resolution import (
    encode_graph_drive_path,
    require_operations_site_config,
    resolve_sharepoint_path,
)
from app.application.use_cases.payment_validation_process_control import (
    read_process_control_snapshot,
    resolve_process_control_path_for_bank,
    update_process_control_row2,
    utc_now_iso,
)
from app.application.use_cases.setup_merge_control_workbook import (
    process_id_from_process_key,
)
from app.application.use_cases.validate_payment_report import _graph_download_by_path
from app.domain.ports.graph import GraphApiPort

logger = logging.getLogger(__name__)

# Fases 1–3 (revisión, correo, merge pendiente/parcial/error). En CONSOLIDADO
# y amortización la salida de operador es Cerrar sin amortizar, no Cancelar.
# Estados de transición quedan fuera: el JobManager debe terminar primero.
CANCEL_ALLOWED_STATES = frozenset(
    {
        "REVISION_CREADA",
        "ERROR_GENERATE",
        "FINALIZADO",
        "ERROR_FINALIZE",
        "PENDIENTE_ASIENTOS",
        "ERROR_NOTIFY",
        "MERGE_PARCIAL",
        "ERROR_MERGE",
    }
)
_CANCEL_ALLOWED_STATES = CANCEL_ALLOWED_STATES  # alias interno


@dataclass(frozen=True)
class CancellationPlan:
    """Plan inmutable revisable antes de ejecutar borrados reversibles."""

    process_id: str
    process_key: str
    state: str
    phase: str
    has_notification: bool
    has_merge_output: bool
    has_financial_writes: bool
    safe_delete: tuple[str, ...]
    keep: tuple[str, ...]
    can_release_batch: bool
    warnings: tuple[str, ...]


async def _delete_safe_file(
    graph: GraphApiPort,
    site_id: str,
    drive_id: str,
    validation_file_path: str,
) -> dict[str, Any]:
    """Elimina un artefacto previamente validado. Un 404 es idempotente."""
    rel = (validation_file_path or "").strip().strip("/")
    if not rel:
        return {"deleted": False, "reason": "empty_path"}
    endpoint = f"/sites/{site_id}/drives/{drive_id}/root:/{encode_graph_drive_path(rel)}:"
    try:
        await graph.delete(endpoint)
        logger.info("cancel: artefacto reversible eliminado path=%s", rel)
        return {"deleted": True, "path": rel}
    except httpx.HTTPStatusError as exc:
        code = exc.response.status_code if exc.response is not None else 0
        if code == 404:
            return {"deleted": False, "reason": "already_absent", "path": rel}
        raise RuntimeError(f"cancel_cleanup_failed|{rel}|http_{code}") from exc
    except Exception as exc:
        raise RuntimeError(f"cancel_cleanup_failed|{rel}") from exc


def _path_has_process_identity(path: str, process_id: str) -> bool:
    """La revisión se borra solo si el nombre contiene el UUID exacto."""
    return bool(process_id and process_id.lower() in PurePosixPath(path).name.lower())


async def _safe_merge_outputs(
    graph: GraphApiPort,
    *,
    site_id: str,
    drive_id: str,
    manifest_path: str,
    process_id: str,
) -> tuple[list[str], list[str]]:
    """Obtiene exclusivamente outputs del manifest identificado por ProcessId."""
    rel = (manifest_path or "").strip().strip("/")
    if not rel:
        return [], []
    short_id = process_id.replace("-", "")[:8].lower()
    if not rel or not short_id or short_id not in PurePosixPath(rel).name.lower().replace("-", ""):
        return [], ["No se borró PDF consolidado: identidad del manifest no verificable."]
    try:
        raw = await _graph_download_by_path(graph, site_id, drive_id, rel)
        payload = json.loads(raw.decode("utf-8"))
    except Exception:
        return [], ["No se borró PDF consolidado: no se pudo validar el manifest."]
    if not isinstance(payload, dict) or not isinstance(payload.get("outputs"), list):
        return [], ["No se borró PDF consolidado: manifest inválido."]
    outputs: list[str] = []
    for item in payload["outputs"]:
        if not isinstance(item, dict):
            return [], ["No se borró PDF consolidado: manifest con output ambiguo."]
        output = str(item.get("output_relative_path") or "").strip().strip("/")
        if not output:
            return [], ["No se borró PDF consolidado: output sin ruta inequívoca."]
        outputs.append(output)
    return list(dict.fromkeys(outputs)), []


async def _build_cancellation_plan(
    graph: GraphApiPort,
    *,
    site_id: str,
    drive_id: str,
    snap: Any,
) -> CancellationPlan:
    """Inspecciona evidencia antes de tocar cualquier artefacto."""
    state = (snap.estado_proceso or "").strip().upper()
    process_key = (snap.process_key or "").strip()
    process_id = (snap.process_id or "").strip() or process_id_from_process_key(process_key)
    apply_key = (snap.apply_idempotency_key or "").strip()
    # ApplyIdempotencyKey se persiste al primer upload confirmado. Estados
    # terminales/parciales son evidencia adicional que nunca se minimiza.
    has_financial_writes = bool(
        (process_key and apply_key == process_key)
        or state in {"AMORTIZACION_PARCIAL", "AMORTIZACION_APLICADA"}
    )
    safe_delete: list[str] = []
    warnings: list[str] = []
    review_path = (snap.validation_file_path or "").strip().strip("/")
    if review_path:
        if _path_has_process_identity(review_path, process_id):
            safe_delete.append(review_path)
        else:
            warnings.append("No se borró Excel de revisión: identidad ProcessId no verificable.")
    merge_outputs, merge_warnings = await _safe_merge_outputs(
        graph,
        site_id=site_id,
        drive_id=drive_id,
        manifest_path=snap.merge_manifest_path,
        process_id=process_id,
    )
    warnings.extend(merge_warnings)
    safe_delete.extend(merge_outputs)
    phase = (
        "amortizacion"
        if state == "CONSOLIDADO"
        else "pdf_consolidado"
        if state in {"MERGE_PARCIAL", "ERROR_MERGE"}
        else "envio_correo"
        if state in {"PENDIENTE_ASIENTOS", "ERROR_NOTIFY"}
        else "revision"
    )
    return CancellationPlan(
        process_id=process_id,
        process_key=process_key,
        state=state,
        phase=phase,
        has_notification=bool((snap.email_pdf_path or "").strip()),
        has_merge_output=bool(merge_outputs),
        has_financial_writes=has_financial_writes,
        safe_delete=tuple(dict.fromkeys(safe_delete)),
        keep=(
            "extractos",
            "tablas_amortizacion",
            "soportes_contables",
            "carpetas_cliente",
            "documentos_originales",
            "logs",
            "historial",
            "evidencia_correo",
            "archivo_bancario",
            "merge_manifest",
        ),
        can_release_batch=not has_financial_writes,
        warnings=tuple(warnings),
    )


def _build_cancelled_control_updates(*, job_id: str | None) -> dict[str, Any]:
    """Cierra el intento como CANCELADO preservando su identidad y auditoría."""
    _ = job_id  # reservado: el job_id queda en el JobManager / respuesta HTTP
    now_iso = utc_now_iso()
    return {
        "EstadoProceso": "CANCELADO",
        "IsActive": "false",
        # ProcessKey/ProcessId, correo, histórico y manifest se conservan para
        # auditoría. Generate creará una identidad nueva al reintentar.
        "ValidationFilePath": "",
        "LastStepErrorCode": "",
        "LastErrorUserMessage": "",
        "LastCompletedStep": "CANCEL",
        "LastStepStatus": "COMPLETED",
        "LastUpdatedAtProceso": now_iso,
    }


def _is_cancelable_snapshot(snap: Any) -> bool:
    estado = (snap.estado_proceso or "").strip()
    apply_key = (snap.apply_idempotency_key or "").strip()
    process_key = (snap.process_key or "").strip()
    return bool(
        snap.is_active
        and estado in _CANCEL_ALLOWED_STATES
        and not (process_key and apply_key == process_key)
    )


async def _auto_detect_cancelable_banks(
    client: GraphApiPort,
    site_id: str,
    drive_id: str,
) -> list[str]:
    """Bancos con proceso cancelable (REVISION_CREADA/ERROR_GENERATE + IsActive)."""
    candidates: list[str] = []
    for bc in (BANK_CODE_BOGOTA, BANK_CODE_BANCOLOMBIA):
        snap = await read_process_control_snapshot(client, site_id, drive_id, bank_code=bc)
        if _is_cancelable_snapshot(snap):
            candidates.append(bc)
    return candidates


async def cancel_active_payment_validation(
    client: GraphApiPort,
    *,
    bank_code: str | None = None,
    process_key: str | None = None,
    job_id: str | None = None,
) -> dict[str, Any]:
    """
    Cancela un proceso activo antes de cualquier escritura financiera.

    Parameters
    ----------
    bank_code:
        Opcional (banco_bogota | banco_bancolombia). Si falta, auto-detecta
        el único banco con proceso cancelable.
    process_key:
        Opcional. Si se envía, debe coincidir con el ProcessKey del control.
    job_id:
        Opcional. Se registra en auditoría del control.
    """
    bank_code_raw = (bank_code or "").strip() or None
    bank_code_source = "body" if bank_code_raw else "auto_detected"
    ready_banks_detected: list[str] = []

    paths = get_payment_validation_paths()
    review_path = paths.review
    if not review_path:
        raise ValueError("missing_sharepoint_folder")

    require_operations_site_config()
    site_search = (os.getenv("GRAPH_SHAREPOINT_SITE_SEARCH") or "").strip()
    drive_name = (os.getenv("GRAPH_SHAREPOINT_DRIVE_NAME") or "").strip()
    review_info = await resolve_sharepoint_path(client, site_search, drive_name, review_path)
    site_id = review_info["site_id"]
    drive_id = review_info["drive_id"]

    if bank_code_raw:
        validate_bank_code(bank_code_raw)
        bank_code = bank_code_raw
    else:
        candidates = await _auto_detect_cancelable_banks(client, site_id, drive_id)
        ready_banks_detected = list(candidates)
        if len(candidates) > 1:
            raise ValueError("MULTIPLE_READY_PROCESSES|" + ",".join(candidates))
        if not candidates:
            # Ningún banco cancelable: éxito idempotente (botón Cancel sin proceso).
            return {
                "status": "ok",
                "already_cancelled": True,
                "bank_code": "",
                "bank_name": "",
                "bank_code_source": bank_code_source,
                "ready_banks_detected": [],
                "process_key_before": "",
                "process_key_cleared": "",
                "process_control_file_path": "",
                "process_control_estado": "CANCELADO",
                "process_control_updated": False,
                "cancellation_plan": None,
                "validation_file_path_before": "",
            }
        bank_code = candidates[0]
        bank_code_source = "auto_detected"

    bank_name = resolve_bank_display_name(bank_code)
    process_control_file_path = resolve_process_control_path_for_bank(bank_code).strip().strip("/")

    snap = await read_process_control_snapshot(client, site_id, drive_id, bank_code=bank_code)
    estado = (snap.estado_proceso or "").strip()
    snap_key = (snap.process_key or "").strip()
    expected_key = (process_key or "").strip()

    fully_idle = estado == "VACIO" and not snap.is_active and not snap_key
    if fully_idle:
        return {
            "status": "ok",
            "already_cancelled": True,
            "bank_code": bank_code,
            "bank_name": bank_name,
            "bank_code_source": bank_code_source,
            "ready_banks_detected": ready_banks_detected,
            "process_key_before": "",
            "process_key_cleared": "",
            "process_control_file_path": process_control_file_path,
            "process_control_estado": "CANCELADO",
            "process_control_updated": False,
            "cancellation_plan": None,
            "validation_file_path_before": "",
        }

    if expected_key and snap_key and expected_key != snap_key:
        raise ValueError(f"process_key_mismatch|{expected_key}|{snap_key}")

    plan = await _build_cancellation_plan(
        client, site_id=site_id, drive_id=drive_id, snap=snap
    )
    if plan.has_financial_writes:
        raise ValueError(f"cancel_not_allowed_financial_writes|{estado}|{snap_key}")
    if estado not in _CANCEL_ALLOWED_STATES:
        raise ValueError(f"cancel_not_allowed|{estado or 'VACIO'}|{snap_key}")
    # Si un Apply falló en versiones anteriores no hay prueba durable de que
    # ninguna tabla haya sido escrita. Fallar cerrado protege contabilidad.
    if estado == "ERROR_APPLY":
        raise ValueError(f"cancel_not_allowed_financial_writes_unknown|{estado}|{snap_key}")

    cleanup: list[dict[str, Any]] = []
    for rel in plan.safe_delete:
        cleanup.append(
            await _delete_safe_file(client, site_id, drive_id, rel)
        )

    updates = _build_cancelled_control_updates(job_id=job_id)
    await update_process_control_row2(
        client, site_id, drive_id, bank_code=bank_code, updates=updates
    )

    logger.info(
        "cancel: proceso cancelado bank=%s source=%s estado_antes=%s process_key=%s",
        bank_code,
        bank_code_source,
        estado,
        snap_key,
    )

    return {
        "status": "ok",
        "already_cancelled": False,
        "bank_code": bank_code,
        "bank_name": bank_name,
        "bank_code_source": bank_code_source,
        "ready_banks_detected": ready_banks_detected,
        "process_key_before": snap_key,
        "process_key_cleared": snap_key,
        "process_control_file_path": process_control_file_path,
        "process_control_estado": "CANCELADO",
        "process_control_updated": True,
        "estado_antes": estado,
        "cancellation_plan": {
            "process_id": plan.process_id,
            "state": plan.state,
            "phase": plan.phase,
            "has_notification": plan.has_notification,
            "has_merge_output": plan.has_merge_output,
            "has_financial_writes": plan.has_financial_writes,
            "safe_delete": list(plan.safe_delete),
            "keep": list(plan.keep),
            "can_release_batch": plan.can_release_batch,
            "warnings": list(plan.warnings),
        },
        "cleanup": cleanup,
    }
