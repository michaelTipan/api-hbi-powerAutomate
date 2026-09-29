"""Readiness de fase 3 con lectura de asientos y decisiones del registro."""

from __future__ import annotations

import asyncio
from datetime import date
from decimal import Decimal
from io import BytesIO
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock

import pytest
from openpyxl import Workbook

import app.application.ui.merge_readiness as mr
from app.application.services.amortization_decisions import (
    DecisionsRegistryUnavailableError,
    add_confirmation,
    add_exclusion,
    add_unused_asiento,
    empty_registry,
)
from app.application.services.review_schema import (
    AplicacionPagosCols,
    InternalPathCols,
    ReviewSheets,
    TipoAplicacionConfirmado,
)
from tests.test_finalize_validation import make_distrib_row
from tests.ui_fixtures import make_snap

PK = "payment-validation|banco_bancolombia|2026-07-29|abc-123"
HIST = "hist/demo.xlsx"


def _folder(credito: str) -> str:
    return f"clientes/C{credito}/CREDITO # {credito}/ASIENTOS CONTABLES CRED {credito}"


def _hist(pagos: list[dict[str, Any]]) -> bytes:
    wb = Workbook()
    ws = wb.active
    assert ws is not None
    ws.title = ReviewSheets.APLICACION_PAGOS
    ws.append(
        list(AplicacionPagosCols.HEADERS)
        + ["_ruta_extracto", "_ruta_unidad_credito", InternalPathCols.RUTA_ASIENTOS_CONTABLES, "_ruta_tabla_amortizacion"]
    )
    for p in pagos:
        row, _ = make_distrib_row(
            id_pago=p["id_pago"],
            cliente=p.get("cliente", f"Cliente {p['credito']}"),
            credito=p["credito"],
            fecha_banco=p.get("fecha", date(2026, 7, 29)),
            monto_banco=p["monto"],
            tipo_aplicacion=p.get("tipo", TipoAplicacionConfirmado.PAGO_OBLIGACION_ACTUAL),
            ruta_pdf_internal=f"extractos/{p['credito']}.pdf",
        )
        ws.append(list(row) + [_folder(p["credito"]), f"clientes/C{p['credito']}/TABLA.xlsx"])
    buf = BytesIO()
    wb.save(buf)
    return buf.getvalue()


def _asiento_pdf(amount: float, *, credit: str, fecha: str = "29/07/2026") -> bytes:
    from reportlab.pdfgen.canvas import Canvas

    buf = BytesIO()
    canvas = Canvas(buf)
    amt = f"{float(amount):,.2f}"
    canvas.drawString(50, 740, f"Comprobante 1 Fecha {fecha}")
    canvas.drawString(50, 720, f"{amt} PAGO: No.Rad. {credit} Linea 544 1 11100505")
    canvas.drawString(50, 700, f"{amt} PAGO: No.Rad. {credit} Linea 544 1 13410519")
    canvas.save()
    return buf.getvalue()


class FakeDrive:
    def __init__(self, hist: bytes) -> None:
        self.hist = hist
        self.folders: dict[str, dict[str, bytes]] = {}
        self.processed: dict[str, list[str]] = {}
        self.downloads: list[str] = []

    def add(self, credito: str, name: str, blob: bytes) -> str:
        self.folders.setdefault(_folder(credito), {})[name] = blob
        return f"{_folder(credito)}/{name}"

    async def download(self, _g, _s, _d, path: str) -> bytes:
        self.downloads.append(path)
        if path == HIST:
            return self.hist
        for folder, files in self.folders.items():
            for name, blob in files.items():
                if path == f"{folder}/{name}":
                    return blob
        raise FileNotFoundError(path)

    async def children(self, _g, _s, _d, path: str) -> list[dict[str, Any]]:
        if path.endswith("/PROCESADOS"):
            base = path[: -len("/PROCESADOS")]
            return [
                {"name": n, "file": {}, "lastModifiedDateTime": "2026-07-20T10:00:00Z"}
                for n in self.processed.get(base, [])
            ]
        return [
            {"name": n, "file": {}, "eTag": f'"{n}"', "webUrl": f"https://sp/{n}"}
            for n in self.folders.get(path, {})
        ]


@pytest.fixture(autouse=True)
def _clean(monkeypatch: pytest.MonkeyPatch):
    mr.clear_verification_caches()
    monkeypatch.setattr(mr, "resolve_sharepoint_from_env", AsyncMock(return_value={"site_id": "s", "drive_id": "d"}))
    monkeypatch.setattr(mr, "control_indicates_already_merged", lambda _s: False)
    monkeypatch.setattr(mr, "get_job_manager", lambda: SimpleNamespace(has_completed_merge=lambda _pk: False))

    async def _no_facts(*_a, **_k):
        return None

    monkeypatch.setattr(mr, "_load_table_facts", _no_facts)
    yield
    mr.clear_verification_caches()


def _run(monkeypatch, drive: FakeDrive, *, registry: Any = None, registry_path: str = ""):
    monkeypatch.setattr(mr, "_graph_download_by_path", drive.download)
    monkeypatch.setattr(mr, "_list_drive_folder_children", drive.children)

    async def _load(*_a, **_k):
        if isinstance(registry, Exception):
            raise registry
        return registry

    monkeypatch.setattr(mr, "load_registry_for_process", _load)
    snap = make_snap(
        estado_proceso="PENDIENTE_ASIENTOS",
        historical_file_path=HIST,
        email_pdf_path="out/correo.pdf",
        process_key=PK,
        decisions_registry_path=registry_path or ("logs/decisiones.json" if registry is not None else ""),
    )
    return asyncio.run(mr.assess_merge_readiness(AsyncMock(), snap, "banco_bancolombia"))


def _registry() -> dict[str, Any]:
    return empty_registry(process_key=PK, bank_code="banco_bancolombia", report_date_iso="2026-07-29")


def test_happy_path_reads_asiento_and_is_ready(monkeypatch):
    drive = FakeDrive(_hist([{"id_pago": "P1", "credito": "100", "monto": 1000}]))
    drive.add("100", "asiento_100.pdf", _asiento_pdf(1000, credit="100"))
    r = _run(monkeypatch, drive)
    assert r.status == "ready"
    v = r.verification
    assert v["credits_total"] == 1 and v["credits_ready"] == 1
    g = v["groups"][0]
    assert g["segun_asientos"] == 1000
    assert g["asientos"][0]["web_url"] == "https://sp/asiento_100.pdf"
    assert g["asientos"][0]["fecha"] == "2026-07-29"
    dto = mr.readiness_to_ui(r)
    assert dto.verification is not None and dto.status == "ready"


def test_bank_greater_blocks_with_summary_message_then_confirmation_unblocks(monkeypatch):
    drive = FakeDrive(_hist([{"id_pago": "P1", "credito": "100", "monto": 1000}]))
    drive.add("100", "asiento_100.pdf", _asiento_pdf(990, credit="100"))
    r = _run(monkeypatch, drive)
    assert r.status == "incomplete"
    assert r.user_message == "0 de 1 créditos listos para consolidar."
    assert r.missing_items == []
    assert [m["code"] for m in r.verification["groups"][0]["motivos"]] == ["DIFERENCIA_BANCO"]

    reg, _ = add_confirmation(
        _registry(), key="100|2026-07-29", credits=["100"], clientes={}, fecha_banco="2026-07-29",
        monto_banco="1000", monto_asientos="990", nota="", quien="op", fase="consolidacion",
    )
    r2 = _run(monkeypatch, drive, registry=reg)
    assert r2.status == "ready"


def test_unreadable_registry_is_fail_closed(monkeypatch):
    drive = FakeDrive(_hist([{"id_pago": "P1", "credito": "100", "monto": 1000}]))
    drive.add("100", "asiento_100.pdf", _asiento_pdf(1000, credit="100"))
    r = _run(
        monkeypatch, drive, registry=DecisionsRegistryUnavailableError("x", "boom"),
        registry_path="logs/decisiones.json",
    )
    assert r.status == "unknown"
    assert "registro de decisiones" in r.user_message


def test_excluded_credit_does_not_block_the_rest(monkeypatch):
    drive = FakeDrive(
        _hist(
            [
                {"id_pago": "P1", "credito": "100", "monto": 1000},
                {"id_pago": "P2", "credito": "200", "monto": 500},
            ]
        )
    )
    drive.add("100", "asiento_100.pdf", _asiento_pdf(1000, credit="100"))
    r = _run(monkeypatch, drive)
    assert r.status == "incomplete"
    reg, _ = add_exclusion(
        _registry(), credits=["200"], clientes={}, id_pagos=["P2"], tablas={},
        motivo_codigo="FALTA_ASIENTO", nota="", quien="op", fase="consolidacion",
    )
    r2 = _run(monkeypatch, drive, registry=reg)
    assert r2.status == "ready"
    assert r2.missing_items == []
    assert r2.expected_groups == 1
    assert r2.verification["credits_excluded"] == 1
    assert r2.verification["consolidados"] == 1


def test_all_excluded_offers_undo_or_cancel(monkeypatch):
    drive = FakeDrive(_hist([{"id_pago": "P1", "credito": "100", "monto": 1000}]))
    reg, _ = add_exclusion(
        _registry(), credits=["100"], clientes={}, id_pagos=["P1"], tablas={},
        motivo_codigo="FALTA_ASIENTO", nota="", quien="op", fase="consolidacion",
    )
    r = _run(monkeypatch, drive, registry=reg)
    assert r.status == "incomplete"
    assert "Todos los créditos están excluidos" in r.user_message


def test_asiento_of_other_credit_then_marked_unused_is_skipped(monkeypatch):
    drive = FakeDrive(_hist([{"id_pago": "P1", "credito": "100", "monto": 1000}]))
    drive.add("100", "asiento_100.pdf", _asiento_pdf(1000, credit="100"))
    otro = drive.add("100", "asiento_100_b.pdf", _asiento_pdf(700, credit="999"))
    r = _run(monkeypatch, drive)
    assert r.status == "incomplete"
    assert [m["code"] for m in r.verification["groups"][0]["motivos"]] == ["ASIENTO_OTRO_CREDITO"]

    reg, _ = add_unused_asiento(
        _registry(), path=otro, credito_carpeta="100", nota="", quien="op",
        motivo_codigo="OTRO_CREDITO", fase="consolidacion",
    )
    drive.downloads.clear()
    mr.clear_verification_caches()
    r2 = _run(monkeypatch, drive, registry=reg)
    assert r2.status == "ready"
    assert otro not in drive.downloads
    states = {a["name"]: a["state"] for a in r2.verification["groups"][0]["asientos"]}
    assert states == {"asiento_100.pdf": "usable", "asiento_100_b.pdf": "no_usado"}


def test_already_processed_name_is_shown_but_ignored(monkeypatch):
    drive = FakeDrive(_hist([{"id_pago": "P1", "credito": "100", "monto": 1000}]))
    drive.add("100", "asiento_100.pdf", _asiento_pdf(1000, credit="100"))
    drive.add("100", "asiento_100_viejo.pdf", _asiento_pdf(1000, credit="100"))
    drive.processed[_folder("100")] = ["asiento_100_viejo.pdf"]
    r = _run(monkeypatch, drive)
    assert r.status == "ready"
    viejo = next(a for a in r.verification["groups"][0]["asientos"] if a["name"] == "asiento_100_viejo.pdf")
    assert viejo["state_label"] == "Ya aplicado el 20/07"


def test_shared_credit_folder_is_listed_and_downloaded_once(monkeypatch):
    drive = FakeDrive(
        _hist(
            [
                {"id_pago": "P1", "credito": "322", "monto": 1000},
                {"id_pago": "P2", "credito": "322", "monto": 1000},
            ]
        )
    )
    path = drive.add("322", "asiento_322.pdf", _asiento_pdf(2000, credit="322"))
    r = _run(monkeypatch, drive)
    assert r.status == "ready"
    assert drive.downloads.count(path) == 1
    # Mismo crédito y misma fecha: un solo consolidado para las dos consignaciones.
    assert r.verification["consolidados"] == 1


def test_type_question_uses_table_facts(monkeypatch):
    drive = FakeDrive(_hist([{"id_pago": "P1", "credito": "100", "monto": 3000}]))
    drive.add("100", "asiento_100.pdf", _asiento_pdf(3000, credit="100"))

    async def _facts(*_a, **_k):
        return {"cuota": Decimal("1000.00"), "saldo_capital": Decimal("900000.00")}

    monkeypatch.setattr(mr, "_load_table_facts", _facts)
    r = _run(monkeypatch, drive)
    g = r.verification["groups"][0]
    assert [m["code"] for m in g["motivos"]] == ["CONFIRMAR_TIPO"]
    assert g["tipo"]["sugerido"] == "PAGO CUOTA + ABONO A CAPITAL"
    assert r.status == "incomplete"
