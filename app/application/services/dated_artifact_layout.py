"""Jerarquía SharePoint ``YYYY/MM/YYYY-MM-DD`` + id corto (8) para artefactos de lote.

Usado por HISTORICO, PDFs de correo, manifiestos merge, archivo JSON y logs.
No aplica a Control ni a la carpeta de revisión del día (sigue plano con UUID completo).
"""
from __future__ import annotations

import logging
import re
from datetime import date, datetime
from typing import Any, Protocol

from app.application.sharepoint_resolution import encode_graph_drive_path

logger = logging.getLogger(__name__)

SHORT_PROCESS_ID_LEN = 8
_DAY_FOLDER_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


class _GraphLike(Protocol):
    async def get(self, *a: Any, **k: Any) -> Any: ...
    async def post_json(self, *a: Any, **k: Any) -> Any: ...


def short_process_id(process_id: str, *, length: int = SHORT_PROCESS_ID_LEN) -> str:
    """Prefijo estable de 8 hex del process_id (sin guiones)."""
    raw = (process_id or "").strip().replace("-", "")
    if not raw:
        return "unknown"
    n = max(4, min(int(length), 32))
    return raw[:n].lower()


def parse_process_date(value: date | datetime | str | None) -> date | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    s = str(value).strip()[:10]
    if not s:
        return None
    try:
        return date.fromisoformat(s)
    except ValueError:
        return None


def dated_folder_relative(process_date: date | datetime | str) -> str:
    """``2026/08/2026-08-02``."""
    d = parse_process_date(process_date)
    if d is None:
        raise ValueError("invalid_process_date_for_dated_folder")
    return f"{d.year:04d}/{d.month:02d}/{d.isoformat()}"


def join_dated_artifact_path(
    root_folder: str,
    process_date: date | datetime | str,
    filename: str,
) -> str:
    """``{root}/YYYY/MM/YYYY-MM-DD/{filename}``."""
    root = (root_folder or "").strip().strip("/")
    name = (filename or "").strip().strip("/")
    if not name:
        raise ValueError("dated_artifact_requires_filename")
    mid = dated_folder_relative(process_date)
    if root:
        return f"{root}/{mid}/{name}".replace("//", "/")
    return f"{mid}/{name}".replace("//", "/")


async def ensure_folder_child(
    graph: _GraphLike,
    site_id: str,
    drive_id: str,
    parent_path: str,
    folder_name: str,
) -> None:
    parent = (parent_path or "").strip().strip("/")
    name = (folder_name or "").strip()
    if not name:
        return
    if parent:
        enc = encode_graph_drive_path(parent)
        endpoint = f"/sites/{site_id}/drives/{drive_id}/root:/{enc}:/children"
    else:
        endpoint = f"/sites/{site_id}/drives/{drive_id}/root/children"
    body: dict[str, Any] = {
        "name": name,
        "folder": {},
        "@microsoft.graph.conflictBehavior": "fail",
    }
    try:
        await graph.post_json(endpoint, body)
    except Exception as exc:
        msg = str(exc).lower()
        if "409" in msg or "namealreadyexists" in msg or "conflict" in msg:
            return
        logger.debug("dated_layout ensure_folder %s/%s: %s", parent, name, exc)


async def ensure_parent_folders(
    graph: _GraphLike,
    site_id: str,
    drive_id: str,
    file_rel_path: str,
) -> None:
    """Crea cada segmento de carpeta hasta el padre del archivo."""
    parts = [p for p in (file_rel_path or "").strip("/").split("/") if p]
    if len(parts) < 2:
        return
    acc = ""
    for part in parts[:-1]:
        parent = acc
        await ensure_folder_child(graph, site_id, drive_id, parent, part)
        acc = f"{acc}/{part}".strip("/") if acc else part


async def list_files_under_dated_or_flat(
    graph: _GraphLike,
    site_id: str,
    drive_id: str,
    root_folder: str,
    *,
    name_predicate=None,
) -> list[tuple[str, str]]:
    """
    Lista archivos bajo ``root`` en layout nuevo (año/mes/día) o plano legacy.

    Devuelve ``(relative_path, filename)``.
    """
    root = (root_folder or "").strip().strip("/")
    out: list[tuple[str, str]] = []

    async def _children(folder_rel: str) -> list[dict[str, Any]]:
        if folder_rel:
            enc = encode_graph_drive_path(folder_rel)
            endpoint = f"/sites/{site_id}/drives/{drive_id}/root:/{enc}:/children"
        else:
            endpoint = f"/sites/{site_id}/drives/{drive_id}/root/children"
        try:
            resp = await graph.get(endpoint)
            return list(resp.get("value") or [])
        except Exception:
            logger.info("dated_layout: list fail folder=%s", folder_rel, exc_info=True)
            return []

    def _accept(name: str) -> bool:
        if name_predicate is None:
            return True
        return bool(name_predicate(name))

    top = await _children(root)
    for item in top:
        name = str(item.get("name") or "")
        if not name:
            continue
        is_folder = "folder" in item
        rel = f"{root}/{name}".replace("//", "/") if root else name
        if not is_folder:
            if _accept(name):
                out.append((rel, name))
            continue
        # Año (2026) o día legacy directo bajo root
        if _DAY_FOLDER_RE.match(name):
            day_kids = await _children(rel)
            for kid in day_kids:
                kn = str(kid.get("name") or "")
                if kn and "folder" not in kid and _accept(kn):
                    out.append((f"{rel}/{kn}".replace("//", "/"), kn))
            continue
        if re.fullmatch(r"\d{4}", name):
            months = await _children(rel)
            for month_item in months:
                mn = str(month_item.get("name") or "")
                if not mn or "folder" not in month_item:
                    continue
                month_rel = f"{rel}/{mn}".replace("//", "/")
                days = await _children(month_rel)
                for day_item in days:
                    dn = str(day_item.get("name") or "")
                    if not dn or "folder" not in day_item:
                        continue
                    day_rel = f"{month_rel}/{dn}".replace("//", "/")
                    files = await _children(day_rel)
                    for f in files:
                        fn = str(f.get("name") or "")
                        if fn and "folder" not in f and _accept(fn):
                            out.append((f"{day_rel}/{fn}".replace("//", "/"), fn))
    return out
