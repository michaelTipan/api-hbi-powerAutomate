"""Diagnóstico sandbox: amortización créditos 128/16 — job vs Control vs UI."""
from __future__ import annotations

import base64
import json
import os
import re
import sys
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime
from http.cookiejar import CookieJar
from pathlib import Path

BASE = "https://app-hbiauto-prod-001-afawg2g7frgte8c5.eastus-01.azurewebsites.net"
PUB = Path(r"D:\CMC\HBI_Capital\app-hbiauto-prod-001.PublishSettings")
ENV_PACK = Path(r"D:\CMC\HBI_Capital\api-hbi-powerAutomate.env")


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
    url = f"{scm}/api/vfs/site/wwwroot/{path.lstrip('/')}"
    req = urllib.request.Request(url, headers={"Authorization": f"Basic {auth}"})
    with urllib.request.urlopen(req, timeout=120) as r:
        return r.read()


def kudu_list(scm: str, auth: str, path: str) -> list[dict]:
    raw = kudu_get(scm, auth, path.rstrip("/") + "/")
    return json.loads(raw.decode())


def api_key() -> str:
    for line in ENV_PACK.read_text(encoding="utf-8").splitlines():
        if line.startswith("API_HTTP_KEY="):
            return line.split("=", 1)[1].strip()
    raise SystemExit("no API_HTTP_KEY")


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


def summarize_issues(raw_issues: list | None) -> list[dict]:
    out: list[dict] = []
    for item in raw_issues or []:
        if not isinstance(item, dict):
            continue
        loc = item.get("location") if isinstance(item.get("location"), dict) else {}
        out.append(
            {
                "issue_id": item.get("issue_id"),
                "title": item.get("title"),
                "user_message": (item.get("user_message") or "")[:120],
                "technical_reference": item.get("technical_reference"),
                "credit": loc.get("credit") if isinstance(loc, dict) else None,
            }
        )
    return out


def parse_amort_json(cell: str) -> dict | None:
    if not cell or not str(cell).strip():
        return None
    try:
        return json.loads(cell)
    except json.JSONDecodeError:
        return {"raw_error": cell[:200]}


def find_matching_controls(scm: str, auth: str) -> list[dict]:
    hits: list[dict] = []
    for bank in ("banco_bogota", "banco_bancolombia"):
        ctrl_path = f".payment_validation_control/sandbox/{bank}.json"
        try:
            ctrl = json.loads(kudu_get(scm, auth, ctrl_path).decode())
        except urllib.error.HTTPError:
            continue
        cells = ctrl.get("cells") or {}
        amort_raw = cells.get("LastAmortizationAttemptJson") or ""
        blob = str(amort_raw).casefold()
        if "128" not in blob and "16" not in blob:
            continue
        if "tabla de amortización" not in blob and "table_path_not_found" not in blob:
            continue
        hits.append(
            {
                "bank": bank,
                "process_key": cells.get("ProcessKey") or cells.get("process_key"),
                "estado": cells.get("EstadoProceso"),
                "process_id": cells.get("ProcessId"),
                "last_updated": cells.get("LastUpdatedAtProceso"),
                "last_amort": parse_amort_json(amort_raw),
            }
        )
    return hits


def recent_amort_jobs(scm: str, auth: str, process_key: str | None, limit: int = 8) -> list[dict]:
    entries = kudu_list(scm, auth, ".payment_validation_jobs")
    jobs: list[tuple[str, dict]] = []
    for ent in entries:
        name = ent.get("name") or ""
        if not name.endswith(".json"):
            continue
        job_id = name.replace(".json", "")
        try:
            job = json.loads(kudu_get(scm, auth, f".payment_validation_jobs/{name}").decode())
        except urllib.error.HTTPError:
            continue
        jtype = str(job.get("type") or "").lower()
        if "amortization" not in jtype and "apply" not in jtype:
            continue
        pk = str(job.get("process_key") or (job.get("request") or {}).get("process_key") or "")
        if process_key and pk and pk != process_key:
            continue
        jobs.append((job_id, job))

    def sort_key(item: tuple[str, dict]) -> str:
        _id, job = item
        for field in ("finished_at", "updated_at", "created_at", "queued_at"):
            val = str(job.get(field) or "")
            if val:
                return val
        return _id

    jobs.sort(key=sort_key, reverse=True)
    out: list[dict] = []
    for job_id, job in jobs[:limit]:
        result = job.get("result") if isinstance(job.get("result"), dict) else {}
        summary = job.get("result_summary") if isinstance(job.get("result_summary"), dict) else {}
        issues_raw = summary.get("operational_issues") or result.get("operational_issues")
        out.append(
            {
                "job_id": job_id,
                "status": job.get("status"),
                "process_key": job.get("process_key"),
                "finished_at": job.get("finished_at"),
                "outcome": summary.get("outcome") or result.get("outcome"),
                "issues": summarize_issues(issues_raw if isinstance(issues_raw, list) else None),
            }
        )
    return out


def spa_has_fix(scm: str, auth: str) -> dict:
    assets_dir = kudu_list(scm, auth, "app/static/operator-ui/assets")
    js_files = [a["name"] for a in assets_dir if a.get("name", "").endswith(".js")]
    found_in: list[str] = []
    markers = (
        "amortizationIssuesProjectionFresh",
        "syncAmortEphemeralFromDetail",
    )
    for name in js_files:
        raw = kudu_get(scm, auth, f"app/static/operator-ui/assets/{name}").decode(
            "utf-8", errors="ignore"
        )
        if all(m in raw for m in markers):
            found_in.append(name)
    return {"js_assets": js_files, "fix_bundle": found_in}


def ui_process_detail(session: UiSession, process_key: str) -> tuple[int, dict | str]:
    return session.call("GET", f"/api/ui/v1/processes/{urllib.parse.quote(process_key, safe='')}")


def main() -> None:
    scm, auth = kudu_auth()
    print("=== HEALTH ===")
    health = json.loads(
        urllib.request.urlopen(f"{BASE}/health", timeout=60).read().decode()
    )
    print(json.dumps({k: health.get(k) for k in ("status", "build", "commit", "environment")}, indent=2))

    print("\n=== SPA FIX MARKERS ===")
    spa = spa_has_fix(scm, auth)
    print(json.dumps(spa, indent=2))

    print("\n=== CONTROL ROWS (128/16 amort) ===")
    controls = find_matching_controls(scm, auth)
    if not controls:
        print("No control row matched 128/16 in LastAmortizationAttemptJson")
    for row in controls:
        amort = row.get("last_amort") or {}
        print(json.dumps(
            {
                "bank": row["bank"],
                "process_key": row["process_key"],
                "estado": row["estado"],
                "last_updated": row["last_updated"],
                "attempt_id": amort.get("attempt_id"),
                "outcome": amort.get("outcome"),
                "issues": summarize_issues(amort.get("operational_issues")),
            },
            indent=2,
            ensure_ascii=False,
        ))

    target_pk = None
    if controls:
        target_pk = str(controls[0].get("process_key") or "")
    if len(sys.argv) > 1:
        target_pk = sys.argv[1]

    print("\n=== RECENT AMORT JOBS ===")
    jobs = recent_amort_jobs(scm, auth, target_pk or None, limit=10)
    if not jobs:
        print("No amort jobs found")
    for j in jobs:
        print(json.dumps(j, indent=2, ensure_ascii=False))

    if target_pk:
        print(f"\n=== UI PROCESS DETAIL ({target_pk}) ===")
        pwd = os.environ.get("UI_PASSWORD", "")
        user = os.environ.get("UI_USERNAME", "operador_hbi")
        session = UiSession()
        if pwd:
            code, login = session.call(
                "POST",
                "/api/ui/v1/auth/login",
                body={"username": user, "password": pwd},
            )
            print("login", code, type(login).__name__)
            if code == 200:
                code, detail = ui_process_detail(session, target_pk)
                print("detail_http", code)
                if isinstance(detail, dict):
                    la = detail.get("last_amortization_attempt") or {}
                    print(
                        json.dumps(
                            {
                                "operational_status": detail.get("operational_status"),
                                "control_estado": detail.get("control_estado_proceso"),
                                "attempt_id": la.get("attempt_id"),
                                "issues": summarize_issues(la.get("operational_issues")),
                            },
                            indent=2,
                            ensure_ascii=False,
                        )
                    )
        else:
            print("SKIP UI detail (set UI_PASSWORD env)")


if __name__ == "__main__":
    main()
