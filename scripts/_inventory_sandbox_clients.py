# -*- coding: utf-8 -*-
"""Lista clientes del sandbox y créditos con extracto/tabla/asientos."""
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
USED_CLIENTS = {"GEOEXCON", "EQUINORTE", "AGRECAR"}
# También tocados en matriz/negativos previos
USED_SOFT = {"ACIMOR", "MINCIVIL", "INVERSIONES Y PROYECTOS MIOS", "INVERSIONES"}
SKIP_TOP = {
    "00 CARGA TRANSACCIONES BANCO",
    "01 VALIDACION PAGOS",
    "asientos_prueba",
}
WORK = Path(r"D:\CMC\HBI_Capital\_work\prod_validation")


def children(c: httpx.Client, drive: str, item_id: str = "root") -> list[dict]:
    r = c.get(
        f"{BASE}/graph/sharepoint/drives/{quote(drive, safe='')}/children",
        params={"folder_item_id": item_id},
        timeout=120,
    )
    r.raise_for_status()
    return list((r.json() or {}).get("value") or [])


def find_child(items: list[dict], name: str) -> dict | None:
    target = name.casefold()
    for it in items:
        if str(it.get("name") or "").casefold() == target:
            return it
    return None


def walk_to(c: httpx.Client, drive: str, parts: list[str]) -> str:
    item_id = "root"
    for part in parts:
        kids = children(c, drive, item_id)
        hit = find_child(kids, part)
        if not hit:
            raise RuntimeError(f"No encontrado: {part} bajo {parts}")
        item_id = str(hit["id"])
    return item_id


def summarize_credit(c: httpx.Client, drive: str, credit_item: dict) -> dict:
    name = str(credit_item.get("name") or "")
    kid = children(c, drive, str(credit_item["id"]))
    names = [str(x.get("name") or "") for x in kid]
    extractos = [n for n in names if n.lower().endswith(".pdf") and "extracto" in n.casefold()]
    tablas = [
        n
        for n in names
        if n.lower().endswith((".xlsx", ".xlsm"))
        and ("amort" in n.casefold() or "tabla" in n.casefold())
    ]
    asiento_dirs = [x for x in kid if "folder" in x and "asiento" in str(x.get("name") or "").casefold()]
    asiento_pdfs = 0
    for ad in asiento_dirs:
        ad_kids = children(c, drive, str(ad["id"]))
        asiento_pdfs += sum(
            1
            for x in ad_kids
            if str(x.get("name") or "").lower().endswith(".pdf") and "folder" not in x
        )
        # PROCESADOS
        for x in ad_kids:
            if "folder" in x and "procesado" in str(x.get("name") or "").casefold():
                pk = children(c, drive, str(x["id"]))
                asiento_pdfs += sum(
                    1 for p in pk if str(p.get("name") or "").lower().endswith(".pdf")
                )
    return {
        "credito_folder": name,
        "extractos": extractos,
        "tablas": tablas,
        "asiento_pdfs_count": asiento_pdfs,
        "ready_pago": bool(extractos and tablas),
    }


def main() -> None:
    with httpx.Client(timeout=180) as c:
        drive = c.get(f"{BASE}/graph/sharepoint/resolve-env").json()["resolved"]["drive_id"]
        print("drive", drive)
        parts = ROOT.split("/")
        root_id = walk_to(c, drive, parts)
        top = children(c, drive, root_id)
        clients = []
        for it in top:
            if "folder" not in it:
                continue
            name = str(it.get("name") or "").strip()
            if not name or name in SKIP_TOP or name.startswith("0"):
                continue
            credits = []
            for ch in children(c, drive, str(it["id"])):
                if "folder" not in ch:
                    continue
                cn = str(ch.get("name") or "")
                if "credito" not in cn.casefold() and "crédito" not in cn.casefold():
                    # a veces carpeta de crédito sin la palabra
                    if "#" not in cn and "cred" not in cn.casefold():
                        continue
                try:
                    credits.append(summarize_credit(c, drive, ch))
                except Exception as exc:
                    credits.append({"credito_folder": cn, "error": str(exc)[:200]})
            clients.append(
                {
                    "cliente": name,
                    "used_in_e2e": name.upper() in {u.upper() for u in USED_CLIENTS}
                    or any(name.upper().startswith(u.upper()) for u in USED_SOFT),
                    "credits": credits,
                    "ready_credits": [
                        x for x in credits if x.get("ready_pago") and not x.get("error")
                    ],
                }
            )

        clients.sort(key=lambda x: (x["used_in_e2e"], x["cliente"].upper()))
        out = {
            "root": ROOT,
            "used_clients_e2e": sorted(USED_CLIENTS),
            "clients": clients,
        }
        (WORK / "sandbox_clients_inventory.json").write_text(
            json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print("\n=== CLIENTES (no usados en E2E primero) ===")
        for cl in clients:
            ready = cl["ready_credits"]
            flag = "USED" if cl["used_in_e2e"] else "FREE"
            print(
                f"[{flag}] {cl['cliente']}: {len(cl['credits'])} créditos, "
                f"{len(ready)} listos (extracto+tabla)"
            )
            for r in ready[:4]:
                print(
                    f"    - {r['credito_folder']} | extractos={len(r['extractos'])} "
                    f"tablas={r['tablas']} asientos={r['asiento_pdfs_count']}"
                )


if __name__ == "__main__":
    main()
