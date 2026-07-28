"""Inspección sandbox: extractos y cuota pendiente por cliente de prueba."""
from __future__ import annotations

import asyncio
import json
import os
import sys
from datetime import date
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
ENV = ROOT.parent / "api-hbi-powerAutomate.env"
load_dotenv(ENV)
sys.path.insert(0, str(ROOT))

from app.adapters.secondary.ms_graph_client import MsGraphClient
from app.application.services.payment_helpers import (
    extract_fecha_limite_pago_from_pdf,
    extract_total_a_pagar_from_pdf,
    find_best_amortization_table,
)
from app.application.sharepoint_resolution import encode_graph_drive_path, resolve_sharepoint_from_env
from app.application.use_cases.payment_validation_generate import _extract_pending_installment

TARGETS = [
    "GEOEXCON",
    "EQUINORTE",
    "ACIMOR",
    "MINCIVIL",
    "INVERSIONES Y PROYECTOS",
    "AGRECAR",
]

EXCLUDED_PREFIXES = (
    "00 ",
    "01 ",
    "02 ",
    "03 ",
    "04 ",
    "05 ",
    "06 ",
)


def _norm(s: str) -> str:
    import unicodedata

    t = unicodedata.normalize("NFKD", s or "")
    t = "".join(c for c in t if not unicodedata.combining(c))
    return " ".join(t.upper().split())


def _match_client(folder: str, target: str) -> bool:
    nf, nt = _norm(folder), _norm(target)
    return nt in nf or nf in nt


async def _children(graph: MsGraphClient, site_id: str, drive_id: str, rel: str) -> list[dict]:
    enc = encode_graph_drive_path(rel.strip("/"))
    data = await graph.get_json(f"/sites/{site_id}/drives/{drive_id}/root:/{enc}:/children")
    return list(data.get("value") or [])


async def _download(graph: MsGraphClient, site_id: str, drive_id: str, rel: str) -> bytes:
    enc = encode_graph_drive_path(rel.strip("/"))
    return await graph.get_bytes(f"/sites/{site_id}/drives/{drive_id}/root:/{enc}:/content")


def _pick_latest_pdf(items: list[dict]) -> dict | None:
    pdfs = [
        it
        for it in items
        if str(it.get("name", "")).lower().endswith(".pdf") and "file" in it
    ]
    if not pdfs:
        return None
    pdfs.sort(
        key=lambda it: str(it.get("lastModifiedDateTime") or it.get("createdDateTime") or ""),
        reverse=True,
    )
    return pdfs[0]


async def inspect_credit(
    graph: MsGraphClient,
    site_id: str,
    drive_id: str,
    client_folder: str,
    credit_name: str,
    clients_base: str,
) -> dict:
    credit_rel = f"{clients_base}/{client_folder}/{credit_name}".replace("//", "/")
    children = await _children(graph, site_id, drive_id, credit_rel)
    names = [str(it.get("name") or "") for it in children]
    folders = {
        str(it.get("name") or ""): it
        for it in children
        if "folder" in it
    }
    files = [n for n in names if n and not any(c.get("name") == n and "folder" in c for c in children)]
    excel_only = [n for n in names if n.lower().endswith((".xlsx", ".xlsm", ".xls"))]

    out: dict = {
        "credito": credit_name,
        "extracto": None,
        "tabla": None,
        "error": None,
    }

    extract_folder = None
    for cand in ("EXTRACTOS", "Extractos", "EXTRACTO"):
        if cand in folders:
            extract_folder = cand
            break
    if extract_folder:
        ex_children = await _children(graph, site_id, drive_id, f"{credit_rel}/{extract_folder}")
        latest = _pick_latest_pdf(ex_children)
        if latest:
            pdf_rel = f"{credit_rel}/{extract_folder}/{latest['name']}"
            try:
                pdf_bytes = await _download(graph, site_id, drive_id, pdf_rel)
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
        table_name = find_best_amortization_table(excel_only or names, client_folder, credit_name)
        table_bytes = await _download(graph, site_id, drive_id, f"{credit_rel}/{table_name}")
        pending = _extract_pending_installment(table_bytes, client_folder)
        out["tabla"] = {
            "archivo": table_name,
            "cuota_pendiente": pending.get("cuota") or pending.get("total") or pending.get("ki"),
            "fecha_limite": (
                pending.get("fecha_limite").isoformat()
                if hasattr(pending.get("fecha_limite"), "isoformat")
                else pending.get("fecha_limite")
            ),
            "keys": sorted([str(k) for k in pending.keys()]),
            "raw_preview": {
                k: (v.isoformat() if hasattr(v, "isoformat") else v)
                for k, v in list(pending.items())[:12]
            },
        }
    except Exception as exc:
        out["tabla"] = {"error": f"{type(exc).__name__}: {exc}"}

    return out


async def main() -> None:
    clients_base = os.getenv("GRAPH_CLIENTS_BASE_PATH", "").strip().strip("/")
    graph = MsGraphClient()
    ctx = await resolve_sharepoint_from_env(graph)
    site_id = ctx["site_id"]
    drive_id = ctx["drive_id"]

    root_children = await _children(graph, site_id, drive_id, clients_base)
    folders = [
        str(it.get("name") or "")
        for it in root_children
        if "folder" in it and str(it.get("name") or "").strip()
    ]
    folders = [
        f
        for f in folders
        if not any(f.startswith(p) for p in EXCLUDED_PREFIXES)
        and "AUTOMATIZACION" not in _norm(f)
    ]

    report: list[dict] = []
    for target in TARGETS:
        matches = [f for f in folders if _match_client(f, target)]
        entry: dict = {"target": target, "matches": matches, "credits": []}
        if not matches:
            entry["error"] = "cliente_no_encontrado"
            report.append(entry)
            continue
        # Prefer exact-ish shortest match
        matches.sort(key=lambda x: (0 if _norm(x) == _norm(target) else 1, len(x)))
        client_folder = matches[0]
        entry["cliente_folder"] = client_folder
        try:
            credit_items = await _children(
                graph, site_id, drive_id, f"{clients_base}/{client_folder}"
            )
            credits = [
                str(it.get("name") or "")
                for it in credit_items
                if "folder" in it
                and str(it.get("name") or "").strip()
                and _norm(str(it.get("name") or ""))
                not in {"ASIENTOS CONTABLES", "EXTRACTOS", "DOCUMENTOS"}
            ]
            # Heurística: carpetas de crédito suelen contener CREDITO / # / dígitos
            credit_like = [
                c
                for c in credits
                if any(tok in _norm(c) for tok in ("CREDITO", "CRED", "#"))
                or any(ch.isdigit() for ch in c)
            ]
            if not credit_like:
                credit_like = credits
            for credit_name in sorted(credit_like)[:4]:
                detail = await inspect_credit(
                    graph, site_id, drive_id, client_folder, credit_name, clients_base
                )
                entry["credits"].append(detail)
        except Exception as exc:
            entry["error"] = f"{type(exc).__name__}: {exc}"
        report.append(entry)

    out_path = ROOT.parent / "inspeccion_clientes_prueba.json"
    out_path.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2, default=str))
    print(f"\nOK -> {out_path}", file=sys.stderr)


if __name__ == "__main__":
    asyncio.run(main())
