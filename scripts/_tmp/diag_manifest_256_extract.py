# -*- coding: utf-8 -*-
"""RO: extract credit 256 / id_pago from merge manifest d01a537c."""
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

from scripts.support.ui_appservice_graph_http import AppServiceGraphHttp  # noqa: E402

BASE = "https://app-hbiauto-prod-001-afawg2g7frgte8c5.eastus-01.azurewebsites.net"
API = (os.getenv("API_HTTP_KEY") or "").strip()
MPATH = (
    "INFORMACION CREDITOS-CLIENTES/03 COMWARE PRUEBAS- INFORMACION CREDITOS CLIENTES/"
    "02 VALIDACION PAGOS/90 ACCESO RESTRINGIDO/01 TRAZABILIDAD/2026/08/2026-08-21/"
    "merge_manifest_banco_bancolombia_2026-08-21_d01a537c.json"
)
PID = "2c91424b-5bfe-4d6e-a8cc-6409eda6d7ea"
OUT = ROOT / "scripts" / "_tmp" / "diag_manifest_256_outputs.json"


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
    return base64.b64decode(r.json()["content_base64"])


def matches_256(o: dict) -> bool:
    idp = str(o.get("id_pago") or "")
    if idp == PID:
        return True
    creds = o.get("creditos_seleccionados") or []
    if any("256" in str(c) for c in creds):
        return True
    if "256" in str(o.get("credito") or ""):
        return True
    return False


async def main():
    http = AppServiceGraphHttp(base_url=BASE, api_key=API, timeout=180.0)
    try:
        diag = await http._client.get(f"{BASE}/graph/diagnostics")
        diag.raise_for_status()
        drive = str(((diag.json() or {}).get("operations_site") or {}).get("drive_id") or "")
        raw = await download(http, drive, MPATH)
        m = json.loads(raw.decode("utf-8"))
        print("manifest keys", sorted(m.keys()))
        outs = []
        for key, val in m.items():
            if isinstance(val, list):
                for o in val:
                    if isinstance(o, dict) and matches_256(o):
                        outs.append({"section": key, **o})
            elif isinstance(val, dict):
                # nested lists
                for k2, v2 in val.items():
                    if isinstance(v2, list):
                        for o in v2:
                            if isinstance(o, dict) and matches_256(o):
                                outs.append({"section": f"{key}.{k2}", **o})
        OUT.write_text(json.dumps(outs, ensure_ascii=False, indent=2), encoding="utf-8")
        print("matched", len(outs), "->", OUT)
        for o in outs:
            print(
                "section",
                o.get("section"),
                "id",
                o.get("id_pago"),
                "tipo",
                o.get("tipo_aplicacion_canonica") or o.get("tipo_aplicacion"),
                "creds",
                o.get("creditos_seleccionados") or o.get("credito"),
                "monto",
                o.get("monto_banco") or o.get("valor_banco") or o.get("valor"),
                "paths",
                o.get("asiento_pdf_paths") or o.get("asiento_pdf_path"),
            )
    finally:
        await http.aclose()


if __name__ == "__main__":
    asyncio.run(main())
