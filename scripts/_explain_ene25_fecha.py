"""Confirma por qué Extracto Ene-25.pdf no tiene fecha_limite legible."""
from __future__ import annotations

import base64
import io
import re
from datetime import date
from pathlib import Path
from urllib.parse import quote

import httpx
from pypdf import PdfReader

from app.application.services.payment_helpers import (
    extract_fecha_limite_pago_from_pdf,
    extract_fecha_limite_pago_from_pdf_text,
)

BASE = "https://app-hbiauto-prod-001-afawg2g7frgte8c5.eastus-01.azurewebsites.net"


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
        cur = next(i["id"] for i in children(c, drive, cur) if i.get("name") == p)
    return cur


def main() -> None:
    key = api_key()
    with httpx.Client(timeout=180, headers={"X-API-Key": key}) as c:
        drive = c.get(f"{BASE}/graph/sharepoint/resolve-env").json()["resolved"]["drive_id"]
        unit = walk(c, drive, ["INFORMACION CREDITOS-CLIENTES", "TRAVEL CARGA", "CREDITO #  138"])
        it = next(i for i in children(c, drive, unit) if i.get("name") == "Extracto Ene-25.pdf")
        raw = base64.b64decode(
            c.get(
                f"{BASE}/graph/sharepoint/drives/{quote(drive, safe='')}/item-content",
                params={"item_id": it["id"]},
            ).json()["content_base64"]
        )
    text = ""
    for page in PdfReader(io.BytesIO(raw)).pages:
        text += (page.extract_text() or "") + "\n"
    print("parser_result", extract_fecha_limite_pago_from_pdf(raw))
    print("parser_text_result", extract_fecha_limite_pago_from_pdf_text(text))
    for line in text.splitlines():
        low = line.lower()
        if "limite" in low or "límite" in low or "29/02" in line or "29-02" in line or "vencim" in low:
            print("LINE:", repr(line))
    try:
        date(2025, 2, 29)
        print("python_accepts_2025-02-29")
    except ValueError as exc:
        print("python_rejects_2025-02-29:", exc)


if __name__ == "__main__":
    main()
