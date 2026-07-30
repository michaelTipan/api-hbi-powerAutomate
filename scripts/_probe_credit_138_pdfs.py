"""Identifica PDFs de TRAVEL CARGA #138 sin fecha_limite legible."""
from __future__ import annotations

import base64
import re
from pathlib import Path
from urllib.parse import quote

import httpx

from app.application.use_cases.payment_validation_generate import (
    extract_fecha_limite_pago_from_pdf,
    extract_total_a_pagar_from_pdf,
)

BASE = "https://app-hbiauto-prod-001-afawg2g7frgte8c5.eastus-01.azurewebsites.net"
CLIENT = "TRAVEL CARGA"
CREDIT = "CREDITO #  138"  # double space as in SharePoint


def api_key() -> str:
    env = Path(r"D:\CMC\HBI_Capital\api-hbi-powerAutomate.env").read_text(encoding="utf-8")
    return re.search(r"^API_HTTP_KEY=(.+)$", env, re.M).group(1).strip()


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


def main() -> None:
    key = api_key()
    with httpx.Client(timeout=180, headers={"X-API-Key": key}) as c:
        drive = c.get(f"{BASE}/graph/sharepoint/resolve-env").json()["resolved"]["drive_id"]
        unit = walk(
            c,
            drive,
            ["INFORMACION CREDITOS-CLIENTES", CLIENT, CREDIT],
        )
        items = children(c, drive, unit)
        pdfs = [
            i
            for i in items
            if str(i.get("name", "")).lower().endswith(".pdf")
            and "extracto" in str(i.get("name", "")).lower()
        ]
        print("pdfs", len(pdfs))
        bad = []
        good = []
        for it in pdfs:
            name = it["name"]
            r = c.get(
                f"{BASE}/graph/sharepoint/drives/{quote(drive, safe='')}/item-content",
                params={"item_id": it["id"]},
                timeout=180,
            )
            r.raise_for_status()
            raw = base64.b64decode(r.json()["content_base64"])
            fe = extract_fecha_limite_pago_from_pdf(raw)
            tot = extract_total_a_pagar_from_pdf(raw) if fe else None
            row = {"name": name, "fecha_limite": str(fe) if fe else None, "total": tot, "bytes": len(raw)}
            if fe is None:
                bad.append(row)
                print("BAD", name)
            else:
                good.append(row)
                print("OK ", name, fe, tot)
        print("SUMMARY good", len(good), "bad", len(bad))
        for b in bad:
            print(" -", b["name"])


if __name__ == "__main__":
    main()
