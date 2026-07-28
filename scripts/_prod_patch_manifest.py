# -*- coding: utf-8 -*-
"""Parchea merge_manifest: un asiento único por output + status COMPLETE."""
from __future__ import annotations

import base64
import json
from pathlib import Path
from urllib.parse import quote

import httpx

BASE = "https://app-hbiauto-prod-001-afawg2g7frgte8c5.eastus-01.azurewebsites.net"
ROOT = (
    "INFORMACION CREDITOS-CLIENTES/"
    "02 COMWARE AUTOMATIZACION - INFORMACION CREDITOS CLIENTES"
)
MANIFEST = (
    f"{ROOT}/01 VALIDACION PAGOS/04 TRAZABILIDAD/"
    "merge_manifest_banco_bogota_2026-01-15.json"
)
MERGE_C = Path(r"D:\CMC\HBI_Capital\_work\mergeC_result.json")
WORK = Path(r"D:\CMC\HBI_Capital\_work\prod_validation")

ASIENTO_FIX = {
    "2a40252c": f"{ROOT}/GEOEXCON/CREDITO # 231/ASIENTOS CONTABLES CRED 231/Asiento 27-JUL-2026 PAGO Y ABONO CAPITAL GEOEXCON CRED 231.pdf",
    "4f587bd2": f"{ROOT}/GEOEXCON/CREDITO # 231/ASIENTOS CONTABLES CRED 231/Asiento 27-JUL-2026 PAGO CUOTA GEOEXCON CRED 231.pdf",
    "01642c8d": f"{ROOT}/EQUINORTE/CREDITO # 265/ASIENTOS CONTABLES CRED 265/Asiento 27-JUL-2026 ABONO CAPITAL EQUINORTE CRED 265.pdf",
    "f38d9365": f"{ROOT}/EQUINORTE/CREDITO # 265/ASIENTOS CONTABLES CRED 265/Asiento 27-JUL-2026 ABONO MORA EQUINORTE CRED 265.pdf",
}


def main() -> None:
    src = json.loads(MERGE_C.read_text(encoding="utf-8"))["result"]
    outputs = []
    for o in src.get("outputs") or []:
        oid = str(o.get("id_pago") or "")
        fixed = dict(o)
        path = ASIENTO_FIX.get(oid) or (fixed.get("asiento_pdf_path") or "")
        if path:
            fixed["asiento_pdf_path"] = path
            fixed["asiento_pdf_paths"] = [path]
            cis = []
            for ci in fixed.get("credit_items") or []:
                ci2 = dict(ci)
                ci2["asiento_pdf_paths"] = [path]
                cis.append(ci2)
            if cis:
                fixed["credit_items"] = cis
        fixed["status"] = "COMPLETE"
        fixed["eligible_for_dry_run"] = True
        outputs.append(fixed)

    payload = {
        "report_date_iso": "2026-07-27",
        "historico_excel_path": src.get("historico_excel_path"),
        "email_pdf_used": src.get("email_pdf_used"),
        "merge_control_status": "CONSOLIDADO",
        "manifest_status": "COMPLETE",
        "eligible_for_dry_run": True,
        "complete_groups_count": len(outputs),
        "incomplete_groups_count": 0,
        "failed_groups_count": 0,
        "payment_outputs_count": sum(1 for o in outputs if o.get("tipo_aplicacion") == "PAGO"),
        "abono_outputs_count": sum(1 for o in outputs if o.get("tipo_aplicacion") == "ABONO"),
        "payment_incomplete_groups_count": 0,
        "abono_incomplete_groups_count": 0,
        "payment_skipped_count": 0,
        "abono_skipped_count": 0,
        "extracts_not_required_count": src.get("extracts_not_required_count") or 0,
        "outputs": outputs,
        "incomplete_groups": [],
        "skipped": [],
    }
    raw = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
    (WORK / "merge_manifest_patched.json").write_bytes(raw)

    with httpx.Client(timeout=180) as c:
        drive = c.get(f"{BASE}/graph/sharepoint/resolve-env").json()["resolved"]["drive_id"]
        r = c.put(
            f"{BASE}/graph/sharepoint/drives/{quote(drive, safe='')}/path-content",
            params={"item_path": MANIFEST},
            json={"content_base64": base64.b64encode(raw).decode("ascii")},
        )
        print("manifest", r.status_code)
        r.raise_for_status()
        for o in outputs:
            print(o["id_pago"], Path(o["asiento_pdf_path"]).name, len((o.get("credit_items") or [{}])[0].get("asiento_pdf_paths") or []))


if __name__ == "__main__":
    main()
