"""Sube health.py, verifica BODY_INTRO en Azure y reinicia via OneDeploy static."""
from __future__ import annotations

import json
import time
import xml.etree.ElementTree as ET
from base64 import b64encode
from pathlib import Path

import httpx

PUB = Path(r"D:\CMC\HBI_Historico_Recursos\contexto-despliegue-anterior\app-hbiauto-prod-001.PublishSettings")
HEALTH = Path(r"D:\CMC\HBI_Capital\api-hbi-powerAutomate\app\adapters\primary\http\routers\health.py")
NOTIFY = Path(
    r"D:\CMC\HBI_Capital\api-hbi-powerAutomate\app\application\use_cases\send_validar_extractos_notification.py"
)
APP = "https://app-hbiauto-prod-001-afawg2g7frgte8c5.eastus-01.azurewebsites.net"


def main() -> None:
    root = ET.parse(PUB).getroot()
    profiles = root.findall(".//publishProfile")
    p = next(x for x in profiles if x.attrib.get("publishMethod") == "ZipDeploy")
    scm = p.attrib["publishUrl"].split(":")[0]
    user = p.attrib["userName"]
    pwd = p.attrib["userPWD"]
    auth = b64encode(f"{user}:{pwd}".encode("ascii")).decode("ascii")
    h = {"Authorization": f"Basic {auth}"}
    base = f"https://{scm}"

    with httpx.Client(timeout=120, headers=h) as c:
        for local, remote in (
            (HEALTH, "app/adapters/primary/http/routers/health.py"),
            (NOTIFY, "app/application/use_cases/send_validar_extractos_notification.py"),
        ):
            r = c.put(
                f"{base}/api/vfs/site/wwwroot/{remote}",
                content=local.read_bytes(),
                headers={**h, "Content-Type": "application/octet-stream"},
            )
            print("upload", remote, r.status_code)

        cmd = {
            "command": "python3 -c \"import pathlib; t=pathlib.Path('.env').read_text(encoding='utf-8'); print([l for l in t.splitlines() if 'BODY_INTRO' in l][0])\"",
            "dir": "/home/site/wwwroot",
        }
        r = c.post(f"{base}/api/command", json=cmd)
        print("env_line", r.json().get("Output") or r.json().get("Error"))

        r = c.post(
            f"{base}/api/publish?type=static&path=/home/site/wwwroot/.restarttrigger&restart=true",
            content=b"buen-dia",
            headers={**h, "Content-Type": "application/octet-stream"},
        )
        print("restart", r.status_code)

    deadline = time.time() + 180
    while time.time() < deadline:
        try:
            body = httpx.get(f"{APP}/health", timeout=30).json()
            print("health", body)
            if body.get("build") == "notify-buen-dia-20260730":
                print("LIVE_OK")
                return
        except Exception as exc:
            print("wait", exc)
        time.sleep(10)
    print("RESTART_PENDING")


if __name__ == "__main__":
    main()
