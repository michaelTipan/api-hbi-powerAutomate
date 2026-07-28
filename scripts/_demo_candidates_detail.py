# -*- coding: utf-8 -*-
"""Detalle de extractos para candidatos de demo (no usados en E2E)."""
from __future__ import annotations

import json
from pathlib import Path
from urllib.parse import quote

import httpx

BASE = "https://app-hbiauto-prod-001-afawg2g7frgte8c5.eastus-01.azurewebsites.net"
ROOT = (
    "INFORMACION CREDITOS-CLIENTES/"
    "02 COMWARE AUTOMATIZACION - INFORMACION CREDITOS CLIENTES"
)
# (cliente, folder crédito)
TARGETS = [
    ("A&M CONSTRUCOL", "CREDITO # 215"),
    ("G&J INGENIERIA", "CREDITO # 224 VIGENTE"),
    ("G&J INGENIERIA", "CREDITO # 284 VIGENTE"),
    ("DIEGO RAMIRO PAZMIÑO DIAZ", "1 CREDITO # 32"),
    ("DIEGO RAMIRO PAZMIÑO DIAZ", "2 CREDITO # 92"),
    ("INDUCAB", "CREDITO # 150"),
    ("INDUCAB", "CREDITO # 88"),
    ("AGRECAR", "4 CREDITO # 71"),  # crédito no tocado del cliente usado
]


def children(c, drive, item_id="root"):
    r = c.get(
        f"{BASE}/graph/sharepoint/drives/{quote(drive, safe='')}/children",
        params={"folder_item_id": item_id},
        timeout=120,
    )
    r.raise_for_status()
    return list((r.json() or {}).get("value") or [])


def walk(c, drive, parts):
    item_id = "root"
    for part in parts:
        kids = children(c, drive, item_id)
        hit = next((x for x in kids if str(x.get("name") or "") == part), None)
        if not hit:
            # fuzzy
            hit = next(
                (x for x in kids if str(x.get("name") or "").casefold() == part.casefold()),
                None,
            )
        if not hit:
            raise RuntimeError(f"missing {part}")
        item_id = str(hit["id"])
    return item_id


def main():
    out = []
    with httpx.Client(timeout=180) as c:
        drive = c.get(f"{BASE}/graph/sharepoint/resolve-env").json()["resolved"]["drive_id"]
        for cliente, cred in TARGETS:
            try:
                cid = walk(c, drive, ROOT.split("/") + [cliente, cred])
                kids = children(c, drive, cid)
                extractos = sorted(
                    [
                        str(x.get("name") or "")
                        for x in kids
                        if str(x.get("name") or "").lower().endswith(".pdf")
                        and "extracto" in str(x.get("name") or "").casefold()
                    ]
                )
                tablas = [
                    str(x.get("name") or "")
                    for x in kids
                    if str(x.get("name") or "").lower().endswith((".xlsx", ".xlsm"))
                    and "amort" in str(x.get("name") or "").casefold()
                    or (
                        str(x.get("name") or "").lower().endswith((".xlsx", ".xlsm"))
                        and "tabla" in str(x.get("name") or "").casefold()
                    )
                ]
                folders = [str(x.get("name") or "") for x in kids if "folder" in x]
                out.append(
                    {
                        "cliente": cliente,
                        "credito": cred,
                        "latest_extractos": extractos[-3:],
                        "extractos_count": len(extractos),
                        "tablas": tablas,
                        "folders": folders,
                    }
                )
                print(f"OK {cliente} / {cred}: {len(extractos)} extractos, last={extractos[-1] if extractos else '-'}")
            except Exception as exc:
                print(f"FAIL {cliente}/{cred}: {exc}")
                out.append({"cliente": cliente, "credito": cred, "error": str(exc)})
    Path(r"D:\CMC\HBI_Capital\_work\prod_validation\demo_candidates.json").write_text(
        json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8"
    )


if __name__ == "__main__":
    main()
