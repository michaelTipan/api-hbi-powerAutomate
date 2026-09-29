"""Flujo completo dry-run → apply con un crédito problemático y su exclusión.

Un crédito con problema bloquea la escritura de todo el lote (nada se escribe mientras
quede un problema sin resolver); al excluirlo, el resto se aplica y el proceso queda con
amortización parcial, sin tocar la tabla del crédito excluido.
"""

from __future__ import annotations

import asyncio
import json
from datetime import date
from types import SimpleNamespace
from typing import Any

import pytest

from app.application.services import amortization_decisions as reg_mod
from app.application.services.amortization_decisions import add_exclusion, empty_registry
from app.application.use_cases.amortization_fill_apply import run_amortization_fill_apply
from app.application.use_cases.amortization_fill_dry_run import run_amortization_fill_dry_run
from tests.test_amortization_fill_apply import MockGraphApply
from tests.test_amortization_fill_dry_run import (
    _accounting_text,
    _amort_table_date_at_row,
    _asiento_pdf_placeholder,
    _hist_bytes_multi_credit,
    _ibr_bytes,
)

FECHA = date(2026, 4, 22)
REG_PATH = "LOGS/2026/04/22/decisiones_banco_bogota_2026-04-22_abcd1234.json"
TIPO = "PAGO DE OBLIGACIÓN ACTUAL"


@pytest.fixture(autouse=True)
def env_sharepoint(monkeypatch):
    monkeypatch.setenv("GRAPH_SHAREPOINT_SITE_SEARCH", "TEST")
    monkeypatch.setenv("GRAPH_SHAREPOINT_DRIVE_NAME", "")
    monkeypatch.setenv("GRAPH_PAYMENT_VALIDATION_CONTROL_PATH", "CTL")
    monkeypatch.setenv("GRAPH_PAYMENT_VALIDATION_LOGS_PATH", "LOGS")
    monkeypatch.setenv("GRAPH_IBR_DIARIO_PATH", "CTL/IBR_DIARIO.xlsx")
    reg_mod.clear_registry_cache()
    yield
    reg_mod.clear_registry_cache()


@pytest.fixture
def control_updates(monkeypatch):
    updates: list[dict[str, Any]] = []

    async def _update(*_a, **k):
        updates.append(dict(k.get("updates") or {}))

    monkeypatch.setattr(
        "app.application.use_cases.amortization_fill_apply.update_process_control_row2", _update
    )
    return updates


def _registry_path_in_control(monkeypatch, path: str) -> None:
    async def _snap(*_a, **_k):
        return SimpleNamespace(estado_proceso="", decisions_registry_path=path, merge_skipped_count=None)

    monkeypatch.setattr(
        "app.application.use_cases.amortization_fill_dry_run.read_process_control_snapshot", _snap
    )


def _asiento(credito: str) -> str:
    return f"clientes/CLIENTE {credito}/CREDITO # {credito}/ASIENTOS CONTABLES CRED {credito}/a{credito}.pdf"


def _files() -> dict[str, bytes]:
    outputs = []
    # P1 cuadra (asiento 50M = banco 50M); P2 no (asiento 50M > banco 40M).
    for id_pago, credito, monto in (("P1", "258", 50_000_000.0), ("P2", "300", 40_000_000.0)):
        outputs.append(
            {
                "id_pago": id_pago,
                "cliente": f"CLIENTE {credito}",
                "credito": credito,
                "tipo_aplicacion_original": TIPO,
                "monto_banco": monto,
                "fecha_banco": FECHA.isoformat(),
                "creditos_seleccionados": [credito],
                "credit_items": [
                    {
                        "credito": credito,
                        "tipo_aplicacion_original": TIPO,
                        "ruta_tabla_amortizacion": f"TABLAS/amort_{credito}.xlsx",
                        "asiento_pdf_paths": [_asiento(credito)],
                        "extracto_pdf_paths": [f"clientes/CLIENTE {credito}/extracto.pdf"],
                    }
                ],
                "output_relative_path": f"OUT/{id_pago}.pdf",
            }
        )
    manifest = {
        "report_date_iso": FECHA.isoformat(),
        "historico_excel_path": "HIST/cartera.xlsx",
        "outputs": outputs,
    }
    return {
        "CTL/dummy.xlsx": b"x",
        f"LOGS/merge_manifest_{FECHA.isoformat()}.json": json.dumps(manifest).encode("utf-8"),
        "HIST/cartera.xlsx": _hist_bytes_multi_credit(
            [
                ("P1", "CLIENTE 258", "258", "TABLAS/amort_258.xlsx", FECHA),
                ("P2", "CLIENTE 300", "300", "TABLAS/amort_300.xlsx", FECHA),
            ],
            monto_banco=50_000_000.0,
        ),
        "TABLAS/amort_258.xlsx": _amort_table_date_at_row(FECHA, 8),
        "TABLAS/amort_300.xlsx": _amort_table_date_at_row(FECHA, 8),
        _asiento("258"): _asiento_pdf_placeholder(),
        _asiento("300"): _asiento_pdf_placeholder(),
        "CTL/IBR_DIARIO.xlsx": _ibr_bytes(),
    }


def _patch_text(monkeypatch) -> None:
    text = _accounting_text()
    for mod in (
        "app.application.use_cases.amortization_fill_dry_run.extract_text_from_pdf",
        "app.application.services.abono_dry_run.extract_text_from_pdf",
    ):
        monkeypatch.setattr(mod, lambda _b: text)


def _dry(g):
    return asyncio.run(
        run_amortization_fill_dry_run(
            g,
            report_date_iso=FECHA.isoformat(),
            historical_file_path="HIST/cartera.xlsx",
            update_process_control=False,
        )
    )


def _apply(g):
    return asyncio.run(
        run_amortization_fill_apply(
            g, report_date_iso=FECHA.isoformat(), historical_file_path="HIST/cartera.xlsx"
        )
    )


def _store_exclusion(g: MockGraphApply, credito: str) -> None:
    reg = empty_registry(process_key="", bank_code="banco_bogota", report_date_iso=FECHA.isoformat())
    reg, _ = add_exclusion(
        reg, credits=[credito], clientes={credito: f"CLIENTE {credito}"}, id_pagos=["P2"],
        tablas={credito: f"TABLAS/amort_{credito}.xlsx"}, motivo_codigo="FALTA_ASIENTO",
        nota="", quien="operador",
    )
    g.files[REG_PATH] = json.dumps(reg).encode("utf-8")


def test_credito_con_problema_bloquea_la_escritura_del_lote(monkeypatch, control_updates):
    _patch_text(monkeypatch)
    g = MockGraphApply(_files())
    dry = _dry(g)
    assert dry["can_apply"] is False
    conc = dry["conciliation"]
    assert [p["code"] for p in conc["problems"]] == ["CONCILIACION_ASIENTOS_MAYOR_BANCO"]
    assert conc["problems"][0]["credits"] == ["300"]
    by_credit = {it["credito"]: it for it in dry["items"]}
    assert by_credit["258"]["application_status"] == "WOULD_APPLY"
    assert by_credit["300"]["error_code"] == "CONCILIACION_ASIENTOS_MAYOR_BANCO"

    applied = _apply(g)
    assert applied["status"] != "ok"
    assert "TABLAS/amort_258.xlsx" not in g.uploaded
    assert "TABLAS/amort_300.xlsx" not in g.uploaded


def test_exclusion_aplica_el_resto_y_deja_amortizacion_parcial(monkeypatch, control_updates):
    _patch_text(monkeypatch)
    g = MockGraphApply(_files())
    _store_exclusion(g, "300")
    _registry_path_in_control(monkeypatch, REG_PATH)

    dry = _dry(g)
    assert dry["can_apply"] is True
    conc = dry["conciliation"]
    assert conc["problems"] == []
    assert conc["excluded_credits"] == ["300"]
    assert conc["decisions_registry_path"] == REG_PATH
    assert [it["credito"] for it in dry["items"]] == ["258"]

    applied = _apply(g)
    assert applied["status"] == "partial"
    assert applied["partial_only_exclusions"] is True
    assert "TABLAS/amort_258.xlsx" in g.uploaded
    assert "TABLAS/amort_300.xlsx" not in g.uploaded
    assert applied["all_expected_events_completed"] is True
    assert [e["credito"] for e in applied["excluded_credit_events"]] == ["300"]
    assert "300 · CLIENTE 300" in applied["user_message"]
    assert "cierre el proceso con amortización incompleta" in applied["next_action"]
    assert applied.get("operational_issues") in (None, [])
    assert any(u.get("EstadoProceso") == "AMORTIZACION_PARCIAL" for u in control_updates)
    # Tras procesar, la exclusión queda bloqueada (ya no se puede deshacer).
    stored = json.loads(g.files[REG_PATH].decode("utf-8"))
    assert stored["exclusions"][0]["locked_at"]


def test_todos_los_creditos_excluidos_no_escribe_y_queda_parcial(monkeypatch, control_updates):
    _patch_text(monkeypatch)
    g = MockGraphApply(_files())
    reg = empty_registry(process_key="", bank_code="banco_bogota", report_date_iso=FECHA.isoformat())
    for credito in ("258", "300"):
        reg, _ = add_exclusion(
            reg, credits=[credito], clientes={}, id_pagos=[], tablas={},
            motivo_codigo="APLICACION_MANUAL", nota="", quien="operador",
        )
    g.files[REG_PATH] = json.dumps(reg).encode("utf-8")
    _registry_path_in_control(monkeypatch, REG_PATH)

    applied = _apply(g)
    assert applied["status"] == "partial"
    assert g.uploaded.get("TABLAS/amort_258.xlsx") is None
    assert g.uploaded.get("TABLAS/amort_300.xlsx") is None
    assert "No se actualizó ninguna tabla" in applied["user_message"]


def test_registro_declarado_pero_ilegible_bloquea_todo_el_lote(monkeypatch, control_updates):
    _patch_text(monkeypatch)
    g = MockGraphApply(_files())
    _registry_path_in_control(monkeypatch, REG_PATH)  # la ruta existe en Control, el archivo no
    dry = _dry(g)
    assert dry["can_apply"] is False
    assert dry["decisions_registry_block"]["error_code"] == "DECISIONS_REGISTRY_UNAVAILABLE"
    applied = _apply(g)
    assert applied["status"] != "ok"
    assert not any(k.startswith("TABLAS/") for k in g.uploaded)
