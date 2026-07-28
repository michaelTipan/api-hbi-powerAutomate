"""Lee TOTAL A PAGAR de los extractos PDF más recientes (en raíz del crédito)."""
from __future__ import annotations

import base64
import json
import re
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
    "02 COMWARE AUTOMATIZACION - INFORMACION CREDITOS CLIENTES"
)

# crédito a inspeccionar: (cliente, nombre carpeta crédito)
TARGETS = [
    ("GEOEXCON", "CREDITO # 231"),
    ("GEOEXCON", "CREDITO # 254"),
    ("EQUINORTE", "CREDITO # 258"),
    ("EQUINORTE", "CREDITO # 264"),
    ("EQUINORTE", "CREDITO # 265"),
    ("AGRECAR", "2 CREDITO #37 VIGENTE"),
    ("AGRECAR", "4 CREDITO # 71"),
    ("INVERSIONES Y PROYECTOS MIOS", "CREDITO # 318"),
]


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
        items = children(c, drive, cur)
        hit = next((i for i in items if i.get("name") == p), None)
        if not hit:
            raise FileNotFoundError(p)
        cur = hit["id"]
    return cur


def download(c, drive, item_id):
    r = c.get(
        f"{BASE}/graph/sharepoint/drives/{quote(drive, safe='')}/item-content",
        params={"item_id": item_id},
        timeout=180,
    )
    r.raise_for_status()
    return base64.b64decode(r.json()["content_base64"])


def is_extract(name: str) -> bool:
    n = name.lower()
    return n.endswith(".pdf") and "extracto" in n


def main():
    with httpx.Client() as c:
        drive = c.get(f"{BASE}/graph/sharepoint/resolve-env", timeout=60).json()["resolved"][
            "drive_id"
        ]
        base_id = walk(c, drive, CLIENTS_BASE.split("/"))
        root = {i["name"]: i for i in children(c, drive, base_id) if "folder" in i}

        report = []
        for client, credit in TARGETS:
            entry = {"cliente": client, "credito": credit, "extractos": []}
            try:
                client_it = root[client]
                credit_it = next(
                    i
                    for i in children(c, drive, client_it["id"])
                    if i.get("name") == credit and "folder" in i
                )
                files = [
                    i
                    for i in children(c, drive, credit_it["id"])
                    if "file" in i and is_extract(str(i.get("name") or ""))
                ]
                files.sort(
                    key=lambda i: str(
                        i.get("lastModifiedDateTime") or i.get("createdDateTime") or ""
                    ),
                    reverse=True,
                )
                for f in files[:3]:
                    row = {"archivo": f["name"], "modificado": f.get("lastModifiedDateTime")}
                    try:
                        pdf = download(c, drive, f["id"])
                        row["total_a_pagar"] = extract_total_a_pagar_from_pdf(pdf)
                        due = extract_fecha_limite_pago_from_pdf(pdf)
                        row["fecha_limite"] = due.isoformat() if due else None
                    except Exception as exc:
                        row["error"] = f"{type(exc).__name__}: {exc}"
                    entry["extractos"].append(row)
            except Exception as exc:
                entry["error"] = f"{type(exc).__name__}: {exc}"
            report.append(entry)

    out = Path(__file__).resolve().parents[2] / "inspeccion_extractos.json"
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"OK {out}")


if __name__ == "__main__":
    main()
