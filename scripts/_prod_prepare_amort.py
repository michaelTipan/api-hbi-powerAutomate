# -*- coding: utf-8 -*-
"""Prepara sandbox: asientos parseables + IBR + control CONSOLIDADO (sin borrar rutas reales)."""
from __future__ import annotations

import base64
import json
from datetime import date
from io import BytesIO
from pathlib import Path
from urllib.parse import quote

import httpx
from openpyxl import Workbook, load_workbook

BASE = "https://app-hbiauto-prod-001-afawg2g7frgte8c5.eastus-01.azurewebsites.net"
ROOT = (
    "INFORMACION CREDITOS-CLIENTES/"
    "02 COMWARE AUTOMATIZACION - INFORMACION CREDITOS CLIENTES"
)
CONTROL = (
    f"{ROOT}/01 VALIDACION PAGOS/01 CONTROL/"
    "control_proceso_validacion_pagos_banco_bogota.xlsx"
)
IBR = f"{ROOT}/01 VALIDACION PAGOS/01 CONTROL/IBR_DIARIO.xlsx"
ASIENTOS = Path(r"D:\CMC\HBI_Capital\asientos_prueba\generados")
WORK = Path(r"D:\CMC\HBI_Capital\_work\prod_validation")
WORK.mkdir(parents=True, exist_ok=True)

# Rutas exactas del manifest mergeC (sobrescribir con PDF parseable)
UPLOADS = [
    (
        "Asiento 27-JUL-2026 PAGO CUOTA GEOEXCON CRED 231.pdf",
        f"{ROOT}/GEOEXCON/CREDITO # 231/ASIENTOS CONTABLES CRED 231/Asiento 27-JUL-2026 PAGO CUOTA GEOEXCON CRED 231.pdf",
    ),
    (
        "Asiento 27-JUL-2026 PAGO Y ABONO CAPITAL GEOEXCON CRED 231.pdf",
        f"{ROOT}/GEOEXCON/CREDITO # 231/ASIENTOS CONTABLES CRED 231/Asiento 27-JUL-2026 PAGO Y ABONO CAPITAL GEOEXCON CRED 231.pdf",
    ),
    (
        "Asiento 27-JUL-2026 PAGO CUOTA GEOEXCON CRED 254.pdf",
        f"{ROOT}/GEOEXCON/CREDITO # 254/ASIENTOS CONTABLES CRED 254/Asiento 27-JUL-2026 PAGO CUOTA GEOEXCON CRED 254.pdf",
    ),
    (
        "Asiento 27-JUL-2026 PAGO CUOTA EQUINORTE CRED 258.pdf",
        f"{ROOT}/EQUINORTE/CREDITO # 258/ASIENTOS CONTABLES CRED 258/Asiento 27-JUL-2026 PAGO CUOTA EQUINORTE CRED 258.pdf",
    ),
    (
        "Asiento 27-JUL-2026 PAGO CUOTA EQUINORTE CRED 264.pdf",
        f"{ROOT}/EQUINORTE/CREDITO # 264/ASIENTOS CONTABLES CRED 264/Asiento 27-JUL-2026 PAGO CUOTA EQUINORTE CRED 264.pdf",
    ),
    (
        "Asiento 27-JUL-2026 ABONO CAPITAL EQUINORTE CRED 265.pdf",
        f"{ROOT}/EQUINORTE/CREDITO # 265/ASIENTOS CONTABLES CRED 265/Asiento 27-JUL-2026 ABONO CAPITAL EQUINORTE CRED 265.pdf",
    ),
    (
        "Asiento 27-JUL-2026 ABONO MORA EQUINORTE CRED 265.pdf",
        f"{ROOT}/EQUINORTE/CREDITO # 265/ASIENTOS CONTABLES CRED 265/Asiento 27-JUL-2026 ABONO MORA EQUINORTE CRED 265.pdf",
    ),
    # Nombre histórico en SharePoint (crédito mal extraído como 2)
    (
        "Asiento 27-JUL-2026 PAGO CUOTA AGRECAR CRED 37.pdf",
        f"{ROOT}/AGRECAR/2 CREDITO #37 VIGENTE/ASIENTOS CONTABLES CRED 37/Asiento 27-JUL-2026 PAGO CUOTA AGRECAR CRED 2.pdf",
    ),
]


def upload(c: httpx.Client, drive: str, local: Path, remote: str) -> None:
    r = c.put(
        f"{BASE}/graph/sharepoint/drives/{quote(drive, safe='')}/path-content",
        params={"item_path": remote},
        json={"content_base64": base64.b64encode(local.read_bytes()).decode("ascii")},
        timeout=180,
    )
    print("upload", r.status_code, remote.rsplit("/", 1)[-1])
    r.raise_for_status()


def download_file(c: httpx.Client, drive: str, remote: str) -> bytes:
    # List by walking is heavy; use Graph search via children from parent
    parent = "/".join(remote.split("/")[:-1])
    name = remote.split("/")[-1]
    r = c.get(
        f"{BASE}/graph/sharepoint/drives/{quote(drive, safe='')}/children",
        params={"path": parent} if False else None,
        timeout=120,
    )
    # children endpoint: check signature
    # From OpenAPI earlier - GET /drives/{drive_id}/children — may need folder item id
    # Alternative: use site resolve + file-from-env only for configured path.
    # Try path as query used in some scripts:
    r = c.request(
        "GET",
        f"{BASE}/graph/sharepoint/drives/{quote(drive, safe='')}/item-content",
        params={"path": remote},
        timeout=120,
    )
    if r.status_code == 200 and r.headers.get("content-type", "").startswith("application/json"):
        data = r.json()
        if "content_base64" in data:
            return base64.b64decode(data["content_base64"])
    # Fallback: PUT then we can't read — use local patch via setup recreate is bad.
    # Use Microsoft Graph through diagnostics? 
    raise RuntimeError(f"download failed {r.status_code} {r.text[:300]}")


def ensure_ibr(c: httpx.Client, drive: str) -> None:
    c.post(f"{BASE}/graph/sharepoint/payment-validation/setup/ibr-workbook", json={}).raise_for_status()
    wb = Workbook()
    ws = wb.active
    ws.title = "IBR"
    ws.append(["Inicio", "Fin", "Valor"])
    ws.append([date(2026, 1, 1), date(2026, 12, 31), 0.1245])
    bio = BytesIO()
    wb.save(bio)
    r = c.put(
        f"{BASE}/graph/sharepoint/drives/{quote(drive, safe='')}/path-content",
        params={"item_path": IBR},
        json={"content_base64": base64.b64encode(bio.getvalue()).decode("ascii")},
        timeout=180,
    )
    print("ibr", r.status_code)
    r.raise_for_status()


def patch_control_via_fresh(c: httpx.Client, drive: str) -> None:
    """Reescribe control conservando rutas reales del E2E y estado CONSOLIDADO."""
    import sys

    sys.path.insert(0, r"D:\CMC\HBI_Capital\api-hbi-powerAutomate")
    from app.application.use_cases.setup_merge_control_workbook import (
        _build_process_control_workbook_bytes,
    )

    raw = _build_process_control_workbook_bytes("banco_bogota", "Banco Bogotá")
    wb = load_workbook(BytesIO(raw))
    ws = wb[wb.sheetnames[0]]
    headers = [str(ws.cell(1, c).value or "").strip() for c in range(1, ws.max_column + 1)]
    col = {h: i + 1 for i, h in enumerate(headers) if h}

    def setv(name: str, value) -> None:
        if name in col:
            ws.cell(2, col[name], value=value)

    setv("ProcessKey", "payment-validation|banco_bogota|2026-07-27")
    setv("ProcessDate", "2026-07-27")
    setv("BankCode", "banco_bogota")
    setv("BankName", "Banco Bogotá")
    setv("EstadoProceso", "CONSOLIDADO")
    setv("IsActive", True)
    setv("ApplyIdempotencyKey", "")
    setv("LastCompletedStep", "MERGE")
    setv("LastStepStatus", "COMPLETED")
    setv("LastStepErrorCode", "")
    setv("LastErrorUserMessage", "")
    setv("LastErrorNextAction", "")
    setv(
        "HistoricalFilePath",
        f"{ROOT}/01 VALIDACION PAGOS/03 HISTORICO/cartera_validada_banco_bogota_2026-07-27.xlsx",
    )
    setv(
        "SecretaryFilePath",
        f"{ROOT}/01 VALIDACION PAGOS/03 HISTORICO/soporte_asientos_contables_banco_bogota_2026-07-27.xlsx",
    )
    setv(
        "EmailPdfPath",
        f"{ROOT}/01 VALIDACION PAGOS/05 CORREOS ENVIADOS/ABONOS BANCO BOGOTA 2026-01-15.pdf",
    )
    setv(
        "MergeManifestPath",
        f"{ROOT}/01 VALIDACION PAGOS/04 TRAZABILIDAD/merge_manifest_banco_bogota_2026-01-15.json",
    )
    setv("NotifyIdempotencyKey", "payment-validation|banco_bogota|2026-07-27")
    setv("MergeIdempotencyKey", "payment-validation|banco_bogota|2026-07-27")

    bio = BytesIO()
    wb.save(bio)
    r = c.put(
        f"{BASE}/graph/sharepoint/drives/{quote(drive, safe='')}/path-content",
        params={"item_path": CONTROL},
        json={"content_base64": base64.b64encode(bio.getvalue()).decode("ascii")},
        timeout=180,
    )
    print("control", r.status_code)
    (WORK / "control_put.json").write_text(
        json.dumps({"status": r.status_code, "body": r.text[:500]}, ensure_ascii=False),
        encoding="utf-8",
    )
    r.raise_for_status()


def main() -> None:
    with httpx.Client(timeout=180) as c:
        print("health", c.get(f"{BASE}/health").json())
        drive = c.get(f"{BASE}/graph/sharepoint/resolve-env").json()["resolved"]["drive_id"]
        print("drive", drive)
        for name, remote in UPLOADS:
            local = ASIENTOS / name
            if not local.exists():
                print("MISSING", name)
                continue
            upload(c, drive, local, remote)
        ensure_ibr(c, drive)
        patch_control_via_fresh(c, drive)
        print("DONE")


if __name__ == "__main__":
    main()
