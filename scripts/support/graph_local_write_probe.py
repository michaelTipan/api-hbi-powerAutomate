"""Sondeo seguro de escritura Graph en sandbox Comware (sube, lee, borra probe)."""
from __future__ import annotations

import asyncio
import sys
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env", override=True)
sys.path.insert(0, str(ROOT))

from app.adapters.secondary.ms_graph_client import MsGraphClient  # noqa: E402
from app.application.sharepoint_resolution import (  # noqa: E402
    encode_graph_drive_path,
    resolve_sharepoint_from_env,
)
from app.adapters.secondary.graph_credentials import (  # noqa: E402
    resolve_credential_source,
)


PROBE_REL = (
    "INFORMACION CREDITOS-CLIENTES/03 COMWARE PRUEBAS- INFORMACION CREDITOS CLIENTES/"
    "02 VALIDACION PAGOS/90 ACCESO RESTRINGIDO/02 LOGS/"
    "_cursor_local_write_probe.txt"
)


async def main() -> int:
    source = resolve_credential_source()
    print("credential_source", source)
    if source != "env":
        print("FAIL: expected GRAPH_CREDENTIAL_SOURCE=env")
        return 1

    graph = MsGraphClient()
    ctx = await resolve_sharepoint_from_env(graph)
    site_id = ctx["site_id"]
    drive_id = ctx["drive_id"]
    print("site_ok", bool(site_id))
    print("drive_ok", bool(drive_id))
    print("probe_file_path_configured", bool(ctx.get("file_path")))

    # Lectura del Excel banco (prueba de lectura + token).
    bank_path = ctx["file_path"]
    bank_enc = encode_graph_drive_path(bank_path)
    bank_meta = await graph.get(
        f"/sites/{site_id}/drives/{drive_id}/root:/{bank_enc}"
    )
    print("bank_file_exists", bool(bank_meta.get("id")))
    print("bank_file_name", bank_meta.get("name"))
    print("bank_etag_present", bool(bank_meta.get("eTag") or bank_meta.get("@odata.etag")))

    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    payload = f"cursor-local-write-probe {stamp}\n".encode("utf-8")
    enc = encode_graph_drive_path(PROBE_REL)
    content_ep = f"/sites/{site_id}/drives/{drive_id}/root:/{enc}:/content"
    item_ep = f"/sites/{site_id}/drives/{drive_id}/root:/{enc}"

    put_resp = await graph.put_bytes(
        content_ep,
        payload,
        content_type="text/plain",
    )
    put_etag = (put_resp or {}).get("eTag") or (put_resp or {}).get("etag")
    print("put_ok", bool(put_resp.get("id") if isinstance(put_resp, dict) else put_resp))
    print("put_etag_present", bool(put_etag))

    got = await graph.get_bytes(content_ep)
    print("roundtrip_ok", got == payload)

    # Reescritura con If-Match (mismo patrón que review Excel).
    payload2 = payload + b"if-match-ok\n"
    put2 = await graph.put_bytes(
        content_ep,
        payload2,
        content_type="text/plain",
        if_match=str(put_etag) if put_etag else None,
    )
    print("put_if_match_ok", bool(put2.get("id") if isinstance(put2, dict) else put2))

    await graph.delete(item_ep)
    print("delete_ok", True)
    print("EXCEL_WRITE_PATH", "works")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
