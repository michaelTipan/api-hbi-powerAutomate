"""
Mueve PDFs de asientos contables a PROCESADOS dentro de la carpeta ASIENTOS CONTABLES CRED del crédito.
"""

from __future__ import annotations

import logging
import re
from collections import Counter
from dataclasses import dataclass
from typing import Any, Literal

import httpx

from app.application.sharepoint_resolution import encode_graph_drive_path
from app.domain.ports.graph import GraphApiPort

logger = logging.getLogger(__name__)

PROCESADOS_FOLDER_NAME = "PROCESADOS"
ASIENTOS_FOLDER_MARKER = "ASIENTOS CONTABLES CRED"

AccountingPdfMoveStatus = Literal[
    "moved", "already_moved", "skipped", "warning", "error"
]


@dataclass(frozen=True)
class AccountingPdfMoveRecord:
    source_path: str
    processed_folder_path: str
    destination_path: str
    status: AccountingPdfMoveStatus
    reason: str
    bank_code: str
    credito: str
    id_pago: str
    event_index: int

    def as_dict(self) -> dict[str, Any]:
        return {
            "source_path": self.source_path,
            "processed_folder_path": self.processed_folder_path,
            "destination_path": self.destination_path,
            "status": self.status,
            "reason": self.reason,
            "bank_code": self.bank_code,
            "credito": self.credito,
            "id_pago": self.id_pago,
            "event_index": self.event_index,
        }


def _normalize_rel_path(path: str) -> str:
    return path.strip().strip("/").replace("\\", "/")


def _sanitize_filename_token(value: str, *, fallback: str) -> str:
    cleaned = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", str(value or "").strip())
    cleaned = re.sub(r"[^\w.\-]+", "_", cleaned)
    cleaned = cleaned.strip("._-")
    return cleaned or fallback


def _credito_slug(credito: str) -> str:
    digits = re.search(r"\d+", str(credito or ""))
    if digits:
        return digits.group(0)
    return _sanitize_filename_token(credito, fallback="credito")


def _parent_asientos_folder(asiento_pdf_path: str) -> str | None:
    """
    Carpeta que contiene el PDF (ASIENTOS CONTABLES CRED {n}), no PROCESADOS.
    """
    rel = _normalize_rel_path(asiento_pdf_path)
    if not rel or "/" not in rel:
        return None
    parent = rel.rsplit("/", 1)[0]
    parts = parent.split("/")
    if any(p.casefold() == PROCESADOS_FOLDER_NAME.casefold() for p in parts):
        idx = next(
            i
            for i, p in enumerate(parts)
            if p.casefold() == PROCESADOS_FOLDER_NAME.casefold()
        )
        if idx <= 0:
            return None
        parent = "/".join(parts[:idx])
    if ASIENTOS_FOLDER_MARKER.casefold() not in parent.casefold():
        return None
    return parent


def _is_under_procesados(asiento_pdf_path: str) -> bool:
    parts = _normalize_rel_path(asiento_pdf_path).split("/")
    return any(p.casefold() == PROCESADOS_FOLDER_NAME.casefold() for p in parts)


def build_processed_asiento_filename(
    *,
    payment_date_iso: str,
    bank_code: str,
    credito: str,
    id_pago: str,
    event_index: int,
    use_event_suffix: bool,
    collision_suffix: int = 0,
) -> str:
    date_part = _sanitize_filename_token(payment_date_iso, fallback="sin-fecha")
    bank_part = _sanitize_filename_token(bank_code, fallback="banco")
    cred_part = _credito_slug(credito)
    pago_part = _sanitize_filename_token(id_pago, fallback="pago")
    stem = f"asiento_{date_part}_{bank_part}_credito-{cred_part}_pago-{pago_part}"
    if use_event_suffix and event_index > 0:
        stem += f"_evento-{event_index}"
    if collision_suffix > 0:
        stem += f"_{collision_suffix}"
    return f"{stem}.pdf"


def _item_endpoint(site_id: str, drive_id: str, rel_path: str) -> str:
    enc = encode_graph_drive_path(rel_path)
    return f"/sites/{site_id}/drives/{drive_id}/root:/{enc}:"


async def _drive_item_exists(
    graph: GraphApiPort, site_id: str, drive_id: str, rel_path: str
) -> bool:
    try:
        await graph.get(_item_endpoint(site_id, drive_id, rel_path))
        return True
    except httpx.HTTPStatusError as exc:
        if exc.response is not None and exc.response.status_code == 404:
            return False
        raise


async def _ensure_procesados_folder(
    graph: GraphApiPort, site_id: str, drive_id: str, asientos_parent: str
) -> str:
    processed_folder = f"{asientos_parent}/{PROCESADOS_FOLDER_NAME}"
    if await _drive_item_exists(graph, site_id, drive_id, processed_folder):
        return processed_folder
    enc_parent = encode_graph_drive_path(asientos_parent)
    children_ep = (
        f"/sites/{site_id}/drives/{drive_id}/root:/{enc_parent}:/children"
    )
    try:
        await graph.post_json(
            children_ep,
            {
                "name": PROCESADOS_FOLDER_NAME,
                "folder": {},
                "@microsoft.graph.conflictBehavior": "fail",
            },
        )
    except httpx.HTTPStatusError as exc:
        if exc.response is not None and exc.response.status_code in (409, 200):
            pass
        elif await _drive_item_exists(graph, site_id, drive_id, processed_folder):
            pass
        else:
            raise
    return processed_folder


def _allocate_destination_path(
    processed_folder: str,
    *,
    payment_date_iso: str,
    bank_code: str,
    credito: str,
    id_pago: str,
    event_index: int,
    use_event_suffix: bool,
    existing_destinations: set[str],
) -> str:
    for collision in range(0, 50):
        name = build_processed_asiento_filename(
            payment_date_iso=payment_date_iso,
            bank_code=bank_code,
            credito=credito,
            id_pago=id_pago,
            event_index=event_index,
            use_event_suffix=use_event_suffix,
            collision_suffix=collision,
        )
        dest = f"{processed_folder}/{name}"
        key = dest.casefold()
        if key not in existing_destinations:
            existing_destinations.add(key)
            return dest
    raise ValueError("destination_name_exhausted")


def candidate_processed_asiento_paths(
    asiento_pdf_path: str,
    *,
    payment_date_iso: str = "",
    bank_code: str = "",
    credito: str = "",
    id_pago: str = "",
    event_index: int = 0,
    use_event_suffix: bool = False,
    extra_payment_dates: tuple[str, ...] | list[str] | None = None,
) -> list[str]:
    """
    Candidatos en PROCESADOS para reintentos parciales (asiento ya movido).

    Orden: mismo nombre original → nombres canónicos por fecha(s) conocida(s).
    """
    parent = _parent_asientos_folder(asiento_pdf_path)
    if not parent:
        return []
    processed_folder = f"{parent}/{PROCESADOS_FOLDER_NAME}"
    source = _normalize_rel_path(asiento_pdf_path)
    original_name = source.rsplit("/", 1)[-1] if "/" in source else source
    out: list[str] = []
    seen: set[str] = set()

    def _add(path: str) -> None:
        key = path.casefold()
        if key in seen:
            return
        seen.add(key)
        out.append(path)

    if original_name:
        _add(f"{processed_folder}/{original_name}")

    dates: list[str] = []
    for raw in (payment_date_iso, *(extra_payment_dates or ())):
        d = str(raw or "").strip()
        if d and d not in dates:
            dates.append(d)
    if not dates:
        dates.append("sin-fecha")

    for date_iso in dates:
        try:
            dest = _allocate_destination_path(
                processed_folder,
                payment_date_iso=date_iso,
                bank_code=bank_code,
                credito=credito,
                id_pago=id_pago,
                event_index=event_index,
                use_event_suffix=use_event_suffix,
                existing_destinations=set(),
            )
            _add(dest)
            if use_event_suffix is False and event_index > 0:
                dest_sfx = _allocate_destination_path(
                    processed_folder,
                    payment_date_iso=date_iso,
                    bank_code=bank_code,
                    credito=credito,
                    id_pago=id_pago,
                    event_index=event_index,
                    use_event_suffix=True,
                    existing_destinations=set(),
                )
                _add(dest_sfx)
        except ValueError:
            continue
    return out


async def list_processed_asiento_paths(
    graph: GraphApiPort,
    site_id: str,
    drive_id: str,
    asiento_pdf_path: str,
) -> list[str]:
    """Lista PDFs bajo PROCESADOS del crédito (recuperación cuando el nombre canónico no coincide)."""
    parent = _parent_asientos_folder(asiento_pdf_path)
    if not parent:
        return []
    processed_folder = f"{parent}/{PROCESADOS_FOLDER_NAME}"
    if not await _drive_item_exists(graph, site_id, drive_id, processed_folder):
        return []
    enc = encode_graph_drive_path(processed_folder)
    ep = f"/sites/{site_id}/drives/{drive_id}/root:/{enc}:/children"
    try:
        payload = await graph.get(ep, params={"$select": "name,file", "$top": "200"})
    except Exception as exc:
        logger.warning("No se pudo listar PROCESADOS %s: %s", processed_folder, exc)
        return []
    out: list[str] = []
    for item in payload.get("value") or []:
        if not isinstance(item, dict) or not item.get("file"):
            continue
        name = str(item.get("name") or "").strip()
        if not name.lower().endswith(".pdf"):
            continue
        out.append(f"{processed_folder}/{name}")
    return out


def match_processed_asiento_path(
    candidates: list[str],
    *,
    id_pago: str,
    credito: str,
    original_name: str = "",
) -> str | None:
    """Elige el mejor match en PROCESADOS por nombre original, id_pago o crédito."""
    if not candidates:
        return None
    orig = (original_name or "").casefold()
    if orig:
        for path in candidates:
            if path.rsplit("/", 1)[-1].casefold() == orig:
                return path
    pago_token = _sanitize_filename_token(id_pago, fallback="").casefold()
    if pago_token:
        needle = f"pago-{pago_token}"
        hits = [p for p in candidates if needle in p.rsplit("/", 1)[-1].casefold()]
        if len(hits) == 1:
            return hits[0]
        if len(hits) > 1:
            cred = _credito_slug(credito).casefold()
            cred_hits = [p for p in hits if cred and f"credito-{cred}" in p.rsplit("/", 1)[-1].casefold()]
            if len(cred_hits) == 1:
                return cred_hits[0]
            return hits[0]
    cred = _credito_slug(credito).casefold()
    if cred:
        hits = [p for p in candidates if f"credito-{cred}" in p.rsplit("/", 1)[-1].casefold()]
        if len(hits) == 1:
            return hits[0]
    return None


async def resolve_asiento_pdf_bytes_with_procesados_fallback(
    download_fn,
    *,
    asiento_path: str,
    payment_date_iso: str = "",
    bank_code: str = "",
    credito: str = "",
    id_pago: str = "",
    event_index: int = 0,
    use_event_suffix: bool = False,
    extra_payment_dates: tuple[str, ...] | list[str] | None = None,
    list_procesados_fn=None,
) -> tuple[bytes, str, str]:
    """
    Descarga asiento desde ruta original o PROCESADOS.

    Returns:
        (pdf_bytes, resolved_path, source_label) donde source_label es ORIGINAL|PROCESADOS.
    """
    source = _normalize_rel_path(asiento_path)
    try:
        return await download_fn(source), source, "ORIGINAL"
    except Exception:
        pass

    for candidate in candidate_processed_asiento_paths(
        source,
        payment_date_iso=payment_date_iso,
        bank_code=bank_code,
        credito=credito,
        id_pago=id_pago,
        event_index=event_index,
        use_event_suffix=use_event_suffix,
        extra_payment_dates=extra_payment_dates,
    ):
        try:
            return await download_fn(candidate), candidate, "PROCESADOS"
        except Exception:
            continue

    if list_procesados_fn is not None:
        try:
            listed = await list_procesados_fn(source)
        except Exception:
            listed = []
        original_name = source.rsplit("/", 1)[-1] if "/" in source else source
        matched = match_processed_asiento_path(
            list(listed or []),
            id_pago=id_pago,
            credito=credito,
            original_name=original_name,
        )
        if matched:
            return await download_fn(matched), matched, "PROCESADOS"

    raise FileNotFoundError(
        f"asiento_not_found_original_nor_procesados:{source}"
    )


async def move_used_accounting_pdf_to_processed(
    graph: GraphApiPort,
    site_id: str,
    drive_id: str,
    *,
    asiento_pdf_path: str,
    bank_code: str,
    id_pago: str,
    credito: str,
    payment_date_iso: str,
    event_index: int,
    use_event_suffix: bool,
    existing_destinations: set[str],
) -> AccountingPdfMoveRecord:
    source = _normalize_rel_path(asiento_pdf_path)
    bank_code = (bank_code or "").strip()
    id_pago = (id_pago or "").strip()
    credito = (credito or "").strip()
    event_index = int(event_index or 0)

    if not source:
        return AccountingPdfMoveRecord(
            source_path="",
            processed_folder_path="",
            destination_path="",
            status="skipped",
            reason="missing_asiento_pdf_path",
            bank_code=bank_code,
            credito=credito,
            id_pago=id_pago,
            event_index=event_index,
        )

    asientos_parent = _parent_asientos_folder(source)
    if not asientos_parent:
        return AccountingPdfMoveRecord(
            source_path=source,
            processed_folder_path="",
            destination_path="",
            status="warning",
            reason="ASIENTO_NOT_UNDER_ASIENTOS_CONTABLES_CRED_FOLDER",
            bank_code=bank_code,
            credito=credito,
            id_pago=id_pago,
            event_index=event_index,
        )

    processed_folder = f"{asientos_parent}/{PROCESADOS_FOLDER_NAME}"

    if _is_under_procesados(source):
        return AccountingPdfMoveRecord(
            source_path=source,
            processed_folder_path=processed_folder,
            destination_path=source,
            status="already_moved",
            reason="source_already_under_PROCESADOS",
            bank_code=bank_code,
            credito=credito,
            id_pago=id_pago,
            event_index=event_index,
        )

    try:
        processed_folder = await _ensure_procesados_folder(
            graph, site_id, drive_id, asientos_parent
        )
    except Exception as exc:
        logger.warning("No se pudo crear PROCESADOS en %s: %s", asientos_parent, exc)
        return AccountingPdfMoveRecord(
            source_path=source,
            processed_folder_path=processed_folder,
            destination_path="",
            status="error",
            reason=f"PROCESADOS_FOLDER_CREATE_FAILED|{exc!s}"[:500],
            bank_code=bank_code,
            credito=credito,
            id_pago=id_pago,
            event_index=event_index,
        )

    dest_path = _allocate_destination_path(
        processed_folder,
        payment_date_iso=payment_date_iso,
        bank_code=bank_code,
        credito=credito,
        id_pago=id_pago,
        event_index=event_index,
        use_event_suffix=use_event_suffix,
        existing_destinations=existing_destinations,
    )
    dest_name = dest_path.rsplit("/", 1)[-1]

    source_exists = await _drive_item_exists(graph, site_id, drive_id, source)
    dest_exists = await _drive_item_exists(graph, site_id, drive_id, dest_path)

    if not source_exists and dest_exists:
        return AccountingPdfMoveRecord(
            source_path=source,
            processed_folder_path=processed_folder,
            destination_path=dest_path,
            status="already_moved",
            reason="source_missing_destination_present",
            bank_code=bank_code,
            credito=credito,
            id_pago=id_pago,
            event_index=event_index,
        )

    if not source_exists and not dest_exists:
        return AccountingPdfMoveRecord(
            source_path=source,
            processed_folder_path=processed_folder,
            destination_path=dest_path,
            status="warning",
            reason="ACCOUNTING_PDF_NOT_FOUND_FOR_MOVE",
            bank_code=bank_code,
            credito=credito,
            id_pago=id_pago,
            event_index=event_index,
        )

    if source_exists and dest_exists:
        alt_dest = _allocate_destination_path(
            processed_folder,
            payment_date_iso=payment_date_iso,
            bank_code=bank_code,
            credito=credito,
            id_pago=id_pago,
            event_index=event_index,
            use_event_suffix=use_event_suffix,
            existing_destinations=existing_destinations,
        )
        dest_path = alt_dest
        dest_name = dest_path.rsplit("/", 1)[-1]
        dest_exists = await _drive_item_exists(graph, site_id, drive_id, dest_path)
        if dest_exists:
            return AccountingPdfMoveRecord(
                source_path=source,
                processed_folder_path=processed_folder,
                destination_path=dest_path,
                status="warning",
                reason="destination_exists_no_overwrite",
                bank_code=bank_code,
                credito=credito,
                id_pago=id_pago,
                event_index=event_index,
            )

    parent_ref_path = f"/drive/root:/{processed_folder}"
    try:
        await graph.patch_json(
            _item_endpoint(site_id, drive_id, source),
            {
                "parentReference": {
                    "driveId": drive_id,
                    "path": parent_ref_path,
                },
                "name": dest_name,
            },
        )
        return AccountingPdfMoveRecord(
            source_path=source,
            processed_folder_path=processed_folder,
            destination_path=dest_path,
            status="moved",
            reason="",
            bank_code=bank_code,
            credito=credito,
            id_pago=id_pago,
            event_index=event_index,
        )
    except Exception as exc:
        logger.warning("Fallo moviendo asiento %s -> %s: %s", source, dest_path, exc)
        return AccountingPdfMoveRecord(
            source_path=source,
            processed_folder_path=processed_folder,
            destination_path=dest_path,
            status="error",
            reason=str(exc)[:500],
            bank_code=bank_code,
            credito=credito,
            id_pago=id_pago,
            event_index=event_index,
        )


def _payment_date_iso_for_item(item: dict[str, Any], dry_run: dict[str, Any] | None) -> str:
    raw = str(item.get("payment_date_iso") or "").strip()
    if raw:
        return raw
    if dry_run:
        return str(dry_run.get("report_date_iso") or "").strip()
    return ""


def _event_suffix_flags(items: list[dict[str, Any]]) -> dict[tuple[str, str], bool]:
    counts: Counter[tuple[str, str]] = Counter()
    for it in items:
        key = (
            str(it.get("id_pago") or "").strip(),
            _credito_slug(str(it.get("credito") or "")),
        )
        if key[0]:
            counts[key] += 1
    return {k: counts[k] > 1 for k in counts}


def _normalize_payment_date_iso(raw: Any) -> str:
    if raw is None:
        return ""
    if hasattr(raw, "isoformat"):
        try:
            return str(raw.isoformat())[:10]
        except Exception:
            return ""
    text = str(raw).strip()
    if len(text) >= 10 and text[4:5] == "-" and text[7:8] == "-":
        return text[:10]
    return text


def _asiento_paths_from_mapping(mapping: dict[str, Any]) -> list[str]:
    raw_paths = mapping.get("asiento_pdf_paths")
    if isinstance(raw_paths, list):
        paths = [
            _normalize_rel_path(str(p))
            for p in raw_paths
            if str(p or "").strip()
        ]
        if paths:
            return paths
    single = _normalize_rel_path(str(mapping.get("asiento_pdf_path") or ""))
    if not single:
        return []
    if " | " in single:
        return [
            _normalize_rel_path(part)
            for part in single.split(" | ")
            if part.strip()
        ]
    return [single]


def collect_used_asiento_items_from_merge_manifest(
    manifest: dict[str, Any],
    *,
    fallback_payment_date_iso: str = "",
) -> list[dict[str, Any]]:
    """
    Extrae asientos usados en el consolidado (outputs COMPLETE del merge manifest).

    No incluye incomplete_groups ni archivos sueltos de ASIENTOS.
    """
    from app.application.services.merge_group_validation import MERGE_GROUP_COMPLETE

    report_date = (
        _normalize_payment_date_iso(manifest.get("report_date_iso"))
        or _normalize_payment_date_iso(fallback_payment_date_iso)
    )
    items: list[dict[str, Any]] = []
    seen_paths: set[str] = set()

    for output in manifest.get("outputs") or []:
        if not isinstance(output, dict):
            continue
        status = str(output.get("status") or MERGE_GROUP_COMPLETE).strip()
        if status and status != MERGE_GROUP_COMPLETE:
            continue

        id_pago = str(output.get("id_pago") or "").strip()
        payment_date = (
            _normalize_payment_date_iso(output.get("fecha_banco")) or report_date
        )
        legacy_credito = str(output.get("credito") or "").strip()
        credit_items = output.get("credit_items")
        per_credit_index: Counter[str] = Counter()

        def _append(path: str, credito: str) -> None:
            norm = _normalize_rel_path(path)
            if not norm:
                return
            key = norm.casefold()
            if key in seen_paths:
                return
            seen_paths.add(key)
            cred = (credito or legacy_credito or "").strip()
            per_credit_index[cred] += 1
            items.append(
                {
                    "asiento_pdf_path": norm,
                    "id_pago": id_pago,
                    "credito": cred,
                    "event_index": per_credit_index[cred],
                    "payment_date_iso": payment_date,
                }
            )

        if isinstance(credit_items, list) and credit_items:
            for ci in credit_items:
                if not isinstance(ci, dict):
                    continue
                credito = str(ci.get("credito") or "").strip() or legacy_credito
                for path in _asiento_paths_from_mapping(ci):
                    _append(path, credito)
        else:
            for path in _asiento_paths_from_mapping(output):
                _append(path, legacy_credito)

    return items


async def _process_accounting_pdf_moves(
    graph: GraphApiPort,
    site_id: str,
    drive_id: str,
    *,
    eligible: list[dict[str, Any]],
    bank_code: str,
    dry_run: dict[str, Any] | None = None,
) -> dict[str, Any]:
    suffix_flags = _event_suffix_flags(eligible)
    existing_destinations: set[str] = set()
    moves: list[AccountingPdfMoveRecord] = []

    for it in eligible:
        id_pago = str(it.get("id_pago") or "").strip()
        credito = str(it.get("credito") or "").strip()
        event_index = int(it.get("event_index") or 0)
        use_suffix = suffix_flags.get((id_pago, _credito_slug(credito)), False)
        rec = await move_used_accounting_pdf_to_processed(
            graph,
            site_id,
            drive_id,
            asiento_pdf_path=str(it.get("asiento_pdf_path") or ""),
            bank_code=bank_code,
            id_pago=id_pago,
            credito=credito,
            payment_date_iso=_payment_date_iso_for_item(it, dry_run),
            event_index=event_index,
            use_event_suffix=use_suffix,
            existing_destinations=existing_destinations,
        )
        moves.append(rec)

    moved = sum(1 for m in moves if m.status == "moved")
    already = sum(1 for m in moves if m.status == "already_moved")
    warnings = sum(1 for m in moves if m.status == "warning")
    errors = sum(1 for m in moves if m.status == "error")
    skipped = sum(1 for m in moves if m.status == "skipped")

    return {
        "accounting_pdfs_processed_count": len(moves),
        "accounting_pdfs_moved_count": moved,
        "accounting_pdfs_already_moved_count": already,
        "accounting_pdfs_move_warnings_count": warnings,
        "accounting_pdfs_move_errors_count": errors,
        "accounting_pdfs_move_skipped_count": skipped,
        "accounting_pdfs_moves": [m.as_dict() for m in moves],
    }


async def process_used_accounting_pdfs_after_apply(
    graph: GraphApiPort,
    site_id: str,
    drive_id: str,
    *,
    items: list[dict[str, Any]],
    bank_code: str,
    verified_tabla_paths: set[str],
    dry_run: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """
    Mueve asientos de eventos APPLIED cuyas tablas pasaron verificación post-upload.
    """
    eligible: list[dict[str, Any]] = []
    for it in items:
        if not isinstance(it, dict):
            continue
        if it.get("apply_status") != "APPLIED":
            continue
        tabla = str(it.get("tabla_amortizacion_path") or "").strip()
        if tabla and tabla not in verified_tabla_paths:
            continue
        asiento = str(it.get("asiento_pdf_path") or "").strip()
        if not asiento:
            continue
        eligible.append(it)

    return await _process_accounting_pdf_moves(
        graph,
        site_id,
        drive_id,
        eligible=eligible,
        bank_code=bank_code,
        dry_run=dry_run,
    )


async def process_used_accounting_pdfs_after_soft_close(
    graph: GraphApiPort,
    site_id: str,
    drive_id: str,
    *,
    manifest: dict[str, Any],
    bank_code: str,
    fallback_payment_date_iso: str = "",
) -> dict[str, Any]:
    """
    Mueve a PROCESADOS los asientos usados en el consolidado (merge manifest).

    Best-effort a nivel de cada PDF (warnings/errors en el summary; no lanza).
    """
    eligible = collect_used_asiento_items_from_merge_manifest(
        manifest,
        fallback_payment_date_iso=fallback_payment_date_iso,
    )
    return await _process_accounting_pdf_moves(
        graph,
        site_id,
        drive_id,
        eligible=eligible,
        bank_code=bank_code,
        dry_run={"report_date_iso": fallback_payment_date_iso}
        if fallback_payment_date_iso
        else None,
    )


def empty_accounting_pdf_move_summary() -> dict[str, Any]:
    return {
        "accounting_pdfs_processed_count": 0,
        "accounting_pdfs_moved_count": 0,
        "accounting_pdfs_already_moved_count": 0,
        "accounting_pdfs_move_warnings_count": 0,
        "accounting_pdfs_move_errors_count": 0,
        "accounting_pdfs_move_skipped_count": 0,
        "accounting_pdfs_moves": [],
    }


def _filename_has_isolated_credit(filename: str, credit: str) -> bool:
    digits = _credito_slug(credit)
    if not digits:
        return False
    stem = filename.rsplit(".", 1)[0] if "." in filename else filename
    return re.search(rf"(?<!\d){re.escape(digits)}(?!\d)", stem) is not None


async def _list_pdf_names_in_folder(
    graph: GraphApiPort, site_id: str, drive_id: str, folder: str
) -> list[str]:
    rel = _normalize_rel_path(folder)
    if not rel:
        return []
    enc = encode_graph_drive_path(rel)
    try:
        payload = await graph.get(
            f"/sites/{site_id}/drives/{drive_id}/root:/{enc}:/children"
        )
    except httpx.HTTPStatusError as exc:
        if exc.response is not None and exc.response.status_code == 404:
            return []
        raise
    items = payload.get("value") if isinstance(payload, dict) else []
    names: list[str] = []
    for item in items or []:
        if not isinstance(item, dict) or "folder" in item:
            continue
        name = str(item.get("name") or "").strip()
        if name and name.lower().endswith(".pdf") and not name.startswith("~$"):
            names.append(name)
    return names


async def restore_processed_asientos_for_credit(
    graph: GraphApiPort,
    site_id: str,
    drive_id: str,
    *,
    asientos_dir: str,
    credit: str,
) -> list[AccountingPdfMoveRecord]:
    """Mueve a ASIENTOS los PDF de PROCESADOS de un crédito fallido.

    Si la carpeta ASIENTOS ya tiene un PDF con el crédito en el nombre,
    no toca PROCESADOS (el operador ya reemplazó el archivo).
    """
    parent = _normalize_rel_path(asientos_dir)
    credito = str(credit or "").strip()
    if not parent or not credito:
        return []
    processed_folder = f"{parent}/{PROCESADOS_FOLDER_NAME}"
    records: list[AccountingPdfMoveRecord] = []

    try:
        parent_names = await _list_pdf_names_in_folder(
            graph, site_id, drive_id, parent
        )
    except Exception as exc:
        logger.warning("restore PROCESADOS: list ASIENTOS falló %s: %s", parent, exc)
        return [
            AccountingPdfMoveRecord(
                source_path="",
                processed_folder_path=processed_folder,
                destination_path="",
                status="error",
                reason=f"ASIENTOS_LIST_FAILED|{exc!s}"[:500],
                bank_code="",
                credito=credito,
                id_pago="",
                event_index=0,
            )
        ]

    if any(_filename_has_isolated_credit(n, credito) for n in parent_names):
        return [
            AccountingPdfMoveRecord(
                source_path="",
                processed_folder_path=processed_folder,
                destination_path="",
                status="skipped",
                reason="asientos_already_has_credit_pdf",
                bank_code="",
                credito=credito,
                id_pago="",
                event_index=0,
            )
        ]

    try:
        processed_names = await _list_pdf_names_in_folder(
            graph, site_id, drive_id, processed_folder
        )
    except Exception as exc:
        logger.warning(
            "restore PROCESADOS: list falló %s: %s", processed_folder, exc
        )
        return [
            AccountingPdfMoveRecord(
                source_path="",
                processed_folder_path=processed_folder,
                destination_path="",
                status="warning",
                reason=f"PROCESADOS_LIST_FAILED|{exc!s}"[:500],
                bank_code="",
                credito=credito,
                id_pago="",
                event_index=0,
            )
        ]

    parent_lower = {n.casefold() for n in parent_names}
    for name in processed_names:
        if not _filename_has_isolated_credit(name, credito):
            continue
        source = f"{processed_folder}/{name}"
        dest_name = name
        if dest_name.casefold() in parent_lower:
            records.append(
                AccountingPdfMoveRecord(
                    source_path=source,
                    processed_folder_path=processed_folder,
                    destination_path=f"{parent}/{dest_name}",
                    status="skipped",
                    reason="destination_exists_no_overwrite",
                    bank_code="",
                    credito=credito,
                    id_pago="",
                    event_index=0,
                )
            )
            continue
        parent_ref_path = f"/drive/root:/{parent}"
        try:
            await graph.patch_json(
                _item_endpoint(site_id, drive_id, source),
                {
                    "parentReference": {
                        "driveId": drive_id,
                        "path": parent_ref_path,
                    },
                    "name": dest_name,
                },
            )
            parent_lower.add(dest_name.casefold())
            records.append(
                AccountingPdfMoveRecord(
                    source_path=source,
                    processed_folder_path=processed_folder,
                    destination_path=f"{parent}/{dest_name}",
                    status="moved",
                    reason="restored_from_PROCESADOS",
                    bank_code="",
                    credito=credito,
                    id_pago="",
                    event_index=0,
                )
            )
        except Exception as exc:
            logger.warning(
                "restore PROCESADOS: falló %s -> %s: %s", source, parent, exc
            )
            records.append(
                AccountingPdfMoveRecord(
                    source_path=source,
                    processed_folder_path=processed_folder,
                    destination_path=f"{parent}/{dest_name}",
                    status="error",
                    reason=str(exc)[:500],
                    bank_code="",
                    credito=credito,
                    id_pago="",
                    event_index=0,
                )
            )
    return records
