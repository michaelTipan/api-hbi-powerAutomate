# -*- coding: utf-8 -*-
"""RO: diagnosticar Maderpol crédito 248 en sandbox (Control + jobs + carpeta SP)."""
from __future__ import annotations

import asyncio
import base64
import json
import os
import re
import sys
from pathlib import Path
from urllib.parse import quote

import httpx
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
load_dotenv(Path(r"D:\CMC\HBI_Capital\api-hbi-powerAutomate.env"), override=False)
os.environ["UI_SHAREPOINT_SMOKE"] = "1"

from app.application.config.payment_validation_settings import (  # noqa: E402
    get_payment_validation_paths,
    list_payment_banks,
    resolve_bank_control_file_path,
)
from app.application.use_cases.payment_validation_process_control import (  # noqa: E402
    parse_process_control_row2,
)
from scripts.support.ui_appservice_graph_http import AppServiceGraphHttp  # noqa: E402

BASE = "https://app-hbiauto-prod-001-afawg2g7frgte8c5.eastus-01.azurewebsites.net"
OUT = ROOT / "scripts" / "_tmp" / "diag_maderpol_248_sandbox.json"
API_KEY = (os.getenv("API_HTTP_KEY") or "").strip()


def _cred_token(s: str) -> str:
    m = re.search(r"(\d{1,6})", str(s or ""))
    return m.group(1) if m else str(s or "").strip()


def _summarize_attempt(raw: str) -> dict:
    if not raw:
        return {"empty": True}
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return {"parse_error": True, "prefix": raw[:300]}
    issues = data.get("operational_issues") or []
    return {
        "attempt_id": data.get("attempt_id"),
        "outcome": data.get("outcome"),
        "user_message": data.get("user_message"),
        "next_action": data.get("next_action"),
        "issues_count": len(issues),
        "issues": [
            {
                "title": i.get("title"),
                "technical_reference": i.get("technical_reference"),
                "user_message": (i.get("user_message") or "")[:240],
                "credit": (i.get("location") or {}).get("credit"),
                "payment_id": (i.get("location") or {}).get("payment_id"),
            }
            for i in issues
            if isinstance(i, dict)
        ],
        "affected_payment_ids": data.get("affected_payment_ids"),
    }


def _summarize_result(result: dict) -> dict:
    items_248: list[dict] = []
    for it in result.get("items") or []:
        if not isinstance(it, dict):
            continue
        if _cred_token(str(it.get("credito") or "")) != "248" and "MADERPOL" not in str(
            it.get("cliente") or ""
        ).upper():
            continue
        items_248.append(
            {
                "id_pago": it.get("id_pago"),
                "credito": it.get("credito"),
                "cliente": it.get("cliente"),
                "application_status": it.get("application_status"),
                "error_code": it.get("error_code"),
                "apply_error_code": it.get("apply_error_code"),
                "advisory_code": it.get("advisory_code"),
                "tabla_amortizacion_path": it.get("tabla_amortizacion_path"),
                "warnings": it.get("warnings"),
            }
        )
    op_issues = result.get("operational_issues") or []
    return {
        "outcome": result.get("outcome"),
        "can_apply": result.get("can_apply"),
        "status": result.get("status"),
        "user_message": result.get("user_message"),
        "operational_issues_count": len(op_issues),
        "operational_issues_248": [
            {
                "title": i.get("title"),
                "technical_reference": i.get("technical_reference"),
                "credit": (i.get("location") or {}).get("credit"),
            }
            for i in op_issues
            if isinstance(i, dict)
            and (
                _cred_token(str((i.get("location") or {}).get("credit") or "")) == "248"
                or "248" in str(i.get("title") or "")
            )
        ],
        "items_248": items_248,
    }


async def _children(http: AppServiceGraphHttp, drive: str, fid: str = "root"):
    r = await http._client.get(
        f"{BASE}/graph/sharepoint/drives/{quote(drive, safe='')}/children",
        params={"folder_item_id": fid},
    )
    r.raise_for_status()
    return list((r.json() or {}).get("value") or [])


async def _walk(http: AppServiceGraphHttp, drive: str, parts: list[str]) -> str:
    cur = "root"
    for i, p in enumerate(parts):
        kids = await _children(http, drive, cur)
        hit = next((x for x in kids if x.get("name") == p), None)
        if not hit:
            raise FileNotFoundError("/".join(parts[: i + 1]))
        cur = str(hit["id"])
    return cur


async def _download_by_path(http: AppServiceGraphHttp, drive: str, rel_path: str) -> bytes:
    parts = [p for p in rel_path.strip("/").split("/") if p]
    name = parts[-1]
    folder_id = await _walk(http, drive, parts[:-1]) if len(parts) > 1 else "root"
    kids = await _children(http, drive, folder_id)
    hit = next((x for x in kids if x.get("name") == name), None)
    if not hit:
        raise FileNotFoundError(rel_path)
    r = await http._client.get(
        f"{BASE}/graph/sharepoint/drives/{quote(drive, safe='')}/item-content",
        params={"item_id": str(hit["id"])},
    )
    r.raise_for_status()
    return base64.b64decode(r.json()["content_base64"])


async def main() -> None:
    report: dict = {"health": None, "controls": [], "jobs_248": []}
    report["health"] = httpx.get(f"{BASE}/health", timeout=60).json()
    http = AppServiceGraphHttp(base_url=BASE, api_key=API_KEY, timeout=180.0)
    try:
        diag = await http._client.get(f"{BASE}/graph/diagnostics")
        diag.raise_for_status()
        drive = str(((diag.json() or {}).get("operations_site") or {}).get("drive_id") or "")
        if not drive:
            raise RuntimeError("no operations drive_id")

        for bank in list_payment_banks():
            cpath = resolve_bank_control_file_path(bank.bank_code)
            entry: dict = {"bank_code": bank.bank_code, "control_path": cpath}
            try:
                raw = await _download_by_path(http, drive, cpath)
                snap = parse_process_control_row2(raw, control_file_path=cpath)
                entry.update(
                    {
                        "estado": snap.estado_proceso,
                        "is_active": snap.is_active,
                        "process_key": snap.process_key,
                        "historical_file_path": snap.historical_file_path,
                        "last_amortization_attempt": _summarize_attempt(
                            snap.last_amortization_attempt_json
                        ),
                    }
                )
            except Exception as exc:
                entry["error"] = str(exc)
            report["controls"].append(entry)

        paths = get_payment_validation_paths()
        logs_root = paths.logs
        parts = [p for p in logs_root.strip("/").split("/") if p]
        folder_id = await _walk(http, drive, parts)
        log_folders = await _children(http, drive, folder_id)
        for lf in sorted(
            log_folders, key=lambda x: x.get("lastModifiedDateTime") or "", reverse=True
        )[:30]:
            fname = str(lf.get("name") or "")
            if not fname.lower().endswith(".json"):
                continue
            try:
                r = await http._client.get(
                    f"{BASE}/graph/sharepoint/drives/{quote(drive, safe='')}/item-content",
                    params={"item_id": str(lf["id"])},
                )
                r.raise_for_status()
                blob = base64.b64decode(r.json()["content_base64"]).decode(
                    "utf-8", errors="replace"
                )
                if "248" not in blob and "MADERPOL" not in blob.upper():
                    continue
                job = json.loads(blob)
                jtype = str(job.get("type") or job.get("job_type") or "")
                if "amort" not in jtype.lower():
                    continue
                result = job.get("result") if isinstance(job.get("result"), dict) else {}
                report["jobs_248"].append(
                    {
                        "log_file": fname,
                        "job_id": job.get("job_id"),
                        "type": jtype,
                        "status": job.get("status"),
                        "modified": lf.get("lastModifiedDateTime"),
                        "result_summary": _summarize_result(result),
                    }
                )
            except Exception:
                continue

        clients_base = os.getenv("GRAPH_CLIENTS_BASE_PATH", "").strip("/")
        base_parts = [p for p in clients_base.split("/") if p]
        folder_id = await _walk(http, drive, base_parts)
        kids = await _children(http, drive, folder_id)
        client = next(
            (k for k in kids if "MADERPOL" in str(k.get("name") or "").upper()),
            None,
        )
        if client:
            cred_folders = await _children(http, drive, str(client["id"]))
            cred248 = next(
                (c for c in cred_folders if "248" in str(c.get("name") or "")),
                None,
            )
            if cred248:
                files = await _children(http, drive, str(cred248["id"]))
                report["maderpol_248_files"] = {
                    "client": client.get("name"),
                    "credit_folder": cred248.get("name"),
                    "files": sorted(str(f.get("name") or "") for f in files),
                }
            else:
                report["maderpol_client"] = {
                    "name": client.get("name"),
                    "credit_folders": [c.get("name") for c in cred_folders],
                }
    finally:
        await http.aclose()

    OUT.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(report, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    asyncio.run(main())
