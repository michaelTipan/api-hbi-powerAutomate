"""Diagnóstico sandbox: control store + jobs + timing proyección vía Kudu/API."""
from __future__ import annotations

import base64
import json
import time
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path

PUB = Path(r"D:\CMC\HBI_Capital\app-hbiauto-prod-001.PublishSettings")
DEST = "https://app-hbiauto-prod-001-afawg2g7frgte8c5.eastus-01.azurewebsites.net"
PK = "payment-validation|banco_bancolombia|2026-08-21|d01a537c-5393-4f4b-ad54-0dd6485da59d"
ENV_PACK = Path(r"D:\CMC\HBI_Capital\api-hbi-powerAutomate.env")


def _pub_auth() -> tuple[str, str]:
    root = ET.parse(PUB).getroot()
    for p in root.findall(".//publishProfile"):
        if p.attrib.get("publishMethod") == "ZipDeploy":
            scm = p.attrib["publishUrl"].split(":")[0]
            user = p.attrib["userName"]
            pwd = p.attrib["userPWD"]
            return f"https://{scm}", base64.b64encode(f"{user}:{pwd}".encode()).decode()
    raise SystemExit("no ZipDeploy profile")


def kudu_get(scm: str, auth: str, vfs_path: str) -> bytes:
    url = f"{scm}/api/vfs/site/wwwroot/{vfs_path.lstrip('/')}"
    req = urllib.request.Request(url, headers={"Authorization": f"Basic {auth}"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return r.read()


def kudu_list(scm: str, auth: str, vfs_path: str) -> list[dict]:
    raw = kudu_get(scm, auth, vfs_path if vfs_path.endswith("/") else vfs_path + "/")
    return json.loads(raw.decode())


def api_key() -> str:
    for line in ENV_PACK.read_text(encoding="utf-8").splitlines():
        if line.startswith("API_HTTP_KEY="):
            return line.split("=", 1)[1].strip()
    raise SystemExit("no API key")


def main() -> None:
    scm, auth = _pub_auth()
    print("=== control bancolombia ===")
    ctrl = json.loads(
        kudu_get(scm, auth, ".payment_validation_control/sandbox/banco_bancolombia.json")
    )
    cells = ctrl.get("cells") or {}
    for k in (
        "EstadoProceso",
        "IsActive",
        "ProcessKey",
        "ApplyIdempotencyKey",
        "MergeIdempotencyKey",
        "LastCompletedStep",
        "ApplyJobId",
        "DryRunJobId",
        "MergeJobId",
        "LastAmortizationAttemptJson",
    ):
        v = cells.get(k)
        if k == "LastAmortizationAttemptJson" and v:
            v = str(v)[:200] + ("…" if len(str(v)) > 200 else "")
        print(f"  {k}={v!r}")

    print("=== recent jobs dir (names only) ===")
    jobs = kudu_list(scm, auth, ".payment_validation_jobs")
    files = [j for j in jobs if j.get("mime") != "inode/directory"]
    files.sort(key=lambda j: j.get("mtime") or "", reverse=True)
    print(f"  total_json={len(files)}")
    hits = []
    for meta in files[:80]:
        name = meta.get("name") or ""
        if not name.endswith(".json"):
            continue
        try:
            payload = json.loads(kudu_get(scm, auth, f".payment_validation_jobs/{name}"))
        except Exception as exc:
            print(f"  skip {name}: {exc}")
            continue
        blob = json.dumps(payload, ensure_ascii=False)
        if PK in blob or "banco_bancolombia" in blob:
            hits.append(
                {
                    "job_id": payload.get("job_id") or name,
                    "type": payload.get("type"),
                    "status": payload.get("status"),
                    "finished_at": payload.get("finished_at"),
                    "process_key": (payload.get("process_key") or (payload.get("request") or {}).get("process_key")),
                    "outcome": ((payload.get("result_summary") or payload.get("result") or {}) or {}).get(
                        "outcome"
                    )
                    if isinstance(payload.get("result_summary") or payload.get("result"), dict)
                    else None,
                }
            )
    hits.sort(key=lambda h: str(h.get("finished_at") or ""), reverse=True)
    for h in hits[:25]:
        print(
            f"  {h['type']} status={h['status']} outcome={h['outcome']} "
            f"finished={h['finished_at']} id={h['job_id']}"
        )

    # Health already known; try paths-probe timing
    key = api_key()
    print("=== timed paths-probe ===")
    t0 = time.perf_counter()
    req = urllib.request.Request(
        f"{DEST}/graph/diagnostics/paths-probe",
        headers={"X-API-Key": key},
    )
    with urllib.request.urlopen(req, timeout=120) as r:
        body = r.read()
    print(f"  ms={(time.perf_counter()-t0)*1000:.0f} bytes={len(body)}")

    print("=== timed /health ===")
    t0 = time.perf_counter()
    with urllib.request.urlopen(f"{DEST}/health", timeout=30) as r:
        h = json.loads(r.read().decode())
    print(f"  ms={(time.perf_counter()-t0)*1000:.0f} build={h.get('build')}")


if __name__ == "__main__":
    main()
