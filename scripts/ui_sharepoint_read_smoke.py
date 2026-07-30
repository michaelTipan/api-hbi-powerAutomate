#!/usr/bin/env python
"""Smoke read-only contra sandbox SharePoint.

DESHABILITADO por defecto. No forma parte de pytest.

Uso (solo con autorización explícita):

  set UI_SHAREPOINT_SMOKE=1
  set ACTIVE_ENVIRONMENT=sandbox
  # overlay sandbox ya aplicado vía switch-env
  python scripts/ui_sharepoint_read_smoke.py --bank banco_bancolombia

Solo GET/list/download. Sin mutaciones.
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sys


def main() -> int:
    if (os.getenv("UI_SHAREPOINT_SMOKE") or "").strip() != "1":
        print(
            "Smoke deshabilitado. Exporte UI_SHAREPOINT_SMOKE=1 para ejecutar "
            "(solo sandbox, solo lectura).",
            file=sys.stderr,
        )
        return 2

    if (os.getenv("ACTIVE_ENVIRONMENT") or "").strip().lower() != "sandbox":
        print("Fail-closed: ACTIVE_ENVIRONMENT debe ser sandbox.", file=sys.stderr)
        return 2

    parser = argparse.ArgumentParser()
    parser.add_argument("--bank", default="banco_bancolombia")
    args = parser.parse_args()

    async def _run() -> None:
        from app.adapters.secondary.ms_graph_client import MsGraphClient
        from app.adapters.secondary.ui_sharepoint_read import UiSharePointReadAdapter
        from app.application.ui.process_query import UiProcessQueryService

        # MsGraphClient implementa get/get_bytes; el adaptador tipa UiGraphHttpReadPort.
        http = MsGraphClient()
        reader = UiSharePointReadAdapter(http)  # type: ignore[arg-type]
        detail = await UiProcessQueryService(reader).project_bank(args.bank)
        print("process_key=", detail.process_key)
        print("operational_status=", detail.operational_status)
        print("steps=", [(s.name, s.status) for s in detail.steps])

    asyncio.run(_run())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
