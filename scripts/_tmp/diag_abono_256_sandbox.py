# -*- coding: utf-8 -*-
"""RO: diagnosticar Abono crédito 256 en sandbox (Control + LastAmortizationAttemptJson)."""
from __future__ import annotations

import asyncio
import base64
import json
import os
import re
import sys
from pathlib import Path
from urllib.parse import quote

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
load_dotenv(Path(r"D:\CMC\HBI_Capital\api-hbi-powerAutomate.env"), override=False)
os.environ["UI_SHAREPOINT_SMOKE"] = "1"

from app.application.config.payment_validation_settings import (  # noqa: E402
    list_payment_banks,
    resolve_bank_control_file_path,
    get_payment_validation_paths,
)
from app.application.use_cases.payment_validation_process_control import (  # noqa: E402
    parse_process_control_row2,
)
from scripts.support.ui_appservice_graph_http import AppServiceGraphHttp  # noqa: E402

BASE = "https://app-hbiauto-prod-001-afawg2g7frgte8c5.eastus-01.azurewebsites.net"
OUT = ROOT / "scripts" / "_tmp" / "diag_abono_256_sandbox.json"
API_KEY = (os.getenv("API_HTTP_KEY") or "").strip()


async def children(http: AppServiceGraphHttp, drive: str, fid: str = "root"):
    r = await http._client.get(
        f"{BASE}/graph/sharepoint/drives/{quote(drive, safe='')}/children",
        params={"folder_item_id": fid},
    )
    r.raise_for_status()
    return list((r.json() or {}).get("value") or [])


async def walk(http: AppServiceGraphHttp, drive: str, parts: list[str]):
    cur = "root"
    for i, p in enumerate(parts):
        kids = await children(http, drive, cur)
        hit = next((i for i in kids if i.get("name") == p), None)
        if not hit:
            raise FileNotFoundError("/".join(parts[: i + 1]))
        cur = str(hit["id"])
    return cur


async def download_by_path(http: AppServiceGraphHttp, drive: str, rel_path: str) -> bytes:
    parts = [p for p in rel_path.strip("/").split("/") if p]
    name = parts[-1]
    folder_id = await walk(http, drive, parts[:-1]) if len(parts) > 1 else "root"
    kids = await children(http, drive, folder_id)
    hit = next((i for i in kids if i.get("name") == name), None)
    if not hit:
        raise FileNotFoundError(rel_path)
    r = await http._client.get(
        f"{BASE}/graph/sharepoint/drives/{quote(drive, safe='')}/item-content",
        params={"item_id": str(hit["id"])},
    )
    r.raise_for_status()
    return base64.b64decode(r.json()["content_base64"])


def _cred_token(s: str) -> str:
    m = re.search(r"(\d{1,6})", str(s or ""))
    return m.group(1) if m else str(s or "").strip()


def _summarize_amort_attempt(raw: str) -> dict:
    if not raw:
        return {"empty": True}
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return {"parse_error": True, "prefix": raw[:200]}
    out: dict = {
        "top_keys": sorted(data.keys()) if isinstance(data, dict) else [],
        "outcome": data.get("outcome"),
        "can_apply": data.get("can_apply"),
        "error_code": data.get("error_code"),
        "user_message": data.get("user_message"),
        "status": data.get("status"),
    }
    issues = data.get("operational_issues") or []
    out["operational_issues"] = [
        {
            "title": i.get("title"),
            "technical_reference": i.get("technical_reference"),
            "user_message": i.get("user_message"),
            "next_action": i.get("next_action"),
            "credit": (i.get("location") or {}).get("credit"),
            "payment_id": (i.get("location") or {}).get("payment_id"),
        }
        for i in issues
        if isinstance(i, dict)
    ]
    blocking = data.get("blocking_abono_groups") or []
    out["blocking_abono_groups"] = []
    for g in blocking:
        if not isinstance(g, dict):
            continue
        creds = [str(c) for c in (g.get("creditos_seleccionados") or [])]
        out["blocking_abono_groups"].append(
            {
                "id_pago": g.get("id_pago"),
                "creditos": creds,
                "reconciliation_status": g.get("reconciliation_status"),
                "schedule_resolution_status": g.get("schedule_resolution_status"),
                "blocking_errors": g.get("blocking_errors"),
                "mentions_256": any(_cred_token(c) == "256" for c in creds),
            }
        )
    # abono_group_results (richer)
    agr = data.get("abono_group_results") or []
    out["abono_group_results_256"] = []
    for g in agr:
        if not isinstance(g, dict):
            continue
        creds = [str(c) for c in (g.get("creditos_seleccionados") or [])]
        if not any(_cred_token(c) == "256" for c in creds):
            continue
        out["abono_group_results_256"].append(
            {
                "id_pago": g.get("id_pago"),
                "creditos": creds,
                "reconciliation_status": g.get("reconciliation_status"),
                "schedule_resolution_status": g.get("schedule_resolution_status"),
                "group_ready_for_apply": g.get("group_ready_for_apply"),
                "monto_banco": g.get("monto_banco"),
                "total_asientos": g.get("total_asientos"),
                "diferencia": g.get("diferencia"),
                "blocking_errors": g.get("blocking_errors"),
                "warnings": g.get("warnings"),
            }
        )
    # items mentioning 256
    items_256 = []
    for it in data.get("items") or []:
        if not isinstance(it, dict):
            continue
        if _cred_token(str(it.get("credito") or "")) != "256" and "256" not in str(
            it.get("cliente") or ""
        ):
            continue
        items_256.append(
            {
                "id_pago": it.get("id_pago"),
                "credito": it.get("credito"),
                "tipo": it.get("tipo_aplicacion_canonica") or it.get("tipo_aplicacion"),
                "application_status": it.get("application_status"),
                "error_code": it.get("error_code"),
                "advisory_code": it.get("advisory_code"),
                "warnings": it.get("warnings"),
            }
        )
    out["items_256"] = items_256
    return out


async def main():
    report: dict = {"controls": [], "notes": []}
    http = AppServiceGraphHttp(base_url=BASE, api_key=API_KEY, timeout=180.0)
    try:
        # drive id via diagnostics (same as other smoke scripts)
        diag = await http._client.get(f"{BASE}/graph/diagnostics")
        diag.raise_for_status()
        drive = str(((diag.json() or {}).get("operations_site") or {}).get("drive_id") or "")
        if not drive:
            raise RuntimeError("no operations drive_id")

        paths = get_payment_validation_paths()
        report["paths"] = {
            "control": paths.control,
            "logs": paths.logs,
            "historical": paths.historical,
        }

        for bank in list_payment_banks():
            cpath = resolve_bank_control_file_path(bank.bank_code)
            entry: dict = {"bank_code": bank.bank_code, "control_path": cpath}
            try:
                raw = await download_by_path(http, drive, cpath)
                snap = parse_process_control_row2(raw, control_file_path=cpath)
                entry.update(
                    {
                        "estado": snap.estado_proceso,
                        "is_active": snap.is_active,
                        "process_key": snap.process_key,
                        "process_id": snap.process_id,
                        "merge_manifest_path": snap.merge_manifest_path,
                        "historical_file_path": snap.historical_file_path,
                        "last_completed_step": snap.last_completed_step,
                        "execution_id": snap.execution_id,
                        "last_amort_len": len(snap.last_amortization_attempt_json or ""),
                    }
                )
                entry["last_amortization_attempt"] = _summarize_amort_attempt(
                    snap.last_amortization_attempt_json or ""
                )
            except Exception as exc:
                entry["error"] = f"{type(exc).__name__}: {exc}"
            report["controls"].append(entry)

        # Also try to pull job result if process has amort issues on panel — via
        # listing dated logs for amortization apply/dry-run dumps if any.
        try:
            logs_parts = [p for p in paths.logs.strip("/").split("/") if p]
            logs_id = await walk(http, drive, logs_parts)
            kids = await children(http, drive, logs_id)
            # dated layout: years
            years = [k for k in kids if "folder" in k and str(k.get("name")).isdigit()]
            recent_json = []
            for y in sorted(years, key=lambda x: x.get("name") or "", reverse=True)[:2]:
                months = await children(http, drive, str(y["id"]))
                for m in sorted(months, key=lambda x: x.get("name") or "", reverse=True)[:3]:
                    if "folder" not in m:
                        continue
                    days = await children(http, drive, str(m["id"]))
                    for d in sorted(days, key=lambda x: x.get("name") or "", reverse=True)[:5]:
                        if "folder" not in d:
                            continue
                        files = await children(http, drive, str(d["id"]))
                        for f in files:
                            name = str(f.get("name") or "")
                            if not name.lower().endswith(".json"):
                                continue
                            if "amort" in name.lower() or "merge_manifest" in name.lower():
                                recent_json.append(
                                    {
                                        "path": f"{y['name']}/{m['name']}/{d['name']}/{name}",
                                        "size": f.get("size"),
                                        "lastModified": f.get("lastModifiedDateTime"),
                                    }
                                )
            report["recent_log_json"] = recent_json[:30]
        except Exception as exc:
            report["notes"].append(f"logs walk: {type(exc).__name__}: {exc}")

    finally:
        await http.aclose()

    OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"WROTE {OUT}")
    for c in report["controls"]:
        print(
            f"BANK={c.get('bank_code')} estado={c.get('estado')} active={c.get('is_active')} "
            f"amort_len={c.get('last_amort_len')} err={c.get('error')}"
        )
        la = c.get("last_amortization_attempt") or {}
        print(
            f"  outcome={la.get('outcome')} can_apply={la.get('can_apply')} "
            f"issues={len(la.get('operational_issues') or [])} "
            f"blocking={len(la.get('blocking_abono_groups') or [])}"
        )
        for g in la.get("blocking_abono_groups") or []:
            if g.get("mentions_256") or True:
                print(
                    f"  BLOCK id={g.get('id_pago')} creds={g.get('creditos')} "
                    f"recon={g.get('reconciliation_status')} errs={g.get('blocking_errors')}"
                )


if __name__ == "__main__":
    asyncio.run(main())
