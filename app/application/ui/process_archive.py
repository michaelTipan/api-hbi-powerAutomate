"""Archivo de procesos (Fase 2): snapshots JSON en 04 ARCHIVO PROCESOS.

No modifica el Control activo. Escritura best-effort (fallo no tumba Apply/Generate).
Lectura para GET /process-history.
"""
from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Protocol

from app.application.config.payment_validation_settings import (
    resolve_process_archive_folder_path,
)
from app.application.sharepoint_resolution import encode_graph_drive_path
from app.application.ui.environment import resolve_active_environment
from app.application.use_cases.setup_merge_control_workbook import (
    process_date_from_process_key,
)

logger = logging.getLogger(__name__)

ARCHIVE_SCHEMA_VERSION = 1
_FILENAME_RE = re.compile(
    r"^proceso_(?P<bank>[a-z0-9_]+)_(?P<date>\d{4}-\d{2}-\d{2})_(?P<pid>[^.]+)\.json$",
    re.IGNORECASE,
)


class _GraphLike(Protocol):
    async def get(self, *a: Any, **k: Any) -> Any: ...
    async def get_bytes(self, *a: Any, **k: Any) -> Any: ...
    async def put_bytes(self, *a: Any, **k: Any) -> Any: ...


@dataclass(frozen=True)
class ProcessArchiveSnapshot:
    schema_version: int
    environment: str
    process_key: str
    process_id: str
    bank_code: str
    bank_name: str
    process_date: str | None
    closed_at: str
    archive_reason: str
    control_estado_proceso: str
    operational_status: str
    paths: dict[str, str | None]
    archive_path: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "environment": self.environment,
            "process_key": self.process_key,
            "process_id": self.process_id,
            "bank_code": self.bank_code,
            "bank_name": self.bank_name,
            "process_date": self.process_date,
            "closed_at": self.closed_at,
            "archive_reason": self.archive_reason,
            "control_estado_proceso": self.control_estado_proceso,
            "operational_status": self.operational_status,
            "paths": dict(self.paths),
            "archive_path": self.archive_path,
        }


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _nz(value: str | None) -> str:
    return (value or "").strip()


def archive_filename(*, bank_code: str, process_date: str, process_id: str) -> str:
    bc = _nz(bank_code) or "banco"
    pd = _nz(process_date) or "0000-00-00"
    pid = _nz(process_id) or "unknown"
    return f"proceso_{bc}_{pd}_{pid}.json"


def archive_relative_path(*, bank_code: str, process_date: str, process_id: str) -> str:
    folder = resolve_process_archive_folder_path().strip().strip("/")
    name = archive_filename(
        bank_code=bank_code, process_date=process_date, process_id=process_id
    )
    return f"{folder}/{name}".replace("//", "/")


def operational_status_for_archive_estado(estado: str) -> str:
    e = _nz(estado).upper()
    if e == "AMORTIZACION_APLICADA":
        return "COMPLETADO"
    if e in {"CANCELADO", "VACIO"}:
        return "CANCELADO"
    if "ERROR" in e:
        return "ERROR_RECUPERABLE"
    if e:
        return "COMPLETADO"
    return "DESCONOCIDO"


def build_snapshot_payload(
    *,
    process_key: str,
    process_id: str,
    bank_code: str,
    bank_name: str,
    process_date: str | None,
    control_estado_proceso: str,
    archive_reason: str,
    validation_file_path: str | None = None,
    historical_file_path: str | None = None,
    secretary_file_path: str | None = None,
    email_pdf_path: str | None = None,
    merge_manifest_path: str | None = None,
    closed_at: str | None = None,
    environment: str | None = None,
) -> ProcessArchiveSnapshot:
    pk = _nz(process_key)
    pid = _nz(process_id)
    if not pid and "|" in pk:
        pid = pk.rsplit("|", 1)[-1]
    pd = _nz(process_date) or None
    if not pd and pk:
        d = process_date_from_process_key(pk)
        pd = d.isoformat() if d else None
    estado = _nz(control_estado_proceso)
    env = environment or resolve_active_environment().environment
    rel = archive_relative_path(
        bank_code=_nz(bank_code),
        process_date=pd or "0000-00-00",
        process_id=pid or "unknown",
    )
    return ProcessArchiveSnapshot(
        schema_version=ARCHIVE_SCHEMA_VERSION,
        environment=env,
        process_key=pk,
        process_id=pid,
        bank_code=_nz(bank_code),
        bank_name=_nz(bank_name),
        process_date=pd,
        closed_at=closed_at or _utc_now_iso(),
        archive_reason=_nz(archive_reason) or "unknown",
        control_estado_proceso=estado,
        operational_status=operational_status_for_archive_estado(estado),
        paths={
            "validation_file": _nz(validation_file_path) or None,
            "historical_file": _nz(historical_file_path) or None,
            "secretary_file": _nz(secretary_file_path) or None,
            "email_pdf": _nz(email_pdf_path) or None,
            "merge_manifest": _nz(merge_manifest_path) or None,
        },
        archive_path=rel,
    )


def snapshot_from_control_snap(
    snap: Any,
    *,
    archive_reason: str,
    control_estado_proceso: str | None = None,
    validation_file_path: str | None = None,
) -> ProcessArchiveSnapshot | None:
    """Construye snapshot desde ProcessControlSnapshot (o duck-type)."""
    pk = _nz(getattr(snap, "process_key", None))
    if not pk:
        return None
    estado = _nz(control_estado_proceso) or _nz(getattr(snap, "estado_proceso", None))
    return build_snapshot_payload(
        process_key=pk,
        process_id=_nz(getattr(snap, "process_id", None)),
        bank_code=_nz(getattr(snap, "bank_code", None)),
        bank_name=_nz(getattr(snap, "bank_name", None)),
        process_date=None,
        control_estado_proceso=estado,
        archive_reason=archive_reason,
        validation_file_path=(
            validation_file_path
            if validation_file_path is not None
            else getattr(snap, "validation_file_path", None)
        ),
        historical_file_path=getattr(snap, "historical_file_path", None),
        secretary_file_path=getattr(snap, "secretary_file_path", None),
        email_pdf_path=getattr(snap, "email_pdf_path", None),
        merge_manifest_path=getattr(snap, "merge_manifest_path", None),
    )


async def upload_process_archive_snapshot(
    graph: _GraphLike,
    site_id: str,
    drive_id: str,
    snapshot: ProcessArchiveSnapshot,
) -> str:
    """Sube/reemplaza el JSON. Idempotente por path (mismo process_id)."""
    rel = snapshot.archive_path.strip().strip("/")
    enc = encode_graph_drive_path(rel)
    body = json.dumps(snapshot.to_dict(), ensure_ascii=False, indent=2).encode("utf-8")
    await graph.put_bytes(
        f"/sites/{site_id}/drives/{drive_id}/root:/{enc}:/content",
        body,
        content_type="application/json",
    )
    return rel


async def try_archive_process_snapshot(
    graph: _GraphLike,
    site_id: str,
    drive_id: str,
    snap: Any,
    *,
    archive_reason: str,
    control_estado_proceso: str | None = None,
    validation_file_path: str | None = None,
) -> str | None:
    """Best-effort: nunca propaga error al flujo productivo."""
    try:
        snapshot = snapshot_from_control_snap(
            snap,
            archive_reason=archive_reason,
            control_estado_proceso=control_estado_proceso,
            validation_file_path=validation_file_path,
        )
        if snapshot is None:
            return None
        return await upload_process_archive_snapshot(
            graph, site_id, drive_id, snapshot
        )
    except Exception:
        logger.warning(
            "process_archive: no se pudo archivar reason=%s",
            archive_reason,
            exc_info=True,
        )
        return None


def parse_archive_filename(name: str) -> dict[str, str] | None:
    m = _FILENAME_RE.match((name or "").strip())
    if not m:
        return None
    return {
        "bank_code": m.group("bank"),
        "process_date": m.group("date"),
        "process_id": m.group("pid"),
    }


def snapshot_from_dict(data: dict[str, Any], *, archive_path: str = "") -> ProcessArchiveSnapshot:
    paths_raw = data.get("paths") if isinstance(data.get("paths"), dict) else {}
    paths = {
        "validation_file": _nz(paths_raw.get("validation_file")) or None,
        "historical_file": _nz(paths_raw.get("historical_file")) or None,
        "secretary_file": _nz(paths_raw.get("secretary_file")) or None,
        "email_pdf": _nz(paths_raw.get("email_pdf")) or None,
        "merge_manifest": _nz(paths_raw.get("merge_manifest")) or None,
    }
    pk = _nz(data.get("process_key"))
    estado = _nz(data.get("control_estado_proceso"))
    return ProcessArchiveSnapshot(
        schema_version=int(data.get("schema_version") or ARCHIVE_SCHEMA_VERSION),
        environment=_nz(data.get("environment")) or "unknown",
        process_key=pk,
        process_id=_nz(data.get("process_id")),
        bank_code=_nz(data.get("bank_code")),
        bank_name=_nz(data.get("bank_name")),
        process_date=_nz(data.get("process_date")) or None,
        closed_at=_nz(data.get("closed_at")) or "",
        archive_reason=_nz(data.get("archive_reason")) or "unknown",
        control_estado_proceso=estado,
        operational_status=_nz(data.get("operational_status"))
        or operational_status_for_archive_estado(estado),
        paths=paths,
        archive_path=_nz(archive_path) or _nz(data.get("archive_path")),
    )


async def list_archive_folder_children(
    graph: _GraphLike,
    site_id: str,
    drive_id: str,
    *,
    folder_rel: str | None = None,
) -> list[dict[str, Any]]:
    folder = (folder_rel or resolve_process_archive_folder_path()).strip().strip("/")
    if folder:
        enc = encode_graph_drive_path(folder)
        endpoint = f"/sites/{site_id}/drives/{drive_id}/root:/{enc}:/children"
    else:
        endpoint = f"/sites/{site_id}/drives/{drive_id}/root/children"
    try:
        resp = await graph.get(endpoint)
    except Exception:
        logger.info("process_archive: list children failed folder=%s", folder, exc_info=True)
        return []
    return list(resp.get("value") or [])


async def list_process_archive_snapshots(
    graph: _GraphLike,
    site_id: str,
    drive_id: str,
    *,
    bank_code: str | None = None,
    limit: int = 100,
) -> list[ProcessArchiveSnapshot]:
    """Lista snapshots JSON (parsea cada archivo; acotado por limit)."""
    children = await list_archive_folder_children(graph, site_id, drive_id)
    folder = resolve_process_archive_folder_path().strip().strip("/")
    want_bank = _nz(bank_code).lower()
    candidates: list[tuple[str, str]] = []
    for item in children:
        name = str(item.get("name") or "")
        meta = parse_archive_filename(name)
        if not meta:
            continue
        if want_bank and meta["bank_code"].lower() != want_bank:
            continue
        rel = f"{folder}/{name}".replace("//", "/")
        candidates.append((rel, name))
    # Más recientes primero por nombre (fecha + id en el filename).
    candidates.sort(key=lambda t: t[1], reverse=True)
    out: list[ProcessArchiveSnapshot] = []
    for rel, _name in candidates[: max(1, min(limit, 200))]:
        try:
            enc = encode_graph_drive_path(rel)
            raw = await graph.get_bytes(
                f"/sites/{site_id}/drives/{drive_id}/root:/{enc}:/content"
            )
            data = json.loads(raw.decode("utf-8"))
            if not isinstance(data, dict):
                continue
            out.append(snapshot_from_dict(data, archive_path=rel))
        except Exception:
            logger.info("process_archive: skip unreadable %s", rel, exc_info=True)
            continue
    return out


async def load_process_archive_snapshot(
    graph: _GraphLike,
    site_id: str,
    drive_id: str,
    process_key: str,
) -> ProcessArchiveSnapshot | None:
    """Busca un process_key en el archivo (por process_id del key o listado)."""
    key = _nz(process_key)
    if not key:
        return None
    pid = key.rsplit("|", 1)[-1] if "|" in key else ""
    # Intento directo: reconstruir path desde process_key.
    parts = key.split("|")
    if len(parts) >= 4:
        bank = parts[1]
        date_s = parts[2]
        rel = archive_relative_path(
            bank_code=bank, process_date=date_s, process_id=parts[3]
        )
        try:
            enc = encode_graph_drive_path(rel)
            raw = await graph.get_bytes(
                f"/sites/{site_id}/drives/{drive_id}/root:/{enc}:/content"
            )
            data = json.loads(raw.decode("utf-8"))
            if isinstance(data, dict):
                snap = snapshot_from_dict(data, archive_path=rel)
                if snap.process_key == key or (pid and snap.process_id == pid):
                    return snap
        except Exception:
            pass
    for snap in await list_process_archive_snapshots(
        graph, site_id, drive_id, limit=200
    ):
        if snap.process_key == key or (pid and snap.process_id == pid):
            return snap
    return None
