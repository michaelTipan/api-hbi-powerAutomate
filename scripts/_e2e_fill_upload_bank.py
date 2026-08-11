"""Rellena BANCO_BOGOTA.xlsx local (_work) con la batería E2E y lo sube a SharePoint (mismo item_id).

Plantilla HBI controlada: columnas Fecha | Crédito | Concepto | Transacción.
Sin Tipo Aplicación (la secretaria confirma Tipo en Aplicacion_Pagos v3).
"""
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

# Filas de prueba (Fecha, Crédito, Concepto, Transacción) — plantilla HBI v3
ROWS: list[tuple[str, str, str, str]] = [
    ("23-abr", "19000171.00", "GEOEXCON", "E2E PAGO exacto 231"),
    ("22-abr", "48497024.00", "EQUINORTE", "E2E PAGO exacto 258"),
    ("15-ene", "20469925.01", "ACIMOR", "E2E negativo sin CREDITO"),
    ("23-abr", "30469925.02", "MINCIVIL", "E2E negativo sin CREDITO"),
    ("16-may", "5000000.00", "INVERSIONES Y PROYECTOS MIOS", "E2E sin extracto 318"),
    ("27-jul", "25075203.00", "AGRECAR", "E2E PAGO 37 ATRASADO"),
    ("15-abr", "32691683.00", "EQUINORTE", "E2E ADELANTADO 264"),
    ("23-abr", "24000171.00", "GEOEXCON", "E2E cuota+capital 231"),
    ("27-jul", "500000.00", "EQUINORTE", "E2E abono capital 265"),
    ("27-jul", "200000.00", "EQUINORTE", "E2E abono mora 265"),
    ("23-feb", "6514755.00", "GEOEXCON", "E2E PAGO 254"),
    ("23-abr", "1000000.00", "CLIENTE_INEXISTENTE_XYZ", "E2E nombre cliente mal"),
]


def main() -> None:
    wb = load_workbook(WORK)
    ws = wb.active
    # Cabecera HBI v3 (sobrescribe si plantilla antigua tenía Tipo Aplicación)
    headers = ["Fecha", "Crédito", "Concepto", "Transacción"]
    for c, h in enumerate(headers, start=1):
        ws.cell(1, c).value = h
    # Limpiar filas de datos previas y 5ª columna residual
    for r in range(2, ws.max_row + 1):
        for c in range(1, 8):
            ws.cell(r, c).value = None
    for i, (fecha, monto, concepto, trx) in enumerate(ROWS):
        r = 2 + i
        ws.cell(r, 1).value = fecha
        ws.cell(r, 2).value = float(monto)
        ws.cell(r, 3).value = concepto
        ws.cell(r, 4).value = trx
    buf = io.BytesIO()
    wb.save(buf)
    raw = buf.getvalue()
    WORK.write_bytes(raw)

    # Subir al item sandbox (requiere API key en entorno; no hardcodear secretos aquí)
    print(f"wrote {WORK} bytes={len(raw)} rows={len(ROWS)} headers={headers}")
    print("Upload: use existing deploy harness with X-API-Key; path must be PRUEBAS.")


if __name__ == "__main__":
    main()
