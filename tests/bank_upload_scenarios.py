"""Escenarios compartidos del Excel de carga del banco (golden de Generate).

Se usan para comprobar que agregar columnas opcionales o alias al Excel de
carga no cambia las filas del Excel de revisión que ya se generaban.
"""

from __future__ import annotations

import asyncio
import json
from datetime import date, datetime
from pathlib import Path
from typing import Any
from unittest import mock

import openpyxl

from app.application.services.review_schema import ReviewSheets
from app.application.use_cases.payment_validation_generate import generate_payment_validation
from tests.test_generate_validation import (
    MockGraphClient,
    _fake_fecha_limite_from_marker_bytes,
    create_excel,
    load_generated_workbook,
    make_pdf_extractor_mock,
    set_env_vars,
    setup_client_structure,
    sheet_to_dicts,
)

GOLDEN_PATH = Path(__file__).parent / "fixtures" / "golden_generate_review_rows.json"

PROCESS_DATE = date(2025, 12, 31)

# Fila por fila: (Fecha, Crédito, Concepto, Transacción)
BASE_ROWS: list[list[Any]] = [
    [datetime(2025, 12, 23), 6500739, "GEOEXCON", "PAGO PSE"],
    [datetime(2025, 12, 30), 5000000, "EQUINORTE", "TRANSFERENCIA"],
    [datetime(2025, 12, 30), 1200000, "Partida x identificar", ""],
    [datetime(2025, 12, 30), 800000, "CLIENTE INEXISTENTE", ""],
    [datetime(2025, 12, 23), 18826879, "GEOEXCON", "PAGO SUCURSAL"],
]

STANDARD_HEADERS = ["Fecha", "Crédito", "Concepto", "Transacción"]


def build_bank_excel(
    headers: list[str] | None = None,
    rows: list[list[Any]] | None = None,
) -> bytes:
    return create_excel(list(headers or STANDARD_HEADERS), [list(r) for r in (rows or BASE_ROWS)])


def _json_value(value: Any) -> Any:
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, float) and value.is_integer():
        return int(value)
    return value


def snapshot_review_workbook(wb: openpyxl.Workbook) -> dict[str, Any]:
    """Filas de Aplicacion_Pagos y Errores con los ID Pago reemplazados por su orden."""
    id_map: dict[str, str] = {}

    def _stable_id(raw: Any) -> Any:
        key = str(raw or "").strip()
        if not key:
            return raw
        if key not in id_map:
            id_map[key] = f"PAGO_{len(id_map) + 1}"
        return id_map[key]

    out: dict[str, Any] = {}
    for sheet in (ReviewSheets.APLICACION_PAGOS, ReviewSheets.ERRORES):
        rows = sheet_to_dicts(wb[sheet], marker="ID Pago")
        normalized: list[dict[str, Any]] = []
        for row in rows:
            item = {str(k): _json_value(v) for k, v in row.items()}
            if "ID Pago" in item:
                item["ID Pago"] = _stable_id(item["ID Pago"])
            normalized.append(item)
        out[sheet] = normalized
    return out


def run_generate_snapshot(
    bank_bytes: bytes,
    *,
    bank_code: str = "banco_bogota",
) -> dict[str, Any]:
    async def _run() -> dict[str, Any]:
        set_env_vars()
        client = MockGraphClient()
        client.children = []
        setup_client_structure(client)
        client.downloaded_files["banco.xlsx"] = bank_bytes
        with mock.patch(
            "app.application.use_cases.payment_validation_generate.extract_total_a_pagar_from_pdf",
            side_effect=make_pdf_extractor_mock(client),
        ), mock.patch(
            "app.application.use_cases.payment_validation_generate.extract_fecha_limite_pago_from_pdf",
            side_effect=_fake_fecha_limite_from_marker_bytes(),
        ):
            await generate_payment_validation(client, PROCESS_DATE, bank_code=bank_code)
        return snapshot_review_workbook(load_generated_workbook(client))

    return asyncio.run(_run())


def load_golden() -> dict[str, Any]:
    return json.loads(GOLDEN_PATH.read_text(encoding="utf-8"))


def write_golden() -> None:
    data = {
        bank: run_generate_snapshot(build_bank_excel(), bank_code=bank)
        for bank in ("banco_bogota", "banco_bancolombia")
    }
    GOLDEN_PATH.write_text(
        json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
