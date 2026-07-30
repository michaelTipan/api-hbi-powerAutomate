"""Fuerza upload con If-Match y reinicio; espera health nuevo."""
from __future__ import annotations

import time
import xml.etree.ElementTree as ET
from base64 import b64encode
from pathlib import Path

import httpx

PUB = Path(r"D:\CMC\HBI_Historico_Recursos\contexto-despliegue-anterior\app-hbiauto-prod-001.PublishSettings")
APP = "https://app-hbiauto-prod-001-afawg2g7frgte8c5.eastus-01.azurewebsites.net"
ROOT = Path(r"D:\CMC\HBI_Capital\api-hbi-powerAutomate")
FILES = {
    "app/adapters/primary/http/routers/health.py": ROOT
    / "app/adapters/primary/http/routers/health.py",
    "app/application/use_cases/send_validar_extractos_notification.py": ROOT
    / "app/application/use_cases/send_validar_extractos_notification.py",
}


def main() -> None:
    root = ET.parse(PUB).getroot()
    p = next(
        x
        for x in root.findall(".//publishProfile")
        if x.attrib.get("publishMethod") == "ZipDeploy"
    )
    scm = p.attrib["publishUrl"].split(":")[0]
    auth = b64encode(f"{p.attrib['userName']}:{p.attrib['userPWD']}".encode()).decode()
    h = {"Authorization": f"Basic {auth}"}
    base = f"https://{scm}"

    with httpx.Client(timeout=120) as c:
        for remote, local in FILES.items():
            r = c.put(
                f"{base}/api/vfs/site/wwwroot/{remote}",
                content=local.read_bytes(),
                headers={
                    **h,
                    "Content-Type": "application/octet-stream",
                    "If-Match": "*",
                },
            )
            print("put", remote, r.status_code)
        r = c.post(
            f"{base}/api/command",
            headers={**h, "Content-Type": "application/json"},
            json={"command": "touch application.py run.sh .ostype", "dir": "/home/site/wwwroot"},
        )
        print("touch", r.status_code, (r.json() or {}).get("ExitCode"))
        r = c.post(
            f"{base}/api/publish?type=static&path=/home/site/wwwroot/.restarttrigger2&restart=true",
            content=b"1",
            headers={**h, "Content-Type": "application/octet-stream"},
        )
        print("publish_restart", r.status_code)

    for i in range(30):
        time.sleep(10)
        try:
            body = httpx.get(f"{APP}/health", timeout=30).json()
            print(i, body)
            if body.get("build") == "notify-buen-dia-20260730":
                print("LIVE_OK")
                return
        except Exception as exc:
            print(i, "err", exc)
    print("RESTART_PENDING")


if __name__ == "__main__":
    main()
