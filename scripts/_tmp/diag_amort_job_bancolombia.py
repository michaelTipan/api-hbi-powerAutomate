"""Job amort bancolombia 2026-08-31 + compare to Control."""
from __future__ import annotations

import base64
import json
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path

PUB = Path(r"D:\CMC\HBI_Capital\app-hbiauto-prod-001.PublishSettings")
JOB_ID = "2f136f87-2596-4d5f-a4f7-ccab7c78886c"
PROCESS_KEY = "payment-validation|banco_bancolombia|2026-08-31|32147a43-5362-447e-a32f-df5c31fd1567"


def kudu_auth() -> tuple[str, str]:
    root = ET.parse(PUB).getroot()
    for p in root.findall(".//publishProfile"):
        if p.attrib.get("publishMethod") == "ZipDeploy":
            scm = p.attrib["publishUrl"].split(":")[0]
            auth = base64.b64encode(
                f"{p.attrib['userName']}:{p.attrib['userPWD']}".encode()
            ).decode()
            return f"https://{scm}", auth
    raise SystemExit("no profile")


def kudu_get(scm: str, auth: str, path: str) -> bytes:
    url = f"{scm}/api/vfs/site/wwwroot/{path.lstrip('/')}"
    req = urllib.request.Request(url, headers={"Authorization": f"Basic {auth}"})
    with urllib.request.urlopen(req, timeout=120) as r:
        return r.read()


def summarize_issues(raw: list | None) -> None:
    for i in raw or []:
        if not isinstance(i, dict):
            continue
        loc = i.get("location") or {}
        print(
            " ",
            i.get("issue_id"),
            "credit=",
            loc.get("credit") if isinstance(loc, dict) else None,
            "ref=",
            i.get("technical_reference"),
            "msg=",
            (i.get("user_message") or "")[:100],
        )


def main() -> None:
    scm, auth = kudu_auth()
    job = json.loads(kudu_get(scm, auth, f".payment_validation_jobs/{JOB_ID}.json").decode())
    print("JOB", JOB_ID)
    print("status", job.get("status"))
    print("finished_at", job.get("finished_at"))
    print("process_key", job.get("process_key"))
    result = job.get("result") if isinstance(job.get("result"), dict) else {}
    summary = job.get("result_summary") if isinstance(job.get("result_summary"), dict) else {}
    print("outcome result", result.get("outcome"))
    print("outcome summary", summary.get("outcome"))
    print("--- job result operational_issues ---")
    ri = result.get("operational_issues")
    summarize_issues(ri if isinstance(ri, list) else None)
    print("--- job result_summary operational_issues ---")
    si = summary.get("operational_issues")
    summarize_issues(si if isinstance(si, list) else None)

    # List other recent amort jobs for same process
    entries = json.loads(kudu_get(scm, auth, ".payment_validation_jobs/").decode())
    matches: list[tuple[str, dict]] = []
    for ent in entries:
        name = ent.get("name") or ""
        if not name.endswith(".json"):
            continue
        jid = name[:-5]
        try:
            j = json.loads(kudu_get(scm, auth, f".payment_validation_jobs/{name}").decode())
        except Exception:
            continue
        pk = str(j.get("process_key") or "")
        if pk != PROCESS_KEY:
            continue
        if "amortization" not in str(j.get("type") or "").lower():
            continue
        matches.append((jid, j))
    matches.sort(key=lambda x: str(x[1].get("finished_at") or x[1].get("created_at") or ""), reverse=True)
    print("\n=== ALL AMORT JOBS FOR PROCESS (newest first) ===")
    for jid, j in matches[:6]:
        rs = j.get("result_summary") if isinstance(j.get("result_summary"), dict) else {}
        rr = j.get("result") if isinstance(j.get("result"), dict) else {}
        oi = rs.get("operational_issues") or rr.get("operational_issues")
        n = len(oi) if isinstance(oi, list) else 0
        print(jid, j.get("status"), j.get("finished_at"), "issues=", n, "outcome=", rs.get("outcome") or rr.get("outcome"))


if __name__ == "__main__":
    main()
