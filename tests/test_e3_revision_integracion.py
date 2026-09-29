"""Revisión de integración E3: fase 3 (merge real) → fase 4 (conciliación del lote) → cierre.

Cada escenario usa el merge real para producir el manifest, las mismas funciones del lote que
el dry-run para la fase 4 y el movimiento real de asientos del cierre (nunca se borra nada).
"""
from __future__ import annotations

import asyncio
from datetime import date
from typing import Any

from app.application.services.abono_dry_run import infer_manifest_tipo_aplicacion
from app.application.services.accounting_pdf_parser import ACCOUNT_VALOR_PAGADO_CLIENTE
from app.application.services.accounting_pdf_processed_move import (
    move_unused_asientos_best_effort,
    process_used_accounting_pdfs_after_soft_close,
)
from app.application.services.amortization_decisions import (
    add_confirmation,
    add_exclusion,
    add_unused_asiento,
    conciliation_key,
    set_group_assignments,
    unused_asientos,
)
from app.application.services.lot_conciliation import (
    apply_exclusions,
    assign_shared_asientos,
    build_lot_model,
    completeness_excluded_pairs,
    completeness_waived_pairs,
    evaluate_lot_conciliation,
    exclusions_outside_lot,
    planner_outputs,
)
from app.application.services.merge_manifest_gate import assess_apply_event_completeness
from app.application.services.merge_manifest_view import as_payment_manifest, manifest_payment_outputs
from app.application.services.review_schema import TipoAplicacionConfirmado as T
from tests.test_amortization_fill_apply import MockGraphApply
from tests.test_merge_composite_control_workbook import _MergeGraph
from tests.test_merge_consolidados_por_grupo import CLIENTE, _fila, _pdfs, _ruta, _setup
from tests.test_merge_phase3_decisions import _manifest, _registry, _run, control  # noqa: F401

CAPITAL = "544113410519"


def _fase4(manifest: dict[str, Any], montos: dict[str, float], registry=None):
    outputs = manifest_payment_outputs(manifest)

    async def _go():
        model = build_lot_model(
            outputs,
            tipo_fn=infer_manifest_tipo_aplicacion,
            payment_date_fn=lambda o, _t, _c: str(o.get("fecha_banco") or ""),
            legacy_paths_fn=lambda o: list(o.get("asiento_pdf_paths") or []),
            legacy_credit_fn=lambda _p: "",
        )
        excluded = apply_exclusions(model, registry)
        excluded.extend(exclusions_outside_lot(model, registry, excluded))

        async def _sin_fecha(_credit, _path):
            return None

        await assign_shared_asientos(model, registry=registry, asiento_date_fn=_sin_fecha)
        planned, _covered = planner_outputs(model)
        items = [
            {
                "id_pago": out["id_pago"],
                "credito": ci["credito"],
                "application_status": "WOULD_APPLY",
                "error_code": None,
                "asiento_pdf_path": path,
                "event_index": idx,
                "idempotency_key": f"{out['id_pago']}|{ci['credito']}|{path}",
                "detected_codes": [ACCOUNT_VALOR_PAGADO_CLIENTE, CAPITAL],
                "payment_application": {"valor_pagado_cliente": montos[path]},
                "tabla_amortizacion_path": f"T/{ci['credito']}.xlsx",
            }
            for out in planned
            for ci in out.get("credit_items") or []
            for idx, path in enumerate(ci.get("asiento_pdf_paths") or [])
        ]
        conc = await evaluate_lot_conciliation(
            model, items=items, abono_group_results=[], registry=registry, excluded=excluded
        )
        return items, conc

    return asyncio.run(_go())


def _cierre(g_merge: _MergeGraph, manifest: dict[str, Any], registry=None, *, soft_close: bool = True):
    """Cierre: usados (y excluidos en el cierre) → PROCESADOS; no usados → NO USADOS."""
    files = {k: v for k, v in g_merge.initial.items() if "/ASIENTOS CONTABLES CRED " in k}
    g = MockGraphApply(dict(files))
    unused = unused_asientos(registry)
    asyncio.run(
        process_used_accounting_pdfs_after_soft_close(
            g, "s", "d", manifest=manifest, bank_code="banco_bogota",
            fallback_payment_date_iso="2026-05-12",
            exclude_paths={a["path"] for a in unused},
            include_excluded=soft_close,
        )
    )
    asyncio.run(move_unused_asientos_best_effort(g, "s", "d", unused=unused))
    destino: dict[str, str] = {}
    for src, blob in files.items():
        assert src not in g.files, f"quedó sin mover: {src}"
        [dest] = [k for k, v in g.files.items() if k.endswith(".pdf") and v == blob]
        destino[src] = dest
    assert sum(1 for k in g.files if k.endswith(".pdf")) == len(files)
    return destino


def _procesados(destino: dict[str, str]) -> set[str]:
    return {s for s, d in destino.items() if "/PROCESADOS/" in d and "/NO USADOS/" not in d}


def _no_usados(destino: dict[str, str]) -> set[str]:
    return {s for s, d in destino.items() if "/PROCESADOS/NO USADOS/" in d}


def _paths_unicos(items: list[dict[str, Any]]) -> list[str]:
    paths = [it["asiento_pdf_path"] for it in items]
    assert len(paths) == len(set(paths)), "un asiento aplicado dos veces"
    return sorted(paths)


def test_caso_normal(control):
    g = _MergeGraph()
    jasp = "GRUPO EMPRESARIAL JASP"
    filas = [
        _fila("P1", "264", T.PAGO_OBLIGACION_ACTUAL, date(2026, 9, 25), 1000),
        _fila("J1", "102", T.CANCELACION_PAGO_TOTAL, date(2026, 9, 9), 1000, cliente=jasp),
        _fila("J1", "133", T.CANCELACION_PAGO_TOTAL, date(2026, 9, 9), 1000, cliente=jasp),
    ]
    hist, email = _setup(
        g, filas,
        {
            (CLIENTE, "264"): [("a.pdf", 1000, "25/09/2026")],
            (jasp, "102"): [("a.pdf", 500, "09/09/2026")],
            (jasp, "133"): [("a.pdf", 500, "09/09/2026")],
        },
    )
    assert _run(g, hist, email).merge_control_status == "CONSOLIDADO"
    assert sorted(_pdfs(g)) == [
        "09 SEPTIEMBRE PAGO TOTAL GRUPO EMPRESARIAL JASP CRED 102 Y 133.pdf",
        "25 SEPTIEMBRE PAGO CUOTA RUEDA INVERSIONES CRED 264.pdf",
    ]
    manifest = _manifest(g)
    montos = {_ruta(CLIENTE, "264", "a.pdf"): 1000, _ruta(jasp, "102", "a.pdf"): 500, _ruta(jasp, "133", "a.pdf"): 500}
    items, conc = _fase4(manifest, montos)
    assert conc["problems"] == []
    assert _paths_unicos(items) == sorted(montos)
    destino = _cierre(g, manifest, soft_close=False)
    assert _procesados(destino) == set(montos)


def test_exclusion_en_fase_3_con_asiento_no_corresponde(control):
    g = _MergeGraph()
    filas = [
        _fila("P1", "258", T.PAGO_OBLIGACION_ACTUAL, date(2026, 9, 22), 100),
        _fila("P2", "265", T.PAGO_OBLIGACION_ACTUAL, date(2026, 9, 22), 100),
    ]
    hist, email = _setup(
        g, filas,
        {
            (CLIENTE, "258"): [("a.pdf", 100, "22/09/2026"), ("otro.pdf", 70, "22/09/2026")],
            (CLIENTE, "265"): [("b.pdf", 100, "22/09/2026")],
        },
    )
    reg, _ = add_exclusion(
        _registry(), credits=["265"], clientes={"265": CLIENTE}, id_pagos=["P2"], tablas={},
        motivo_codigo="FALTA_ASIENTO", nota="", quien="op", fase="consolidacion",
    )
    reg, _ = add_unused_asiento(
        reg, path=_ruta(CLIENTE, "258", "otro.pdf"), credito_carpeta="258", nota="", quien="op",
        motivo_codigo="NO_CORRESPONDE", fase="consolidacion",
    )
    control["registry"] = reg
    assert _run(g, hist, email).merge_control_status == "CONSOLIDADO"
    assert list(_pdfs(g)) == ["22 SEPTIEMBRE PAGO CUOTA RUEDA INVERSIONES CRED 258.pdf"]
    manifest = _manifest(g)

    items, conc = _fase4(manifest, {_ruta(CLIENTE, "258", "a.pdf"): 100}, registry=reg)
    assert conc["problems"] == []
    assert [e["credito"] for e in conc["excluded"]] == ["265"]
    assert _paths_unicos(items) == [_ruta(CLIENTE, "258", "a.pdf")]

    destino = _cierre(g, manifest, reg)
    assert _procesados(destino) == {_ruta(CLIENTE, "258", "a.pdf"), _ruta(CLIENTE, "265", "b.pdf")}
    assert _no_usados(destino) == {_ruta(CLIENTE, "258", "otro.pdf")}


def test_exclusion_en_fase_4(control):
    g = _MergeGraph()
    filas = [
        _fila("P1", "258", T.PAGO_OBLIGACION_ACTUAL, date(2026, 9, 22), 100),
        _fila("P2", "265", T.PAGO_OBLIGACION_ACTUAL, date(2026, 9, 22), 100),
    ]
    hist, email = _setup(
        g, filas,
        {(CLIENTE, "258"): [("a.pdf", 100, "22/09/2026")], (CLIENTE, "265"): [("b.pdf", 90, "22/09/2026")]},
    )
    assert _run(g, hist, email).merge_control_status == "CONSOLIDADO"
    assert len(_pdfs(g)) == 2
    manifest = _manifest(g)
    montos = {_ruta(CLIENTE, "258", "a.pdf"): 100, _ruta(CLIENTE, "265", "b.pdf"): 90}

    _items, conc = _fase4(manifest, montos)
    [problema] = conc["problems"]
    assert problema["excludable"]

    reg, _ = add_exclusion(
        _registry(), credits=["265"], clientes={"265": CLIENTE}, id_pagos=["P2"], tablas={},
        motivo_codigo="FALTA_ASIENTO", nota="", quien="op",
    )
    items, conc = _fase4(manifest, montos, registry=reg)
    assert conc["problems"] == []
    assert [e["credito"] for e in conc["excluded"]] == ["265"]
    assert _paths_unicos(items) == [_ruta(CLIENTE, "258", "a.pdf")]

    destino = _cierre(g, manifest, reg)
    assert _procesados(destino) == set(montos)


def test_continuar_con_los_asientos_carbonera_87(control):
    g = _MergeGraph()
    cli = "CARBONERA"
    filas = [_fila("P1", "87", T.PAGO_OBLIGACION_ACTUAL, date(2026, 9, 23), 22_044_688, cliente=cli)]
    hist, email = _setup(g, filas, {(cli, "87"): [("a.pdf", 22_032_455, "23/09/2026")]})
    assert _run(g, hist, email).merge_control_status == "CONSOLIDADO"
    assert list(_pdfs(g)) == ["23 SEPTIEMBRE PAGO CUOTA CARBONERA CRED 87.pdf"]
    manifest = _manifest(g)
    montos = {_ruta(cli, "87", "a.pdf"): 22_032_455}

    _items, conc = _fase4(manifest, montos)
    assert len(conc["problems"]) == 1 and conc["problems"][0]["confirmable"]

    reg, _ = add_confirmation(
        _registry(), key=conciliation_key("87", "2026-09-23"), credits=["87"], clientes={"87": cli},
        fecha_banco="2026-09-23", monto_banco=22_044_688, monto_asientos=22_032_455, nota="", quien="op",
    )
    items, conc = _fase4(manifest, montos, registry=reg)
    assert conc["problems"] == []
    assert conc["confirmed"][0]["monto_sin_aplicar"] == 12_233.0
    assert items[0]["payment_application"]["valor_pagado_cliente"] == 22_032_455

    destino = _cierre(g, manifest, reg, soft_close=False)
    assert _procesados(destino) == set(montos)


def test_asignacion_a_dos_fechas(control):
    g = _MergeGraph()
    filas = [
        _fila("P-AB", "247", T.ABONO_A_CAPITAL, date(2026, 9, 22), 100),
        _fila("P-CU", "247", T.PAGO_OBLIGACION_ACTUAL, date(2026, 9, 25), 50),
    ]
    a1, a2 = _ruta(CLIENTE, "247", "a1.pdf"), _ruta(CLIENTE, "247", "a2.pdf")
    hist, email = _setup(
        g, filas, {(CLIENTE, "247"): [("a1.pdf", 100, "24/09/2026"), ("a2.pdf", 50, "26/09/2026")]}
    )
    reg, _ = set_group_assignments(
        _registry(), group_key="247", quien="op",
        items=[
            {"credito": "247", "asiento_pdf_path": a1, "id_pago": "P-AB", "fecha_banco": "2026-09-22"},
            {"credito": "247", "asiento_pdf_path": a2, "id_pago": "P-CU", "fecha_banco": "2026-09-25"},
        ],
    )
    control["registry"] = reg
    assert _run(g, hist, email).merge_control_status == "CONSOLIDADO"
    assert sorted(_pdfs(g)) == [
        "22 SEPTIEMBRE ABONO A CAPITAL RUEDA INVERSIONES CRED 247.pdf",
        "25 SEPTIEMBRE PAGO CUOTA RUEDA INVERSIONES CRED 247.pdf",
    ]
    manifest = _manifest(g)
    items, conc = _fase4(manifest, {a1: 100, a2: 50}, registry=reg)
    assert conc["problems"] == []
    assert {(it["id_pago"], it["asiento_pdf_path"]) for it in items} == {("P-AB", a1), ("P-CU", a2)}

    destino = _cierre(g, manifest, reg, soft_close=False)
    assert destino[a1].rsplit("/", 1)[-1].startswith("2026-09-22_")
    assert destino[a2].rsplit("/", 1)[-1].startswith("2026-09-25_")


def test_pago_y_abono_misma_fecha_apply_completo_sin_evento_faltante(control):
    g = _MergeGraph()
    filas = [
        _fila("P-AB", "247", T.ABONO_A_CAPITAL, date(2026, 9, 25), 100),
        _fila("P-CU", "247", T.PAGO_OBLIGACION_ACTUAL, date(2026, 9, 25), 50),
    ]
    a1, a2 = _ruta(CLIENTE, "247", "a1.pdf"), _ruta(CLIENTE, "247", "a2.pdf")
    hist, email = _setup(
        g, filas, {(CLIENTE, "247"): [("a1.pdf", 100, "25/09/2026"), ("a2.pdf", 50, "25/09/2026")]}
    )
    assert _run(g, hist, email).merge_control_status == "CONSOLIDADO"
    manifest = _manifest(g)
    items, conc = _fase4(manifest, {a1: 100, a2: 50})
    assert conc["problems"] == []
    assert _paths_unicos(items) == sorted([a1, a2])

    applied = [{**it, "apply_status": "APPLIED"} for it in items]
    check = assess_apply_event_completeness(
        manifest,
        applied,
        waived_pairs=completeness_waived_pairs(conc),
        excluded_pairs=completeness_excluded_pairs(conc),
    )
    assert check["all_expected_events_completed"] is True, check
    assert _procesados(_cierre(g, manifest, soft_close=False)) == {a1, a2}


def test_lote_viejo_con_manifest_viejo(control):
    g = _MergeGraph()
    filas = [
        _fila("P1", "258", T.PAGO_OBLIGACION_ACTUAL, date(2026, 9, 22), 100),
        _fila("P2", "265", T.ABONO_A_CAPITAL, date(2026, 9, 22), 200),
    ]
    hist, email = _setup(
        g, filas,
        {(CLIENTE, "258"): [("a.pdf", 100, "22/09/2026")], (CLIENTE, "265"): [("b.pdf", 200, "22/09/2026")]},
    )
    _run(g, hist, email)
    nuevo = _manifest(g)
    viejo = as_payment_manifest(nuevo)
    viejo.pop("manifest_version", None)
    for out in viejo["outputs"]:
        for key in ("consolidado_key", "group_key", "nombre_consolidado"):
            out.pop(key, None)
    montos = {_ruta(CLIENTE, "258", "a.pdf"): 100, _ruta(CLIENTE, "265", "b.pdf"): 200}

    items_v1, conc_v1 = _fase4(viejo, montos)
    items_v2, conc_v2 = _fase4(nuevo, montos)
    assert conc_v1["problems"] == conc_v2["problems"] == []
    assert _paths_unicos(items_v1) == _paths_unicos(items_v2) == sorted(montos)
    assert _procesados(_cierre(g, viejo)) == _procesados(_cierre(g, nuevo)) == set(montos)
