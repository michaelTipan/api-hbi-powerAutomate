# -*- coding: utf-8 -*-
"""RO: riesgo top-5 createdDateTime vs regla actual max(fecha_limite).

Fase 1: inventario metadata (sin descargar PDF).
Fase 2: parse PDF solo créditos con pool>=3 del lote primario/secundario,
         y todos con pool>5 (donde top-5 podría cortar).
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import os
import re
import sys
import unicodedata
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import quote

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
load_dotenv(Path(r"D:\CMC\HBI_Capital\api-hbi-powerAutomate.env"), override=False)
os.environ["UI_SHAREPOINT_SMOKE"] = "1"

from app.application.services.colombia_time import parse_graph_datetime  # noqa: E402
from app.application.services.extract_selection import (  # noqa: E402
    choose_extract_as_of_bank_date,
    unreadable_pdf_reason,
)
from app.application.services.payment_helpers import (  # noqa: E402
    extract_fecha_limite_pago_from_pdf,
)
from scripts.support.ui_appservice_graph_http import AppServiceGraphHttp  # noqa: E402

BASE = "https://app-hbiauto-prod-001-afawg2g7frgte8c5.eastus-01.azurewebsites.net"
API = (os.getenv("API_HTTP_KEY") or "").strip()
CLIENTS_BASE = "INFORMACION CREDITOS-CLIENTES"
OUT = ROOT / "scripts" / "_tmp" / "audit_extract_top5_created_risk_20260825.json"
BANK_DATE = date(2026, 8, 25)

PRIMARY = [
    "SERGIO EDUARDO GOMEZ",
    "INGEROZCOL",
    "OBRAS CIVILES DE OCCIDENTE",
    "MADERPOL",
    "ICOEQUIPOS",
    "A&M CONSTRUCOL",
    "VICTOR JULIO SOTO",
    "SERVIPETROLEOS",
]
SECONDARY = [
    "A CONSTRUIR",
    "ACIMOR",
    "AGRECAR",
    "CALABRESA",
    "COLMATIC",
    "EQUINORTE",
    "GEOEXCON",
    "INDUCAB",
    "INVERSIONES Y PROYECTOS MIOS",
    "JORGE SANTAMARIA",
    "MINCIVIL",
    "PAVIMENTOS LA ROCA",
    "RENTAL EP",
]
EXTRA = ["CONSTRUMAQUINAS", "G&J INGENIERIA", "SERVI AMBIENTALES", "INVERSIONES TORRES"]

_CREDITO_RE = re.compile(r"(?i)^CREDITO")
_EXTRACT_RE = re.compile(r"(?i)extracto")
SKIP_TOP = {
    "00 CARGA TRANSACCIONES BANCO",
    "01 VALIDACION PAGOS",
    "02 VALIDACION PAGOS",
    "03 COMWARE PRUEBAS- INFORMACION CREDITOS CLIENTES",
}


def log(msg: str) -> None:
    print(msg, flush=True)


def _norm(s: str) -> str:
    t = unicodedata.normalize("NFKD", s or "")
    t = "".join(c for c in t if not unicodedata.combining(c))
    return " ".join(t.upper().split())


def _match(folder: str, needles: list[str]) -> str | None:
    fn = _norm(folder)
    for n in needles:
        nn = _norm(n)
        if nn in fn or fn.startswith(nn) or nn.startswith(fn):
            return n
        toks = [t for t in nn.split() if len(t) > 2]
        if len(toks) >= 2 and all(t in fn for t in toks[:2]):
            return n
        if len(toks) == 1 and toks[0] in fn:
            return n
    return None


def _created(item: dict) -> str:
    fsi = item.get("fileSystemInfo") if isinstance(item.get("fileSystemInfo"), dict) else {}
    return str(item.get("createdDateTime") or fsi.get("createdDateTime") or "").strip()


def _modified(item: dict) -> str:
    fsi = item.get("fileSystemInfo") if isinstance(item.get("fileSystemInfo"), dict) else {}
    return str(item.get("lastModifiedDateTime") or fsi.get("lastModifiedDateTime") or "").strip()


def _created_utc(item: dict) -> datetime:
    dt = parse_graph_datetime(_created(item))
    return (dt or datetime.min.replace(tzinfo=timezone.utc)).astimezone(timezone.utc)


def _is_extract(item: dict) -> bool:
    if "folder" in item:
        return False
    name = str(item.get("name") or "")
    return name.lower().endswith(".pdf") and bool(_EXTRACT_RE.search(name))


async def children(http, drive, fid="root"):
    r = await http._client.get(
        f"{BASE}/graph/sharepoint/drives/{quote(drive, safe='')}/children",
        params={"folder_item_id": fid},
    )
    r.raise_for_status()
    return list((r.json() or {}).get("value") or [])


async def walk(http, drive, parts):
    cur = "root"
    for p in parts:
        hit = next((x for x in await children(http, drive, cur) if x.get("name") == p), None)
        if not hit:
            raise FileNotFoundError(p)
        cur = str(hit["id"])
    return cur


async def download_id(http, drive, item_id: str) -> bytes:
    import base64

    r = await http._client.get(
        f"{BASE}/graph/sharepoint/drives/{quote(drive, safe='')}/item-content",
        params={"item_id": item_id},
    )
    r.raise_for_status()
    return base64.b64decode(r.json()["content_base64"])


def cand(item, parent, source):
    name = str(item.get("name") or "")
    return {
        "item": item,
        "name": name,
        "id": item.get("id"),
        "relative_path": f"{parent.rstrip('/')}/{name}".replace("//", "/"),
        "source_location": source,
        "createdDateTime": _created(item),
        "lastModifiedDateTime": _modified(item),
        "size": item.get("size"),
    }


async def build_pool(http, drive, credit_path, items):
    pool = []
    for it in items:
        if _is_extract(it):
            pool.append(cand(it, credit_path, "credit_root"))
    ex = next(
        (x for x in items if "folder" in x and str(x.get("name") or "").casefold() == "extractos"),
        None,
    )
    if ex:
        kids = await children(http, drive, str(ex["id"]))
        ex_path = f"{credit_path}/{ex['name']}".replace("//", "/")
        for it in kids:
            if _is_extract(it):
                pool.append(cand(it, ex_path, "extractos_folder"))
    return pool


async def parse_pool(http, drive, pool_ordered):
    scored = []
    damaged = []
    for c in pool_ordered:
        try:
            raw = await download_id(http, drive, str(c["id"]))
        except Exception as ex:
            damaged.append({"name": c["name"], "reason": f"dl:{type(ex).__name__}", "created": c["createdDateTime"]})
            continue
        fe = await asyncio.to_thread(extract_fecha_limite_pago_from_pdf, raw)
        if fe is None:
            damaged.append(
                {
                    "name": c["name"],
                    "reason": unreadable_pdf_reason(raw),
                    "created": c["createdDateTime"],
                }
            )
            continue
        scored.append((c, fe, raw, hashlib.sha256(raw).hexdigest()))
    return scored, damaged


def mrow(c, fe=None):
    return {
        "name": c.get("name") if c else None,
        "source": c.get("source_location") if c else None,
        "createdDateTime": c.get("createdDateTime") if c else None,
        "lastModifiedDateTime": c.get("lastModifiedDateTime") if c else None,
        "size": c.get("size") if c else None,
        "fecha_limite": fe.isoformat() if fe else None,
    }


async def main():
    if not API:
        raise RuntimeError("missing API key")
    needles = PRIMARY + SECONDARY + EXTRA
    http = AppServiceGraphHttp(base_url=BASE, api_key=API, timeout=180.0)
    report: dict[str, Any] = {
        "mode": "read_only",
        "rule_today": "max(fecha_limite) full pool; createdDateTime only tiebreak",
        "proposal_A": "top5 by created then max(fecha_limite)",
        "proposal_B": "newest created only (= what user described as 'el mas reciente de esos 5')",
    }
    try:
        diag = await http._client.get(f"{BASE}/graph/diagnostics")
        diag.raise_for_status()
        drive = str(((diag.json() or {}).get("operations_site") or {}).get("drive_id") or "")
        hj = (await http._client.get(f"{BASE}/health")).json()
        report["health"] = {"build": hj.get("build_id") or hj.get("build"), "env": hj.get("environment")}
        log(f"health={report['health']}")

        root = await walk(http, drive, CLIENTS_BASE.split("/"))
        top = await children(http, drive, root)
        folders = [it for it in top if "folder" in it and str(it.get("name")) not in SKIP_TOP]
        matched = []
        for it in folders:
            name = str(it.get("name") or "")
            hit = _match(name, needles)
            if hit:
                matched.append((hit, it, name))
        report["matched_clients"] = [{"needle": n, "folder": f} for n, _, f in matched]
        log(f"matched_clients={len(matched)}")

        # Phase 1 metadata inventory
        inventory = []
        for needle, fit, fname in matched:
            kids = await children(http, drive, str(fit["id"]))
            credits = [c for c in kids if "folder" in c and _CREDITO_RE.search(str(c.get("name") or ""))]
            for cred in sorted(credits, key=lambda x: str(x.get("name") or ""))[:12]:
                cname = str(cred.get("name") or "")
                cpath = f"{CLIENTS_BASE}/{fname}/{cname}"
                citems = await children(http, drive, str(cred["id"]))
                pool = await build_pool(http, drive, cpath, citems)
                if not pool:
                    continue
                by_c = sorted(pool, key=lambda c: _created_utc(c["item"]), reverse=True)
                inventory.append(
                    {
                        "needle": needle,
                        "client": fname,
                        "credit": cname,
                        "credit_path": cpath,
                        "credit_id": cred["id"],
                        "pool_count": len(pool),
                        "by_created": [mrow(c) for c in by_c],
                        "pool": by_c,  # keep for phase 2 (in-memory only; strip before write)
                        "priority": needle in PRIMARY,
                    }
                )
        log(f"credits_with_extracts={len(inventory)}")
        report["phase1_pool_stats"] = {
            "credits": len(inventory),
            "pool_eq_1": sum(1 for i in inventory if i["pool_count"] == 1),
            "pool_2_to_5": sum(1 for i in inventory if 2 <= i["pool_count"] <= 5),
            "pool_gt_5": sum(1 for i in inventory if i["pool_count"] > 5),
            "max_pool": max((i["pool_count"] for i in inventory), default=0),
            "gt5_list": [
                {"client": i["client"], "credit": i["credit"], "pool": i["pool_count"]}
                for i in inventory
                if i["pool_count"] > 5
            ],
        }
        log(json.dumps(report["phase1_pool_stats"], ensure_ascii=False))

        # Phase 2: parse risky / primary
        to_parse = []
        for i in inventory:
            if i["pool_count"] > 5:
                to_parse.append(i)
            elif i["priority"] and i["pool_count"] >= 1:
                to_parse.append(i)
            elif i["needle"] in SECONDARY and i["pool_count"] >= 3:
                to_parse.append(i)
            elif i["needle"] in EXTRA and i["pool_count"] >= 2:
                to_parse.append(i)
        # Cap to keep runtime reasonable
        to_parse = to_parse[:40]
        log(f"phase2_parse_credits={len(to_parse)}")

        analyses = []
        for idx, i in enumerate(to_parse, 1):
            pool = i["pool"]
            by_c = pool
            top5 = by_c[:5]
            newest = by_c[:1]
            log(f"[{idx}/{len(to_parse)}] parse {i['client']}/{i['credit']} pool={len(pool)}")
            scored, damaged = await parse_pool(http, drive, by_c)
            out_all = choose_extract_as_of_bank_date(scored, BANK_DATE)
            top5_ids = {str(c["id"]) for c in top5}
            scored_t5 = [t for t in scored if str(t[0]["id"]) in top5_ids]
            out_t5 = choose_extract_as_of_bank_date(scored_t5, BANK_DATE) if scored_t5 else None
            scored_n = [t for t in scored if newest and str(t[0]["id"]) == str(newest[0]["id"])]
            out_n = choose_extract_as_of_bank_date(scored_n, BANK_DATE) if scored_n else None

            w_all = out_all.candidate
            w_t5 = out_t5.candidate if out_t5 else None
            w_n = out_n.candidate if out_n else None
            rank = None
            if w_all:
                for rnk, c in enumerate(by_c, 1):
                    if str(c["id"]) == str(w_all["id"]):
                        rank = rnk
                        break
            fe_map = {str(t[0]["id"]): t[1] for t in scored}
            mismatch_a = bool(w_all) and (
                not w_t5 or str(w_all["id"]) != str(w_t5["id"])
            )
            mismatch_b = bool(w_all) and (
                not w_n or str(w_all["id"]) != str(w_n["id"])
            )
            analyses.append(
                {
                    "client": i["client"],
                    "credit": i["credit"],
                    "needle": i["needle"],
                    "pool_count": len(pool),
                    "parsed": len(scored),
                    "damaged": damaged,
                    "inventory": [mrow(c, fe_map.get(str(c["id"]))) for c in by_c],
                    "current": {
                        "reason": out_all.selection_reason,
                        "error": out_all.error_code,
                        "winner": mrow(w_all, out_all.fecha_limite) if w_all else None,
                    },
                    "proposal_A": {
                        "error": out_t5.error_code if out_t5 else "no_scored_in_top5",
                        "winner": mrow(w_t5, out_t5.fecha_limite) if w_t5 and out_t5 else None,
                        "mismatch": mismatch_a,
                    },
                    "proposal_B": {
                        "error": out_n.error_code if out_n else "newest_unreadable",
                        "winner": mrow(w_n, out_n.fecha_limite) if w_n and out_n else None,
                        "mismatch": mismatch_b,
                    },
                    "winner_created_rank": rank,
                    "winner_outside_top5": bool(w_all) and rank is not None and rank > 5,
                }
            )

        mism_a = [a for a in analyses if a["proposal_A"]["mismatch"]]
        mism_b = [a for a in analyses if a["proposal_B"]["mismatch"]]
        outside = [a for a in analyses if a["winner_outside_top5"]]

        report["phase1_inventory"] = [
            {
                "needle": i["needle"],
                "client": i["client"],
                "credit": i["credit"],
                "pool_count": i["pool_count"],
                "by_created": i["by_created"],
            }
            for i in inventory
        ]
        report["phase2_analyses"] = analyses
        report["summary"] = {
            "credits_inventoried": len(inventory),
            "credits_parsed": len(analyses),
            "pool_gt_5": report["phase1_pool_stats"]["pool_gt_5"],
            "proposal_A_mismatches": len(mism_a),
            "proposal_B_mismatches": len(mism_b),
            "winner_outside_top5": len(outside),
            "cases_A": [
                {
                    "client": a["client"],
                    "credit": a["credit"],
                    "pool": a["pool_count"],
                    "rank": a["winner_created_rank"],
                    "current": a["current"]["winner"],
                    "top5": a["proposal_A"]["winner"],
                }
                for a in mism_a
            ],
            "cases_B_sample": [
                {
                    "client": a["client"],
                    "credit": a["credit"],
                    "pool": a["pool_count"],
                    "rank": a["winner_created_rank"],
                    "current": a["current"]["winner"],
                    "newest": a["proposal_B"]["winner"],
                }
                for a in mism_b[:25]
            ],
            "cases_outside_top5": [
                {
                    "client": a["client"],
                    "credit": a["credit"],
                    "pool": a["pool_count"],
                    "rank": a["winner_created_rank"],
                    "current": a["current"]["winner"],
                }
                for a in outside
            ],
        }
        log(json.dumps(report["summary"], ensure_ascii=False, indent=2))
    finally:
        await http.aclose()

    OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    log(f"WROTE {OUT}")


if __name__ == "__main__":
    asyncio.run(main())
