"""El job de merge respeta las decisiones de fase 3 (excluir, no corresponde, tipo)."""
from __future__ import annotations

import asyncio
import json
from datetime import date
from io import BytesIO
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
from openpyxl import Workbook
from pypdf import PdfReader

from app.application.services.amortization_decisions import (
    add_exclusion,
    add_tipo_correction,
    add_unused_asiento,
    empty_registry,
)
from app.application.services.review_schema import (
    AplicacionPagosCols,
    REVIEW_SCHEMA_VERSION,
    ReviewSheets,
    TipoAplicacionConfirmado,
    ValidarPago,
    merge_name_token_for_tipos,
)
from app.application.sharepoint_resolution import encode_graph_drive_path
from app.application.use_cases import merge_composite_validado_pdfs as m
from tests.test_finalize_validation import make_distrib_row
from tests.test_merge_composite_control_workbook import (
    _MergeGraph,
    _asiento_pdf,
    _bank_bytes,
    _tiny_pdf,
)
from tests.test_merge_verification import _pago, _row

PK = "payment-validation|banco_bogota|2026-05-12"
REG_PATH = "logs/2026-05-12/decisiones_banco_bogota_2026-05-12_x.json"


def _folder(cred: str) -> str:
    return f"clientes/EQUINORTE/CREDITO# {cred}/ASIENTOS CONTABLES CRED {cred}"


def _hist(credits_by_pago: dict[str, str]) -> bytes:
    wb = Workbook()
    ws = wb.active
    ws.title = ReviewSheets.APLICACION_PAGOS
    ws.append(
        list(AplicacionPagosCols.HEADERS)
        + ["_ruta_extracto", "_ruta_unidad_credito", "_ruta_asientos_contables"]
    )
    for id_pago, cred in credits_by_pago.items():
        row, _ = make_distrib_row(
            id_pago=id_pago,
            validar_pago=ValidarPago.SI,
            credito=cred,
            cliente="EQUINORTE",
            tipo_aplicacion=TipoAplicacionConfirmado.ABONO_A_CAPITAL,
            abono_capital=1000,
            valor_int=0,
            mora_a_aplicar=0,
            fecha_banco=date(2026, 6, 3),
        )
        ws.append(list(row) + [_folder(cred)])
    meta = wb.create_sheet(ReviewSheets.META)
    meta.append(["Campo", "Valor"])
    meta.append(["ReviewSchemaVersion", REVIEW_SCHEMA_VERSION])
    bio = BytesIO()
    wb.save(bio)
    return bio.getvalue()


def _setup(g: _MergeGraph, credits_by_pago: dict[str, str], extra_pdf: dict[str, str] | None = None):
    hist, email = "HIST/abono.xlsx", "EMAIL/mail.pdf"
    g.initial["bank/report.xlsx"] = _bank_bytes()
    g.initial[hist] = _hist(credits_by_pago)
    g.initial[email] = _tiny_pdf()
    for cred in credits_by_pago.values():
        names = [f"asiento {cred}.pdf"] + ([extra_pdf[cred]] if extra_pdf and cred in extra_pdf else [])
        g.children[_folder(cred)] = [{"name": n, "file": {}} for n in names]
        for n in names:
            g.initial[f"{_folder(cred)}/{n}"] = _asiento_pdf(1000.0, credit=cred)
    return hist, email


@pytest.fixture
def control(monkeypatch):
    monkeypatch.setenv("GRAPH_SHAREPOINT_SITE_SEARCH", "TEST_SITE")
    monkeypatch.setenv("GRAPH_SHAREPOINT_DRIVE_NAME", "TEST_DRIVE")
    monkeypatch.setenv("GRAPH_SHAREPOINT_FILE_PATH", "bank/report.xlsx")
    import app.application.use_cases.payment_validation_process_control as pc

    state: dict[str, Any] = {"updates": [], "locks": [], "registry": None}

    async def _fake_read(_g, _s, _d, *, bank_code: str):
        return SimpleNamespace(
            control_file_path="CTL/ignored.xlsx",
            estado_proceso="PENDIENTE_ASIENTOS",
            is_active=True,
            process_key=PK,
            validation_file_path="",
            historical_file_path="",
            secretary_file_path="",
            email_pdf_path="",
            notify_idempotency_key="",
            merge_manifest_path="",
            merge_idempotency_key="",
            bank_code=bank_code,
            bank_name="",
            decisions_registry_path=REG_PATH,
        )

    async def _fake_update(_g, _s, _d, *, bank_code: str, updates: dict):
        state["updates"].append(dict(updates))
        return True

    async def _fake_resolve(_g, _a: str, _b: str, _p: str):
        return {
            "site_id": "s1",
            "drive_id": "d1",
            "path_encoded": encode_graph_drive_path("bank/report.xlsx"),
            "file_path": "bank/report.xlsx",
        }

    async def _fake_load(_g, _s, _d, *, registry_path: str, process_key: str):
        assert registry_path == REG_PATH and process_key == PK
        return state["registry"]

    async def _fake_lock(_g, _s, _d, **kwargs):
        state["locks"].append(kwargs)

    monkeypatch.setattr(pc, "read_process_control_snapshot", _fake_read)
    monkeypatch.setattr(pc, "update_process_control_row2", _fake_update)
    monkeypatch.setattr(m, "resolve_sharepoint_path", _fake_resolve)
    monkeypatch.setattr(m, "_load_merge_decisions_registry", _fake_load)
    monkeypatch.setattr(m, "_lock_consolidation_decisions_best_effort", _fake_lock)
    return state


def _run(g: _MergeGraph, hist: str, email: str):
    ctx = {"site_id": "s1", "drive_id": "d1", "path_encoded": "x", "file_path": "bank/report.xlsx"}

    async def run():
        with patch(
            "app.application.use_cases.merge_composite_validado_pdfs.resolve_sharepoint_from_env",
            new_callable=AsyncMock,
            return_value=ctx,
        ):
            return await m.merge_composite_validado_pdfs(
                g, bank_code="banco_bogota", historical_file_path=hist, email_pdf_path=email
            )

    return asyncio.run(run())


def _manifest(g: _MergeGraph) -> dict[str, Any]:
    key = next(k for k in g.uploaded if k.endswith(".json") and "merge_manifest" in k)
    return json.loads(g.uploaded[key].decode("utf-8"))


def _registry() -> dict[str, Any]:
    return empty_registry(process_key=PK, bank_code="banco_bogota", report_date_iso="2026-05-12")


def test_sin_decisiones_el_merge_no_cambia(control):
    g = _MergeGraph()
    hist, email = _setup(g, {"AB1": "258", "AB2": "265"})
    result = _run(g, hist, email)
    assert result.merge_control_status == "CONSOLIDADO"
    assert result.outputs_count == 2
    manifest = _manifest(g)
    assert manifest["excluded_groups"] == []
    assert control["locks"] == []


def test_credito_excluido_en_fase_3_no_se_consolida_y_queda_en_el_manifest(control):
    reg, _ = add_exclusion(
        _registry(), credits=["265"], clientes={"265": "EQUINORTE"}, id_pagos=["AB2"], tablas={},
        motivo_codigo="FALTA_ASIENTO", nota="", quien="op", fase="consolidacion",
    )
    control["registry"] = reg
    g = _MergeGraph()
    hist, email = _setup(g, {"AB1": "258", "AB2": "265"})
    result = _run(g, hist, email)
    assert result.merge_control_status == "CONSOLIDADO"
    assert [o.id_pago for o in result.outputs] == ["AB1"]
    manifest = _manifest(g)
    assert manifest["decisions_registry_path"] == REG_PATH
    assert manifest["excluded_groups"][0]["id_pago"] == "AB2"
    assert manifest["excluded_groups"][0]["creditos"] == ["265"]
    assert manifest["excluded_groups"][0]["motivo_codigo"] == "FALTA_ASIENTO"
    assert len(control["locks"]) == 1
    assert control["locks"][0]["registry_path"] == REG_PATH


def test_todos_excluidos_no_consolida(control):
    reg, _ = add_exclusion(
        _registry(), credits=["258"], clientes={}, id_pagos=["AB1"], tablas={},
        motivo_codigo="FALTA_ASIENTO", nota="", quien="op", fase="consolidacion",
    )
    control["registry"] = reg
    g = _MergeGraph()
    hist, email = _setup(g, {"AB1": "258"})
    with pytest.raises(ValueError, match="merge_all_credits_excluded"):
        _run(g, hist, email)
    assert control["updates"][-1]["EstadoProceso"] == "ERROR_MERGE"
    assert control["locks"] == []


def test_asiento_no_corresponde_no_entra_al_consolidado(control):
    g = _MergeGraph()
    hist, email = _setup(g, {"AB1": "258"}, extra_pdf={"258": "otro 258.pdf"})
    unused_path = f"{_folder('258')}/otro 258.pdf"
    reg, _ = add_unused_asiento(
        _registry(), path=unused_path, credito_carpeta="258", nota="", quien="op",
        motivo_codigo="NO_CORRESPONDE", fase="consolidacion",
    )
    control["registry"] = reg
    result = _run(g, hist, email)
    assert result.merge_control_status == "CONSOLIDADO"
    out = result.outputs[0]
    assert out.credit_items[0]["asiento_pdf_paths"] == [f"{_folder('258')}/asiento 258.pdf"]
    merged_key = next(k for k in g.uploaded if k.endswith(".pdf"))
    assert len(PdfReader(BytesIO(g.uploaded[merged_key])).pages) == 2


def test_sin_marca_ambos_asientos_entran(control):
    g = _MergeGraph()
    hist, email = _setup(g, {"AB1": "258"}, extra_pdf={"258": "otro 258.pdf"})
    result = _run(g, hist, email)
    assert len(result.outputs[0].credit_items[0]["asiento_pdf_paths"]) == 2


def test_registro_ilegible_bloquea_antes_de_consolidar(monkeypatch):
    from app.application.services import amortization_decisions as ad

    async def _raise(*_a, **_k):
        raise ad.DecisionsRegistryUnavailableError(REG_PATH, "HTTPStatusError")

    monkeypatch.setattr(ad, "load_registry_for_process", _raise)
    with pytest.raises(ValueError, match="decisions_registry_unavailable"):
        asyncio.run(
            m._load_merge_decisions_registry(None, "s", "d", registry_path=REG_PATH, process_key=PK)
        )


def test_sin_ruta_de_registro_no_lee_nada():
    assert asyncio.run(
        m._load_merge_decisions_registry(None, "s", "d", registry_path="", process_key=PK)
    ) is None


def test_merge_bloqueado_por_registro_ilegible_no_marca_consolidando(monkeypatch, control):
    async def _raise(*_a, **_k):
        raise ValueError("decisions_registry_unavailable")

    monkeypatch.setattr(m, "_load_merge_decisions_registry", _raise)
    g = _MergeGraph()
    hist, email = _setup(g, {"AB1": "258"})
    with pytest.raises(ValueError, match="decisions_registry_unavailable"):
        _run(g, hist, email)
    assert control["updates"] == []


def test_tipo_segun_asientos_cambia_nombre_y_extracto_nunca_valores():
    queue = [_pago("P1", [_row("40", tipo="PAGO CUOTA", monto=1_700_000, fecha=date(2026, 9, 22))])]
    reg, _ = add_tipo_correction(
        _registry(), group_key="40", id_pago="P1", credits=["40"], tipo_anterior="PAGO CUOTA",
        tipo_nuevo="PAGO TOTAL", nota="saldo en cero", quien="op",
    )
    kept, excluded, unused = m._apply_consolidation_decisions(queue, reg)
    assert excluded == [] and unused == frozenset()
    rows = kept[0][2]
    assert rows[0]["tipo_aplicacion_original"] == "PAGO TOTAL"
    assert rows[0]["include_extract_in_composite"] is False
    assert rows[0]["monto_banco"] == 1_700_000
    assert "PAGO TOTAL" in merge_name_token_for_tipos([r.get("tipo_aplicacion_original") for r in rows])
    assert queue[0][2][0]["tipo_aplicacion_original"] == "PAGO CUOTA"


def test_grupo_excluido_sale_completo_con_su_consignacion_compartida():
    queue = [
        _pago(
            "PT",
            [
                _row("95", tipo="PAGO CUOTA", monto=50_000_000, fecha=date(2026, 9, 15)),
                _row("194", tipo="PAGO CUOTA", monto=50_000_000, fecha=date(2026, 9, 15)),
            ],
        ),
        _pago("P1", [_row("10", tipo="PAGO CUOTA", monto=1, fecha=date(2026, 9, 15))]),
    ]
    reg, _ = add_exclusion(
        _registry(), credits=["95", "194"], clientes={}, id_pagos=["PT"], tablas={},
        motivo_codigo="FALTA_ASIENTO", nota="", quien="op", fase="consolidacion",
    )
    kept, excluded, _ = m._apply_consolidation_decisions(queue, reg)
    assert [k[0] for k in kept] == ["P1"]
    assert excluded[0]["creditos"] == ["194", "95"]
