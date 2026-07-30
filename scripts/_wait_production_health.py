"""Espera a que /health muestre production-20260730; fuerza restart si hace falta."""
from __future__ import annotations

import time
import xml.etree.ElementTree as ET
from base64 import b64encode
from pathlib import Path

import httpx

PUB = Path(r"D:\CMC\HBI_Historico_Recursos\contexto-despliegue-anterior\app-hbiauto-prod-001.PublishSettings")
APP = "https://app-hbiauto-prod-001-afawg2g7frgte8c5.eastus-01.azurewebsites.net"
TARGET = "production-20260730"


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
        # Confirmar archivos en disco
        cmd = {
            "command": (
                "python3 -c \"import pathlib; "
                "h=pathlib.Path('app/adapters/primary/http/routers/health.py').read_text(); "
                "e=pathlib.Path('.env').read_text(encoding='utf-8'); "
                "print('HEALTH', [l for l in h.splitlines() if 'HEALTH_BUILD' in l][0]); "
                "print('ENV', [l for l in e.splitlines() if l.startswith('ACTIVE_ENVIRONMENT=')][0]); "
                "print('BASE', [l for l in e.splitlines() if l.startswith('GRAPH_CLIENTS_BASE_PATH=')][0])\""
            ),
            "dir": "/home/site/wwwroot",
        }
        r = c.post(f"{base}/api/command", headers={**h, "Content-Type": "application/json"}, json=cmd)
        print((r.json() or {}).get("Output") or (r.json() or {}).get("Error"))

        for attempt in range(3):
            body = httpx.get(f"{APP}/health", timeout=30).json()
            print("before", attempt, body)
            if body.get("build") == TARGET:
                print("LIVE_OK")
                return
            c.post(
                f"{base}/api/command",
                headers={**h, "Content-Type": "application/json"},
                json={"command": "touch application.py run.sh .ostype", "dir": "/home/site/wwwroot"},
            )
            c.post(
                f"{base}/api/publish?type=static&path=/home/site/wwwroot/.restarttrigger_prod{attempt}&restart=true",
                content=b"1",
                headers={**h, "Content-Type": "application/octet-stream"},
            )
            for i in range(24):
                time.sleep(10)
                try:
                    body = httpx.get(f"{APP}/health", timeout=30).json()
                    print(attempt, i, body)
                    if body.get("build") == TARGET:
                        print("LIVE_OK")
                        return
                except Exception as exc:
                    print(attempt, i, "err", exc)
        print("RESTART_PENDING")


if __name__ == "__main__":
    main()
