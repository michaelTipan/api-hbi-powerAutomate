# -*- coding: utf-8 -*-
from __future__ import annotations

import json
import time
from pathlib import Path

import httpx

BASE = "https://app-hbiauto-prod-001-afawg2g7frgte8c5.eastus-01.azurewebsites.net"
WORK = Path(r"D:\CMC\HBI_Capital\_work\prod_validation")


def poll(c: httpx.Client, url: str, label: str) -> dict:
    for i in range(90):
        b = c.get(url, timeout=120).json()
        res = b.get("result") or {}
        print(
            label,
            i,
            b.get("status"),
            res.get("status"),
            res.get("error_code") or res.get("preflight_error_code"),
            res.get("can_apply"),
            res.get("tables_uploaded_count"),
            res.get("already_applied"),
        )
        if b.get("status") in ("completed", "failed"):
            return b
        time.sleep(8)
    raise TimeoutError(label)


def main() -> None:
    with httpx.Client(timeout=180) as c:
        r = c.post(
            f"{BASE}/graph/sharepoint/payment-validation/amortization/dry-run/queue",
            json={"bank_code": "banco_bogota"},
        )
        print("dry q", r.status_code, r.json())
        r.raise_for_status()
        d = poll(
            c,
            f"{BASE}/graph/sharepoint/payment-validation/jobs/{r.json()['job_id']}",
            "dry",
        )
        (WORK / "amort_dry.json").write_text(
            json.dumps(d, ensure_ascii=False, indent=2, default=str), encoding="utf-8"
        )
        res = d.get("result") or {}
        print("SUMMARY", res.get("summary"))
        print("can_apply", res.get("can_apply"), "status", res.get("status"))
        for it in res.get("items") or []:
            print(
                " item",
                it.get("id_pago"),
                it.get("credito"),
                it.get("tipo_aplicacion"),
                it.get("application_status"),
                it.get("error_code"),
                (it.get("ibr") or {}).get("status"),
                str(it.get("tabla_amortizacion_path") or "")[:70],
            )

        r = c.post(
            f"{BASE}/graph/sharepoint/payment-validation/amortization/apply/queue",
            json={"bank_code": "banco_bogota"},
        )
        print("apply q", r.status_code, r.json())
        r.raise_for_status()
        a = poll(
            c,
            f"{BASE}/graph/sharepoint/payment-validation/jobs/{r.json()['job_id']}",
            "apply",
        )
        (WORK / "amort_apply.json").write_text(
            json.dumps(a, ensure_ascii=False, indent=2, default=str), encoding="utf-8"
        )
        res = a.get("result") or {}
        print(
            "APPLY",
            {
                k: res.get(k)
                for k in [
                    "status",
                    "tables_uploaded_count",
                    "apply_wrote_changes",
                    "already_applied",
                    "process_control_estado",
                    "error_code",
                    "preflight_error_code",
                    "user_message",
                ]
            },
        )


if __name__ == "__main__":
    main()
