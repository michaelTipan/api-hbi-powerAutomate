# -*- coding: utf-8 -*-
"""Inventario rápido sandbox (03 COMWARE PRUEBAS) + metadatos de último extracto."""
from __future__ import annotations

import base64
import json
import os
import sys
from datetime import datetime
from pathlib import Path
from urllib.parse import quote

import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app.application.services.payment_helpers import (  # noqa: E402
    extract_fecha_limite_pago_from_pdf,
    extract_total_a_pagar_from_pdf,
)

BASE = "https://app-hbiauto-prod-001-afawg2g7frgte8c5.eastus-01.azurewebsites.net"
CLIENTS_BASE = (
    "INFORMACION CREDITOS-CLIENTES/"
    "03 COMWARE PRUEBAS- INFORMACION CREDITOS CLIENTES"
)
SKIP = {
    "00 CARGA TRANSACCIONES BANCO",
    "01 VALIDACION PAGOS",
    "02 VALIDACION PAGOS",
    "EQUINORTE",
    "EQUIPOS DEL NORTE",
}
OUT = Path(r"D:\CMC\HBI_Capital\_work\sandbox_mini")
OUT.mkdir(parents=True, exist_ok=True)


def load_api_key() -> str:
    env = Path(r"D:\CMC\HBI_Capital\api-hbi-powerAutomate.env")
    for line in env.read_text(encoding="utf-8").splitlines():
        if line.strip().startswith("API_HTTP_KEY="):
            return line.split("=", 1)[1].strip()
    raise RuntimeError("API_HTTP_KEY missing")


def children(c: httpx.Client, drive: str, fid: str = "root") -> list[dict]:
    r = c.get(
        f"{BASE}/graph/sharepoint/drives/{quote(drive, safe='')}/children",
        params={"folder_item_id": fid},
        timeout=120,
    )
    r.raise_for_status()
    return list((r.json() or {}).get("value") or [])


def walk(c: httpx.Client, drive: str, parts: list[str]) -> str:
    cur = "root"
    for p in parts:
        items = children(c, drive, cur)
        hit = next((i for i in items if i.get("name") == p), None)
        if not hit:
            raise FileNotFoundError(p)
        cur = str(hit["id"])
    return cur


def download(c: httpx.Client, drive: str, item_id: str) -> bytes:
    r = c.get(
        f"{BASE}/graph/sharepoint/drives/{quote(drive, safe='')}/item-content",
        params={"item_id": item_id},
        timeout=180,
    )
    r.raise_for_status()
    return base64.b64decode(r.json()["content_base64"])


def is_extract_pdf(name: str) -> bool:
    n = (name or "").lower()
    return n.endswith(".pdf") and "extracto" in n


def created_key(it: dict) -> str:
    return str(it.get("createdDateTime") or it.get("lastModifiedDateTime") or "")


def collect_extracts(c: httpx.Client, drive: str, credit_id: str, credit_path: str) -> list[dict]:
    """Raíz + EXTRACTOS (si existe); anota createdDateTime."""
    kids = children(c, drive, credit_id)
    found: list[dict] = []
    for it in kids:
        name = str(it.get("name") or "")
        if "folder" in it and name.casefold() == "extractos":
            for ex in children(c, drive, str(it["id"])):
                en = str(ex.get("name") or "")
                if is_extract_pdf(en) and "folder" not in ex:
                    found.append(
                        {
                            **ex,
                            "_rel": f"{credit_path}/{name}/{en}",
                            "_source": "extractos",
                        }
                    )
        elif is_extract_pdf(name) and "folder" not in it:
            found.append({**it, "_rel": f"{credit_path}/{name}", "_source": "root"})
    return found


def has_tabla(kids: list[dict]) -> bool:
    for it in kids:
        n = str(it.get("name") or "").casefold()
        if n.endswith((".xlsx", ".xlsm")) and ("amort" in n or "tabla" in n):
            return True
    return False


def main() -> None:
    key = load_api_key()
    headers = {"X-API-Key": key}
    with httpx.Client(headers=headers, timeout=180) as c:
        # drive id via paths-probe / diagnostics
        probe = c.get(f"{BASE}/graph/diagnostics/paths-probe")
        probe.raise_for_status()
        pj = probe.json()
        drive = (pj.get("operations_site") or {}).get("drive_id")
        if not drive:
            # fallback diagnostics
            d = c.get(f"{BASE}/graph/diagnostics").json()
            drive = d.get("drive_id") or (d.get("operations") or {}).get("drive_id")
        print("drive", drive)
        print("active_env", pj.get("active_environment"))

        parts = CLIENTS_BASE.split("/")
        root_id = walk(c, drive, parts)
        top = children(c, drive, root_id)
        clients = [
            it
            for it in top
            if "folder" in it
            and str(it.get("name") or "") not in SKIP
            and not str(it.get("name") or "").upper().startswith("EQUINORTE")
        ]
        clients.sort(key=lambda x: str(x.get("name") or ""))
        print(f"clientes_visibles={len(clients)}")
        for it in clients:
            print(" -", it.get("name"))

        # Analizar hasta 10 clientes
        selected = clients[:10]
        inventory: list[dict] = []
        for cit in selected:
            cname = str(cit.get("name") or "")
            ckids = children(c, drive, str(cit["id"]))
            credits: list[dict] = []
            # unidades de crédito = carpetas hijas (no extractos sueltos en raíz)
            for unit in ckids:
                if "folder" not in unit:
                    continue
                uname = str(unit.get("name") or "")
                if uname.casefold() in {"extractos", "asientos contables", "email", "correos"}:
                    continue
                ukids = children(c, drive, str(unit["id"]))
                extracts = collect_extracts(
                    c, drive, str(unit["id"]), f"{CLIENTS_BASE}/{cname}/{uname}"
                )
                if not extracts:
                    continue
                extracts.sort(key=created_key, reverse=True)
                latest = extracts[0]
                meta = {
                    "client": cname,
                    "credit": uname,
                    "extract_name": latest.get("name"),
                    "extract_source": latest.get("_source"),
                    "createdDateTime": latest.get("createdDateTime"),
                    "lastModifiedDateTime": latest.get("lastModifiedDateTime"),
                    "has_tabla": has_tabla(ukids),
                    "extract_count": len(extracts),
                }
                try:
                    pdf = download(c, drive, str(latest["id"]))
                    fe = extract_fecha_limite_pago_from_pdf(pdf)
                    try:
                        total = extract_total_a_pagar_from_pdf(pdf)
                    except Exception as exc:
                        total = None
                        meta["total_error"] = str(exc)[:120]
                    meta["fecha_limite"] = fe.isoformat() if fe else None
                    meta["total_a_pagar"] = total
                    meta["pdf_ok"] = fe is not None and total is not None
                except Exception as exc:
                    meta["pdf_ok"] = False
                    meta["pdf_error"] = str(exc)[:200]
                credits.append(meta)
                print(
                    f"  {cname} | {uname} | fe={meta.get('fecha_limite')} "
                    f"total={meta.get('total_a_pagar')} tabla={meta.get('has_tabla')} "
                    f"src={meta.get('extract_source')} n={meta.get('extract_count')}"
                )
            inventory.append({"client": cname, "credits": credits})

    out = OUT / "inventory.json"
    out.write_text(json.dumps(inventory, ensure_ascii=False, indent=2), encoding="utf-8")
    print("wrote", out)


if __name__ == "__main__":
    main()
