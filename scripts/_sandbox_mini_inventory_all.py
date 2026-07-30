# -*- coding: utf-8 -*-
"""Inventario completo sandbox (sin Equinorte)."""
from __future__ import annotations

import base64
import json
import sys
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
SKIP_PREFIX = ("00 ", "01 ", "02 ", "03 ", "04 ", "05 ", "06 ")
SKIP_NAMES = {"EQUINORTE", "EQUIPOS DEL NORTE"}
OUT = Path(r"D:\CMC\HBI_Capital\_work\sandbox_mini")


def api_key() -> str:
    for line in Path(r"D:\CMC\HBI_Capital\api-hbi-powerAutomate.env").read_text(encoding="utf-8").splitlines():
        if line.startswith("API_HTTP_KEY="):
            return line.split("=", 1)[1].strip()
    raise RuntimeError("no key")


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
        hit = next(i for i in children(c, drive, cur) if i.get("name") == p)
        cur = str(hit["id"])
    return cur


def is_ex(name: str) -> bool:
    n = (name or "").lower()
    return n.endswith(".pdf") and "extracto" in n


def has_tabla(kids: list[dict]) -> bool:
    for it in kids:
        n = str(it.get("name") or "").casefold()
        if n.endswith((".xlsx", ".xlsm")) and ("amort" in n or "tabla" in n):
            return True
    return False


def extracts_in_unit(c: httpx.Client, drive: str, unit_id: str) -> list[dict]:
    out: list[dict] = []
    for it in children(c, drive, unit_id):
        n = str(it.get("name") or "")
        if "folder" in it and n.casefold() == "extractos":
            for x in children(c, drive, str(it["id"])):
                if is_ex(str(x.get("name") or "")) and "folder" not in x:
                    out.append(x)
        elif is_ex(n) and "folder" not in it:
            out.append(it)
    return out


def main() -> None:
    key = api_key()
    usable: list[dict] = []
    empty_clients: list[str] = []
    with httpx.Client(headers={"X-API-Key": key}, timeout=180) as c:
        drive = c.get(f"{BASE}/graph/diagnostics/paths-probe").json()["operations_site"]["drive_id"]
        root = walk(c, drive, CLIENTS_BASE.split("/"))
        tops = [
            i
            for i in children(c, drive, root)
            if "folder" in i
            and not str(i.get("name") or "").startswith(SKIP_PREFIX)
            and str(i.get("name") or "").upper() not in SKIP_NAMES
            and not str(i.get("name") or "").upper().startswith("EQUINORTE")
        ]
        print("clients", len(tops))
        for cit in tops:
            cname = str(cit.get("name") or "")
            ckids = children(c, drive, str(cit["id"]))
            units = [
                i
                for i in ckids
                if "folder" in i
                and str(i.get("name") or "").casefold()
                not in {"extractos", "asientos contables", "email", "correos"}
            ]
            found = 0
            for u in units:
                uk = children(c, drive, str(u["id"]))
                if not has_tabla(uk):
                    continue
                ex = extracts_in_unit(c, drive, str(u["id"]))
                if not ex:
                    continue
                ex.sort(key=lambda x: str(x.get("createdDateTime") or ""), reverse=True)
                latest = ex[0]
                try:
                    pdf = base64.b64decode(
                        c.get(
                            f"{BASE}/graph/sharepoint/drives/{quote(drive, safe='')}/item-content",
                            params={"item_id": latest["id"]},
                            timeout=180,
                        ).json()["content_base64"]
                    )
                    fe = extract_fecha_limite_pago_from_pdf(pdf)
                    try:
                        tot = float(extract_total_a_pagar_from_pdf(pdf))
                    except Exception:
                        tot = None
                except Exception as exc:
                    print(f"ERR {cname}/{u.get('name')}: {exc}")
                    continue
                row = {
                    "client": cname,
                    "credit": str(u.get("name") or ""),
                    "fecha_limite": fe.isoformat() if fe else None,
                    "total_a_pagar": tot,
                    "extract": latest.get("name"),
                    "created": latest.get("createdDateTime"),
                    "n_extracts": len(ex),
                    "pdf_ok": bool(fe and tot),
                }
                usable.append(row)
                found += 1
                print(
                    f"OK {cname} | {row['credit']} | fe={row['fecha_limite']} "
                    f"total={row['total_a_pagar']} n={row['n_extracts']}"
                )
            if found == 0:
                empty_clients.append(cname)
                print(f"EMPTY {cname} units={len(units)}")

    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "usable_all.json").write_text(
        json.dumps({"usable": usable, "empty_clients": empty_clients}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print("usable_ok", sum(1 for u in usable if u["pdf_ok"]), "total_rows", len(usable))
    print("empty", len(empty_clients))


if __name__ == "__main__":
    main()
