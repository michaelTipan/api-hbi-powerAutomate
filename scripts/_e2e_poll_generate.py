"""Poll job con reintentos ante timeout (1 worker bloquea status durante Generate)."""
from __future__ import annotations

import json
import time
from pathlib import Path

import httpx

BASE = "https://app-hbiauto-prod-001-afawg2g7frgte8c5.eastus-01.azurewebsites.net"
JOB = "f1f6915f-28bb-4ac6-820f-6cef6588e437"
OUT = Path(r"D:\CMC\HBI_Capital\_work\generate_result.json")


def main() -> None:
    deadline = time.time() + 1800
    while time.time() < deadline:
        try:
            with httpx.Client(timeout=90) as c:
                r = c.get(f"{BASE}/graph/sharepoint/payment-validation/jobs/{JOB}")
                print(time.strftime("%H:%M:%S"), r.status_code, end=" ")
                if r.status_code != 200:
                    print(r.text[:200])
                    time.sleep(10)
                    continue
                data = r.json()
                st = data.get("status")
                print(st)
                OUT.write_text(
                    json.dumps(data, ensure_ascii=False, indent=2, default=str),
                    encoding="utf-8",
                )
                if st in ("completed", "failed", "error"):
                    print("DONE")
                    return
        except Exception as exc:
            print(time.strftime("%H:%M:%S"), "poll_err", type(exc).__name__, str(exc)[:120])
        time.sleep(15)
    raise SystemExit("timeout waiting job")


if __name__ == "__main__":
    main()
