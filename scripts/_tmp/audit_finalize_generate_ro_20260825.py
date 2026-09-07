# -*- coding: utf-8 -*-
"""RO audit: Validación de pagos prod — inventario + parse negocio (sin mutar).

Solo GET vía proxy Graph del App Service. No PUT/POST/PATCH/DELETE.
"""
from __future__ import annotations

import asyncio
import base64
import json
import os
import sys
from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path
from typing import Any
from urllib.parse import quote

import openpyxl
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
load_dotenv(Path(r"D:\CMC\HBI_Capital\api-hbi-powerAutomate.env"), override=False)
os.environ["UI_SHAREPOINT_SMOKE"] = "1"

from scripts.support.ui_appservice_graph_http import AppServiceGraphHttp  # noqa: E402

BASE = "https://app-hbiauto-prod-001-afawg2g7frgte8c5.eastus-01.azurewebsites.net"
API = (os.getenv("API_HTTP_KEY") or "").strip()
VAL_ROOT = "INFORMACION CREDITOS-CLIENTES/02 VALIDACION PAGOS"
OUT = ROOT / "scripts" / "_tmp" / "audit_finalize_generate_ro_20260825.json"

# Deploy window (Colombia UTC-5 ≈ 2026-08-25). Compare before ~17:00Z (12:00 COT)
# vs after first merge/border deploys (~20:00Z / 15:00 COT).
CUTOFF_PRE_ISO = "2026-08-25T17:00:00Z"  # ~12:00 COT
CUTOFF_POST_ISO = "2026-08-25T20:00:00Z"  # ~15:00 COT


def _iso(s: Any) -> str:
    return str(s or "").strip()


def _parse_iso(s: str) -> datetime | None:
    if not s:
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except Exception:
        return None


async def children(http: AppServiceGraphHttp, drive: str, fid: str = "root") -> list[dict]:
    r = await http._client.get(
        f"{BASE}/graph/sharepoint/drives/{quote(drive, safe='')}/children",
        params={"folder_item_id": fid},
    )
    r.raise_for_status()
    return list((r.json() or {}).get("value") or [])


async def walk(http: AppServiceGraphHttp, drive: str, parts: list[str]) -> str:
    cur = "root"
    for i, p in enumerate(parts):
        kids = await children(http, drive, cur)
        hit = next((x for x in kids if x.get("name") == p), None)
        if not hit:
            raise FileNotFoundError("/".join(parts[: i + 1]))
        cur = str(hit["id"])
    return cur


async def download_by_id(http: AppServiceGraphHttp, drive: str, item_id: str) -> bytes:
    r = await http._client.get(
        f"{BASE}/graph/sharepoint/drives/{quote(drive, safe='')}/item-content",
        params={"item_id": item_id},
    )
    r.raise_for_status()
    return base64.b64decode(r.json()["content_base64"])


async def inventory_tree(
    http: AppServiceGraphHttp,
    drive: str,
    folder_id: str,
    rel: str,
    *,
    depth: int = 0,
    max_depth: int = 6,
) -> list[dict]:
    out: list[dict] = []
    kids = await children(http, drive, folder_id)
    for it in kids:
        name = str(it.get("name") or "")
        is_folder = "folder" in it
        path = f"{rel}/{name}" if rel else name
        entry = {
            "path": path,
            "name": name,
            "is_folder": is_folder,
            "size": it.get("size"),
            "createdDateTime": it.get("createdDateTime"),
            "lastModifiedDateTime": it.get("lastModifiedDateTime"),
            "id": it.get("id"),
        }
        out.append(entry)
        if is_folder and depth < max_depth:
            # Skip deep year trees partially but include HISTORICO recent
            out.extend(
                await inventory_tree(
                    http,
                    drive,
                    str(it["id"]),
                    path,
                    depth=depth + 1,
                    max_depth=max_depth,
                )
            )
    return out


def _cell_value(ws: Any, row: int, col: int) -> Any:
    cell = ws.cell(row, col)
    val = cell.value
    if val is not None and val != "":
        return val
    # Explode vertical merge: look for top-left of merge containing this cell
    for rng in ws.merged_cells.ranges:
        min_r, min_c, max_r, max_c = rng.min_row, rng.min_col, rng.max_row, rng.max_col
        if min_r <= row <= max_r and min_c <= col <= max_c:
            return ws.cell(min_r, min_c).value
    return val


def _header_map(ws: Any, header_row: int = 3) -> dict[str, int]:
    m: dict[str, int] = {}
    for c in range(1, (ws.max_column or 0) + 1):
        h = str(ws.cell(header_row, c).value or "").strip()
        if h and h not in m:
            m[h] = c
    return m


def _norm_money(v: Any) -> str | None:
    if v is None or v == "":
        return None
    try:
        return f"{float(v):.2f}"
    except Exception:
        return str(v).strip()


def _norm_date(v: Any) -> str | None:
    if v is None or v == "":
        return None
    if hasattr(v, "isoformat"):
        try:
            return v.isoformat()[:10]
        except Exception:
            pass
    s = str(v).strip()
    return s[:10] if s else None


def parse_aplicacion_sheet(wb: openpyxl.Workbook, sheet_name: str) -> dict[str, Any]:
    if sheet_name not in wb.sheetnames:
        return {"error": f"missing_sheet:{sheet_name}", "rows": []}
    ws = wb[sheet_name]
    hmap = _header_map(ws, 3)
    # Fallback header row 1 for some secretary variants
    if "ID Pago" not in hmap and "Cliente" not in hmap:
        hmap = _header_map(ws, 1)
        first_data = 2
        header_row = 1
    else:
        first_data = 4
        header_row = 3

    wanted = [
        "ID Pago",
        "Cliente",
        "Crédito",
        "Monto banco",
        "Fecha banco",
        "Fecha límite",
        "Validar Pago",
        "Tipo de aplicación",
        "Observación",
        "Valor obligación actual",
        "Saldo vencido",
        "Link extracto",
        "Link tabla",
        "Link carpeta crédito",
        "Tipo caso",
        "Descripción",
        "Qué debe hacer",
    ]
    rows: list[dict[str, Any]] = []
    max_r = ws.max_row or first_data
    for r in range(first_data, max_r + 1):
        id_pago = str(_cell_value(ws, r, hmap["ID Pago"]) or "").strip() if "ID Pago" in hmap else ""
        cliente = str(_cell_value(ws, r, hmap["Cliente"]) or "").strip() if "Cliente" in hmap else ""
        credito = str(_cell_value(ws, r, hmap["Crédito"]) or "").strip() if "Crédito" in hmap else ""
        if not id_pago and not cliente and not credito:
            continue
        row: dict[str, Any] = {"excel_row": r}
        for name in wanted:
            if name not in hmap:
                continue
            raw = _cell_value(ws, r, hmap[name])
            if name in ("Monto banco", "Valor obligación actual", "Saldo vencido"):
                row[name] = _norm_money(raw)
            elif name in ("Fecha banco", "Fecha límite"):
                row[name] = _norm_date(raw)
            elif name.startswith("Link"):
                # Prefer hyperlink target if present
                cell = ws.cell(r, hmap[name])
                href = getattr(getattr(cell, "hyperlink", None), "target", None) or getattr(
                    cell, "hyperlink", None
                )
                if href and str(href).lower().startswith("http"):
                    row[name] = "has_http_link"
                elif raw and str(raw).lower().startswith("http"):
                    row[name] = "has_http_link"
                elif raw:
                    row[name] = "has_label"
                else:
                    row[name] = None
            else:
                row[name] = str(raw).strip() if raw is not None and raw != "" else None
        rows.append(row)

    # Detect merges on monto/fecha
    merges = []
    for rng in ws.merged_cells.ranges:
        merges.append(str(rng))
    return {
        "sheet": sheet_name,
        "header_row": header_row,
        "headers_found": sorted(hmap.keys()),
        "row_count": len(rows),
        "merged_ranges_sample": merges[:40],
        "merged_count": len(merges),
        "rows": rows,
    }


def business_key(row: dict[str, Any]) -> tuple:
    return (
        str(row.get("ID Pago") or ""),
        str(row.get("Cliente") or ""),
        str(row.get("Crédito") or ""),
    )


def si_rows(rows: list[dict]) -> list[dict]:
    out = []
    for r in rows:
        vp = str(r.get("Validar Pago") or "").strip().upper()
        if vp in ("SI", "SÍ", "YES", "TRUE", "1"):
            out.append(r)
    return out


def summarize_rows(parsed: dict) -> dict:
    rows = parsed.get("rows") or []
    si = si_rows(rows)
    keys = sorted(business_key(r) for r in rows)
    si_keys = sorted(business_key(r) for r in si)
    montos = sorted(
        {
            (business_key(r), r.get("Monto banco"), r.get("Fecha banco"), r.get("Tipo de aplicación"))
            for r in si
        }
    )
    return {
        "row_count": len(rows),
        "si_count": len(si),
        "no_or_empty": len(rows) - len(si),
        "unique_id_pago": len({r.get("ID Pago") for r in rows}),
        "keys": keys,
        "si_keys": si_keys,
        "si_payload": [
            {
                "key": list(business_key(r)),
                "monto": r.get("Monto banco"),
                "fecha_banco": r.get("Fecha banco"),
                "tipo": r.get("Tipo de aplicación"),
                "fecha_limite": r.get("Fecha límite"),
                "obligacion": r.get("Valor obligación actual"),
            }
            for r in sorted(si, key=business_key)
        ],
        "merged_count": parsed.get("merged_count"),
    }


def classify_file(name: str, modified: str) -> str:
    n = name.lower()
    dt = _parse_iso(modified)
    bucket = "other_day"
    if dt and dt.astimezone(timezone.utc).date().isoformat() == "2026-08-25":
        if modified < CUTOFF_PRE_ISO or (dt and dt < _parse_iso(CUTOFF_PRE_ISO)):  # type: ignore
            bucket = "today_pre_noon"
        elif dt and dt >= _parse_iso(CUTOFF_POST_ISO):  # type: ignore
            bucket = "today_post_changes"
        else:
            bucket = "today_mid_window"
    kind = "other"
    if "validacion_pagos" in n or "validación_pagos" in n:
        kind = "review"
    elif "cartera_validada" in n:
        kind = "cartera_validada"
    elif "soporte_asientos" in n or "asientos_pendientes" in n:
        kind = "asientos"
    elif n.endswith(".xlsx"):
        kind = "xlsx"
    elif n.endswith(".pdf"):
        kind = "pdf"
    return f"{bucket}:{kind}"


async def main() -> None:
    if not API:
        raise RuntimeError("API_HTTP_KEY missing")
    http = AppServiceGraphHttp(base_url=BASE, api_key=API, timeout=180.0)
    report: dict[str, Any] = {
        "mode": "read_only",
        "started_at": datetime.now(timezone.utc).isoformat(),
        "val_root": VAL_ROOT,
        "cutoffs": {"pre": CUTOFF_PRE_ISO, "post": CUTOFF_POST_ISO},
    }
    try:
        diag = await http._client.get(f"{BASE}/graph/diagnostics")
        diag.raise_for_status()
        djson = diag.json() or {}
        drive = str(((djson.get("operations_site") or {}).get("drive_id") or ""))
        report["environment"] = djson.get("environment") or djson.get("ACTIVE_ENVIRONMENT")
        report["drive_id_prefix"] = drive[:12]

        health = await http._client.get(f"{BASE}/health")
        health.raise_for_status()
        hj = health.json() or {}
        report["health"] = {
            "build_id": hj.get("build_id") or hj.get("build"),
            "environment": hj.get("environment"),
            "ui_enabled": hj.get("ui_enabled"),
        }

        parts = [p for p in VAL_ROOT.split("/") if p]
        root_id = await walk(http, drive, parts)
        inv = await inventory_tree(http, drive, root_id, VAL_ROOT, max_depth=5)
        report["inventory_count"] = len(inv)
        report["inventory"] = [
            {
                "path": e["path"],
                "is_folder": e["is_folder"],
                "size": e["size"],
                "created": e["createdDateTime"],
                "modified": e["lastModifiedDateTime"],
                "class": classify_file(e["name"], _iso(e["lastModifiedDateTime"])),
            }
            for e in inv
            if (not e["is_folder"])
            or e["path"].count("/") <= 5
        ]

        # Focus: today's xlsx under REVISION / HISTORICO / any asientos
        candidates = [
            e
            for e in inv
            if not e["is_folder"]
            and str(e["name"]).lower().endswith(".xlsx")
            and (
                "2026-08-25" in str(e["name"])
                or (
                    _parse_iso(_iso(e["lastModifiedDateTime"]))
                    and _parse_iso(_iso(e["lastModifiedDateTime"])).date().isoformat()  # type: ignore
                    == "2026-08-25"
                )
                or "2026-08-24" in str(e["name"])
                or "2026-08-23" in str(e["name"])
            )
        ]
        # Prefer validation-related names
        interesting = [
            e
            for e in candidates
            if any(
                k in e["name"].lower()
                for k in (
                    "validacion_pagos",
                    "validación_pagos",
                    "cartera_validada",
                    "soporte_asientos",
                    "asientos",
                )
            )
        ]
        if not interesting:
            interesting = candidates

        report["xlsx_candidates"] = [
            {
                "path": e["path"],
                "size": e["size"],
                "modified": e["lastModifiedDateTime"],
                "created": e["createdDateTime"],
                "class": classify_file(e["name"], _iso(e["lastModifiedDateTime"])),
                "id": e["id"],
            }
            for e in interesting
        ]

        parsed_files: list[dict] = []
        # Cap downloads to avoid huge pulls — prioritize today + recent hist
        interesting_sorted = sorted(
            interesting,
            key=lambda e: _iso(e["lastModifiedDateTime"]),
            reverse=True,
        )[:24]

        for e in interesting_sorted:
            try:
                raw = await download_by_id(http, drive, str(e["id"]))
                wb = openpyxl.load_workbook(BytesIO(raw), data_only=False)
                sheets_info = {}
                for sn in wb.sheetnames:
                    low = sn.lower()
                    if any(
                        x in low
                        for x in (
                            "aplicaci",
                            "asientos",
                            "errores",
                            "cartera",
                            "valid",
                        )
                    ) or sn in (
                        "Aplicacion_Pagos",
                        "Asientos_Pendientes",
                        "Errores",
                    ):
                        sheets_info[sn] = parse_aplicacion_sheet(wb, sn)
                # If named sheets missing, try first sheet
                if not sheets_info and wb.sheetnames:
                    sheets_info[wb.sheetnames[0]] = parse_aplicacion_sheet(wb, wb.sheetnames[0])
                summaries = {sn: summarize_rows(p) for sn, p in sheets_info.items()}
                # Drop full row dumps for huge files — keep SI payload only
                compact_sheets = {}
                for sn, p in sheets_info.items():
                    compact_sheets[sn] = {
                        "headers_found": p.get("headers_found"),
                        "row_count": p.get("row_count"),
                        "merged_count": p.get("merged_count"),
                        "merged_ranges_sample": p.get("merged_ranges_sample"),
                        "summary": summaries[sn],
                        # Keep all rows only if small
                        "rows": p.get("rows") if (p.get("row_count") or 0) <= 80 else None,
                        "rows_omitted": (p.get("row_count") or 0) > 80,
                    }
                parsed_files.append(
                    {
                        "path": e["path"],
                        "modified": e["lastModifiedDateTime"],
                        "created": e["createdDateTime"],
                        "class": classify_file(e["name"], _iso(e["lastModifiedDateTime"])),
                        "size": e["size"],
                        "sheetnames": wb.sheetnames,
                        "sheets": compact_sheets,
                    }
                )
            except Exception as ex:
                parsed_files.append(
                    {
                        "path": e["path"],
                        "modified": e["lastModifiedDateTime"],
                        "error": f"{type(ex).__name__}: {ex}",
                    }
                )

        report["parsed_files"] = parsed_files

        # Cross-compare: same bank+date cartera vs asientos SI keys
        comparisons = []
        by_stem: dict[str, list] = {}
        for pf in parsed_files:
            path = pf.get("path") or ""
            name = Path(path).name.lower()
            # Extract bank+date token if present
            token = None
            for bank in ("banco_bogota", "banco_bancolombia"):
                if bank in name:
                    # find date yyyy-mm-dd
                    import re

                    m = re.search(r"(\d{4}-\d{2}-\d{2})", name)
                    if m:
                        token = f"{bank}:{m.group(1)}"
            if token:
                by_stem.setdefault(token, []).append(pf)

        for token, files in sorted(by_stem.items()):
            cartera = [f for f in files if "cartera_validada" in (f.get("path") or "").lower()]
            asientos = [
                f
                for f in files
                if "soporte_asientos" in (f.get("path") or "").lower()
                or "asientos" in (f.get("path") or "").lower()
            ]
            reviews = [
                f
                for f in files
                if "validacion_pagos" in (f.get("path") or "").lower()
                or "validación_pagos" in (f.get("path") or "").lower()
            ]
            entry: dict[str, Any] = {"token": token, "files": [f.get("path") for f in files]}
            if cartera and asientos:
                csum = None
                asum = None
                for sn, sh in (cartera[0].get("sheets") or {}).items():
                    if "summary" in sh:
                        csum = sh["summary"]
                        entry["cartera_sheet"] = sn
                        break
                for sn, sh in (asientos[0].get("sheets") or {}).items():
                    if "summary" in sh:
                        asum = sh["summary"]
                        entry["asientos_sheet"] = sn
                        break
                if csum and asum:
                    entry["cartera_si_count"] = csum.get("si_count")
                    entry["asientos_row_count"] = asum.get("row_count")
                    # Asientos usually only SI rows
                    c_si = {tuple(x["key"]) for x in csum.get("si_payload") or []}
                    a_keys = {tuple(k) for k in (asum.get("keys") or [])}
                    # keys may be tuples serialized as lists
                    a_keys2 = set()
                    for k in asum.get("keys") or []:
                        a_keys2.add(tuple(k) if isinstance(k, (list, tuple)) else (k,))
                    entry["si_keys_in_cartera_not_asientos"] = [
                        list(k) for k in sorted(c_si - a_keys2)
                    ]
                    entry["keys_in_asientos_not_cartera_si"] = [
                        list(k) for k in sorted(a_keys2 - c_si)
                    ]
                    entry["cartera_asientos_si_match"] = not entry[
                        "si_keys_in_cartera_not_asientos"
                    ] and not entry["keys_in_asientos_not_cartera_si"]
            if reviews:
                entry["review_paths"] = [f.get("path") for f in reviews]
                entry["review_classes"] = [f.get("class") for f in reviews]
            comparisons.append(entry)

        report["comparisons"] = comparisons
        report["finished_at"] = datetime.now(timezone.utc).isoformat()
    finally:
        await http.aclose()

    OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    print(f"WROTE {OUT}")
    print("health", report.get("health"))
    print("inventory_count", report.get("inventory_count"))
    print("xlsx_candidates", len(report.get("xlsx_candidates") or []))
    print("parsed_files", len(report.get("parsed_files") or []))
    for c in report.get("comparisons") or []:
        print(
            "cmp",
            c.get("token"),
            "match=",
            c.get("cartera_asientos_si_match"),
            "si_c=",
            c.get("cartera_si_count"),
            "asientos=",
            c.get("asientos_row_count"),
        )


if __name__ == "__main__":
    asyncio.run(main())
