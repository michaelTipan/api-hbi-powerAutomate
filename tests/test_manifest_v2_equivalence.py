"""Entrega 3: la fase 4 da lo mismo con el manifest nuevo (un output por consolidado)
que con el viejo (un output por ID Pago con todos los asientos de la carpeta)."""

from __future__ import annotations

import copy
from typing import Any

import pytest

from app.application.services.amortization_decisions import add_exclusion
from app.application.services.merge_manifest_gate import (
    assess_apply_event_completeness,
    assess_manifest_completeness,
    count_expected_credit_events,
)
from app.application.services.lot_conciliation import completeness_waived_pairs
from app.application.services.merge_manifest_view import (
    as_payment_manifest,
    manifest_payment_outputs,
    manifest_version,
)
from tests.test_lot_conciliation_scenarios import _bank, _no_bank, _out, _registry, _run


def _v2(outputs: list[dict[str, Any]], destinos: dict[str, str]) -> dict[str, Any]:
    """Manifest v2: cada pago solo con sus asientos; un output por (grupo, fecha)."""
    by_key: dict[str, dict[str, Any]] = {}
    for out in outputs:
        pay = copy.deepcopy(out)
        pay["status"] = "COMPLETE"
        for ci in pay["credit_items"]:
            ci["asiento_pdf_paths"] = [p for p in ci["asiento_pdf_paths"] if destinos.get(p, out["id_pago"]) == out["id_pago"]]
        key = f"{'+'.join(sorted(out['creditos_seleccionados']))}|{out['fecha_banco']}"
        cons = by_key.setdefault(
            key,
            {"status": "COMPLETE", "consolidado_key": key, "id_pagos": [], "payments": [], "output_relative_path": f"OUT/{key}.pdf"},
        )
        pay["consolidado_key"] = key
        cons["id_pagos"].append(out["id_pago"])
        cons["payments"].append(pay)
    return {"manifest_version": 2, "manifest_status": "COMPLETE", "eligible_for_dry_run": True, "outputs": list(by_key.values())}


def _v1(outputs: list[dict[str, Any]]) -> dict[str, Any]:
    outs = [{**copy.deepcopy(o), "status": "COMPLETE"} for o in outputs]
    return {"manifest_status": "COMPLETE", "eligible_for_dry_run": True, "outputs": outs}


def _summary(result: tuple) -> dict[str, Any]:
    _model, planned, covered, items, conc = result
    return {
        "planned": [
            (o["id_pago"], {ci["credito"]: list(ci["asiento_pdf_paths"]) for ci in o["credit_items"]}) for o in planned
        ],
        "covered": sorted(o["id_pago"] for o in covered),
        "items": sorted((it["id_pago"], it["credito"], it["asiento_pdf_path"], it["application_status"]) for it in items),
        "problems": [(p["code"], p.get("credits")) for p in conc["problems"]],
        "groups": [
            (g["group_key"], g["status"], [(d["fecha_banco"], d["monto_banco"], d["monto_asientos"], d["status"]) for d in g.get("dates") or []])
            for g in conc["groups"]
        ],
        "waived": sorted(completeness_waived_pairs(conc)),
        "excluded": sorted(conc["excluded_credits"]),
        "lines": (conc["planned_lines"], conc["planned_tables"]),
    }


def _both(outputs, asientos, destinos, **kw) -> tuple[dict[str, Any], dict[str, Any]]:
    v1 = manifest_payment_outputs(_v1(outputs))
    v2 = manifest_payment_outputs(_v2(outputs, destinos))
    return _summary(_run(v1, asientos, **kw)), _summary(_run(v2, asientos, **kw))


CASOS: dict[str, tuple[list[dict[str, Any]], dict[str, dict[str, Any]], dict[str, str], dict[str, Any]]] = {
    "247_misma_fecha": (
        [
            _out("P_ABONO", "ABONO", "2026-09-25", 100_000_000, {"247": ["A/4634.pdf", "A/4635.pdf", "A/4638.pdf"]}),
            _out("P_CUOTA", "PAGO", "2026-09-25", 26_950_278, {"247": ["A/4634.pdf", "A/4635.pdf", "A/4638.pdf"]}),
        ],
        {"A/4634.pdf": _bank(73_049_722), "A/4635.pdf": _bank(26_950_278), "A/4638.pdf": _bank(26_950_278)},
        {"A/4634.pdf": "P_CUOTA", "A/4635.pdf": "P_CUOTA", "A/4638.pdf": "P_CUOTA"},
        {},
    ),
    "322_cuatro_pagos": (
        [_out(f"P{i}", "PAGO", "2026-09-10", 5_000_000, {"322": ["A/4150.pdf", "A/4151.pdf", "A/4158.pdf"]}) for i in range(1, 5)],
        {"A/4150.pdf": _bank(10_000_000), "A/4151.pdf": _bank(10_000_000), "A/4158.pdf": _no_bank(2_731)},
        {"A/4150.pdf": "P1", "A/4151.pdf": "P1", "A/4158.pdf": "P1"},
        {},
    ),
    "jasp_102_133": (
        [_out("P1", "PAGO", "2026-09-09", 105_000_000, {"102": ["A/102.pdf"], "133": ["A/133.pdf"]}, "JASP")],
        {"A/102.pdf": _bank(60_000_000), "A/133.pdf": _bank(45_000_000)},
        {},
        {},
    ),
    "transp_95_194": (
        [
            _out("T1", "PAGO", "2026-09-10", 10_000_000, {"95": ["A/95.pdf"], "194": ["A/194.pdf"]}, "TRANSP"),
            _out("T2", "PAGO", "2026-09-10", 2_000_000, {"194": ["A/194.pdf"]}, "TRANSP"),
        ],
        {"A/95.pdf": _bank(6_000_000), "A/194.pdf": _bank(5_000_000)},
        {"A/95.pdf": "T1", "A/194.pdf": "T1"},
        {},
    ),
    "carbonera_87": (
        [_out("P1", "PAGO", "2026-09-23", 22_044_688, {"87": ["A/4621.pdf"]}, "CARBONERA")],
        {"A/4621.pdf": _bank(22_032_455)},
        {},
        {},
    ),
    "intramaq_retenciones": (
        [_out("P1", "PAGO", "2026-02-19", 15_894_345, {"19": ["A/intramaq.pdf"]}, "INTRAMAQ")],
        {"A/intramaq.pdf": _bank(15_894_345)},
        {},
        {},
    ),
    "dos_fechas_por_fecha_del_asiento": (
        [
            _out("P1", "PAGO", "2026-07-21", 10_000_000, {"248": ["A/21jul.pdf", "A/23jul.pdf"]}, "MADERPOL"),
            _out("P2", "PAGO", "2026-07-23", 5_000_000, {"248": ["A/21jul.pdf", "A/23jul.pdf"]}, "MADERPOL"),
        ],
        {"A/21jul.pdf": _bank(10_000_000), "A/23jul.pdf": _bank(5_000_000)},
        {"A/21jul.pdf": "P1", "A/23jul.pdf": "P2"},
        {"asiento_dates": {"A/21jul.pdf": "2026-07-21", "A/23jul.pdf": "2026-07-23"}},
    ),
}


@pytest.mark.parametrize("caso", sorted(CASOS))
def test_phase4_same_result_with_old_and_new_manifest(caso: str):
    outputs, asientos, destinos, kw = CASOS[caso]
    v1, v2 = _both(outputs, asientos, destinos, **kw)
    assert v2 == v1


def test_247_two_dates_explicit_assignment_same_result():
    shared = ["A/4634.pdf", "A/4635.pdf", "A/4638.pdf"]
    outputs = [
        _out("P_ABONO", "ABONO", "2026-09-22", 100_000_000, {"247": shared}, "RUEDA"),
        _out("P_CUOTA", "PAGO", "2026-09-25", 26_950_278, {"247": shared}, "RUEDA"),
    ]
    asientos = {"A/4634.pdf": _bank(100_000_000), "A/4635.pdf": _bank(26_950_278), "A/4638.pdf": _no_bank(10)}
    destinos = {"A/4634.pdf": "P_ABONO", "A/4635.pdf": "P_CUOTA", "A/4638.pdf": "P_CUOTA"}
    reg = _registry()
    for path, pago in destinos.items():
        reg["assignments"].append({"credito": "247", "asiento_pdf_path": path, "id_pago": pago, "status": "active"})
    dates = {"A/4634.pdf": "2026-09-23", "A/4635.pdf": "2026-09-25", "A/4638.pdf": "2026-09-25"}
    v1, v2 = _both(outputs, asientos, destinos, registry=reg, asiento_dates=dates)
    assert v2 == v1
    assert v2["problems"] == []
    assert [g[2] for g in v2["groups"]][0] == [
        ("2026-09-22", 100_000_000.0, 100_000_000.0, "OK"),
        ("2026-09-25", 26_950_278.0, 26_950_278.0, "OK"),
    ]


def test_exclusion_in_phase4_same_result():
    outputs, asientos, destinos, _kw = CASOS["jasp_102_133"]
    outputs = outputs + [_out("P2", "PAGO", "2026-09-09", 1_000_000, {"250": ["A/250.pdf"]}, "OTRO")]
    asientos = {**asientos, "A/250.pdf": _bank(1_000_000)}
    reg, _ = add_exclusion(
        _registry(), credits=["133"], clientes={}, id_pagos=["P1"], tablas={},
        motivo_codigo="FALTA_ASIENTO", nota="", quien="operador",
    )
    v1, v2 = _both(outputs, asientos, destinos, registry=reg)
    assert v2 == v1
    assert v2["excluded"] == ["102", "133"]


# --- gate y completitud ----------------------------------------------------------------


def test_gate_and_expected_events_read_payments_of_new_manifest():
    outputs, _a, destinos, _kw = CASOS["247_misma_fecha"]
    m2 = _v2(outputs, destinos)
    m1 = _v1(outputs)
    assert manifest_version(m2) == 2 and manifest_version(m1) == 1
    assert [o["id_pago"] for o in manifest_payment_outputs(m2)] == ["P_ABONO", "P_CUOTA"]
    assert as_payment_manifest(m1) is m1
    assert assess_manifest_completeness(m2)["eligible_for_dry_run"] is True
    assert count_expected_credit_events(m2) == count_expected_credit_events(m1) == 2
    apply_items = [{"id_pago": "P_CUOTA", "credito": "247", "apply_status": "APPLIED"} for _ in range(3)]
    res = assess_apply_event_completeness(m2, apply_items, waived_pairs={("P_ABONO", "247")})
    assert res["all_expected_events_completed"] is True


def test_gate_blocks_new_manifest_with_incomplete_payment():
    outputs, _a, destinos, _kw = CASOS["247_misma_fecha"]
    m2 = _v2(outputs, destinos)
    m2["outputs"][0]["payments"][0]["status"] = "PENDING_INPUTS"
    assert assess_manifest_completeness(m2)["eligible_for_dry_run"] is False
