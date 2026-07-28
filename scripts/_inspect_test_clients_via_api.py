"""Inspección de clientes vía API pública del App Service (sin Key Vault local)."""
from __future__ import annotations

import base64
import json
import re
import sys
import unicodedata
from pathlib import Path
from urllib.parse import quote

import httpx

BASE = "https://app-hbiauto-prod-001-afawg2g7frgte8c5.eastus-01.azurewebsites.net"
CLIENTS_BASE = (
    "INFORMACION CREDITOS-CLIENTES/"
    "02 COMWARE AUTOMATIZACION - INFORMACION CREDITOS CLIENTES"
)
TARGETS = [
    "GEOEXCON",
    "EQUINORTE",
    "ACIMOR",
    "MINCIVIL",
    "INVERSIONES Y PROYECTOS",
    "AGRECAR",
]
EXCLUDED_PREFIXES = ("00 ", "01 ", "02 ", "03 ", "04 ", "05 ", "06 ")

# Reusar parsers locales
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app.application.services.payment_helpers import (  # noqa: E402
    extract_fecha_limite_pago_from_pdf,
    extract_total_a_pagar_from_pdf,
    find_best_amortization_table,
)
from app.application.use_cases.payment_validation_generate import (  # noqa: E402
    _extract_pending_installment,
)


def _norm(s: str) -> str:
    t = unicodedata.normalize("NFKD", s or "")
    t = "".join(c for c in t if not unicodedata.combining(c))
    return " ".join(t.upper().split())


def _match(folder: str, target: str) -> bool:
    nf, nt = _norm(folder), _norm(target)
    return nt in nf or nf in nt


def children(client: httpx.Client, drive_id: str, folder_item_id: str = "root") -> list[dict]:
    r = client.get(
        f"{BASE}/graph/sharepoint/drives/{quote(drive_id, safe='')}/children",
        params={"folder_item_id": folder_item_id},
        timeout=120.0,
    )
    r.raise_for_status()
    return list((r.json() or {}).get("value") or [])


def download(client: httpx.Client, drive_id: str, item_id: str) -> bytes:
    r = client.get(
        f"{BASE}/graph/sharepoint/drives/{quote(drive_id, safe='')}/item-content",
        params={"item_id": item_id},
        timeout=180.0,
    )
    r.raise_for_status()
    return base64.b64decode(r.json()["content_base64"])


def find_child(items: list[dict], name: str) -> dict | None:
    for it in items:
        if str(it.get("name") or "") == name:
            return it
    return None


def walk_path(client: httpx.Client, drive_id: str, parts: list[str]) -> str:
    """Devuelve item id de la carpeta final."""
    current = "root"
    for part in parts:
        items = children(client, drive_id, current)
        hit = find_child(items, part)
        if not hit:
            # fuzzy
            hits = [it for it in items if _norm(str(it.get("name") or "")) == _norm(part)]
            if not hits:
                raise FileNotFoundError(f"No se encontró carpeta {part!r} bajo {parts}")
            hit = hits[0]
        current = hit["id"]
    return current


def latest_pdf(items: list[dict]) -> dict | None:
    pdfs = [it for it in items if str(it.get("name", "")).lower().endswith(".pdf") and "file" in it]
    if not pdfs:
        return None
    pdfs.sort(
        key=lambda it: str(it.get("lastModifiedDateTime") or it.get("createdDateTime") or ""),
        reverse=True,
    )
    return pdfs[0]


def inspect_credit(client: httpx.Client, drive_id: str, credit_item: dict, client_folder: str) -> dict:
    credit_name = str(credit_item.get("name") or "")
    kids = children(client, drive_id, credit_item["id"])
    names = [str(it.get("name") or "") for it in kids]
    folders = {str(it.get("name") or ""): it for it in kids if "folder" in it}
    excel_names = [n for n in names if n.lower().endswith((".xlsx", ".xlsm", ".xls"))]

    out: dict = {"credito": credit_name, "extracto": None, "tabla": None}

    extract_folder = None
    for cand in ("EXTRACTOS", "Extractos", "EXTRACTO"):
        if cand in folders:
            extract_folder = folders[cand]
            break
    if extract_folder:
        ex_kids = children(client, drive_id, extract_folder["id"])
        latest = latest_pdf(ex_kids)
        if latest:
            try:
                pdf_bytes = download(client, drive_id, latest["id"])
                total = extract_total_a_pagar_from_pdf(pdf_bytes)
                due = extract_fecha_limite_pago_from_pdf(pdf_bytes)
                out["extracto"] = {
                    "archivo": latest["name"],
                    "total_a_pagar": total,
                    "fecha_limite": due.isoformat() if due else None,
                    "modificado": latest.get("lastModifiedDateTime"),
                }
            except Exception as exc:
                out["extracto"] = {
                    "archivo": latest["name"],
                    "error": f"{type(exc).__name__}: {exc}",
                }

    try:
        table_name = find_best_amortization_table(excel_names or names, client_folder, credit_name)
        table_item = find_child(kids, table_name)
        if not table_item:
            raise FileNotFoundError(f"tabla {table_name} no listada")
        table_bytes = download(client, drive_id, table_item["id"])
        pending = _extract_pending_installment(table_bytes, client_folder)
        out["tabla"] = {
            "archivo": table_name,
            "raw_preview": {
                k: (v.isoformat() if hasattr(v, "isoformat") else v)
                for k, v in list(pending.items())[:15]
            },
        }
    except Exception as exc:
        out["tabla"] = {"error": f"{type(exc).__name__}: {exc}"}

    return out


def main() -> None:
    with httpx.Client() as client:
        resolved = client.get(f"{BASE}/graph/sharepoint/resolve-env", timeout=60.0)
        resolved.raise_for_status()
        drive_id = resolved.json()["resolved"]["drive_id"]

        base_id = walk_path(client, drive_id, CLIENTS_BASE.split("/"))
        root_kids = children(client, drive_id, base_id)
        folders = [
            it
            for it in root_kids
            if "folder" in it
            and str(it.get("name") or "").strip()
            and not any(str(it.get("name") or "").startswith(p) for p in EXCLUDED_PREFIXES)
        ]

        report = []
        for target in TARGETS:
            matches = [it for it in folders if _match(str(it.get("name") or ""), target)]
            matches.sort(
                key=lambda it: (
                    0 if _norm(str(it.get("name") or "")) == _norm(target) else 1,
                    len(str(it.get("name") or "")),
                )
            )
            entry: dict = {
                "target": target,
                "matches": [str(it.get("name") or "") for it in matches],
                "credits": [],
            }
            if not matches:
                entry["error"] = "cliente_no_encontrado"
                report.append(entry)
                continue
            client_it = matches[0]
            client_folder = str(client_it.get("name") or "")
            entry["cliente_folder"] = client_folder
            try:
                credit_kids = children(client, drive_id, client_it["id"])
                credits = [
                    it
                    for it in credit_kids
                    if "folder" in it
                    and str(it.get("name") or "").strip()
                    and _norm(str(it.get("name") or ""))
                    not in {"ASIENTOS CONTABLES", "EXTRACTOS", "DOCUMENTOS"}
                ]
                credit_like = [
                    it
                    for it in credits
                    if any(tok in _norm(str(it.get("name") or "")) for tok in ("CREDITO", "CRED", "#"))
                    or any(ch.isdigit() for ch in str(it.get("name") or ""))
                ] or credits
                for credit_it in sorted(credit_like, key=lambda x: str(x.get("name") or ""))[:4]:
                    entry["credits"].append(
                        inspect_credit(client, drive_id, credit_it, client_folder)
                    )
            except Exception as exc:
                entry["error"] = f"{type(exc).__name__}: {exc}"
            report.append(entry)

    out = Path(__file__).resolve().parents[2] / "inspeccion_clientes_prueba.json"
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2, default=str))
    print(f"\nOK -> {out}", file=sys.stderr)


if __name__ == "__main__":
    main()
