"""Borra el Excel de revisión que bloquea Generate."""
from __future__ import annotations

from urllib.parse import quote

import httpx

BASE = "https://app-hbiauto-prod-001-afawg2g7frgte8c5.eastus-01.azurewebsites.net"
REV = (
    "INFORMACION CREDITOS-CLIENTES/"
    "02 COMWARE AUTOMATIZACION - INFORMACION CREDITOS CLIENTES/"
    "01 VALIDACION PAGOS/02 REVISION"
)


def children(c, drive, fid="root"):
    r = c.get(
        f"{BASE}/graph/sharepoint/drives/{quote(drive, safe='')}/children",
        params={"folder_item_id": fid},
        timeout=120,
    )
    r.raise_for_status()
    return r.json().get("value") or []


def walk(c, drive, parts):
    cur = "root"
    for p in parts:
        hit = next(i for i in children(c, drive, cur) if i.get("name") == p)
        cur = hit["id"]
    return cur


with httpx.Client(timeout=120) as c:
    openapi = c.get(f"{BASE}/openapi.json").json()["paths"]
    key = "/graph/sharepoint/drives/{drive_id}/items/{item_id}"
    print("openapi methods", openapi.get(key))
    drive = c.get(f"{BASE}/graph/sharepoint/resolve-env").json()["resolved"]["drive_id"]
    rid = walk(c, drive, REV.split("/"))
    items = children(c, drive, rid)
    print("before", [i.get("name") for i in items])
    for it in list(items):
        if str(it.get("name", "")).startswith("~$"):
            continue
        item_id = it["id"]
        url = f"{BASE}/graph/sharepoint/drives/{quote(drive, safe='')}/items/{item_id}"
        r = c.delete(url)
        print("delete", it.get("name"), r.status_code, r.text[:200])
        r.raise_for_status()
    items2 = children(c, drive, rid)
    print("after", [i.get("name") for i in items2])
