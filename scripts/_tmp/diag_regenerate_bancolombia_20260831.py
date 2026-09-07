"""Diagnóstico sandbox: fallo Regenerar banco_bancolombia 2026-08-31."""
from __future__ import annotations

import base64
import json
import os
import sys
import time
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from http.cookiejar import CookieJar
from pathlib import Path

BASE = "https://app-hbiauto-prod-001-afawg2g7frgte8c5.eastus-01.azurewebsites.net"
PUB = Path(r"D:\CMC\HBI_Capital\app-hbiauto-prod-001.PublishSettings")
ENV_PACK = Path(r"D:\CMC\HBI_Capital\api-hbi-powerAutomate.env")
BANK = "banco_bancolombia"
DATE = "2026-08-31"


def _pub_auth() -> tuple[str, str]:
    root = ET.parse(PUB).getroot()
    for p in root.findall(".//publishProfile"):
        if p.attrib.get("publishMethod") == "ZipDeploy":
            scm = p.attrib["publishUrl"].split(":")[0]
            user = p.attrib["userName"]
            pwd = p.attrib["userPWD"]
            return f"https://{scm}", base64.b64encode(f"{user}:{pwd}".encode()).decode()
    raise SystemExit("no ZipDeploy profile")


class Session:
    def __init__(self) -> None:
        self.jar = CookieJar()
        self.opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(self.jar))

    def request(
        self,
        method: str,
        path: str,
        *,
        body: dict | None = None,
        headers: dict | None = None,
    ) -> tuple[int, dict | str]:
        url = f"{BASE}{path}"
        data = None
        hdrs = {"Accept": "application/json"}
        if headers:
            hdrs.update(headers)
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


def kudu_get(scm: str, auth: str, vfs_path: str) -> bytes:
    url = f"{scm}/api/vfs/site/wwwroot/{vfs_path.lstrip('/')}"
    req = urllib.request.Request(url, headers={"Authorization": f"Basic {auth}"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return r.read()


def kudu_list(scm: str, auth: str, vfs_path: str) -> list[dict]:
    raw = kudu_get(scm, auth, vfs_path if vfs_path.endswith("/") else vfs_path + "/")
    return json.loads(raw.decode())


def main() -> None:
    password = os.environ.get("UI_PASSWORD") or (sys.argv[1] if len(sys.argv) > 1 else "")
    if not password:
        raise SystemExit("pass UI_PASSWORD or argv[1]")

    s = Session()
    print("=== bootstrap ===")
    code, boot = s.request("GET", "/api/ui/v1/bootstrap")
    print(code, json.dumps(boot, ensure_ascii=False)[:300])

    print("=== login ===")
    code, login = s.request(
        "POST",
        "/api/ui/v1/auth/login",
        body={"username": "operator", "password": password},
    )
    print(code, login if isinstance(login, str) else json.dumps(login, ensure_ascii=False))

    print("=== csrf ===")
    code, csrf = s.request("GET", "/api/ui/v1/auth/csrf")
    token = csrf.get("csrf_token") if isinstance(csrf, dict) else None
    print(code, "token_len", len(token or ""))

    print("=== banks ===")
    code, banks = s.request("GET", "/api/ui/v1/banks")
    if isinstance(banks, list):
        for b in banks:
            if b.get("bank_code") == BANK:
                print(json.dumps(b, ensure_ascii=False, indent=2))

    print("=== processes list (bancolombia) ===")
    code, plist = s.request("GET", f"/api/ui/v1/processes?bank_code={BANK}")
    matches = []
    if isinstance(plist, dict):
        for p in plist.get("processes") or []:
            pk = p.get("process_key") or ""
            if DATE in pk:
                matches.append(p)
                print(json.dumps(p, ensure_ascii=False, indent=2)[:1200])
    print(f"matches={len(matches)}")

    target_key = None
    if matches:
        target_key = matches[0].get("process_key")
    elif isinstance(plist, dict):
        for p in plist.get("processes") or []:
            if (p.get("process_date") or "") == DATE:
                target_key = p.get("process_key")
                print("fallback key", target_key)
                break

    if target_key:
        print("=== process detail ===")
        code, detail = s.request("GET", f"/api/ui/v1/processes/{urllib.parse.quote(target_key, safe='')}")
        if isinstance(detail, dict):
            print("operational_status", detail.get("operational_status"))
            print("control_estado", detail.get("control_estado"))
            actions = detail.get("available_actions") or {}
            print("regenerate", json.dumps(actions.get("regenerate"), ensure_ascii=False))
            print("issues", len(detail.get("operational_issues") or []))
            for iss in (detail.get("operational_issues") or [])[:3]:
                print(" -", iss.get("code"), iss.get("message", "")[:120])

    print("=== recent failed generate jobs (kudu) ===")
    scm, auth = _pub_auth()
    jobs = kudu_list(scm, auth, ".payment_validation_jobs")
    files = [j for j in jobs if j.get("mime") != "inode/directory" and (j.get("name") or "").endswith(".json")]
    files.sort(key=lambda j: j.get("mtime") or "", reverse=True)
    shown = 0
    for meta in files[:120]:
        name = meta.get("name") or ""
        raw = kudu_get(scm, auth, f".payment_validation_jobs/{name}")
        job = json.loads(raw.decode())
        jtype = (job.get("type") or "").lower()
        bank = job.get("bank_code") or ""
        status = (job.get("status") or "").lower()
        if bank != BANK or "generat" not in jtype:
            continue
        if status != "failed":
            continue
        shown += 1
        print(f"\n--- job {name} mtime={meta.get('mtime')} ---")
        for k in ("job_id", "type", "status", "error", "user_message", "next_action", "process_key", "created_at", "finished_at"):
            v = job.get(k)
            if v:
                print(f"  {k}: {v}")
        rs = job.get("result_summary")
        if rs:
            print("  result_summary:", json.dumps(rs, ensure_ascii=False)[:1500])
        if shown >= 5:
            break

    print("\n=== trigger regenerate (dry if REGEN_DRY=1) ===")
    if os.environ.get("REGEN_DRY") == "1":
        print("skipped (REGEN_DRY=1)")
        return
    code, accepted = s.request(
        "POST",
        "/api/ui/v1/processes/generate",
        body={"bank_code": BANK, "force_regenerate": True, "process_date": DATE},
        headers={"X-CSRF-Token": token or ""},
    )
    print("accept", code, accepted if isinstance(accepted, str) else json.dumps(accepted, ensure_ascii=False))
    if code not in (200, 202) or not isinstance(accepted, dict):
        return
    job_id = accepted.get("job_id")
    if not job_id:
        return
    for i in range(60):
        time.sleep(3)
        code, job = s.request("GET", f"/api/ui/v1/jobs/{job_id}")
        st = (job.get("status") or "").lower() if isinstance(job, dict) else ""
        print(f"poll {i+1} status={st}")
        if st in ("completed", "failed"):
            print(json.dumps(job, ensure_ascii=False, indent=2)[:4000])
            break


if __name__ == "__main__":
    import urllib.parse

    main()
