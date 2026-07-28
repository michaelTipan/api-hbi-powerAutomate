"""
Prueba puntual: crear cadena de carpetas contables para 2027-07-28
(hoy del calendario, año +1) en el sitio de Contabilidad de producción.

Usa la misma lógica que Merge (AccountingDestinationResolver):
  {año}/TESORERIA {año}/{MM MES}/[carpeta banco]

La carpeta del banco normalmente NO se crea en producción; en esta prueba,
si falta bajo el mes nuevo, se crea solo para poder subir un PDF de humo.
El usuario borrará el árbol 2027 manualmente.
"""

from __future__ import annotations

import asyncio
import sys
from datetime import date
from pathlib import Path

from dotenv import load_dotenv
import os

ROOT = Path(__file__).resolve().parents[1]
ENV_FILE = ROOT.parent / "api-hbi-powerAutomate.env"
sys.path.insert(0, str(ROOT))

load_dotenv(ENV_FILE)

# Sitio Contabilidad (producción) — en sandbox suele ir vacío.
os.environ["GRAPH_ACCOUNTING_SITE_HOSTNAME"] = "gecolsacat.sharepoint.com"
os.environ["GRAPH_ACCOUNTING_SITE_PATH"] = "sites/HBICapitalContabilidad"
os.environ.setdefault("GRAPH_ACCOUNTING_DRIVE_NAME", "Documentos")
os.environ.setdefault("GRAPH_ACCOUNTING_BOGOTA_FOLDER_NAME", "INGRESOS BANCO BOGOTA")

from app.adapters.secondary.ms_graph_client import MsGraphClient
from app.application.services.accounting_destination import (
    AccountingDestinationError,
    AccountingDestinationResolver,
    build_accounting_month_segments,
)
from app.application.sharepoint_resolution import (
    encode_graph_drive_path,
    resolve_accounting_context,
)

# Minimal PDF válido.
TINY_PDF = (
    b"%PDF-1.4\n"
    b"1 0 obj<< /Type /Catalog /Pages 2 0 R >>endobj\n"
    b"2 0 obj<< /Type /Pages /Kids [3 0 R] /Count 1 >>endobj\n"
    b"3 0 obj<< /Type /Page /Parent 2 0 R /MediaBox [0 0 200 200] >>endobj\n"
    b"xref\n0 4\n0000000000 65535 f \n0000000009 00000 n \n"
    b"0000000058 00000 n \n0000000115 00000 n \n"
    b"trailer<< /Size 4 /Root 1 0 R >>\nstartxref\n190\n%%EOF\n"
)


async def main() -> None:
    # Misma fecha civil de hoy (28 jul) pero en 2027.
    target = date(2027, 7, 28)
    bank_code = "banco_bogota"
    year, tesoreria, month = build_accounting_month_segments(target)
    print("Fecha prueba:", target.isoformat())
    print("Segmentos esperados:", year, "/", tesoreria, "/", month)

    graph = MsGraphClient()
    ctx = await resolve_accounting_context(graph)
    print("Contabilidad site_id ok, drive_id ok")

    resolver = AccountingDestinationResolver(graph, ctx["site_id"], ctx["drive_id"])

    actual_year = await resolver._ensure_folder("", year)
    print(f"OK año: {actual_year!r}")
    actual_tesoreria = await resolver._ensure_folder(actual_year, tesoreria)
    print(f"OK tesoreria: {actual_year}/{actual_tesoreria}")
    tesoreria_path = f"{actual_year}/{actual_tesoreria}"
    actual_month = await resolver._ensure_folder(tesoreria_path, month)
    month_path = f"{tesoreria_path}/{actual_month}"
    print(f"OK mes: {month_path}")

    bank_folder = os.environ["GRAPH_ACCOUNTING_BOGOTA_FOLDER_NAME"]
    try:
        actual_bank = await resolver._require_folder(month_path, bank_folder, bank_code)
        print(f"OK banco (ya existía): {month_path}/{actual_bank}")
    except AccountingDestinationError as exc:
        print(f"Banco ausente bajo el mes nuevo ({exc.code}). Creando solo para esta prueba...")
        await resolver._create_folder(month_path, bank_folder)
        actual_bank = bank_folder
        print(f"OK banco (creado prueba): {month_path}/{actual_bank}")

    dest_folder = f"{month_path}/{actual_bank}"
    pdf_name = f"PRUEBA_consolidado_merge_{target.isoformat()}_banco_bogota.pdf"
    pdf_rel = f"{dest_folder}/{pdf_name}"
    encoded = encode_graph_drive_path(pdf_rel)
    endpoint = (
        f"/sites/{ctx['site_id']}/drives/{ctx['drive_id']}/root:/{encoded}:/content"
    )
    await graph.put_bytes(endpoint, TINY_PDF, content_type="application/pdf")
    print("OK PDF humo subido:", pdf_rel)
    print("LISTO. Puede borrar manualmente la carpeta 2027 en Contabilidad.")


if __name__ == "__main__":
    asyncio.run(main())
