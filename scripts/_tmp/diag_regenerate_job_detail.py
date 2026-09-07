"""Lee job + control bancolombia 2026-08-31 desde Kudu."""
from __future__ import annotations

import base64
import json
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path

PUB = Path(r"D:\CMC\HBI_Capital\app-hbiauto-prod-001.PublishSettings")
JOB = "8e4f4fa8-7495-4e31-9d47-42c0cf0aecb4"


def pub() -> tuple[str, str]:
    root = ET.parse(PUB).getroot()
    for p in root.findall(".//publishProfile"):
        if p.attrib.get("publishMethod") == "ZipDeploy":
            scm = p.attrib["publishUrl"].split(":")[0]
            auth = base64.b64encode(
                f"{p.attrib['userName']}:{p.attrib['userPWD']}".encode()
            ).decode()
            return f"https://{scm}", auth
    raise SystemExit("no profile")


def get(scm: str, auth: str, path: str) -> bytes:
    url = f"{scm}/api/vfs/site/wwwroot/{path.lstrip('/')}"
    req = urllib.request.Request(url, headers={"Authorization": f"Basic {auth}"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return r.read()


def main() -> None:
    scm, auth = pub()
    job = json.loads(get(scm, auth, f".payment_validation_jobs/{JOB}.json"))
    print("=== JOB FULL ===")
    print(json.dumps(job, indent=2, ensure_ascii=False))
    ctrl = json.loads(
        get(scm, auth, ".payment_validation_control/sandbox/banco_bancolombia.json")
    )
    cells = ctrl.get("cells") or {}
    print("\n=== CONTROL (selected) ===")
    for k in (
        "EstadoProceso",
        "IsActive",
        "ProcessKey",
        "ProcessId",
        "ValidationFilePath",
        "LastStepErrorCode",
        "LastErrorUserMessage",
        "LastCompletedStep",
        "LastUpdatedAtProceso",
    ):
        print(f"  {k}={cells.get(k)!r}")


if __name__ == "__main__":
    main()
