# -*- coding: utf-8 -*-
"""Validación producción sandbox: endpoints + flujo completo + amort/IBR."""
from __future__ import annotations

import json
import time
from io import BytesIO
from pathlib import Path

import httpx
from openpyxl import load_workbook

from app.application.services.colombia_time import today_colombia_iso

BASE = "https://app-hbiauto-prod-001-afawg2g7frgte8c5.eastus-01.azurewebsites.net"
WORK = Path(r"D:\CMC\HBI_Capital\_work\prod_validation")
WORK.mkdir(parents=True, exist_ok=True)
ASIENTOS = Path(r"D:\CMC\HBI_Capital\asientos_prueba\generados")

RESULTS: dict = {"endpoints": [], "flow": [], "issues": []}


def save(name: str, data: object) -> None:
    (WORK / name).write_text(
        json.dumps(data, ensure_ascii=False, indent=2, default=str), encoding="utf-8"
    )


def poll(c: httpx.Client, url: str, *, label: str, rounds: int = 90) -> dict:
    for i in range(rounds):
        b = c.get(url, timeout=120).json()
        st = b.get("status")
        res = b.get("result") or {}
        print(f"  [{label}] {i}: job={st} result={res.get('status')} err={res.get('error_code')} already={res.get('already_applied') or res.get('already_merged') or res.get('already_generated') or res.get('already_notified')}")
        if st in ("completed", "failed"):
            return b
        time.sleep(8)
    raise TimeoutError(label)


def check_get(c: httpx.Client, path: str, *, ok_codes=(200,)) -> None:
    r = c.get(f"{BASE}{path}", timeout=90)
    entry = {"method": "GET", "path": path, "status": r.status_code}
    try:
        entry["body_keys"] = list((r.json() if r.headers.get("content-type", "").startswith("application/json") else {}).keys())[:20] if r.status_code < 500 else []
    except Exception:
        entry["body_keys"] = []
    RESULTS["endpoints"].append(entry)
    print(f"GET {path} -> {r.status_code}")
    if r.status_code not in ok_codes:
        RESULTS["issues"].append(f"GET {path} returned {r.status_code}")


def main() -> None:
    with httpx.Client(timeout=180) as c:
        # --- Smoke endpoints ---
        check_get(c, "/health")
        check_get(c, "/graph/diagnostics")
        check_get(c, "/openapi.json")
        check_get(c, "/graph/sharepoint/resolve-env")
        check_get(c, "/graph/sharepoint/sites-search")

        # OpenAPI path inventory
        oa = c.get(f"{BASE}/openapi.json", timeout=90).json()
        paths = sorted(oa.get("paths") or {})
        save("openapi_paths.json", paths)
        RESULTS["openapi_path_count"] = len(paths)

        # Setup workbooks (idempotent)
        for path, label in [
            ("/graph/sharepoint/payment-validation/setup/merge-control-workbook", "setup_control"),
            ("/graph/sharepoint/payment-validation/setup/payment-followup-workbooks", "setup_followup"),
            ("/graph/sharepoint/payment-validation/setup/ibr-workbook", "setup_ibr"),
        ]:
            r = c.post(f"{BASE}{path}", json={})
            RESULTS["endpoints"].append({"method": "POST", "path": path, "status": r.status_code})
            print(label, r.status_code)
            save(f"{label}.json", r.json() if r.content else {})
            if r.status_code not in (200, 201):
                RESULTS["issues"].append(f"{label} -> {r.status_code}")

        # Ensure IBR has a broad rate covering extract dates
        # Download IBR via resolve + diagnostics is hard; use ensure via dry-run later.

        # Reset control: if AMORTIZACION_APLICADA with 0 real writes, set CONSOLIDADO
        # We do this by calling apply after deploy (should ERROR_APPLY) then manually
        # updating via a small job — for now queue dry-run/apply and record.

        # Merge idempotent
        r = c.post(f"{BASE}/graph/sharepoint/merge-composite-validado-pdfs", json={"bank_code": "banco_bogota"})
        RESULTS["endpoints"].append({"method": "POST", "path": "/graph/sharepoint/merge-composite-validado-pdfs", "status": r.status_code})
        print("merge queue", r.status_code, r.json())
        if r.status_code == 202:
            m = poll(c, f"{BASE}/graph/sharepoint/merge-composite-validado-pdfs/jobs/{r.json()['job_id']}", label="merge")
            save("merge_result.json", m)
            RESULTS["flow"].append({"step": "merge", "status": (m.get("result") or {}).get("status"), "already": (m.get("result") or {}).get("already_merged")})

        # Dry-run
        r = c.post(f"{BASE}/graph/sharepoint/payment-validation/amortization/dry-run/queue", json={"bank_code": "banco_bogota"})
        print("dry queue", r.status_code, r.json())
        if r.status_code == 202:
            d = poll(c, f"{BASE}/graph/sharepoint/payment-validation/jobs/{r.json()['job_id']}", label="dry")
            save("amort_dry.json", d)
            res = d.get("result") or {}
            RESULTS["flow"].append({
                "step": "amort_dry",
                "status": res.get("status"),
                "can_apply": res.get("can_apply"),
                "summary": res.get("summary"),
                "ibr_pending": (res.get("summary") or {}).get("pending_ibr"),
                "errors": (res.get("summary") or {}).get("errors"),
            })
            items = res.get("items") or []
            err_codes = {}
            ibr_st = {}
            for it in items:
                e = it.get("error_code") or "-"
                err_codes[e] = err_codes.get(e, 0) + 1
                ib = (it.get("ibr") or {}).get("status") or "-"
                ibr_st[ib] = ibr_st.get(ib, 0) + 1
            RESULTS["flow"][-1]["error_codes"] = err_codes
            RESULTS["flow"][-1]["ibr_statuses"] = ibr_st

        # Apply
        r = c.post(f"{BASE}/graph/sharepoint/payment-validation/amortization/apply/queue", json={"bank_code": "banco_bogota"})
        print("apply queue", r.status_code, r.json())
        if r.status_code == 202:
            a = poll(c, f"{BASE}/graph/sharepoint/payment-validation/jobs/{r.json()['job_id']}", label="apply")
            save("amort_apply.json", a)
            res = a.get("result") or {}
            RESULTS["flow"].append({
                "step": "amort_apply",
                "status": res.get("status"),
                "already_applied": res.get("already_applied"),
                "tables_uploaded_count": res.get("tables_uploaded_count"),
                "apply_wrote_changes": res.get("apply_wrote_changes"),
                "process_control_estado": res.get("process_control_estado"),
                "error_code": res.get("error_code") or res.get("preflight_error_code"),
                "user_message": res.get("user_message"),
            })
            if res.get("status") == "ok" and int(res.get("tables_uploaded_count") or 0) == 0 and not res.get("already_applied"):
                RESULTS["issues"].append("Apply ok with 0 tables (should be ERROR_APPLY after fix)")

        # Apply retry (idempotency / error retry)
        r = c.post(f"{BASE}/graph/sharepoint/payment-validation/amortization/apply/queue", json={"bank_code": "banco_bogota"})
        if r.status_code == 202:
            a2 = poll(c, f"{BASE}/graph/sharepoint/payment-validation/jobs/{r.json()['job_id']}", label="apply2")
            save("amort_apply2.json", a2)
            res = a2.get("result") or {}
            RESULTS["flow"].append({
                "step": "amort_apply_retry",
                "status": res.get("status"),
                "already_applied": res.get("already_applied"),
                "tables_uploaded_count": res.get("tables_uploaded_count"),
                "process_control_estado": res.get("process_control_estado"),
            })

        # Ensure asientos folders
        r = c.post(f"{BASE}/graph/sharepoint/ensure-asientos-contables-folders", json={})
        RESULTS["endpoints"].append({"method": "POST", "path": "/graph/sharepoint/ensure-asientos-contables-folders", "status": r.status_code})
        if r.status_code == 202:
            e = poll(c, f"{BASE}/graph/sharepoint/ensure-asientos-contables-folders/jobs/{r.json()['job_id']}", label="ensure")
            save("ensure_asientos.json", e)
            RESULTS["flow"].append({"step": "ensure_asientos", "status": (e.get("result") or {}).get("status") or e.get("status")})

        # Notify early / already
        r = c.post(f"{BASE}/graph/sharepoint/notify-validar-extractos-email", json={"bank_code": "banco_bogota"})
        RESULTS["endpoints"].append({"method": "POST", "path": "/graph/sharepoint/notify-validar-extractos-email", "status": r.status_code})
        if r.status_code == 202:
            n = poll(c, f"{BASE}/graph/sharepoint/notify-validar-extractos-email/jobs/{r.json()['job_id']}", label="notify")
            save("notify.json", n)
            res = n.get("result") or {}
            RESULTS["flow"].append({
                "step": "notify",
                "job": n.get("status"),
                "already": res.get("merge_control_error_code") or res.get("error_code"),
                "status": res.get("status") or n.get("status"),
            })

        # Generate early (should already_generated or fail gate)
        r = c.post(
            f"{BASE}/graph/sharepoint/payment-validation/generate/queue",
            json={"bank_code": "banco_bogota", "process_date": today_colombia_iso()},
        )
        RESULTS["endpoints"].append({"method": "POST", "path": "/graph/sharepoint/payment-validation/generate/queue", "status": r.status_code})
        if r.status_code == 202:
            g = poll(c, f"{BASE}/graph/sharepoint/payment-validation/jobs/{r.json()['job_id']}", label="generate", rounds=120)
            save("generate.json", g)
            res = g.get("result") or {}
            RESULTS["flow"].append({
                "step": "generate",
                "status": res.get("status") or g.get("status"),
                "already_generated": res.get("already_generated"),
                "error": (g.get("error") or {}).get("error_code") if isinstance(g.get("error"), dict) else g.get("error"),
            })

    save("summary.json", RESULTS)
    print("\n==== SUMMARY ====")
    print(json.dumps(RESULTS, ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    main()
