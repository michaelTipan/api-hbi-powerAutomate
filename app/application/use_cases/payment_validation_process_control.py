"""
Lectura/actualización del control oficial por banco (fila 2, hoja Procesos).

Única fuente operativa del flujo Generate → Apply.
"""

from __future__ import annotations

import asyncio
import io
import os
from dataclasses import dataclass
from datetime import datetime
from typing import Any

import httpx
from openpyxl import load_workbook

from app.application.config.payment_validation_settings import (
    BANK_CODE_BANCOLOMBIA,
    BANK_CODE_BOGOTA,
    normalize_bank_code,
    resolve_bank_control_file_path,
    validate_bank_code,
)
from app.application.services.colombia_time import now_colombia_iso

__all__ = [
    "BANK_CODE_BANCOLOMBIA",
    "BANK_CODE_BOGOTA",
    "ProcessControlSnapshot",
    "normalize_bank_code",
    "validate_bank_code",
    "resolve_process_control_path_for_bank",
    "parse_process_control_row2",
    "download_process_control_bytes",
    "read_process_control_snapshot",
    "update_process_control_row2",
    "utc_now_iso",
]
from app.application.sharepoint_resolution import encode_graph_drive_path
from app.application.use_cases.setup_merge_control_workbook import (
    PROCESS_CONTROL_COLUMNS,
    SHEET_NAME,
)
from app.domain.ports.graph import GraphApiPort


def resolve_process_control_path_for_bank(bank_code: str) -> str:
    return resolve_bank_control_file_path(bank_code)


def utc_now_iso() -> str:
    """
    Marca de tiempo operativa (ISO con offset de Colombia).

    El nombre histórico ``utc_now_iso`` se conserva por compatibilidad de imports;
    el valor es siempre America/Bogota (``-05:00``), no UTC.
    """
    return now_colombia_iso()


def _content_endpoint(site_id: str, drive_id: str, rel_path: str) -> str:
    enc = encode_graph_drive_path(rel_path.strip().strip("/"))
    return f"/sites/{site_id}/drives/{drive_id}/root:/{enc}:/content"


def _item_endpoint(site_id: str, drive_id: str, rel_path: str) -> str:
    """Metadatos del ítem (eTag) sin descargar el .xlsx completo."""
    enc = encode_graph_drive_path(rel_path.strip().strip("/"))
    return f"/sites/{site_id}/drives/{drive_id}/root:/{enc}:"


def _col_index(name: str) -> int:
    return PROCESS_CONTROL_COLUMNS.index(name) + 1


def _is_active_cell(value: Any) -> bool:
    if value is True:
        return True
    if value in (False, None):
        return False
    s = str(value).strip().lower()
    # Excel en español muestra VERDADERO/FALSO; aceptar ambas convenciones.
    return s in ("true", "1", "yes", "si", "sí", "x", "verdadero")


@dataclass(frozen=True)
class ProcessControlSnapshot:
    control_file_path: str
    estado_proceso: str
    is_active: bool
    process_key: str
    process_id: str
    validation_file_path: str
    historical_file_path: str
    secretary_file_path: str
    email_pdf_path: str
    notify_idempotency_key: str
    merge_manifest_path: str
    merge_idempotency_key: str
    apply_idempotency_key: str
    bank_code: str
    bank_name: str
    execution_id: str = ""
    execution_log_path: str = ""


def parse_process_control_row2(raw: bytes, *, control_file_path: str) -> ProcessControlSnapshot:
    wb = load_workbook(filename=io.BytesIO(raw), data_only=True)
    try:
        if SHEET_NAME not in wb.sheetnames:
            raise ValueError("process_control_invalid_structure")
        ws = wb[SHEET_NAME]
        if ws.max_row < 2:
            raise ValueError("process_control_invalid_structure")

        header_map: dict[str, int] = {}
        for c in range(1, (ws.max_column or 0) + 1):
            h = str(ws.cell(row=1, column=c).value or "").strip()
            if h and h not in header_map:
                header_map[h] = c

        def cell(name: str) -> Any:
            if name not in PROCESS_CONTROL_COLUMNS:
                return None
            col = header_map.get(name)
            if col is None:
                # Workbook antiguo sin la columna aditiva.
                if name in ("ExecutionId", "ExecutionLogPath"):
                    return None
                col = _col_index(name)
            if col > (ws.max_column or 0):
                return None
            return ws.cell(row=2, column=col).value

        estado = str(cell("EstadoProceso") or "").strip()
        is_active = _is_active_cell(cell("IsActive"))
        pkey = str(cell("ProcessKey") or "").strip()
        pid = str(cell("ProcessId") or "").strip()
        vpath = str(cell("ValidationFilePath") or "").strip().strip("/")
        hpath = str(cell("HistoricalFilePath") or "").strip().strip("/")
        spath = str(cell("SecretaryFilePath") or "").strip().strip("/")
        epdf = str(cell("EmailPdfPath") or "").strip().strip("/")
        nid = str(cell("NotifyIdempotencyKey") or "").strip()
        mmp = str(cell("MergeManifestPath") or "").strip().strip("/")
        mid = str(cell("MergeIdempotencyKey") or "").strip()
        aid = str(cell("ApplyIdempotencyKey") or "").strip()
        bc = str(cell("BankCode") or "").strip()
        bn = str(cell("BankName") or "").strip()
        eid = str(cell("ExecutionId") or "").strip()
        elp = str(cell("ExecutionLogPath") or "").strip().strip("/")

        return ProcessControlSnapshot(
            control_file_path=control_file_path,
            estado_proceso=estado,
            is_active=is_active,
            process_key=pkey,
            process_id=pid,
            validation_file_path=vpath,
            historical_file_path=hpath,
            secretary_file_path=spath,
            email_pdf_path=epdf,
            notify_idempotency_key=nid,
            merge_manifest_path=mmp,
            merge_idempotency_key=mid,
            apply_idempotency_key=aid,
            bank_code=bc,
            bank_name=bn,
            execution_id=eid,
            execution_log_path=elp,
        )
    finally:
        closer = getattr(wb, "close", None)
        if callable(closer):
            closer()


async def download_process_control_bytes(
    graph: GraphApiPort, site_id: str, drive_id: str, *, bank_code: str
) -> tuple[str, bytes]:
    rel = resolve_process_control_path_for_bank(bank_code).strip().strip("/")
    raw = await graph.get_bytes(_content_endpoint(site_id, drive_id, rel))
    return rel, raw


async def read_process_control_snapshot(
    graph: GraphApiPort, site_id: str, drive_id: str, *, bank_code: str
) -> ProcessControlSnapshot:
    rel, raw = await download_process_control_bytes(graph, site_id, drive_id, bank_code=bank_code)
    return parse_process_control_row2(raw, control_file_path=rel)


async def update_process_control_row2(
    graph: GraphApiPort,
    site_id: str,
    drive_id: str,
    *,
    bank_code: str,
    updates: dict[str, Any],
) -> None:
    rel = resolve_process_control_path_for_bank(bank_code).strip().strip("/")
    content_ep = _content_endpoint(site_id, drive_id, rel)

    def _apply_row2_updates(payload: bytes) -> bytes:
        """Parchea fila 2 del control en hilo aparte (openpyxl bloquea el event loop)."""
        wb = load_workbook(filename=io.BytesIO(payload), data_only=False)
        try:
            if SHEET_NAME not in wb.sheetnames:
                raise ValueError("process_control_invalid_structure")
            ws = wb[SHEET_NAME]
            if ws.max_row < 2:
                raise ValueError("process_control_invalid_structure")

            header_map: dict[str, int] = {}
            for c in range(1, (ws.max_column or 0) + 1):
                h = str(ws.cell(row=1, column=c).value or "").strip()
                if h and h not in header_map:
                    header_map[h] = c

            for key, val in updates.items():
                if key not in PROCESS_CONTROL_COLUMNS:
                    continue
                col = header_map.get(key) or _col_index(key)
                ws.cell(row=2, column=col, value=val)

            buf = io.BytesIO()
            wb.save(buf)
            return buf.getvalue()
        finally:
            closer = getattr(wb, "close", None)
            if callable(closer):
                closer()

    try:
        max_attempts = max(1, int(os.getenv("PROCESS_CONTROL_PUT_MAX_RETRIES", "3")))
    except ValueError:
        max_attempts = 3

    last_exc: Exception | None = None
    for attempt in range(max_attempts):
        etag: str | None = None
        try:
            meta = await graph.get(_item_endpoint(site_id, drive_id, rel))
            etag_raw = str(meta.get("eTag") or meta.get("@odata.etag") or "").strip()
            etag = etag_raw or None
        except Exception:
            etag = None

        raw = await graph.get_bytes(content_ep)
        out = await asyncio.to_thread(_apply_row2_updates, raw)

        try:
            put_kwargs: dict[str, Any] = {
                "content_type": (
                    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                ),
            }
            if etag:
                put_kwargs["if_match"] = etag
            await graph.put_bytes(content_ep, out, **put_kwargs)
            return
        except httpx.HTTPStatusError as exc:
            last_exc = exc
            # 412: otro job/UI escribió el control entre GET y PUT; reintentar con lectura fresca.
            if (
                exc.response is not None
                and exc.response.status_code == 412
                and attempt < max_attempts - 1
            ):
                continue
            raise

    if last_exc is not None:
        raise last_exc

