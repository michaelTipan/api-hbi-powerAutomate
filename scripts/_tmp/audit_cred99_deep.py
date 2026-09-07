# -*- coding: utf-8 -*-
"""Deep RO scan for credit 99 OBRAS CIVILES — find any extract outside pool rules."""
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

from app.application.services.payment_helpers import (  # noqa: E402
    extract_fecha_limite_pago_from_pdf,
)
from scripts.support.ui_appservice_graph_http import AppServiceGraphHttp  # noqa: E402

BASE = "https://app-hbiauto-prod-001-afawg2g7frgte8c5.eastus-01.azurewebsites.net"
CLIENTS = (
    "INFORMACION CREDITOS-CLIENTES/"
    "03 COMWARE PRUEBAS- INFORMACION CREDITOS CLIENTES"
)
OUT = ROOT / "scripts" / "_tmp" / "audit_cred99_deep.json"


async def children(client, drive, fid="root"):
    r = await client.get(
        f"{BASE}/graph/sharepoint/drives/{quote(drive, safe='')}/children",
        params={"folder_item_id": fid},
    )
    r.raise_for_status()
    return list((r.json() or {}).get("value") or [])


async def walk(client, drive, parts):
    cur = "root"
    for p in parts:
        kids = await children(client, drive, cur)
        hit = next((i for i in kids if i.get("name") == p), None)
        if not hit:
            raise FileNotFoundError(p)
        cur = str(hit["id"])
    return cur


async def download(client, drive, item_id):
    r = await client.get(
        f"{BASE}/graph/sharepoint/drives/{quote(drive, safe='')}/item-content",
        params={"item_id": item_id},
    )
    r.raise_for_status()
    return base64.b64decode(r.json()["content_base64"])


async def list_pdfs_recursive(client, drive, folder_id, prefix="", depth=0, max_depth=3):
    """List PDFs under folder (shallow recurse)."""
    out = []
    kids = await children(client, drive, folder_id)
    for it in kids:
        name = str(it.get("name") or "")
        rel = f"{prefix}/{name}".strip("/") if prefix else name
        if "folder" in it:
            if depth < max_depth:
                out.extend(
                    await list_pdfs_recursive(
                        client, drive, str(it["id"]), rel, depth + 1, max_depth
                    )
                )
            else:
                out.append(
                    {
                        "rel": rel,
                        "type": "folder_not_descended",
                        "modified": it.get("lastModifiedDateTime"),
                        "created": it.get("createdDateTime"),
                    }
                )
        elif name.lower().endswith(".pdf"):
            out.append(
                {
                    "rel": rel,
                    "name": name,
                    "id": it.get("id"),
                    "modified": it.get("lastModifiedDateTime"),
                    "created": it.get("createdDateTime"),
                    "size": it.get("size"),
                    "has_extracto": "extracto" in name.lower(),
                    "type": "pdf",
                }
            )
    return out


async def main():
    http = AppServiceGraphHttp(base_url=BASE, api_key=os.environ["API_HTTP_KEY"], timeout=180)
    try:
        _, drive = await http._ensure_ids()  # noqa: SLF001
        client = http._client  # noqa: SLF001
        parts = CLIENTS.split("/")
        root_id = await walk(client, drive, parts)
        kids = await children(client, drive, root_id)
        obras = next(
            (i for i in kids if "OBRAS CIVILES" in str(i.get("name") or "").upper()),
            None,
        )
        if not obras:
            print("OBRAS not found")
            return 1
        client_name = obras["name"]
        print("CLIENT", client_name)
        client_id = str(obras["id"])
        client_kids = await children(client, drive, client_id)
        folders = [i for i in client_kids if "folder" in i]
        root_pdfs = [
            i
            for i in client_kids
            if "folder" not in i and str(i.get("name") or "").lower().endswith(".pdf")
        ]
        print("FOLDERS:", [f["name"] for f in folders])
        print("ROOT_PDFS:", [p["name"] for p in root_pdfs])

        report = {
            "client": client_name,
            "folders": [
                {
                    "name": f["name"],
                    "modified": f.get("lastModifiedDateTime"),
                    "created": f.get("createdDateTime"),
                }
                for f in folders
            ],
            "units": [],
        }

        # Scan each credit-like folder + client root
        targets = [("CLIENT_ROOT", client_id, "")] + [
            (str(f["name"]), str(f["id"]), str(f["name"])) for f in folders
        ]

        for label, fid, prefix in targets:
            pdfs = await list_pdfs_recursive(client, drive, fid, prefix=prefix, max_depth=2)
            unit = {"label": label, "pdf_count": len([p for p in pdfs if p.get("type") == "pdf"]), "pdfs": []}
            for p in pdfs:
                if p.get("type") != "pdf":
                    unit["pdfs"].append(p)
                    continue
                entry = dict(p)
                # parse fecha_limite for extract-like or all PDFs with extracto OR recent
                if p.get("has_extracto") or "99" in (p.get("name") or ""):
                    try:
                        raw = await download(client, drive, str(p["id"]))
                        fe = extract_fecha_limite_pago_from_pdf(raw)
                        entry["fecha_limite"] = fe.isoformat() if fe else None
                        entry["parse"] = "OK" if fe else "FAIL"
                        entry["bytes"] = len(raw)
                    except Exception as exc:
                        entry["parse"] = f"ERR:{type(exc).__name__}"
                        entry["fecha_limite"] = None
                unit["pdfs"].append(entry)
            # sort by fecha_limite desc then modified
            unit["pdfs"].sort(
                key=lambda x: (x.get("fecha_limite") or "", x.get("modified") or ""),
                reverse=True,
            )
            report["units"].append(unit)
            print(f"\n=== {label} pdfs={unit['pdf_count']} ===")
            for p in unit["pdfs"]:
                if p.get("type") != "pdf":
                    print(f"  (folder) {p.get('rel')}")
                    continue
                print(
                    f"  fe={p.get('fecha_limite')} extracto={p.get('has_extracto')} "
                    f"mod={p.get('modified')} name={p.get('name')} path={p.get('rel')}"
                )

        OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print("Wrote", OUT)
        return 0
    finally:
        await http.aclose()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
