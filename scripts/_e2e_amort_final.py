"""Merge idempotente + amortización final."""
from __future__ import annotations

import json
import time
from pathlib import Path

import httpx

BASE = "https://app-hbiauto-prod-001-afawg2g7frgte8c5.eastus-01.azurewebsites.net"
WORK = Path(r"D:\CMC\HBI_Capital\_work")


def poll(c: httpx.Client, url: str) -> dict:
    for _ in range(60):
        b = c.get(url, timeout=90).json()
        res = b.get("result") or {}
        print(b.get("status"), res.get("status"), res.get("error_code"), res.get("already_merged") or res.get("already_applied"))
        if b.get("status") in ("completed", "failed"):
            return b
        time.sleep(8)
    raise TimeoutError(url)


def main() -> None:
    with httpx.Client(timeout=180) as c:
        r = c.post(f"{BASE}/graph/sharepoint/merge-composite-validado-pdfs", json={})
        print("merge_idem", r.status_code, r.json())
        r.raise_for_status()
        m = poll(
            c,
            f"{BASE}/graph/sharepoint/merge-composite-validado-pdfs/jobs/{r.json()['job_id']}",
        )
        (WORK / "mergeD_result.json").write_text(
            json.dumps(m, ensure_ascii=False, indent=2, default=str), encoding="utf-8"
        )

        r = c.post(
            f"{BASE}/graph/sharepoint/payment-validation/amortization/dry-run/queue",
            json={},
        )
        print("dry", r.status_code, r.json())
        r.raise_for_status()
        d = poll(c, f"{BASE}/graph/sharepoint/payment-validation/jobs/{r.json()['job_id']}")
        (WORK / "amort_dry_final.json").write_text(
            json.dumps(d, ensure_ascii=False, indent=2, default=str), encoding="utf-8"
        )

        r = c.post(
            f"{BASE}/graph/sharepoint/payment-validation/amortization/apply/queue",
            json={},
        )
        print("apply", r.status_code, r.json())
        r.raise_for_status()
        a = poll(c, f"{BASE}/graph/sharepoint/payment-validation/jobs/{r.json()['job_id']}")
        (WORK / "amort_apply_final.json").write_text(
            json.dumps(a, ensure_ascii=False, indent=2, default=str), encoding="utf-8"
        )


if __name__ == "__main__":
    main()
