"""Auditoría sandbox: regenerate bancolombia 2026-08-31 — jobs, control, locks."""
from __future__ import annotations

import base64
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from http.cookiejar import CookieJar
from pathlib import Path

BASE = "https://app-hbiauto-prod-001-afawg2g7frgte8c5.eastus-01.azurewebsites.net"
PUB = Path(r"D:\CMC\HBI_Capital\app-hbiauto-prod-001.PublishSettings")
ENV_PACK = Path(r"D:\CMC\HBI_Capital\api-hbi-powerAutomate.env")
BANK = "banco_bancolombia"
DATE = "2026-08-31"
PROCESS_ID = "cfdba744-a025-4469-b8f5-da8ef8428c84"


def kudu_auth() -> tuple[str, str]:
    root = ET.parse(PUB).getroot()
    for p in root.findall(".//publishProfile"):
        if p.attrib.get("publishMethod") == "ZipDeploy":
            scm = p.attrib["publishUrl"].split(":")[0]
            auth = base64.b64encode(
                f"{p.attrib['userName']}:{p.attrib['userPWD']}".encode()
            ).decode()
            return f"https://{scm}", auth
    raise SystemExit("no ZipDeploy profile")


def kudu_get(scm: str, auth: str, path: str) -> bytes:
    enc = urllib.parse.quote(path.strip("/"), safe="/")
    url = f"{scm}/api/vfs/site/wwwroot/{enc}"
    req = urllib.request.Request(url, headers={"Authorization": f"Basic {auth}"})
    with urllib.request.urlopen(req, timeout=90) as r:
        return r.read()


def kudu_list(scm: str, auth: str, path: str) -> list[dict]:
    raw = kudu_get(scm, auth, path.rstrip("/") + "/")
    return json.loads(raw.decode())


def api_key() -> str:
    for line in ENV_PACK.read_text(encoding="utf-8").splitlines():
        if line.startswith("API_HTTP_KEY="):
            return line.split("=", 1)[1].strip()
    raise SystemExit("no API key")


class UiSession:
    def __init__(self) -> None:
        self.opener = urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(CookieJar())
        )

    def call(
        self,
        method: str,
        path: str,
        *,
        body: dict | None = None,
        headers: dict | None = None,
    ) -> tuple[int, object]:
        url = f"{BASE}{path}"
        hdrs = {"Accept": "application/json", "Origin": BASE, "Referer": f"{BASE}/app/"}
        if headers:
            hdrs.update(headers)
        data = None
        if body is not None:
            data = json.dumps(body).encode()
            hdrs["Content-Type"] = "application/json"
        req = urllib.request.Request(url, data=data, headers=hdrs, method=method)
        try:
            with self.opener.open(req, timeout=120) as r:
                raw = r.read().decode()
                try:
                    return r.status, json.loads(raw)
                except json.JSONDecodeError:
                    return r.status, raw
        except urllib.error.HTTPError as e:
            raw = e.read().decode()
            try:
                return e.code, json.loads(raw)
            except json.JSONDecodeError:
                return e.code, raw


def enrich_job_via_api(job_id: str) -> dict:
    """Job enriquecido como lo ve la UI."""
    s = UiSession()
    pwd = os.environ.get("UI_PASSWORD", "")
    s.call("POST", "/api/ui/v1/auth/login", body={"username": "operator", "password": pwd})
    code, csrf = s.call("GET", "/api/ui/v1/auth/csrf")
    token = csrf.get("csrf_token") if isinstance(csrf, dict) else ""
    code, job = s.call("GET", f"/api/ui/v1/jobs/{job_id}")
    return {"http": code, "job": job}


def graph_file_metadata(rel_path: str) -> dict:
    key = api_key()
    enc = urllib.parse.quote(rel_path.strip("/"), safe="/")
    url = f"{BASE}/graph/diagnostics/file-probe?path={enc}"
    req = urllib.request.Request(url, headers={"X-API-Key": key, "Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            return json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        return {"http_error": e.code, "body": e.read().decode()[:2000]}


def main() -> None:
    scm, auth = kudu_auth()

    print("=== HEALTH ===")
    with urllib.request.urlopen(f"{BASE}/health", timeout=30) as r:
        print(r.read().decode())

    print("\n=== CONTROL banco_bancolombia ===")
    ctrl = json.loads(
        kudu_get(scm, auth, ".payment_validation_control/sandbox/banco_bancolombia.json")
    )
    cells = ctrl.get("cells") or {}
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

    val_path = str(cells.get("ValidationFilePath") or "")
    if val_path:
        print("\n=== GRAPH file-probe (review excel) ===")
        probe = graph_file_metadata(val_path)
        print(json.dumps(probe, indent=2, ensure_ascii=False)[:4000])

    print("\n=== RECENT generate jobs bancolombia (last 15 failed/completed) ===")
    jobs_dir = kudu_list(scm, auth, ".payment_validation_jobs")
    files = [
        j
        for j in jobs_dir
        if j.get("mime") != "inode/directory" and (j.get("name") or "").endswith(".json")
    ]
    files.sort(key=lambda j: j.get("mtime") or "", reverse=True)
    shown = 0
    for meta in files:
        if shown >= 20:
            break
        name = meta.get("name") or ""
        raw = kudu_get(scm, auth, f".payment_validation_jobs/{name}")
        job = json.loads(raw.decode())
        if job.get("bank_code") != BANK:
            continue
        jtype = (job.get("type") or "").lower()
        if "generat" not in jtype:
            continue
        st = (job.get("status") or "").lower()
        if st not in ("failed", "completed", "running", "queued"):
            continue
        shown += 1
        err = job.get("error") or {}
        print(
            f"\n--- {name} status={st} mtime={meta.get('mtime')} force_regen={job.get('force_regenerate')} ---"
        )
        print(f"  queued={job.get('queued_at')} finished={job.get('finished_at')}")
        print(f"  requested_by={job.get('requested_by')!r} ui_request_id={job.get('ui_request_id')!r}")
        if err:
            print(f"  error={json.dumps(err, ensure_ascii=False)[:500]}")

    print("\n=== UI ENRICHMENT último job fallido ===")
    enrich = enrich_job_via_api("8e4f4fa8-7495-4e31-9d47-42c0cf0aecb4")
    job = enrich.get("job") if isinstance(enrich.get("job"), dict) else {}
    err = job.get("error") if isinstance(job.get("error"), dict) else {}
    print(f"  user_message={err.get('user_message')!r}")
    print(f"  error_code={err.get('error_code')!r}")
    print(f"  next_action={err.get('next_action')!r}")

    if os.environ.get("TRY_REGEN") == "1":
        print("\n=== LIVE REGENERATE ATTEMPT ===")
        s = UiSession()
        pwd = os.environ.get("UI_PASSWORD", "")
        print("login", s.call("POST", "/api/ui/v1/auth/login", body={"username": "operator", "password": pwd}))
        _, csrf = s.call("GET", "/api/ui/v1/auth/csrf")
        token = csrf.get("csrf_token") if isinstance(csrf, dict) else ""
        code, acc = s.call(
            "POST",
            "/api/ui/v1/processes/generate",
            body={"bank_code": BANK, "force_regenerate": True, "process_date": DATE},
            headers={"X-CSRF-Token": token or ""},
        )
        print("accept", code, acc)
        if isinstance(acc, dict) and acc.get("job_id"):
            jid = acc["job_id"]
            for i in range(40):
                time.sleep(3)
                _, j = s.call("GET", f"/api/ui/v1/jobs/{jid}")
                st = (j.get("status") or "").lower() if isinstance(j, dict) else "?"
                print(f"  poll {i+1}: {st}")
                if st in ("completed", "failed"):
                    print(json.dumps(j, indent=2, ensure_ascii=False)[:5000])
                    break


if __name__ == "__main__":
    main()
