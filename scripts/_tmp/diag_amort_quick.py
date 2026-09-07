"""Quick Kudu: control amort 128/16 + SPA fix markers."""
from __future__ import annotations

import base64
import json
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path

BASE = "https://app-hbiauto-prod-001-afawg2g7frgte8c5.eastus-01.azurewebsites.net"
PUB = Path(r"D:\CMC\HBI_Capital\app-hbiauto-prod-001.PublishSettings")


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


def main() -> None:
    scm, auth = kudu_auth()
    print("HEALTH", kudu_get(scm, auth, "app/build_info.py").decode()[:200])

    health = json.loads(urllib.request.urlopen(f"{BASE}/health", timeout=60).read())
    print("BUILD", health.get("build"))

    assets = json.loads(kudu_get(scm, auth, "app/static/operator-ui/assets/").decode())
    js = [a["name"] for a in assets if str(a.get("name", "")).endswith(".js")]
    for name in js:
        raw = kudu_get(scm, auth, f"app/static/operator-ui/assets/{name}").decode("utf-8", errors="ignore")
        has_fix = "amortizationIssuesProjectionFresh" in raw
        print("SPA", name, "fix_marker=", has_fix)

    for bank in ("banco_bogota", "banco_bancolombia"):
        ctrl = json.loads(
            kudu_get(scm, auth, f".payment_validation_control/sandbox/{bank}.json").decode()
        )
        c = ctrl.get("cells") or {}
        la_raw = c.get("LastAmortizationAttemptJson") or ""
        print("\n===", bank, "===")
        print("ProcessKey", c.get("ProcessKey"))
        print("EstadoProceso", c.get("EstadoProceso"))
        print("LastUpdated", c.get("LastUpdatedAtProceso"))
        if not la_raw:
            print("LastAmort empty")
            continue
        la = json.loads(la_raw)
        print("attempt_id", la.get("attempt_id"))
        print("outcome", la.get("outcome"))
        for i in la.get("operational_issues") or []:
            loc = i.get("location") or {}
            print(
                " issue",
                i.get("issue_id"),
                "credit=",
                loc.get("credit"),
                "ref=",
                i.get("technical_reference"),
                "msg=",
                (i.get("user_message") or "")[:90],
            )


if __name__ == "__main__":
    main()
