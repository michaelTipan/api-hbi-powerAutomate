"""
Bitácora por intento de endpoint (Generate → Apply) en SharePoint.

Organización (relativa a la carpeta de logs de validación):
  {día YYYY-MM-DD}/execution_log_{banco}_{YYYYMMDD}_{HHMMSS}_{step}_{RESULT}_{id8}.json

Un archivo por intento de endpoint; todos los de una corrida completa comparten
el mismo ``execution_id`` (UUID) en el JSON. El recorte ``id8`` del nombre es solo
atajo visual; la auditoría canónica usa el UUID completo.

Activación: EXECUTION_RUN_LOG_ENABLED=true. Con false, las funciones públicas no-op.
Los fallos de escritura NUNCA deben tumbar el flujo financiero.
"""

from __future__ import annotations

import json
import logging
import re
import uuid
from datetime import date, datetime, timezone
from typing import Any

from app.application.config.payment_validation_settings import (
    execution_run_log_enabled,
    resolve_execution_run_logs_folder_path,
)
from app.application.services.colombia_time import now_colombia
from app.application.services.execution_log_sanitizer import sanitize_for_execution_log
from app.application.sharepoint_resolution import encode_graph_drive_path
from app.domain.ports.graph import GraphApiPort

logger = logging.getLogger(__name__)

SCHEMA_VERSION = 1
_MAX_WRITE_RETRIES = 5

_WAITING_AFTER_STEP: dict[str, tuple[str, str]] = {
    "GENERATE": ("SECRETARY_REVIEW", "FINALIZE"),
    "FINALIZE": ("ACCOUNTING_DOCUMENT_UPLOAD", "NOTIFY"),
    "NOTIFY": ("MERGE_EXECUTION", "MERGE"),
    "MERGE": ("DRY_RUN_EXECUTION", "DRY_RUN"),
    "DRY_RUN": ("APPLY_EXECUTION", "APPLY"),
}

_TERMINAL_EVENT = frozenset(
    {
        "SUCCEEDED",
        "FAILED",
        "BLOCKED",
        "PARTIAL",
        "COMPLETED_WITH_WARNINGS",
        "SKIPPED_IDEMPOTENT",
        "ALREADY_COMPLETED",
        "REQUEST_REJECTED",
    }
)

# Tokens de baja cardinalidad en el nombre de archivo (estilo ops / Sentry result).
_FILENAME_RESULT_OK = frozenset(
    {"SUCCEEDED", "SKIPPED_IDEMPOTENT", "ALREADY_COMPLETED"}
)
_FILENAME_RESULT_FAIL = frozenset({"FAILED", "BLOCKED"})
_FILENAME_RESULT_PARTIAL = frozenset({"PARTIAL", "COMPLETED_WITH_WARNINGS"})
_FILENAME_RESULT_STARTED = frozenset({"STARTED", "QUEUED"})


def execution_id_short(execution_id: str) -> str:
    return execution_id.replace("-", "")[:8]


def step_filename_token(step: str) -> str:
    raw = str(step or "step").strip().lower().replace("-", "_")
    raw = re.sub(r"[^a-z0-9_]+", "_", raw)
    return raw or "step"


def filename_result_token(event_status: str) -> str:
    """Mapea status de evento → token estable en el nombre del archivo."""
    st = str(event_status or "").strip().upper()
    if st in _FILENAME_RESULT_STARTED:
        return "STARTED"
    if st == "REQUEST_REJECTED":
        return "REJECTED"
    if st in _FILENAME_RESULT_OK:
        return "SUCCEEDED"
    if st in _FILENAME_RESULT_FAIL:
        return "FAILED"
    if st in _FILENAME_RESULT_PARTIAL:
        return "PARTIAL"
    return "STARTED"


def normalize_bank_token(bank_code: str) -> str:
    return re.sub(r"[^a-z0-9_]+", "_", (bank_code or "banco").strip().lower()) or "banco"


def build_execution_log_relative_path(
    *,
    bank_code: str,
    day: date | str,
    execution_id: str,
    step: str,
    result: str,
    when: datetime | None = None,
) -> str:
    """
    Ruta fechada:
    ``{logs}/YYYY/MM/YYYY-MM-DD/execution_log_{banco}_{YYYYMMDD}_{HHMMSS}_{step}_{RESULT}_{id8}.json``.
    """
    from app.application.services.dated_artifact_layout import join_dated_artifact_path

    stamp = when or now_colombia()
    if stamp.tzinfo is None:
        # now_colombia ya trae zona; si llega naive, no inventar UTC.
        ymd = stamp.strftime("%Y%m%d")
        hms = stamp.strftime("%H%M%S")
    else:
        local = stamp.astimezone(now_colombia().tzinfo)
        ymd = local.strftime("%Y%m%d")
        hms = local.strftime("%H%M%S")
    bank = normalize_bank_token(bank_code)
    step_t = step_filename_token(step)
    result_t = filename_result_token(result)
    id8 = execution_id_short(execution_id)
    name = f"execution_log_{bank}_{ymd}_{hms}_{step_t}_{result_t}_{id8}.json"
    base = resolve_execution_run_logs_folder_path().strip().strip("/")
    return join_dated_artifact_path(base, day, name)


def recompute_summary(events: list[dict[str, Any]]) -> dict[str, Any]:
    """Recalcula el resumen global a partir de events[] (función pura)."""
    if not events:
        return {
            "overall_status": "RUNNING",
            "current_step": None,
            "last_attempted_step": None,
            "last_successful_step": None,
            "failed_step": None,
            "waiting_for": None,
            "next_expected_step": None,
            "can_retry": False,
            "requires_support": False,
            "warnings_count": 0,
            "errors_count": 0,
        }

    last = events[-1]
    last_step = str(last.get("step") or "") or None
    last_status = str(last.get("status") or "")

    last_successful_step: str | None = None
    failed_step: str | None = None
    errors_count = 0
    warnings_count = 0

    for ev in events:
        st = str(ev.get("status") or "")
        step = str(ev.get("step") or "")
        if st in ("SUCCEEDED", "ALREADY_COMPLETED", "SKIPPED_IDEMPOTENT"):
            last_successful_step = step or last_successful_step
            if failed_step == step:
                failed_step = None
        if st in ("FAILED", "BLOCKED"):
            failed_step = step or failed_step
            errors_count += 1
        if st in ("PARTIAL", "COMPLETED_WITH_WARNINGS"):
            warnings_count += 1
        if isinstance(ev.get("error"), dict):
            errors_count += 1

    current_step: str | None = None
    for idx in range(len(events) - 1, -1, -1):
        ev = events[idx]
        st = str(ev.get("status") or "")
        if st != "STARTED":
            continue
        step = str(ev.get("step") or "")
        attempt = ev.get("attempt")
        closed = False
        for later in events[idx + 1 :]:
            if (
                later.get("step") == step
                and later.get("attempt") == attempt
                and str(later.get("status") or "") in _TERMINAL_EVENT
            ):
                closed = True
                break
        if not closed:
            current_step = step or None
            break

    overall = "RUNNING"
    waiting_for: str | None = None
    next_expected: str | None = None

    if last_status == "FAILED":
        overall = "FAILED"
    elif last_status == "BLOCKED":
        overall = "BLOCKED"
    elif last_status == "PARTIAL":
        overall = "PARTIAL"
    elif last_status == "COMPLETED_WITH_WARNINGS":
        overall = "COMPLETED_WITH_WARNINGS"
    elif last_status in ("SUCCEEDED", "ALREADY_COMPLETED", "SKIPPED_IDEMPOTENT"):
        if last_step == "APPLY":
            overall = "SUCCEEDED"
        elif last_step and last_step in _WAITING_AFTER_STEP:
            overall = "WAITING_FOR_NEXT_STEP"
            waiting_for, next_expected = _WAITING_AFTER_STEP[last_step]
        else:
            overall = "WAITING_FOR_NEXT_STEP"
    elif current_step:
        overall = "RUNNING"

    return {
        "overall_status": overall,
        "current_step": current_step,
        "last_attempted_step": last_step,
        "last_successful_step": last_successful_step,
        "failed_step": failed_step,
        "waiting_for": waiting_for,
        "next_expected_step": next_expected,
        "can_retry": overall in ("FAILED", "BLOCKED", "PARTIAL"),
        "requires_support": overall in ("FAILED", "BLOCKED"),
        "warnings_count": warnings_count,
        "errors_count": errors_count,
    }


def _new_document(
    *,
    execution_id: str,
    bank_code: str,
    bank_name: str | None,
    process_date: str | None,
    job_id: str | None,
    step: str | None = None,
) -> dict[str, Any]:
    now = datetime.now(timezone.utc).isoformat()
    return {
        "schema_version": SCHEMA_VERSION,
        "execution_id": execution_id,
        "process_id": None,
        "process_key": None,
        "power_automate_run_id": None,
        "step": (step or "").strip().upper() or None,
        "bank": {"code": bank_code, "name": bank_name or bank_code},
        "dates": {
            "run_started_at": now,
            "run_finished_at": None,
            "process_date": process_date,
            "report_date": None,
            "bank_transaction_dates": [],
        },
        "summary": recompute_summary([]),
        "events": [],
        "artifacts": {},
        "affected_entities": [],
        "metrics": {},
        "manifest_snapshot": None,
        "logging": {
            "revision": 0,
            "last_updated_at": now,
            "write_status": "OK",
            "possible_gaps": False,
            "file_result": None,
        },
        "correlation": {"seed_job_id": job_id},
    }


def _content_endpoint(site_id: str, drive_id: str, rel_path: str) -> str:
    enc = encode_graph_drive_path(rel_path.strip().strip("/"))
    return f"/sites/{site_id}/drives/{drive_id}/root:/{enc}:/content"


def _item_endpoint(site_id: str, drive_id: str, rel_path: str) -> str:
    enc = encode_graph_drive_path(rel_path.strip().strip("/"))
    return f"/sites/{site_id}/drives/{drive_id}/root:/{enc}"


async def _ensure_parent_folders(
    graph: GraphApiPort,
    site_id: str,
    drive_id: str,
    file_rel_path: str,
) -> None:
    from app.application.services.dated_artifact_layout import ensure_parent_folders

    await ensure_parent_folders(graph, site_id, drive_id, file_rel_path)


async def _read_log(
    graph: GraphApiPort,
    site_id: str,
    drive_id: str,
    rel_path: str,
) -> tuple[dict[str, Any] | None, str | None]:
    etag: str | None = None
    try:
        meta = await graph.get(_item_endpoint(site_id, drive_id, rel_path))
        etag = str(meta.get("eTag") or meta.get("@odata.etag") or "") or None
    except Exception:
        etag = None
    try:
        raw = await graph.get_bytes(_content_endpoint(site_id, drive_id, rel_path))
        doc = json.loads(raw.decode("utf-8"))
        if not isinstance(doc, dict):
            return None, etag
        return doc, etag
    except Exception:
        return None, etag


async def _write_log(
    graph: GraphApiPort,
    site_id: str,
    drive_id: str,
    rel_path: str,
    doc: dict[str, Any],
    *,
    if_match: str | None,
) -> dict[str, Any]:
    payload = json.dumps(doc, ensure_ascii=False, indent=2).encode("utf-8")
    return await graph.put_bytes(
        _content_endpoint(site_id, drive_id, rel_path),
        payload,
        content_type="application/json",
        if_match=if_match,
    )


def _append_event(doc: dict[str, Any], event: dict[str, Any]) -> dict[str, Any]:
    events = list(doc.get("events") or [])
    event_id = str(event.get("event_id") or "")
    if event_id and any(str(e.get("event_id") or "") == event_id for e in events):
        return doc
    event = dict(event)
    event["sequence"] = len(events) + 1
    events.append(event)
    doc["events"] = events
    doc["summary"] = recompute_summary(events)
    logging_meta = dict(doc.get("logging") or {})
    logging_meta["revision"] = int(logging_meta.get("revision") or 0) + 1
    logging_meta["last_updated_at"] = datetime.now(timezone.utc).isoformat()
    logging_meta["write_status"] = "OK"
    logging_meta["file_result"] = filename_result_token(str(event.get("status") or ""))
    doc["logging"] = logging_meta

    arts = event.get("artifacts")
    if isinstance(arts, list):
        root_arts = dict(doc.get("artifacts") or {})
        for a in arts:
            if not isinstance(a, dict):
                continue
            role = str(a.get("role") or "OTHER")
            path = str(a.get("path") or a.get("file_name") or role)
            root_arts[f"{role}|{path}"] = a
        doc["artifacts"] = root_arts
    ents = event.get("affected_entities")
    if isinstance(ents, list):
        by_key: dict[str, dict[str, Any]] = {}
        for existing in doc.get("affected_entities") or []:
            if isinstance(existing, dict):
                k = (
                    f"{existing.get('client')}|{existing.get('credit')}|"
                    f"{existing.get('application_type')}"
                )
                by_key[k] = existing
        for ent in ents:
            if isinstance(ent, dict):
                k = f"{ent.get('client')}|{ent.get('credit')}|{ent.get('application_type')}"
                by_key[k] = {**(by_key.get(k) or {}), **ent}
        doc["affected_entities"] = list(by_key.values())
    metrics = event.get("metrics")
    if isinstance(metrics, dict):
        root_m = dict(doc.get("metrics") or {})
        root_m.update(metrics)
        doc["metrics"] = root_m

    overall = str((doc.get("summary") or {}).get("overall_status") or "")
    if overall in (
        "SUCCEEDED",
        "FAILED",
        "BLOCKED",
        "PARTIAL",
        "COMPLETED_WITH_WARNINGS",
    ):
        dates = dict(doc.get("dates") or {})
        dates["run_finished_at"] = datetime.now(timezone.utc).isoformat()
        doc["dates"] = dates

    if event.get("process_id"):
        doc["process_id"] = event.get("process_id")
    if event.get("process_key"):
        doc["process_key"] = event.get("process_key")
    if isinstance(event.get("manifest_snapshot"), dict):
        doc["manifest_snapshot"] = event["manifest_snapshot"]
    step = str(event.get("step") or "").strip().upper()
    if step:
        doc["step"] = step
    return doc


def _day_from_path_or_today(rel: str, fallback: date | None = None) -> date:
    for seg in rel.replace("\\", "/").split("/"):
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", seg):
            try:
                return date.fromisoformat(seg)
            except ValueError:
                break
    return fallback or now_colombia().date()


def _path_looks_like_started_for_step(rel: str, step: str) -> bool:
    name = rel.replace("\\", "/").rsplit("/", 1)[-1].lower()
    step_t = step_filename_token(step)
    return f"_{step_t}_started_" in name or name.endswith(f"_{step_t}_started.json")


async def initialize_execution_log(
    graph: GraphApiPort,
    site_id: str,
    drive_id: str,
    *,
    execution_id: str,
    bank_code: str,
    process_date: date | str,
    job_id: str | None = None,
    bank_name: str | None = None,
) -> dict[str, Any]:
    """
    Crea el JSON inicial del intento GENERATE (QUEUED → archivo ``..._STARTED_...``).
    Si el flag está apagado, no hace nada.
    """
    if not execution_run_log_enabled():
        return {
            "execution_id": execution_id,
            "execution_log_path": "",
            "execution_log_status": "DISABLED",
        }

    day = (
        process_date
        if isinstance(process_date, date)
        else date.fromisoformat(str(process_date)[:10])
    )
    when = now_colombia()
    rel = build_execution_log_relative_path(
        bank_code=bank_code,
        day=day,
        execution_id=execution_id,
        step="GENERATE",
        result="STARTED",
        when=when,
    )
    try:
        await _ensure_parent_folders(graph, site_id, drive_id, rel)
        doc = _new_document(
            execution_id=execution_id,
            bank_code=bank_code,
            bank_name=bank_name,
            process_date=day.isoformat(),
            job_id=job_id,
            step="GENERATE",
        )
        queued = {
            "event_id": f"{execution_id}:GENERATE:main:1:QUEUED:{job_id or 'none'}",
            "step": "GENERATE",
            "substep": None,
            "attempt": 1,
            "status": "QUEUED",
            "job_id": job_id,
            "queued_at": datetime.now(timezone.utc).isoformat(),
            "started_at": None,
            "finished_at": None,
            "duration_ms": None,
            "severity": "info",
            "error": None,
            "metrics": {},
            "artifacts": [],
            "affected_entities": [],
        }
        doc = _append_event(doc, queued)
        await _write_log(
            graph, site_id, drive_id, rel, sanitize_for_execution_log(doc), if_match=None
        )
        return {
            "execution_id": execution_id,
            "execution_log_path": rel,
            "execution_log_status": "OK",
        }
    except Exception as exc:
        logger.warning(
            "execution_log initialize falló execution_id=%s path=%s: %s",
            execution_id,
            rel,
            exc,
        )
        return {
            "execution_id": execution_id,
            "execution_log_path": rel,
            "execution_log_status": "WRITE_FAILED",
            "execution_log_warning": str(exc)[:500],
        }


async def record_execution_event(
    graph: GraphApiPort,
    site_id: str,
    drive_id: str,
    *,
    execution_id: str,
    execution_log_path: str,
    step: str,
    status: str,
    job_id: str | None = None,
    attempt: int = 1,
    substep: str | None = None,
    error: dict[str, Any] | None = None,
    metrics: dict[str, Any] | None = None,
    artifacts: list[dict[str, Any]] | None = None,
    affected_entities: list[dict[str, Any]] | None = None,
    process_id: str | None = None,
    process_key: str | None = None,
    manifest_snapshot: dict[str, Any] | None = None,
    severity: str | None = None,
    bank_code: str | None = None,
    process_date: date | str | None = None,
) -> dict[str, Any]:
    """
    Escribe un archivo por intento/estado de endpoint.
    STARTED/QUEUED → archivo ``..._STARTED_...``.
    Terminal → archivo nuevo ``..._SUCCEEDED|FAILED|...`` (conserva el STARTED).
    Nunca propaga excepciones de negocio.
    """
    if not execution_run_log_enabled():
        return {"execution_log_status": "DISABLED"}
    if not execution_id:
        return {"execution_log_status": "SKIPPED_NO_PATH"}

    step_u = str(step or "").strip().upper() or "STEP"
    status_u = str(status or "").strip().upper()
    result_token = filename_result_token(status_u)
    hint_path = (execution_log_path or "").strip().strip("/")

    bank = normalize_bank_token(bank_code or "")
    if bank == "banco" and hint_path:
        # Intentar inferir banco del nombre previo: execution_log_{bank}_...
        base_name = hint_path.rsplit("/", 1)[-1]
        m = re.match(r"execution_log_([a-z0-9_]+)_", base_name, re.I)
        if m:
            bank = normalize_bank_token(m.group(1))

    if isinstance(process_date, date):
        day = process_date
    elif process_date:
        try:
            day = date.fromisoformat(str(process_date)[:10])
        except ValueError:
            day = _day_from_path_or_today(hint_path)
    else:
        day = _day_from_path_or_today(hint_path)

    when = now_colombia()
    out_rel = build_execution_log_relative_path(
        bank_code=bank,
        day=day,
        execution_id=execution_id,
        step=step_u,
        result=result_token,
        when=when,
    )

    event_id = (
        f"{execution_id}:{step_u}:{substep or 'main'}:{attempt}:{status_u}:{job_id or 'none'}"
    )
    now = datetime.now(timezone.utc).isoformat()
    sev = severity or (
        "error"
        if status_u in ("FAILED", "BLOCKED")
        else "warning"
        if status_u in ("PARTIAL", "COMPLETED_WITH_WARNINGS")
        else "info"
    )
    event: dict[str, Any] = {
        "event_id": event_id,
        "step": step_u,
        "substep": substep,
        "attempt": attempt,
        "status": status_u,
        "job_id": job_id,
        "queued_at": None,
        "started_at": now if status_u == "STARTED" else None,
        "finished_at": now if status_u in _TERMINAL_EVENT else None,
        "duration_ms": None,
        "severity": sev,
        "error": sanitize_for_execution_log(error) if error else None,
        "metrics": sanitize_for_execution_log(metrics or {}),
        "artifacts": sanitize_for_execution_log(artifacts or []),
        "affected_entities": sanitize_for_execution_log(affected_entities or []),
        "process_id": process_id,
        "process_key": process_key,
        "manifest_snapshot": sanitize_for_execution_log(manifest_snapshot)
        if manifest_snapshot
        else None,
    }

    last_err: str | None = None
    for _ in range(_MAX_WRITE_RETRIES):
        try:
            doc: dict[str, Any] | None = None
            etag: str | None = None
            # Continuar el mismo intento: leer el STARTED previo del mismo step.
            if (
                status_u in _TERMINAL_EVENT
                and hint_path
                and _path_looks_like_started_for_step(hint_path, step_u)
            ):
                doc, _etag_ignored = await _read_log(graph, site_id, drive_id, hint_path)
                etag = None  # archivo nuevo; no if-match sobre el STARTED

            if doc is None and hint_path and result_token == "STARTED" and hint_path == out_rel:
                doc, etag = await _read_log(graph, site_id, drive_id, hint_path)

            if doc is None:
                doc = _new_document(
                    execution_id=execution_id,
                    bank_code=bank,
                    bank_name=None,
                    process_date=day.isoformat(),
                    job_id=job_id,
                    step=step_u,
                )
                await _ensure_parent_folders(graph, site_id, drive_id, out_rel)

            doc = _append_event(doc, event)
            safe = sanitize_for_execution_log(doc)
            if isinstance(safe.get("logging"), dict):
                safe["logging"].pop("etag", None)
            await _ensure_parent_folders(graph, site_id, drive_id, out_rel)
            await _write_log(graph, site_id, drive_id, out_rel, safe, if_match=etag)
            return {
                "execution_id": execution_id,
                "execution_log_path": out_rel,
                "execution_log_status": "OK",
                "execution_log_file_result": result_token,
            }
        except Exception as exc:
            last_err = str(exc)
            msg = last_err.lower()
            if "412" in msg or "precondition" in msg:
                continue
            break

    logger.warning(
        "execution_log record falló execution_id=%s step=%s status=%s: %s",
        execution_id,
        step_u,
        status_u,
        last_err,
    )
    return {
        "execution_id": execution_id,
        "execution_log_path": out_rel,
        "execution_log_status": "WRITE_FAILED",
        "execution_log_warning": (last_err or "")[:500],
        "execution_log_file_result": result_token,
    }


def new_execution_id() -> str:
    return str(uuid.uuid4())


def default_process_day() -> date:
    return now_colombia().date()


def should_reuse_execution_id(
    *,
    existing_execution_id: str,
    is_active: bool,
    estado_proceso: str,
) -> bool:
    """
    Reutiliza el ``execution_id`` de control solo cuando sigue siendo la misma corrida
    (activa, o reintento tras fallo temprano en VACIO/ERROR_*). No reutiliza tras
    ``AMORTIZACION_APLICADA`` (nuevo lote de negocio).
    """
    eid = (existing_execution_id or "").strip()
    if not eid:
        return False
    if is_active:
        return True
    estado = (estado_proceso or "").strip().upper()
    if estado == "AMORTIZACION_APLICADA":
        return False
    if estado in ("", "VACIO") or estado.startswith("ERROR_"):
        return True
    return False
