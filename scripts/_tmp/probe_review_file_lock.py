"""Graph probe: metadata + delete dry-run del Excel de revisión bloqueado."""
from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path

# Bootstrap env pack
ENV = Path(r"D:\CMC\HBI_Capital\api-hbi-powerAutomate.env")
REL = (
    "INFORMACION CREDITOS-CLIENTES/03 COMWARE PRUEBAS- INFORMACION CREDITOS CLIENTES/"
    "02 VALIDACION PAGOS/01 REVISION/"
    "validacion_pagos_banco_bancolombia_2026-08-31_cfdba744-a025-4469-b8f5-da8ef8428c84.xlsx"
)


def load_env(path: Path) -> None:
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ[k.strip()] = v.strip()


async def main() -> None:
    load_env(ENV)
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    from app.adapters.secondary.ms_graph_client import MsGraphClient
    from app.application.sharepoint_resolution import (
        encode_graph_drive_path,
        require_operations_site_config,
        resolve_sharepoint_path,
    )

    require_operations_site_config()
    site_search = os.getenv("GRAPH_SHAREPOINT_SITE_SEARCH", "").strip()
    drive_name = os.getenv("GRAPH_SHAREPOINT_DRIVE_NAME", "").strip()
    client = MsGraphClient()
    info = await resolve_sharepoint_path(client, site_search, drive_name, REL.rsplit("/", 1)[0])
    site_id = info["site_id"]
    drive_id = info["drive_id"]
    enc = encode_graph_drive_path(REL)
    meta_ep = f"/sites/{site_id}/drives/{drive_id}/root:/{enc}"

    print("=== GET metadata ===")
    try:
        meta = await client.get(meta_ep)
        keep = {
            k: meta.get(k)
            for k in (
                "id",
                "name",
                "webUrl",
                "size",
                "createdDateTime",
                "lastModifiedDateTime",
                "createdBy",
                "lastModifiedBy",
                "@microsoft.graph.downloadUrl",
            )
        }
        print(json.dumps(keep, indent=2, ensure_ascii=False))
        item_id = meta.get("id")
    except Exception as e:
        print("GET failed:", e)
        return

    if item_id:
        print("\n=== GET checkout (if any) ===")
        try:
            co = await client.get(f"/sites/{site_id}/drives/{drive_id}/items/{item_id}/checkout")
            print(json.dumps(co, indent=2, ensure_ascii=False))
        except Exception as e:
            print("checkout endpoint:", type(e).__name__, str(e)[:500])

        print("\n=== GET ?select=file,publication,shared,parentReference ===")
        try:
            sel = await client.get(
                f"/sites/{site_id}/drives/{drive_id}/items/{item_id}"
                "?$select=id,name,webUrl,file,publication,shared,parentReference,createdBy,lastModifiedBy"
            )
            print(json.dumps(sel, indent=2, ensure_ascii=False)[:3000])
        except Exception as e:
            print("select failed:", e)

    print("\n=== DELETE attempt (real) ===")
    if os.environ.get("DO_DELETE") != "1":
        print("skipped (set DO_DELETE=1 to try)")
        return
    try:
        await client.delete(f"{meta_ep}:")
        print("DELETE ok")
    except Exception as e:
        print("DELETE failed:", type(e).__name__, str(e)[:800])


if __name__ == "__main__":
    asyncio.run(main())
