"""Inspecciona extractos de créditos NUEVOS (no E2E previo) con los mismos helpers de la API.

Selecciona el ganador por max(fecha_limite) — misma regla GENERATE_EXTRACT_SELECTION_V2.
"""
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
    "02 COMWARE AUTOMATIZACION - INFORMACION CREDITOS CLIENTES"
)
OUT = Path(r"D:\CMC\HBI_Capital\_work\stress_e2e\extract_winners.json")

# Créditos listos NO usados en E2E previo + AGRECAR #71 (mismo cliente, crédito distinto)
TARGETS: list[tuple[str, str]] = [
    ("A&M CONSTRUCOL", "CREDITO # 215"),
    ("DIEGO RAMIRO PAZMIÑO DIAZ", "1 CREDITO # 32"),
    ("DIEGO RAMIRO PAZMIÑO DIAZ", "2 CREDITO # 92"),
    ("DIEGO RAMIRO PAZMIÑO DIAZ", "3 CREDITO # 94"),
    ("G&J INGENIERIA", "CREDITO # 224 VIGENTE"),
    ("G&J INGENIERIA", "CREDITO # 284 VIGENTE"),
    ("G&J INGENIERIA", "CREDITO # 296 VIGENTE"),
    ("INDUCAB", "CREDITO # 150"),
    ("INDUCAB", "CREDITO # 88"),
    ("AGRECAR", "4 CREDITO # 71"),
    ("AGRECAR", "3 CREDITO #46REPUESTOS"),
]


def children(c: httpx.Client, drive: str, fid: str = "root") -> list[dict]:
    r = c.get(
        f"{BASE}/graph/sharepoint/drives/{quote(drive, safe='')}/children",
        params={"folder_item_id": fid},
        timeout=120,
    )
    r.raise_for_status()
    return r.json().get("value") or []


def walk(c: httpx.Client, drive: str, parts: list[str]) -> str:
    cur = "root"
    for p in parts:
        items = children(c, drive, cur)
        hit = next((i for i in items if i.get("name") == p), None)
        if not hit:
            raise FileNotFoundError(p)
        cur = hit["id"]
    return cur


def download(c: httpx.Client, drive: str, item_id: str) -> bytes:
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


def list_extract_files(c: httpx.Client, drive: str, credit_id: str) -> list[dict]:
    """PDF extracto en raíz del crédito o en carpeta EXTRACTOS."""
    files = [
        i
        for i in children(c, drive, credit_id)
        if "file" in i and is_extract(str(i.get("name") or ""))
    ]
    for folder in children(c, drive, credit_id):
        if "folder" not in folder:
            continue
        if str(folder.get("name", "")).casefold() != "extractos":
            continue
        files.extend(
            i
            for i in children(c, drive, folder["id"])
            if "file" in i and is_extract(str(i.get("name") or ""))
        )
    return files


def main() -> None:
    OUT.parent.mkdir(parents=True, exist_ok=True)
    report: list[dict] = []
    with httpx.Client(timeout=180) as c:
        drive = c.get(f"{BASE}/graph/sharepoint/resolve-env", timeout=60).json()["resolved"][
            "drive_id"
        ]
        base_id = walk(c, drive, CLIENTS_BASE.split("/"))
        root = {i["name"]: i for i in children(c, drive, base_id) if "folder" in i}

        for client, credit in TARGETS:
            entry: dict = {
                "cliente": client,
                "credito": credit,
                "candidates": [],
                "winner": None,
                "error": None,
            }
            try:
                # coincidencia exacta o fuzzy por normalización de espacios
                client_it = root.get(client)
                if client_it is None:
                    for name, it in root.items():
                        if name.replace("Ñ", "N").replace("ñ", "n") == client.replace(
                            "Ñ", "N"
                        ).replace("ñ", "n"):
                            client_it = it
                            entry["cliente_folder_real"] = name
                            break
                if client_it is None:
                    raise FileNotFoundError(f"cliente:{client}")

                credit_it = next(
                    (
                        i
                        for i in children(c, drive, client_it["id"])
                        if i.get("name") == credit and "folder" in i
                    ),
                    None,
                )
                if credit_it is None:
                    raise FileNotFoundError(f"credito:{credit}")

                files = list_extract_files(c, drive, credit_it["id"])
                scored: list[tuple[dict, object, float | None, bytes]] = []
                for f in files:
                    row = {"archivo": f["name"]}
                    try:
                        pdf = download(c, drive, f["id"])
                        total = extract_total_a_pagar_from_pdf(pdf)
                        due = extract_fecha_limite_pago_from_pdf(pdf)
                        row["total_a_pagar"] = total
                        row["fecha_limite"] = due.isoformat() if due else None
                        if due is not None:
                            scored.append((f, due, total, pdf))
                    except Exception as exc:
                        row["error"] = f"{type(exc).__name__}: {exc}"
                    entry["candidates"].append(row)

                if not scored:
                    entry["error"] = "fecha_limite_extracto_not_readable"
                else:
                    max_d = max(t[1] for t in scored)
                    winners = [t for t in scored if t[1] == max_d]
                    if len(winners) > 1:
                        entry["error"] = "extract_tie_max_fecha_limite"
                        entry["tie_files"] = [w[0]["name"] for w in winners]
                    else:
                        f, due, total, _ = winners[0]
                        entry["winner"] = {
                            "archivo": f["name"],
                            "fecha_limite": due.isoformat(),
                            "total_a_pagar": total,
                            "rule": "max_fecha_limite_v2",
                        }
            except Exception as exc:
                entry["error"] = f"{type(exc).__name__}: {exc}"
            report.append(entry)
            w = entry.get("winner") or {}
            print(
                client,
                credit,
                "->",
                w.get("fecha_limite"),
                w.get("total_a_pagar"),
                entry.get("error"),
            )

    OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    ok = sum(1 for r in report if r.get("winner"))
    print(f"OK winners={ok}/{len(report)} -> {OUT}")


if __name__ == "__main__":
    main()
