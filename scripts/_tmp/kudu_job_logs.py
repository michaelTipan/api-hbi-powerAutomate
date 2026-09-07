"""Lee jobs y execution logs via Kudu."""
from __future__ import annotations

import base64
import json
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path

PUB = Path(r"D:\CMC\HBI_Capital\app-hbiauto-prod-001.PublishSettings")


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


def get(scm: str, auth: str, vfs: str) -> bytes:
    parts = vfs.strip("/").split("/")
    enc = "/".join(urllib.parse.quote(p, safe="") for p in parts)
    url = f"{scm}/api/vfs/site/wwwroot/{enc}"
    req = urllib.request.Request(url, headers={"Authorization": f"Basic {auth}"})
    with urllib.request.urlopen(req, timeout=90) as r:
        return r.read()


def main() -> None:
    scm, auth = pub()
    for jid in (
        "ff05aa8b-b88f-48c2-9ff9-cbb1e196234d",
        "5366a94a-3cce-4eaa-ad8c-c6afe87bbcca",
        "2f32a77f-f464-4027-b5b1-a481d1efb50b",
    ):
        print(f"\n=== JOB {jid} ===")
        job = json.loads(get(scm, auth, f".payment_validation_jobs/{jid}.json"))
        print(json.dumps({k: job.get(k) for k in ("status", "force_regenerate", "queued_at", "finished_at", "error", "result_summary")}, indent=2, ensure_ascii=False)[:2500])
        log_path = job.get("execution_log_path")
        if log_path:
            print(f"\n--- execution log tail ---")
            try:
                raw = get(scm, auth, log_path)
                text = raw.decode("utf-8", errors="replace")
                print(text[-3500:])
            except Exception as e:
                print("log err:", e)


if __name__ == "__main__":
    main()
