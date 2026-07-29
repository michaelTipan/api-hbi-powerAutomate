"""
Prueba one-shot: ¿puede esta app crear (y borrar) una Lista en SharePoint?

No forma parte del producto. No crea INDICE_EXTRACTOS.
Lista temporal: _HBI_CAPABILITY_TEST_LIST_DELETE_ME

Uso en App Service (Kudu), con Key Vault / MI ya configurados:
  cd /home/site/wwwroot
  PYTHONPATH=... python3 scripts/probe_sharepoint_list_capability.py
"""

from __future__ import annotations

import asyncio
import os
import sys

# Arranque desde wwwroot
sys.path.insert(0, os.getcwd())

from dotenv import load_dotenv

load_dotenv()

from app.adapters.secondary.ms_graph_client import MsGraphClient
from app.application.sharepoint_resolution import resolve_sharepoint_from_env

TEST_LIST_DISPLAY_NAME = "_HBI_CAPABILITY_TEST_LIST_DELETE_ME"


async def main() -> int:
    import httpx

    graph = MsGraphClient()
    ctx = await resolve_sharepoint_from_env(graph)
    site_id = ctx["site_id"]
    print(f"SITE_OK site_id={site_id[:32]}...")

    create_body = {
        "displayName": TEST_LIST_DISPLAY_NAME,
        "description": "Prueba temporal HBI — borrar si queda huérfana",
        "list": {"template": "genericList"},
    }
    try:
        created, status = await graph.post_json(f"/sites/{site_id}/lists", create_body)
    except httpx.HTTPStatusError as exc:
        detail = (exc.response.text or "")[:800]
        print(f"CREATE_FAIL http={exc.response.status_code}")
        print(f"CREATE_FAIL_BODY={detail}")
        print("CAPABILITY_RESULT=FAIL_NO_CREATE_PERMISSION_OR_ERROR")
        return 2

    list_id = str(created.get("id") or "")
    if not list_id:
        print(f"CREATE_FAIL missing_id body={created}")
        return 2
    print(f"CREATE_OK http={status} list_id={list_id}")

    fetched = await graph.get(f"/sites/{site_id}/lists/{list_id}")
    print(f"READ_OK displayName={fetched.get('displayName')!r}")

    try:
        await graph.delete(f"/sites/{site_id}/lists/{list_id}")
        print("DELETE_OK")
    except httpx.HTTPStatusError as exc:
        print(f"DELETE_FAIL http={exc.response.status_code} {(exc.response.text or '')[:400]}")
        print("CAPABILITY_RESULT=PARTIAL_CREATE_OK_DELETE_FAIL")
        print(f"MANUAL_CLEANUP_REQUIRED list={TEST_LIST_DISPLAY_NAME} id={list_id}")
        return 4

    try:
        await graph.get(f"/sites/{site_id}/lists/{list_id}")
        print("DELETE_VERIFY_FAIL still_exists")
        return 3
    except httpx.HTTPStatusError as exc:
        print(f"DELETE_VERIFY_OK gone http={exc.response.status_code}")

    print("CAPABILITY_RESULT=PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
