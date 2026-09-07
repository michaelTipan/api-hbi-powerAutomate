# -*- coding: utf-8 -*-
"""RO: parse asiento CRED 256 + list folder for tabla amortización ICOEQUIPOS."""
from __future__ import annotations

import asyncio
import base64
import json
import os
import sys
from pathlib import Path
from urllib.parse import quote

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
load_dotenv(Path(r"D:\CMC\HBI_Capital\api-hbi-powerAutomate.env"), override=False)
os.environ["UI_SHAREPOINT_SMOKE"] = "1"

from app.application.services.accounting_pdf_parser import (  # noqa: E402
    extract_text_from_pdf,
    parse_accounting_text,
)
from scripts.support.ui_appservice_graph_http import AppServiceGraphHttp  # noqa: E402

BASE = "https://app-hbiauto-prod-001-afawg2g7frgte8c5.eastus-01.azurewebsites.net"
API = (os.getenv("API_HTTP_KEY") or "").strip()
ASIENTO = (
    "INFORMACION CREDITOS-CLIENTES/03 COMWARE PRUEBAS- INFORMACION CREDITOS CLIENTES/"
    "ICOEQUIPOS SAS/ASIENTOS CONTABLES CRED 256/CRED 256-1.pdf"
)
CLIENT = (
    "INFORMACION CREDITOS-CLIENTES/03 COMWARE PRUEBAS- INFORMACION CREDITOS CLIENTES/"
    "ICOEQUIPOS SAS"
)
OUT = ROOT / "scripts" / "_tmp" / "diag_abono_256_asiento.json"


async def children(http, drive, fid="root"):
    r = await http._client.get(
        f"{BASE}/graph/sharepoint/drives/{quote(drive, safe='')}/children",
        params={"folder_item_id": fid},
    )
    r.raise_for_status()
    return list((r.json() or {}).get("value") or [])


async def walk(http, drive, parts):
    cur = "root"
    for i, p in enumerate(parts):
        kids = await children(http, drive, cur)
        hit = next((x for x in kids if x.get("name") == p), None)
        if not hit:
            raise FileNotFoundError("/".join(parts[: i + 1]))
        cur = str(hit["id"])
    return cur


async def download(http, drive, rel):
    parts = [p for p in rel.strip("/").split("/") if p]
    fid = await walk(http, drive, parts[:-1])
    kids = await children(http, drive, fid)
    hit = next((x for x in kids if x.get("name") == parts[-1]), None)
    if not hit:
        raise FileNotFoundError(rel)
    r = await http._client.get(
        f"{BASE}/graph/sharepoint/drives/{quote(drive, safe='')}/item-content",
        params={"item_id": str(hit["id"])},
    )
    r.raise_for_status()
    return base64.b64decode(r.json()["content_base64"]), hit


async def main():
    http = AppServiceGraphHttp(base_url=BASE, api_key=API, timeout=180.0)
    report: dict = {}
    try:
        diag = await http._client.get(f"{BASE}/graph/diagnostics")
        diag.raise_for_status()
        drive = str(((diag.json() or {}).get("operations_site") or {}).get("drive_id") or "")

        raw, meta = await download(http, drive, ASIENTO)
        text = extract_text_from_pdf(raw)
        events = []
        try:
            ev = parse_accounting_text(
                text,
                {
                    "id_pago": "2c91424b-5bfe-4d6e-a8cc-6409eda6d7ea",
                    "cliente": "ICOEQUIPOS SAS",
                    "credito": "256",
                    "asiento_pdf_path": ASIENTO,
                },
            )
            events = [ev] if ev else []
        except Exception as exc:
            report["parse_error"] = f"{type(exc).__name__}: {exc}"
            ev = None
        report["asiento"] = {
            "path": ASIENTO,
            "bytes": len(raw),
            "name": meta.get("name"),
            "events_count": len(events),
            "valor_pagado_cliente": getattr(ev, "valor_pagado_cliente", None),
            "capital": getattr(ev, "capital", None),
            "intereses": getattr(ev, "intereses", None),
            "mora": getattr(ev, "mora", None),
            "retenciones": getattr(ev, "retenciones", None),
            "comprobante": getattr(ev, "comprobante", None),
            "fecha_asiento": getattr(ev, "fecha_asiento", None).isoformat()
            if getattr(ev, "fecha_asiento", None)
            else None,
            "monto_banco_manifest": 40_000_000.0,
            "diff_vs_banco": (
                None
                if ev is None
                else float(ev.valor_pagado_cliente) - 40_000_000.0
            ),
            "text_preview": (text or "")[:800],
        }

        # List client folder for tablas
        fid = await walk(http, drive, [p for p in CLIENT.split("/") if p])
        kids = await children(http, drive, fid)
        report["icoequipos_children"] = [
            {
                "name": k.get("name"),
                "folder": "folder" in k,
                "size": k.get("size"),
            }
            for k in kids
        ]
        # Find any amort table xlsx under client (shallow + one level)
        tables = []
        for k in kids:
            name = str(k.get("name") or "")
            if name.lower().endswith((".xlsx", ".xlsm")) and "amort" in name.lower():
                tables.append({"rel": name, "size": k.get("size")})
            if "folder" in k:
                sub = await children(http, drive, str(k["id"]))
                for s in sub:
                    sn = str(s.get("name") or "")
                    if sn.lower().endswith((".xlsx", ".xlsm")) and (
                        "amort" in sn.lower() or "tabla" in sn.lower()
                    ):
                        tables.append(
                            {"rel": f"{name}/{sn}", "size": s.get("size")}
                        )
        report["tables_found"] = tables

        # ASIENTOS folder listing
        asientos_name = "ASIENTOS CONTABLES CRED 256"
        asientos = next((k for k in kids if k.get("name") == asientos_name), None)
        if asientos:
            pdfs = await children(http, drive, str(asientos["id"]))
            report["asientos_folder_pdfs"] = [
                {"name": p.get("name"), "size": p.get("size")}
                for p in pdfs
                if str(p.get("name") or "").lower().endswith(".pdf")
            ]
    finally:
        await http.aclose()

    OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    asyncio.run(main())
