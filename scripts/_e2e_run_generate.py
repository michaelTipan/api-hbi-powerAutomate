"""Orquestador E2E sandbox Banco Bogotá — generate + poll + reporte."""
from __future__ import annotations

import json
import time
from pathlib import Path

import httpx

BASE = "https://app-hbiauto-prod-001-afawg2g7frgte8c5.eastus-01.azurewebsites.net"
WORK = Path(r"D:\CMC\HBI_Capital\_work")
LOG = WORK / "e2e_log.jsonl"


def log(event: str, data: dict) -> None:
    WORK.mkdir(exist_ok=True)
    row = {"event": event, **data}
    with LOG.open("a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False, default=str) + "\n")
    print(event, json.dumps(data, ensure_ascii=False, default=str)[:500])


def poll_job(c: httpx.Client, job_id: str, path: str, timeout_s: int = 900) -> dict:
    t0 = time.time()
    while time.time() - t0 < timeout_s:
        r = c.get(f"{BASE}{path}/{job_id}", timeout=60)
        r.raise_for_status()
        body = r.json()
        st = body.get("status")
        if st in ("completed", "failed", "error"):
            return body
        time.sleep(5)
    raise TimeoutError(job_id)


def main() -> None:
    WORK.mkdir(exist_ok=True)
    with httpx.Client(timeout=120) as c:
        # 1) Generate
        r = c.post(
            f"{BASE}/graph/sharepoint/payment-validation/generate/queue",
            json={"bank_code": "banco_bogota"},
        )
        log("generate_queue", {"status": r.status_code, "body": r.json() if r.content else {}})
        r.raise_for_status()
        job_id = r.json()["job_id"]
        result = poll_job(
            c, job_id, "/graph/sharepoint/payment-validation/jobs", timeout_s=1200
        )
        log("generate_done", result)
        (WORK / "generate_result.json").write_text(
            json.dumps(result, ensure_ascii=False, indent=2, default=str), encoding="utf-8"
        )

        # 2) Idempotencia: segundo generate mismo día
        r2 = c.post(
            f"{BASE}/graph/sharepoint/payment-validation/generate/queue",
            json={"bank_code": "banco_bogota"},
        )
        log("generate2_queue", {"status": r2.status_code, "body": r2.json() if r2.content else {}})
        if r2.status_code == 202:
            job2 = r2.json()["job_id"]
            result2 = poll_job(c, job2, "/graph/sharepoint/payment-validation/jobs")
            log("generate2_done", result2)
            (WORK / "generate2_result.json").write_text(
                json.dumps(result2, ensure_ascii=False, indent=2, default=str),
                encoding="utf-8",
            )


if __name__ == "__main__":
    main()
