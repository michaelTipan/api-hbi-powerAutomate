"""Sube asiento AGRECAR (crédito esperado '2') y reintenta merge."""
from __future__ import annotations

import base64
import json
import time
from pathlib import Path
from urllib.parse import quote

import httpx

BASE = "https://app-hbiauto-prod-001-afawg2g7frgte8c5.eastus-01.azurewebsites.net"
SRC = Path(
    r"D:\CMC\HBI_Capital\asientos_prueba\generados\Asiento 27-JUL-2026 PAGO CUOTA AGRECAR CRED 37.pdf"
)
DEST_NAME = "Asiento 27-JUL-2026 PAGO CUOTA AGRECAR CRED 2.pdf"
RUTA = (
    "INFORMACION CREDITOS-CLIENTES/"
    "02 COMWARE AUTOMATIZACION - INFORMACION CREDITOS CLIENTES/"
    "AGRECAR/2 CREDITO #37 VIGENTE/ASIENTOS CONTABLES CRED 37/"
    + DEST_NAME
)
OUT = Path(r"D:\CMC\HBI_Capital\_work\mergeC_result.json")


def main() -> None:
    with httpx.Client(timeout=180) as c:
        drive = c.get(f"{BASE}/graph/sharepoint/resolve-env").json()["resolved"]["drive_id"]
        up = c.put(
            f"{BASE}/graph/sharepoint/drives/{quote(drive, safe='')}/path-content",
            params={"item_path": RUTA},
            json={"content_base64": base64.b64encode(SRC.read_bytes()).decode("ascii")},
        )
        print("upload", up.status_code, up.text[:200])
        up.raise_for_status()
        r = c.post(f"{BASE}/graph/sharepoint/merge-composite-validado-pdfs", json={})
        print("merge", r.status_code, r.json())
        r.raise_for_status()
        jid = r.json()["job_id"]
        for _ in range(40):
            b = c.get(
                f"{BASE}/graph/sharepoint/merge-composite-validado-pdfs/jobs/{jid}",
                timeout=90,
            ).json()
            res = b.get("result") or {}
            print(
                b.get("status"),
                res.get("merge_control_status"),
                res.get("skipped_count"),
                res.get("already_merged"),
            )
            if b.get("status") in ("completed", "failed"):
                OUT.write_text(
                    json.dumps(b, ensure_ascii=False, indent=2, default=str),
                    encoding="utf-8",
                )
                break
            time.sleep(8)


if __name__ == "__main__":
    main()
