# -*- coding: utf-8 -*-
"""RO audit: Generate extract selection vs max fecha_limite for Bancolombia lote.

Uses AppServiceGraphHttp smoke proxy (GET-only). No SharePoint mutations.
"""
from __future__ import annotations

import asyncio
import hashlib
import io
import json
import os
import re
import sys
import unicodedata
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import quote

from dotenv import load_dotenv
from openpyxl import load_workbook

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

load_dotenv(Path(r"D:\CMC\HBI_Capital\api-hbi-powerAutomate.env"), override=False)
os.environ["UI_SHAREPOINT_SMOKE"] = "1"
os.environ.setdefault("ACTIVE_ENVIRONMENT", "sandbox")

from app.application.config.payment_validation_settings import (  # noqa: E402
    resolve_bank_control_file_path,
)
from app.application.services.extract_selection import (  # noqa: E402
    choose_extract_as_of_bank_date,
    extract_created_datetime_raw,
    extract_last_modified_datetime_raw,
    unreadable_pdf_reason,
)
from app.application.services.payment_helpers import (  # noqa: E402
    extract_fecha_limite_pago_from_pdf,
)
from app.application.services.review_schema import (  # noqa: E402
    AplicacionPagosCols,
    InternalPathCols,
    ReviewSheets,
    find_aplicacion_pagos_sheet,
)
from app.application.sharepoint_resolution import encode_graph_drive_path  # noqa: E402
from app.application.use_cases.payment_validation_process_control import (  # noqa: E402
    parse_process_control_row2,
)
from scripts.support.ui_appservice_graph_http import AppServiceGraphHttp  # noqa: E402

DEFAULT_BASE = (
    "https://app-hbiauto-prod-001-afawg2g7frgte8c5.eastus-01.azurewebsites.net"
)
SANDBOX_MARKER = "03 COMWARE PRUEBAS- INFORMACION CREDITOS CLIENTES"
EXTRACT_SOURCE_CREDIT_ROOT = "credit_root"
EXTRACT_SOURCE_EXTRACTOS = "extractos_folder"
OUT = ROOT / "scripts" / "_tmp" / "audit_bancolombia_extract_selection_out.json"


def _norm(s: str) -> str:
    t = unicodedata.normalize("NFKD", s or "")
    t = "".join(c for c in t if not unicodedata.combining(c))
    return " ".join(t.upper().split())


def _content_ep(site_id: str, drive_id: str, rel: str) -> str:
    enc = encode_graph_drive_path(rel.strip().strip("/"))
    return f"/sites/{site_id}/drives/{drive_id}/root:/{enc}:/content"


class SmokeGraph:
    """AppServiceGraphHttp + children listing via same App Service proxy."""

    def __init__(self, http: AppServiceGraphHttp) -> None:
        self.http = http
        self.base = http._base  # noqa: SLF001
        self._client = http._client  # noqa: SLF001

    async def ensure_ids(self) -> tuple[str, str]:
        return await self.http._ensure_ids()  # noqa: SLF001

    async def children(self, drive_id: str, folder_item_id: str = "root") -> list[dict]:
        r = await self._client.get(
            f"{self.base}/graph/sharepoint/drives/{quote(drive_id, safe='')}/children",
            params={"folder_item_id": folder_item_id},
        )
        r.raise_for_status()
        return list((r.json() or {}).get("value") or [])

    async def walk(self, drive_id: str, parts: list[str]) -> tuple[str, dict]:
        cur = "root"
        item: dict = {"id": "root", "name": "root"}
        for part in parts:
            kids = await self.children(drive_id, cur)
            hit = next((i for i in kids if str(i.get("name") or "") == part), None)
            if hit is None:
                # fuzzy accent-insensitive
                target = _norm(part)
                hits = [i for i in kids if _norm(str(i.get("name") or "")) == target]
                if not hits:
                    raise FileNotFoundError(f"missing segment {part!r} under {parts}")
                hit = hits[0]
            item = hit
            cur = str(hit.get("id") or "")
        return cur, item

    async def get_bytes(self, site_id: str, drive_id: str, rel: str) -> bytes:
        return await self.http.get_bytes(_content_ep(site_id, drive_id, rel))

    async def get_bytes_by_id(self, drive_id: str, item_id: str) -> bytes:
        """Direct App Service item-content (avoids per-path walk)."""
        import base64

        r = await self._client.get(
            f"{self.base}/graph/sharepoint/drives/{quote(drive_id, safe='')}/item-content",
            params={"item_id": item_id},
        )
        r.raise_for_status()
        return base64.b64decode((r.json() or {}).get("content_base64") or "")


def _is_strict_extract_pdf(item: dict) -> bool:
    if "folder" in item:
        return False
    name = str(item.get("name") or "")
    return "extracto" in name.lower() and name.lower().endswith(".pdf")


def _candidate(item: dict, *, parent_path: str, source_location: str) -> dict:
    name = str(item.get("name") or "")
    parent = parent_path.replace("\\", "/").rstrip("/")
    fsi = item.get("fileSystemInfo") if isinstance(item.get("fileSystemInfo"), dict) else {}
    created = item.get("createdDateTime") or fsi.get("createdDateTime")
    modified = item.get("lastModifiedDateTime") or fsi.get("lastModifiedDateTime")
    return {
        "item": item,
        "name": name,
        "parent_path": parent,
        "relative_path": f"{parent}/{name}".replace("//", "/"),
        "source_location": source_location,
        "id": item.get("id"),
        "createdDateTime": created,
        "lastModifiedDateTime": modified,
        "eTag": item.get("eTag") or item.get("etag"),
        "cTag": item.get("cTag") or item.get("ctag"),
    }


async def resolve_extract_pool(
    g: SmokeGraph, drive_id: str, credit_path: str, credit_item_id: str
) -> list[dict]:
    credit_norm = credit_path.replace("\\", "/").rstrip("/")
    kids = await g.children(drive_id, credit_item_id)
    pool: list[dict] = []
    for it in kids:
        if _is_strict_extract_pdf(it):
            pool.append(
                _candidate(it, parent_path=credit_norm, source_location=EXTRACT_SOURCE_CREDIT_ROOT)
            )
    for it in kids:
        if "folder" in it and str(it.get("name") or "").casefold() == "extractos":
            ex_name = str(it.get("name") or "EXTRACTOS")
            ex_path = f"{credit_norm}/{ex_name}".replace("//", "/")
            for child in await g.children(drive_id, str(it["id"])):
                if _is_strict_extract_pdf(child):
                    pool.append(
                        _candidate(
                            child,
                            parent_path=ex_path,
                            source_location=EXTRACT_SOURCE_EXTRACTOS,
                        )
                    )
            break
    return pool


def parse_review_selected(raw: bytes) -> dict[str, dict[str, Any]]:
    """credito_norm -> {ruta, link, cliente, name_hint} from Aplicacion_Pagos."""
    wb = load_workbook(filename=io.BytesIO(raw), data_only=True)
    try:
        ws = find_aplicacion_pagos_sheet(wb)
        header_row = None
        headers: dict[str, int] = {}
        for r in range(1, min(12, (ws.max_row or 1) + 1)):
            row_headers: dict[str, int] = {}
            for c in range(1, (ws.max_column or 0) + 1):
                h = str(ws.cell(r, c).value or "").strip()
                if h and h not in row_headers:
                    row_headers[h] = c
            if "_ruta_extracto" in row_headers or AplicacionPagosCols.ID_PAGO in row_headers:
                header_row = r
                headers = row_headers
                break
        if header_row is None:
            raise RuntimeError("Aplicacion_Pagos header row not found")

        def col(*names: str) -> int | None:
            for n in names:
                if n in headers:
                    return headers[n]
            # accent-insensitive fallback
            want = {_norm(n) for n in names}
            for h, idx in headers.items():
                if _norm(h) in want:
                    return idx
            return None

        c_cred = col(AplicacionPagosCols.CREDITO, "Crédito", "Credito")
        c_cli = col(AplicacionPagosCols.CLIENTE, "Cliente")
        c_ruta = col(InternalPathCols.RUTA_EXTRACTO, "_ruta_extracto")
        c_link = col(AplicacionPagosCols.LINK_EXTRACTO, "Link extracto")
        c_norm = col(InternalPathCols.CREDITO_NORMALIZADO, "_credito_normalizado")
        c_unidad = col(InternalPathCols.RUTA_UNIDAD_CREDITO, "_ruta_unidad_credito")
        out: dict[str, dict[str, Any]] = {}
        for r in range(header_row + 1, (ws.max_row or 1) + 1):
            cred = str(ws.cell(r, c_cred).value or "").strip() if c_cred else ""
            if not cred:
                continue
            digits = (
                str(ws.cell(r, c_norm).value or "").strip()
                if c_norm
                else ""
            ) or (re.sub(r"\D+", "", cred) or cred)
            ruta = str(ws.cell(r, c_ruta).value or "").strip() if c_ruta else ""
            link = str(ws.cell(r, c_link).value or "").strip() if c_link else ""
            # Prefer hyperlink target if present
            if c_link:
                cell = ws.cell(r, c_link)
                if cell.hyperlink and getattr(cell.hyperlink, "target", None):
                    link = str(cell.hyperlink.target)
            cliente = str(ws.cell(r, c_cli).value or "").strip() if c_cli else ""
            unidad = str(ws.cell(r, c_unidad).value or "").strip() if c_unidad else ""
            name_hint = ""
            if ruta:
                name_hint = Path(ruta.replace("\\", "/")).name
            elif link:
                m = re.search(r"([^/\\]+\.pdf)", link, re.I)
                if m:
                    name_hint = m.group(1)
            prev = out.get(digits)
            if prev is None or (ruta and not prev.get("ruta")):
                out[digits] = {
                    "credito": cred,
                    "credito_norm": digits,
                    "cliente": cliente,
                    "ruta": ruta.replace("\\", "/"),
                    "unidad": unidad.replace("\\", "/"),
                    "link": link,
                    "name_hint": name_hint,
                    "row": r,
                }
        meta = {}
        if ReviewSheets.META in wb.sheetnames:
            mws = wb[ReviewSheets.META]
            for r in range(1, min(40, (mws.max_row or 1) + 1)):
                k = str(mws.cell(r, 1).value or "").strip()
                v = mws.cell(r, 2).value
                if k:
                    meta[k] = v
        return {
            "by_credit": out,
            "meta": meta,
            "headers": sorted(headers),
            "header_row": header_row,
        }
    finally:
        closer = getattr(wb, "close", None)
        if callable(closer):
            closer()


def find_credit_folder(client_kids: list[dict], credit_id: str) -> dict | None:
    """Match CREDITO # 99 / CRED 99 / #99 etc."""
    cid = str(credit_id).strip()
    scored: list[tuple[int, dict]] = []
    for it in client_kids:
        if "folder" not in it:
            continue
        name = str(it.get("name") or "")
        n = _norm(name)
        # exclude asientos
        if "ASIENTO" in n:
            continue
        if re.search(rf"(?:CREDITO|CRED|OBLIGACION|#)\s*#?\s*{re.escape(cid)}\b", n):
            scored.append((0, it))
        elif re.search(rf"\b{re.escape(cid)}\b", n) and ("CRED" in n or "OBLIG" in n or "#" in name):
            scored.append((1, it))
    scored.sort(key=lambda t: t[0])
    return scored[0][1] if scored else None


def find_client_folder(root_kids: list[dict], hint: str) -> dict | None:
    if not hint:
        return None
    nh = _norm(hint)
    # exact / contains
    scored: list[tuple[int, dict]] = []
    for it in root_kids:
        if "folder" not in it:
            continue
        name = str(it.get("name") or "")
        if name.startswith(("00 ", "01 ", "02 ", "03 ", "04 ", "05 ", "06 ")):
            continue
        nn = _norm(name)
        if nn == nh:
            scored.append((0, it))
        elif nh in nn or nn in nh:
            scored.append((1, it))
        else:
            # token overlap
            th = set(nh.split())
            tn = set(nn.split())
            if len(th & tn) >= max(1, min(2, len(th))):
                scored.append((2, it))
    scored.sort(key=lambda t: (t[0], len(str(t[1].get("name") or ""))))
    return scored[0][1] if scored else None


async def score_pool(
    g: SmokeGraph,
    site_id: str,
    drive_id: str,
    pool: list[dict],
) -> tuple[list[tuple[dict, date, bytes, str]], list[dict]]:
    _ = site_id
    scored: list[tuple[dict, date, bytes, str]] = []
    damaged: list[dict] = []
    for cand in pool:
        rel = str(cand.get("relative_path") or "")
        name = str(cand.get("name") or "")
        item_id = str(cand.get("id") or "")
        try:
            if item_id:
                pdf = await g.get_bytes_by_id(drive_id, item_id)
            else:
                pdf = await g.get_bytes(site_id, drive_id, rel)
        except Exception as exc:
            damaged.append(
                {
                    "name": name,
                    "relative_path": rel,
                    "source_location": cand.get("source_location"),
                    "reason": "download_failed",
                    "detail": f"{type(exc).__name__}: {exc}",
                    "createdDateTime": extract_created_datetime_raw(cand),
                    "lastModifiedDateTime": extract_last_modified_datetime_raw(cand)
                    or cand.get("lastModifiedDateTime"),
                }
            )
            continue
        fe = await asyncio.to_thread(extract_fecha_limite_pago_from_pdf, pdf)
        if fe is None:
            damaged.append(
                {
                    "name": name,
                    "relative_path": rel,
                    "source_location": cand.get("source_location"),
                    "reason": unreadable_pdf_reason(pdf),
                    "createdDateTime": extract_created_datetime_raw(cand),
                    "lastModifiedDateTime": extract_last_modified_datetime_raw(cand)
                    or cand.get("lastModifiedDateTime"),
                    "size": len(pdf),
                }
            )
            continue
        digest = hashlib.sha256(pdf).hexdigest()
        scored.append((cand, fe, pdf, digest))
    return scored, damaged


def name_matches_selected(cand_name: str, selected: dict | None) -> bool:
    if not selected:
        return False
    hint = (selected.get("name_hint") or "").strip()
    ruta = (selected.get("ruta") or "").replace("\\", "/").strip()
    cn = cand_name.strip()
    if hint and _norm(cn) == _norm(hint):
        return True
    if ruta and ruta.lower().endswith("/" + cn.lower()):
        return True
    if ruta and _norm(Path(ruta).name) == _norm(cn):
        return True
    # Link sometimes encodes spaces as %20
    link = (selected.get("link") or "")
    if cn and cn.replace(" ", "%20") in link:
        return True
    if cn and cn in link:
        return True
    return False


async def main() -> int:
    clients_base = (os.getenv("GRAPH_CLIENTS_BASE_PATH") or "").replace("\\", "/")
    if SANDBOX_MARKER not in clients_base:
        print(f"FAIL: not sandbox clients base: {clients_base}")
        return 2

    base_url = (
        os.getenv("UI_SMOKE_APP_BASE_URL")
        or os.getenv("APP_SERVICE_URL")
        or DEFAULT_BASE
    ).rstrip("/")
    api_key = (os.getenv("API_HTTP_KEY") or "").strip()
    if not api_key:
        print("FAIL: API_HTTP_KEY missing")
        return 2

    http = AppServiceGraphHttp(base_url=base_url, api_key=api_key, timeout=180.0)
    g = SmokeGraph(http)
    report: dict[str, Any] = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "clients_base": clients_base,
        "base_url": base_url,
    }

    try:
        site_id, drive_id = await g.ensure_ids()
        report["site_id_len"] = len(site_id)
        report["drive_id_len"] = len(drive_id)

        # paths-probe quick
        try:
            r = await g._client.get(f"{base_url}/graph/diagnostics/paths-probe")
            if r.status_code == 200:
                probe = r.json()
                report["paths_probe_ok"] = True
                report["paths_probe_snippet"] = {
                    k: probe.get(k)
                    for k in ("environment", "clients_base", "ok", "summary")
                    if k in probe
                } or {k: probe[k] for k in list(probe)[:5]}
            else:
                report["paths_probe_status"] = r.status_code
        except Exception as exc:
            report["paths_probe_error"] = f"{type(exc).__name__}: {exc}"

        control_rel = resolve_bank_control_file_path("banco_bancolombia").strip().strip("/")
        report["control_path"] = control_rel
        control_bytes = await g.get_bytes(site_id, drive_id, control_rel)
        snap = parse_process_control_row2(control_bytes, control_file_path=control_rel)
        report["process"] = {
            "process_key": snap.process_key,
            "process_id": snap.process_id,
            "estado": snap.estado_proceso,
            "is_active": snap.is_active,
            "validation_file_path": snap.validation_file_path,
            "historical_file_path": snap.historical_file_path,
            "bank_code": snap.bank_code,
            "last_completed_step": snap.last_completed_step,
        }
        print("PROCESS", json.dumps(report["process"], ensure_ascii=False, indent=2))

        review_path = snap.validation_file_path or snap.historical_file_path
        if not review_path:
            print("FAIL: no validation/historical path in control")
            return 1
        review_bytes = await g.get_bytes(site_id, drive_id, review_path)
        parsed = parse_review_selected(review_bytes)
        by_credit: dict[str, dict] = parsed["by_credit"]
        report["review_path"] = review_path
        report["review_meta"] = parsed["meta"]
        report["review_headers"] = parsed["headers"]
        report["credits_in_review"] = sorted(by_credit.keys(), key=lambda x: int(x) if x.isdigit() else 0)
        print("CREDITS", report["credits_in_review"])
        for cid, info in sorted(by_credit.items(), key=lambda kv: int(kv[0]) if kv[0].isdigit() else 0):
            print(
                f"  review {cid}: cliente={info.get('cliente')!r} "
                f"name={info.get('name_hint')!r} ruta={info.get('ruta')!r}"
            )

        # Walk clients root
        parts = [p for p in clients_base.split("/") if p]
        root_id, _ = await g.walk(drive_id, parts)
        root_kids = await g.children(drive_id, root_id)

        credits_out: list[dict[str, Any]] = []
        mismatches: list[dict[str, Any]] = []

        for cid in report["credits_in_review"]:
            sel = by_credit[cid]
            cliente_hint = str(sel.get("cliente") or "")
            unidad_path = str(sel.get("unidad") or "").replace("\\", "/").strip().strip("/")
            entry: dict[str, Any] = {
                "credito": cid,
                "cliente_hint": cliente_hint,
                "generate_selected": sel,
            }

            credit_item_id: str | None = None
            credit_path = ""
            client_name = ""
            credit_name = ""

            # Prefer frozen unidad path from Generate review
            if unidad_path and unidad_path.startswith(clients_base):
                rel_parts = [p for p in unidad_path[len(clients_base) :].split("/") if p]
                try:
                    credit_item_id, credit_it = await g.walk(drive_id, parts + rel_parts)
                    credit_name = str(credit_it.get("name") or (rel_parts[-1] if rel_parts else ""))
                    credit_path = unidad_path
                    client_name = rel_parts[0] if rel_parts else ""
                    # Flat unit: unidad == client folder
                    if len(rel_parts) == 1:
                        credit_name = "(flat_client_root)"
                except FileNotFoundError as exc:
                    entry["unidad_walk_error"] = str(exc)

            if not credit_item_id:
                client_it = find_client_folder(root_kids, cliente_hint)
                if client_it is None and cid == "99":
                    client_it = find_client_folder(root_kids, "OBRAS CIVILES")
                if client_it is None and cid == "16":
                    client_it = find_client_folder(root_kids, "SERVIPETROLEOS")
                if client_it is None:
                    entry["error"] = "cliente_folder_not_found"
                    credits_out.append(entry)
                    mismatches.append({**entry, "mismatch_reason": "cliente_not_found"})
                    print(f"!! credito {cid}: cliente no encontrado ({cliente_hint})")
                    continue

                client_name = str(client_it.get("name") or "")
                client_path = f"{clients_base}/{client_name}".replace("//", "/")
                client_kids = await g.children(drive_id, str(client_it["id"]))
                credit_it = find_credit_folder(client_kids, cid)
                if credit_it is None:
                    # flat unit at client root (ruta extracto under client)
                    gen_ruta = str(sel.get("ruta") or "")
                    if gen_ruta and f"/{client_name}/" in gen_ruta.replace("\\", "/"):
                        # pool at client root
                        credit_item_id = str(client_it["id"])
                        credit_path = client_path
                        credit_name = "(flat_client_root)"
                    else:
                        entry["error"] = "credit_folder_not_found"
                        entry["cliente_folder"] = client_name
                        entry["client_child_folders"] = [
                            str(i.get("name")) for i in client_kids if "folder" in i
                        ][:30]
                        credits_out.append(entry)
                        mismatches.append({**entry, "mismatch_reason": "credit_not_found"})
                        print(f"!! credito {cid}: unidad no encontrada bajo {client_name}")
                        continue
                else:
                    credit_name = str(credit_it.get("name") or "")
                    credit_path = f"{client_path}/{credit_name}".replace("//", "/")
                    credit_item_id = str(credit_it["id"])

            entry["cliente_folder"] = client_name
            entry["credit_folder"] = credit_name
            entry["credit_path"] = credit_path

            print(f"\n-- scanning credito {cid} ({cliente_hint}) ...", flush=True)
            pool = await resolve_extract_pool(g, drive_id, credit_path, str(credit_item_id))
            print(f"   pool={len(pool)} path={credit_path}", flush=True)
            entry["pool_size"] = len(pool)

            # Also list non-matching PDFs for diagnosis (name without extracto / subdirs)
            all_kids = await g.children(drive_id, str(credit_item_id))
            other_pdfs = [
                str(i.get("name"))
                for i in all_kids
                if "folder" not in i
                and str(i.get("name") or "").lower().endswith(".pdf")
                and not _is_strict_extract_pdf(i)
            ]
            subfolders = [str(i.get("name")) for i in all_kids if "folder" in i]
            entry["other_root_pdfs"] = other_pdfs
            entry["subfolders"] = subfolders

            # Deeper scan under non-EXTRACTOS folders for name containing extracto (diagnostic only)
            outside_pool: list[str] = []
            for i in all_kids:
                if "folder" not in i:
                    continue
                fname = str(i.get("name") or "")
                if fname.casefold() == "extractos":
                    continue
                for ch in await g.children(drive_id, str(i["id"])):
                    cn = str(ch.get("name") or "")
                    if cn.lower().endswith(".pdf") and "extracto" in cn.lower():
                        outside_pool.append(f"{fname}/{cn}")
            entry["extract_pdfs_outside_pool_rules"] = outside_pool

            scored, damaged = await score_pool(g, site_id, drive_id, pool)
            files: list[dict[str, Any]] = []
            for cand, fe, _pdf, digest in scored:
                files.append(
                    {
                        "name": cand.get("name"),
                        "relative_path": cand.get("relative_path"),
                        "source": cand.get("source_location"),
                        "fecha_limite": fe.isoformat(),
                        "createdDateTime": extract_created_datetime_raw(cand),
                        "lastModifiedDateTime": extract_last_modified_datetime_raw(cand)
                        or cand.get("lastModifiedDateTime"),
                        "sha256_12": digest[:12],
                        "parse": "OK",
                        "selected_by_generate": name_matches_selected(
                            str(cand.get("name") or ""), sel
                        ),
                    }
                )
            for d in damaged:
                files.append(
                    {
                        **d,
                        "fecha_limite": None,
                        "parse": "FAIL",
                        "selected_by_generate": name_matches_selected(
                            str(d.get("name") or ""), sel
                        ),
                    }
                )

            # HEAD logic: fail-closed if any damaged; else choose max fecha_limite
            winner_name = None
            winner_fe = None
            selection_reason = None
            selection_error = None
            if damaged:
                selection_error = "fecha_limite_extracto_not_readable"
                selection_reason = "fail_closed_damaged_pool"
            elif not scored:
                selection_error = "extract_not_found"
            else:
                # bank_date ignored by choose_extract_as_of_bank_date
                outcome = choose_extract_as_of_bank_date(scored, date(2026, 8, 20))
                selection_error = outcome.error_code
                selection_reason = outcome.selection_reason
                if outcome.candidate is not None and outcome.fecha_limite is not None:
                    winner_name = str(outcome.candidate.get("name") or "")
                    winner_fe = outcome.fecha_limite.isoformat()

            for f in files:
                f["is_logic_winner"] = bool(
                    winner_name and _norm(str(f.get("name") or "")) == _norm(winner_name)
                )

            files.sort(
                key=lambda f: (
                    f.get("fecha_limite") or "",
                    f.get("createdDateTime") or "",
                ),
                reverse=True,
            )
            entry["files"] = files
            entry["logic_winner"] = {
                "name": winner_name,
                "fecha_limite": winner_fe,
                "reason": selection_reason,
                "error": selection_error,
            }
            gen_name = sel.get("name_hint") or ""
            gen_match = any(f.get("selected_by_generate") for f in files)
            winner_is_selected = bool(
                winner_name
                and gen_name
                and _norm(winner_name) == _norm(str(gen_name))
            )
            # Also match via ruta
            if not winner_is_selected and winner_name:
                winner_is_selected = name_matches_selected(winner_name, sel)

            entry["match"] = {
                "generate_name": gen_name,
                "logic_winner_name": winner_name,
                "winner_equals_generate": winner_is_selected,
                "generate_found_in_pool": gen_match,
            }

            is_mismatch = False
            reason = None
            if selection_error and not winner_name:
                # Generate somehow selected something despite current logic failing?
                if gen_name:
                    is_mismatch = True
                    reason = f"logic_would_error={selection_error}_but_generate_has={gen_name}"
            elif winner_name and gen_name and not winner_is_selected:
                is_mismatch = True
                reason = "generate_selected_not_max_fecha_limite_winner"
            elif winner_name and not gen_name:
                is_mismatch = True
                reason = "generate_missing_extract_link"
            elif not gen_match and gen_name:
                is_mismatch = True
                reason = "generate_selected_file_not_in_current_pool"

            entry["is_mismatch"] = is_mismatch
            if is_mismatch:
                entry["mismatch_reason"] = reason
                mismatches.append(
                    {
                        "credito": cid,
                        "cliente": client_name,
                        "reason": reason,
                        "generate": gen_name,
                        "winner": winner_name,
                        "winner_fe": winner_fe,
                        "outside_pool": outside_pool,
                        "other_root_pdfs": other_pdfs,
                    }
                )

            credits_out.append(entry)
            flag = "MISMATCH" if is_mismatch else "OK"
            print(
                f"[{flag}] cred={cid} cliente={client_name} pool={len(pool)} "
                f"winner={winner_name!r}@{winner_fe} gen={gen_name!r} reason={selection_reason}"
            )
            for f in files:
                mark = []
                if f.get("is_logic_winner"):
                    mark.append("WINNER")
                if f.get("selected_by_generate"):
                    mark.append("GEN")
                tag = ",".join(mark) if mark else "-"
                print(
                    f"    [{tag}] {f.get('parse')} fe={f.get('fecha_limite')} "
                    f"src={f.get('source')} mod={f.get('lastModifiedDateTime')} "
                    f"name={f.get('name')}"
                )
            if outside_pool:
                print(f"    outside_pool_rules: {outside_pool}")

        report["credits"] = credits_out
        report["mismatches"] = mismatches
        report["mismatch_count"] = len(mismatches)

        # Focus notes for 99 and 16
        for focus in ("99", "16"):
            hit = next((c for c in credits_out if c.get("credito") == focus), None)
            report[f"focus_{focus}"] = hit

        OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
        print(f"\nWrote {OUT}")
        print(f"MISMATCHES: {len(mismatches)}")
        return 0
    finally:
        await http.aclose()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
