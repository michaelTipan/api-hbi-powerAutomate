"""Rellena BANCO_BOGOTA.xlsx local (_work) con la batería E2E y lo sube a SharePoint (mismo item_id)."""
from __future__ import annotations

import base64
import io
from pathlib import Path
from urllib.parse import quote

import httpx
from openpyxl import load_workbook

BASE = "https://app-hbiauto-prod-001-afawg2g7frgte8c5.eastus-01.azurewebsites.net"
WORK = Path(r"D:\CMC\HBI_Capital\_work\BANCO_BOGOTA.xlsx")
BANK_ITEM_ID = "01UDV3W2ZAP2QTC7ZDR5CJGYVIWOYLPOKK"

# Filas de prueba (Fecha, Crédito, Concepto, Tipo Aplicación, Transacción)
ROWS: list[tuple[str, str, str, str, str]] = [
    ("23-abr", "19000171.00", "GEOEXCON", "PAGO", "E2E PAGO exacto 231"),
    ("22-abr", "48497024.00", "EQUINORTE", "PAGO", "E2E PAGO exacto 258"),
    ("15-ene", "20469925.01", "ACIMOR", "PAGO", "E2E negativo sin CREDITO"),
    ("23-abr", "30469925.02", "MINCIVIL", "PAGO", "E2E negativo sin CREDITO"),
    ("16-may", "5000000.00", "INVERSIONES Y PROYECTOS MIOS", "PAGO", "E2E sin extracto 318"),
    ("27-jul", "25075203.00", "AGRECAR", "PAGO", "E2E PAGO 37 ATRASADO"),
    ("15-abr", "32691683.00", "EQUINORTE", "PAGO", "E2E ADELANTADO 264"),
    ("23-abr", "24000171.00", "GEOEXCON", "PAGO Y ABONO CAPITAL", "E2E cuota+capital 231"),
    ("27-jul", "500000.00", "EQUINORTE", "ABONO CAPITAL", "E2E abono capital 265"),
    ("27-jul", "200000.00", "EQUINORTE", "ABONO MORA", "E2E abono mora 265"),
    ("23-feb", "6514755.00", "GEOEXCON", "PAGO", "E2E PAGO 254"),
    ("23-abr", "1000000.00", "CLIENTE_INEXISTENTE_XYZ", "PAGO", "E2E nombre cliente mal"),
]


def main() -> None:
    wb = load_workbook(WORK)
    ws = wb.active
    # Limpiar filas de datos previas (desde 4; 3 es ejemplo bloqueado en plantilla)
    for r in range(4, ws.max_row + 1):
        for c in range(1, 6):
            ws.cell(r, c).value = None
    for i, (fecha, monto, concepto, tipo, trx) in enumerate(ROWS):
        r = 4 + i
        ws.cell(r, 1).value = fecha
        ws.cell(r, 2).value = float(monto)
        ws.cell(r, 3).value = concepto
        ws.cell(r, 4).value = tipo
        ws.cell(r, 5).value = trx
    buf = io.BytesIO()
    wb.save(buf)
    raw = buf.getvalue()
    WORK.write_bytes(raw)
    print(f"Local OK rows={len(ROWS)} bytes={len(raw)}")

    with httpx.Client(timeout=180) as c:
        drive = c.get(f"{BASE}/graph/sharepoint/resolve-env").json()["resolved"]["drive_id"]
        payload = {"content_base64": base64.b64encode(raw).decode("ascii")}
        r = c.put(
            f"{BASE}/graph/sharepoint/drives/{quote(drive, safe='')}/item-content",
            params={"item_id": BANK_ITEM_ID},
            json=payload,
        )
        print("upload", r.status_code, r.text[:300])
        r.raise_for_status()
        print("BANCO_BOGOTA.xlsx actualizado in-place")


if __name__ == "__main__":
    main()
