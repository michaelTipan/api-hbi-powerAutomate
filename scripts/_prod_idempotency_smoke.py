# -*- coding: utf-8 -*-
from __future__ import annotations

import json
import time
from pathlib import Path

import httpx

BASE = "https://app-hbiauto-prod-001-afawg2g7frgte8c5.eastus-01.azurewebsites.net"
WORK = Path(r"D:\CMC\HBI_Capital\_work\prod_validation")


def poll(c: httpx.Client, url: str, label: str) -> dict:
    for i in range(50):
        b = c.get(url, timeout=120).json()
        res = b.get("result") or {}
        print(
            label,
            i,
            b.get("status"),
            res.get("status"),
            res.get("already_applied"),
            res.get("tables_uploaded_count"),
            res.get("already_merged"),
            res.get("merge_control_error_code") or res.get("merge_control_warning"),
        )
        if b.get("status") in ("completed", "failed"):
            return b
        time.sleep(6)
    raise TimeoutError(label)


def main() -> None:
    summary: dict = {}
    with httpx.Client(timeout=180) as c:
        r = c.post(
            f"{BASE}/graph/sharepoint/payment-validation/amortization/apply/queue",
            json={"bank_code": "banco_bogota"},
        )
        a = poll(
            c,
            f"{BASE}/graph/sharepoint/payment-validation/jobs/{r.json()['job_id']}",
            "apply2",
        )
        ar = a.get("result") or {}
        summary["apply_idempotent"] = {
            "already_applied": ar.get("already_applied"),
            "tables_uploaded_count": ar.get("tables_uploaded_count"),
            "process_control_estado": ar.get("process_control_estado"),
            "status": ar.get("status"),
        }

        r = c.post(
            f"{BASE}/graph/sharepoint/merge-composite-validado-pdfs",
            json={"bank_code": "banco_bogota"},
        )
        m = poll(
            c,
            f"{BASE}/graph/sharepoint/merge-composite-validado-pdfs/jobs/{r.json()['job_id']}",
            "merge",
        )
        mr = m.get("result") or {}
        summary["merge_idempotent"] = {
            "already_merged": mr.get("already_merged"),
            "status": mr.get("status") or m.get("status"),
            "merge_control_status": mr.get("merge_control_status"),
        }

        r = c.post(
            f"{BASE}/graph/sharepoint/notify-validar-extractos-email",
            json={"bank_code": "banco_bogota"},
        )
        n = poll(
            c,
            f"{BASE}/graph/sharepoint/notify-validar-extractos-email/jobs/{r.json()['job_id']}",
            "notify",
        )
        nr = n.get("result") or {}
        summary["notify"] = {
            "job": n.get("status"),
            "warning": nr.get("merge_control_warning") or nr.get("merge_control_error_code"),
            "error": (n.get("error") or {}).get("error_code")
            if isinstance(n.get("error"), dict)
            else n.get("error"),
        }

        endpoints = {}
        for p in [
            "/graph/sharepoint/payment-validation/setup/merge-control-workbook",
            "/graph/sharepoint/payment-validation/setup/payment-followup-workbooks",
            "/graph/sharepoint/payment-validation/setup/ibr-workbook",
        ]:
            endpoints[f"POST {p}"] = c.post(f"{BASE}{p}", json={}).status_code
        for p in [
            "/health",
            "/graph/diagnostics",
            "/openapi.json",
            "/graph/sharepoint/resolve-env",
        ]:
            endpoints[f"GET {p}"] = c.get(f"{BASE}{p}").status_code
        oa = c.get(f"{BASE}/openapi.json").json()
        summary["endpoints"] = endpoints
        summary["openapi_path_count"] = len(oa.get("paths") or {})

    (WORK / "idempotency_and_endpoints.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
