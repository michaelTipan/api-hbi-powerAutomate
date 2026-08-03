"""Upload de PDF de asientos contables desde la UI (R3).

Cliente envía id_pago + credito (+ tipo) + PDF base64.
El servidor resuelve RutaAsientosContables desde el histórico y genera el nombre.
Nunca acepta path SharePoint del cliente.
"""
from __future__ import annotations

import base64
import logging
import os
import re
from datetime import date
from io import BytesIO
from typing import Any, Protocol

from openpyxl import load_workbook

from app.application.services.colombia_time import today_colombia_iso
from app.application.services.historical_application_rows import (
    read_validated_abono_rows,
    read_validated_payment_rows,
)
from app.application.services.review_schema import normalize_credito_digits
from app.application.sharepoint_resolution import (
    encode_graph_drive_path,
    resolve_sharepoint_from_env,
)
from app.application.ui.download_limits import ui_max_download_bytes
from app.application.ui.path_guard import assert_path_allowed
from app.application.ui.ports import UiSharePointReadPort
from app.application.ui.schemas import (
    UiAsientosUploadRequest,
    UiAsientosUploadResponse,
)
from app.application.use_cases.merge_composite_validado_pdfs import (
    _filename_contains_credit_isolated,
    _pdf_names_in_children,
    _ruta_asientos_from_cell,
)
from app.application.use_cases.send_validar_extractos_notification import (
    _list_drive_folder_children,
)
from app.application.use_cases.validate_payment_report import _graph_download_by_path

logger = logging.getLogger(__name__)

# Ventana operativa para cargar soportes (no CONSOLIDANDO/CONSOLIDADO).
ASIENTOS_UPLOAD_STATES: frozenset[str] = frozenset(
    {
        "PENDIENTE_ASIENTOS",
        "MERGE_PARCIAL",
        "ERROR_MERGE",
    }
)

_PDF_MAGIC = b"%PDF"
_DEFAULT_MAX_UPLOAD = 10 * 1024 * 1024


class AsientosUploadError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(message)


class _GraphWrite(Protocol):
    async def get(self, *a: Any, **k: Any) -> Any: ...
    async def get_bytes(self, *a: Any, **k: Any) -> Any: ...
    async def put_bytes(self, *a: Any, **k: Any) -> Any: ...


def max_asientos_upload_bytes() -> int:
    raw = (os.getenv("UI_ASIENTOS_MAX_UPLOAD_BYTES") or "").strip()
    if not raw:
        return min(_DEFAULT_MAX_UPLOAD, ui_max_download_bytes())
    try:
        return max(1024, int(raw))
    except ValueError:
        return _DEFAULT_MAX_UPLOAD


def decode_pdf_base64(content_base64: str, *, max_bytes: int | None = None) -> bytes:
    raw_b64 = (content_base64 or "").strip()
    if not raw_b64:
        raise AsientosUploadError("empty_pdf", "El PDF está vacío.")
    # data:application/pdf;base64,...
    if "," in raw_b64 and raw_b64.lower().startswith("data:"):
        raw_b64 = raw_b64.split(",", 1)[1]
    try:
        data = base64.b64decode(raw_b64, validate=False)
    except Exception as exc:
        raise AsientosUploadError(
            "invalid_base64", "No se pudo decodificar el PDF (base64 inválido)."
        ) from exc
    cap = max_bytes if max_bytes is not None else max_asientos_upload_bytes()
    if len(data) > cap:
        raise AsientosUploadError(
            "pdf_too_large",
            f"El PDF supera el límite de {cap} bytes.",
        )
    if len(data) < 5 or not data.startswith(_PDF_MAGIC):
        raise AsientosUploadError(
            "invalid_pdf",
            "El archivo no parece un PDF válido.",
        )
    return data


def _sanitize_token(value: str, *, max_len: int = 48) -> str:
    text = re.sub(r"[^\w\s\-áéíóúÁÉÍÓÚñÑ]", " ", str(value or ""), flags=re.UNICODE)
    text = re.sub(r"\s+", " ", text).strip()
    return text[:max_len].strip()


def _tipo_token(tipo_aplicacion: str | None) -> str:
    raw = (tipo_aplicacion or "").strip()
    if not raw:
        return "PAGO CUOTA"
    upper = raw.upper()
    if upper in {"PAGO", "PAGO CUOTA"}:
        return "PAGO CUOTA"
    if "ABONO" in upper and "MORA" in upper:
        return "ABONO MORA"
    if "ABONO" in upper and "CAPITAL" in upper:
        return "ABONO CAPITAL"
    if "PAGO Y ABONO" in upper:
        return "PAGO Y ABONO CAPITAL"
    if upper == "ABONO":
        return "ABONO CAPITAL"
    cleaned = _sanitize_token(raw, max_len=40)
    return cleaned.upper() if cleaned else "PAGO CUOTA"


def _date_token(process_date: str | None) -> str:
    """Formato 02-AUG-2026 (estilo operador)."""
    raw = (process_date or "").strip()
    try:
        d = date.fromisoformat(raw) if raw else date.fromisoformat(today_colombia_iso())
    except ValueError:
        d = date.fromisoformat(today_colombia_iso())
    months = (
        "JAN",
        "FEB",
        "MAR",
        "APR",
        "MAY",
        "JUN",
        "JUL",
        "AUG",
        "SEP",
        "OCT",
        "NOV",
        "DEC",
    )
    return f"{d.day:02d}-{months[d.month - 1]}-{d.year}"


def build_asiento_filename(
    *,
    credito_digits: str,
    tipo_aplicacion: str | None,
    cliente: str | None,
    process_date: str | None,
    existing_names: list[str],
) -> str:
    """Nombre trazable con dígitos de crédito aislados; evita colisión."""
    digits = (credito_digits or "").strip()
    if not digits:
        raise AsientosUploadError("invalid_credito", "Crédito inválido.")
    date_tok = _date_token(process_date)
    tipo_tok = _tipo_token(tipo_aplicacion)
    cliente_tok = _sanitize_token(cliente or "", max_len=32)
    parts = ["Asiento", date_tok, tipo_tok]
    if cliente_tok:
        parts.append(cliente_tok)
    parts.extend(["CRED", digits])
    base = " ".join(parts) + ".pdf"
    if not _filename_contains_credit_isolated(base, digits):
        raise AsientosUploadError(
            "filename_credit_mismatch",
            "El nombre generado no incluye el crédito de forma aislada.",
        )
    existing = {n.casefold() for n in existing_names}
    if base.casefold() not in existing:
        return base
    stem = base[:-4]
    for i in range(2, 50):
        candidate = f"{stem} evento-{i}.pdf"
        if candidate.casefold() not in existing:
            return candidate
    raise AsientosUploadError(
        "duplicate_asiento_name",
        "Ya existen demasiados PDF con el mismo nombre en la carpeta.",
    )


def _process_date_from_key(process_key: str) -> str | None:
    parts = (process_key or "").split("|")
    if len(parts) >= 3:
        cand = parts[2].strip()
        try:
            date.fromisoformat(cand)
            return cand
        except ValueError:
            return None
    return None


def _find_target_row(
    payment_rows: list[dict[str, Any]],
    abono_rows: list[dict[str, Any]],
    *,
    id_pago: str,
    credito_digits: str,
) -> dict[str, Any]:
    want_id = (id_pago or "").strip()
    want_cred = (credito_digits or "").strip()
    if not want_id or not want_cred:
        raise AsientosUploadError(
            "missing_identity",
            "id_pago y credito son obligatorios.",
        )
    candidates: list[dict[str, Any]] = []
    for row in list(payment_rows) + list(abono_rows):
        if str(row.get("id_pago") or "").strip() != want_id:
            continue
        digits = str(row.get("credito_digits") or "").strip()
        if digits != want_cred:
            continue
        candidates.append(row)
    if not candidates:
        raise AsientosUploadError(
            "row_not_found",
            "No hay fila validada en el histórico para ese id_pago y crédito.",
        )
    # Preferir fila con ruta de asientos
    for row in candidates:
        if _ruta_asientos_from_cell(row.get("ruta_asientos_cell")):
            return row
    raise AsientosUploadError(
        "missing_ruta_asientos_contables",
        "La fila no tiene carpeta de asientos provisionada.",
    )


async def upload_asiento_pdf(
    reader: UiSharePointReadPort,
    graph: _GraphWrite,
    *,
    process_key: str,
    banks: tuple[str, ...],
    body: UiAsientosUploadRequest,
) -> UiAsientosUploadResponse:
    key = (process_key or "").strip()
    matched_bank: str | None = None
    snap = None
    for bank in banks:
        try:
            control = await reader.read_process_control(bank)
        except Exception:
            continue
        if (control.snapshot.process_key or "").strip() == key:
            matched_bank = bank
            snap = control.snapshot
            break
    if snap is None or matched_bank is None:
        raise KeyError(key)

    if not snap.is_active:
        raise AsientosUploadError(
            "process_not_active",
            "No hay un proceso activo para cargar asientos.",
        )
    estado = (snap.estado_proceso or "").strip().upper()
    if estado not in ASIENTOS_UPLOAD_STATES:
        raise AsientosUploadError(
            "control_not_ready_for_asientos",
            "El proceso no está esperando soportes de asientos.",
        )

    historico = (snap.historical_file_path or "").strip().strip("/")
    if not historico:
        raise AsientosUploadError(
            "missing_historical_file",
            "Falta el Excel histórico del proceso.",
        )

    credito_digits = normalize_credito_digits(body.credito) or re.sub(
        r"\D", "", str(body.credito or "")
    )
    pdf_bytes = decode_pdf_base64(body.content_base64)

    from app.application.ui.path_guard import collect_allowed_roots_from_env

    roots = collect_allowed_roots_from_env()
    assert_path_allowed(historico, roots=roots)

    ctx = await resolve_sharepoint_from_env(graph)  # type: ignore[arg-type]
    site_id = str(ctx["site_id"])
    drive_id = str(ctx["drive_id"])
    hist_bytes = await _graph_download_by_path(graph, site_id, drive_id, historico)

    estado_token = (
        os.getenv("GRAPH_VALIDAR_EXTRACTO_ESTADO_CONTAINS") or "VALIDAR"
    ).strip() or "VALIDAR"
    wb = load_workbook(filename=BytesIO(hist_bytes), data_only=True)
    try:
        payment_rows = read_validated_payment_rows(wb, legacy_estado_token=estado_token)
        abono_rows = read_validated_abono_rows(wb)
    finally:
        wb.close()

    row = _find_target_row(
        payment_rows,
        abono_rows,
        id_pago=body.id_pago,
        credito_digits=credito_digits,
    )
    folder = _ruta_asientos_from_cell(row.get("ruta_asientos_cell"))
    if not folder:
        raise AsientosUploadError(
            "missing_ruta_asientos_contables",
            "No hay carpeta ASIENTOS para este crédito.",
        )
    assert_path_allowed(folder, roots=roots)

    children = await _list_drive_folder_children(graph, site_id, drive_id, folder)
    existing = _pdf_names_in_children(children)
    tipo = (body.tipo_aplicacion or str(row.get("tipo_aplicacion_original") or "")).strip() or None
    filename = build_asiento_filename(
        credito_digits=credito_digits,
        tipo_aplicacion=tipo,
        cliente=str(row.get("cliente") or ""),
        process_date=_process_date_from_key(key),
        existing_names=existing,
    )
    replaced = filename.casefold() in {n.casefold() for n in existing}
    target_path = f"{folder}/{filename}".replace("//", "/")
    assert_path_allowed(target_path, roots=roots)

    enc = encode_graph_drive_path(target_path)
    endpoint = f"/sites/{site_id}/drives/{drive_id}/root:/{enc}:/content"
    put_resp = await graph.put_bytes(
        endpoint,
        pdf_bytes,
        content_type="application/pdf",
    )
    web_url: str | None = None
    if isinstance(put_resp, dict):
        web = put_resp.get("webUrl") or put_resp.get("web_url")
        web_url = str(web).strip() if web else None

    return UiAsientosUploadResponse(
        process_key=key,
        bank_code=matched_bank,
        id_pago=str(body.id_pago).strip(),
        credito=credito_digits,
        tipo_aplicacion=tipo,
        filename=filename,
        folder_path=folder,
        web_url=web_url,
        replaced_existing=replaced,
    )
