"""Conciliación del lote (fase 4) con casos reales reproducidos en fixtures sintéticos.

Casos: 247, 322, CARBONERA 87, INTRAMAQ (retenciones), ABIBE $4, CROIL $2.516,
MADERPOL 4120 (retención sin dinero), JASP 102+133 (una consignación, dos créditos),
grupos de dos fechas (asignación por fecha del asiento) y exclusiones.
"""

from __future__ import annotations

import asyncio
from decimal import Decimal
from typing import Any

import pytest

from app.application.services.accounting_pdf_parser import ACCOUNT_VALOR_PAGADO_CLIENTE
from app.application.services.amortization_decisions import (
    add_confirmation,
    add_exclusion,
    conciliation_key,
    empty_registry,
)
from app.application.services.lot_conciliation import (
    ASIENTOS_REQUIEREN_ASIGNACION,
    CONCILIACION_ASIENTOS_MAYOR_BANCO,
    CONCILIACION_BANCO_MAYOR_ASIENTOS,
    apply_exclusions,
    assign_shared_asientos,
    build_lot_model,
    cash_from_parsed,
    completeness_excluded_pairs,
    completeness_waived_pairs,
    evaluate_lot_conciliation,
    exclusions_outside_lot,
    planner_outputs,
)
from app.application.services.amortization_apply_safety import collect_disallowed_warning_items
from app.application.use_cases.amortization_fill_dry_run import (
    BANK_ASIENTOS_NO_CUADRAN,
    _reconcile_bank_vs_asientos_for_payment_outputs,
)

PK = "payment-validation|banco_bogota|2026-07-21|abc12345-0000"
CAPITAL = "544113410519"
INTERES = "544141502030"
SALDOS_MENORES = "544153159505"


def _out(id_pago: str, tipo: str, fecha: str, monto: float, credits: dict[str, list[str]],
         cliente: str = "CLIENTE") -> dict[str, Any]:
    return {
        "id_pago": id_pago,
        "cliente": cliente,
        "tipo": tipo,
        "fecha_banco": fecha,
        "monto_banco": monto,
        "creditos_seleccionados": list(credits),
        "credit_items": [
            {"credito": c, "ruta_tabla_amortizacion": f"T/{c}.xlsx", "asiento_pdf_paths": list(paths)}
            for c, paths in credits.items()
        ],
    }


def _bank(amount: float) -> dict[str, Any]:
    """Asiento con línea de banco (dinero real)."""
    return {"codes": [ACCOUNT_VALOR_PAGADO_CLIENTE, CAPITAL, INTERES], "valor": amount}


def _no_bank(inferred: float) -> dict[str, Any]:
    """Asiento sin línea de banco (saldo menor / retención): el parser infiere un valor."""
    return {"codes": [CAPITAL, SALDOS_MENORES], "valor": inferred}


def _items(planned: list[dict[str, Any]], asientos: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for out in planned:
        for ci in out.get("credit_items") or []:
            for idx, path in enumerate(ci.get("asiento_pdf_paths") or []):
                spec = asientos[path]
                items.append(
                    {
                        "id_pago": out["id_pago"],
                        "credito": ci["credito"],
                        "application_status": "WOULD_APPLY",
                        "error_code": None,
                        "asiento_pdf_path": path,
                        "event_index": idx,
                        "idempotency_key": f"{out['id_pago']}|{ci['credito']}|{path}",
                        "detected_codes": list(spec["codes"]),
                        "payment_application": {"valor_pagado_cliente": spec["valor"]},
                        "tabla_amortizacion_path": ci["ruta_tabla_amortizacion"],
                    }
                )
    return items


def _run(outputs, asientos, *, registry=None, asiento_dates=None, items_hook=None, legacy_check=False,
         pre_legacy_hook=None):
    async def _go():
        model = build_lot_model(
            outputs,
            tipo_fn=lambda o: o["tipo"],
            payment_date_fn=lambda o, _t, _c: o["fecha_banco"],
            legacy_paths_fn=lambda o: list(o.get("asiento_pdf_paths") or []),
            legacy_credit_fn=lambda _p: "",
        )
        excluded = apply_exclusions(model, registry)

        async def _date(_credit, path):
            return (asiento_dates or {}).get(path)

        await assign_shared_asientos(model, registry=registry, asiento_date_fn=_date)
        planned, covered = planner_outputs(model)
        items = _items(planned, asientos)
        if pre_legacy_hook:
            pre_legacy_hook(items)
        if legacy_check:
            items = _reconcile_bank_vs_asientos_for_payment_outputs(planned, items)
        if items_hook:
            items_hook(items)
        conc = await evaluate_lot_conciliation(
            model, items=items, abono_group_results=[], registry=registry, excluded=excluded
        )
        return model, planned, covered, items, conc

    return asyncio.run(_go())


def _registry():
    return empty_registry(process_key=PK, bank_code="banco_bogota", report_date_iso="2026-07-21")


def _codes(conc) -> list[str]:
    return [p["code"] for p in conc["problems"]]


# --- efectivo del asiento ---------------------------------------------------------


def test_efectivo_solo_con_linea_de_banco():
    assert cash_from_parsed([ACCOUNT_VALOR_PAGADO_CLIENTE], "15894345") == Decimal("15894345.00")
    assert cash_from_parsed([CAPITAL, SALDOS_MENORES], 4) == Decimal("0.00")
    assert cash_from_parsed(None, 100) == Decimal("0.00")


# --- casos reales -------------------------------------------------------------------


def test_247_dos_consignaciones_un_credito_una_linea_por_asiento():
    shared = ["A/4634.pdf", "A/4635.pdf", "A/4638.pdf"]
    outputs = [
        _out("P_ABONO", "ABONO", "2026-09-25", 100_000_000, {"247": shared}),
        _out("P_CUOTA", "PAGO", "2026-09-25", 26_950_278, {"247": shared}),
    ]
    asientos = {
        "A/4634.pdf": _bank(73_049_722),
        "A/4635.pdf": _bank(26_950_278),
        "A/4638.pdf": _bank(26_950_278),
    }
    model, planned, covered, items, conc = _run(outputs, asientos)
    assert model.groups[0].key == "247"
    assert conc["shared_asientos"] == 3
    # Con una sola fecha, PAGO antes que ABONO: los tres asientos van a la cuota.
    assert [o["id_pago"] for o in planned] == ["P_CUOTA"]
    assert [o["id_pago"] for o in covered] == ["P_ABONO"]
    assert len(items) == 3
    assert conc["problems"] == []
    assert conc["groups"][0]["status"] == "OK"
    date = conc["groups"][0]["dates"][0]
    assert date["monto_banco"] == date["monto_asientos"] == 126_950_278.0
    assert completeness_waived_pairs(conc) == {("P_ABONO", "247")}
    assert (conc["planned_lines"], conc["planned_tables"]) == (3, 1)


def test_322_cuatro_consignaciones_asientos_compartidos_sin_lineas_duplicadas():
    shared = ["A/4150.pdf", "A/4151.pdf", "A/4158.pdf"]
    outputs = [
        _out(f"P{i}", "PAGO", "2026-09-10", 5_000_000, {"322": shared}) for i in range(1, 5)
    ]
    asientos = {
        "A/4150.pdf": _bank(10_000_000),
        "A/4151.pdf": _bank(10_000_000),
        "A/4158.pdf": _no_bank(2_731),  # saldo menor asumido: no es dinero
    }
    _model, planned, covered, items, conc = _run(outputs, asientos)
    assert [o["id_pago"] for o in planned] == ["P1"]
    assert sorted(o["id_pago"] for o in covered) == ["P2", "P3", "P4"]
    assert len(items) == 3  # una línea por asiento, no cuatro
    assert conc["problems"] == []
    assert {it["conciliation_cash"] for it in items if it["asiento_pdf_path"] == "A/4158.pdf"} == {0.0}


def test_carbonera_87_banco_mayor_requiere_continuar_con_los_asientos():
    outputs = [_out("P1", "PAGO", "2026-09-23", 22_044_688, {"87": ["A/4621.pdf"]}, "CARBONERA")]
    asientos = {"A/4621.pdf": _bank(22_032_455)}
    _m, _p, _c, items, conc = _run(outputs, asientos)
    assert _codes(conc) == [CONCILIACION_BANCO_MAYOR_ASIENTOS]
    problem = conc["problems"][0]
    assert problem["confirmable"] and problem["excludable"]
    assert problem["monto_sin_aplicar"] == 12_233.0
    assert items[0]["application_status"] == "ERROR"
    assert items[0]["error_code"] == CONCILIACION_BANCO_MAYOR_ASIENTOS

    reg, _ = add_confirmation(
        _registry(),
        key=conciliation_key("87", "2026-09-23"),
        credits=["87"],
        clientes={"87": "CARBONERA"},
        fecha_banco="2026-09-23",
        monto_banco=22_044_688,
        monto_asientos=22_032_455,
        nota="",
        quien="operador",
    )
    _m, _p, _c, items, conc = _run(outputs, asientos, registry=reg)
    assert conc["problems"] == []
    assert conc["confirmed"][0]["monto_sin_aplicar"] == 12_233.0
    assert items[0]["application_status"] == "WOULD_APPLY"
    # El valor escrito sigue siendo el del asiento.
    assert items[0]["payment_application"]["valor_pagado_cliente"] == 22_032_455


def test_intramaq_retenciones_dentro_del_asiento_cuadra_con_la_linea_de_banco():
    outputs = [_out("P1", "PAGO", "2026-02-19", 15_894_345, {"19": ["A/intramaq.pdf"]}, "INTRAMAQ")]
    _m, _p, _c, items, conc = _run(outputs, {"A/intramaq.pdf": _bank(15_894_345)})
    assert conc["problems"] == []
    assert items[0]["conciliation_cash"] == 15_894_345.0


@pytest.mark.parametrize(
    "credito,cliente,menor",
    [("111", "ABIBE", 4), ("97", "CROIL", 2_516), ("322", "RUEDA", 2_731)],
)
def test_saldo_menor_sin_linea_de_banco_no_suma_al_efectivo(credito, cliente, menor):
    outputs = [_out("P1", "PAGO", "2026-07-21", 5_000_000, {credito: ["A/pago.pdf", "A/menor.pdf"]}, cliente)]
    asientos = {"A/pago.pdf": _bank(5_000_000), "A/menor.pdf": _no_bank(menor)}
    _m, _p, _c, items, conc = _run(outputs, asientos)
    assert conc["problems"] == []
    assert len(items) == 2  # el asiento de saldo menor se aplica igual
    assert conc["groups"][0]["dates"][0]["monto_asientos"] == 5_000_000.0


def test_maderpol_4120_retencion_sin_dinero_no_bloquea():
    outputs = [_out("P1", "PAGO", "2026-07-21", 10_000_000, {"248": ["A/4119.pdf", "A/4120.pdf"]}, "MADERPOL")]
    asientos = {"A/4119.pdf": _bank(10_000_000), "A/4120.pdf": {"codes": [CAPITAL], "valor": 0}}
    _m, _p, _c, _items_, conc = _run(outputs, asientos)
    assert conc["problems"] == []


def test_jasp_una_consignacion_dos_creditos_forma_un_grupo():
    outputs = [
        _out("P1", "PAGO", "2026-09-09", 105_000_000,
             {"102": ["A/102.pdf"], "133": ["A/133.pdf"]}, "GRUPO EMPRESARIAL JASP")
    ]
    ok = {"A/102.pdf": _bank(60_000_000), "A/133.pdf": _bank(45_000_000)}
    model, _p, _c, _i, conc = _run(outputs, ok)
    assert [g.key for g in model.groups] == ["102+133"]
    assert conc["credit_groups"] == {"102": ["102", "133"], "133": ["102", "133"]}
    assert conc["problems"] == []

    over = {"A/102.pdf": _bank(60_000_000), "A/133.pdf": _bank(50_000_000)}
    _m, _p, _c, items, conc = _run(outputs, over)
    assert _codes(conc) == [CONCILIACION_ASIENTOS_MAYOR_BANCO]
    assert conc["problems"][0]["credits"] == ["102", "133"]
    assert not conc["problems"][0]["confirmable"]
    assert all(it["error_code"] == CONCILIACION_ASIENTOS_MAYOR_BANCO for it in items)


def test_exclusion_de_un_credito_saca_todo_el_grupo():
    outputs = [
        _out("P1", "PAGO", "2026-09-09", 105_000_000, {"102": ["A/102.pdf"], "133": ["A/133.pdf"]}, "JASP"),
        _out("P2", "PAGO", "2026-09-09", 1_000_000, {"250": ["A/250.pdf"]}, "OTRO"),
    ]
    asientos = {
        "A/102.pdf": _bank(60_000_000),
        "A/133.pdf": _bank(50_000_000),
        "A/250.pdf": _bank(1_000_000),
    }
    reg, _ = add_exclusion(
        _registry(), credits=["133"], clientes={}, id_pagos=["P1"], tablas={},
        motivo_codigo="FALTA_ASIENTO", nota="", quien="operador",
    )
    _m, planned, _c, items, conc = _run(outputs, asientos, registry=reg)
    assert [o["id_pago"] for o in planned] == ["P2"]
    assert conc["problems"] == []
    assert sorted(e["credito"] for e in conc["excluded"]) == ["102", "133"]
    assert conc["excluded_credits"] == ["102", "133"]
    assert {g["group_key"]: g["status"] for g in conc["groups"]} == {"102+133": "EXCLUDED", "250": "OK"}
    assert completeness_excluded_pairs(conc) == {("P1", "102"), ("P1", "133")}
    assert (conc["planned_lines"], conc["planned_tables"]) == (1, 1)
    assert len(items) == 1


def test_credito_excluido_al_consolidar_sigue_excluido_en_la_amortizacion():
    """Sin consolidado (el merge lo saltó), la fase 4 igual lo lista como excluido."""
    outputs = [_out("P2", "PAGO", "2026-09-09", 1_000_000, {"250": ["A/250.pdf"]}, "OTRO")]
    reg, _ = add_exclusion(
        _registry(), credits=["102", "133"], clientes={"102": "JASP", "133": "JASP"},
        id_pagos=["P1"], tablas={"133": "T/133.xlsx"},
        motivo_codigo="FALTA_ASIENTO", nota="", quien="operador", fase="consolidacion",
    )

    async def _go():
        model = build_lot_model(
            outputs,
            tipo_fn=lambda o: o["tipo"],
            payment_date_fn=lambda o, _t, _c: o["fecha_banco"],
            legacy_paths_fn=lambda o: [],
            legacy_credit_fn=lambda _p: "",
        )
        excluded = apply_exclusions(model, reg)
        assert excluded == []
        excluded.extend(exclusions_outside_lot(model, reg, excluded))

        async def _no_date(_credit, _path):
            return None

        await assign_shared_asientos(model, registry=reg, asiento_date_fn=_no_date)
        planned, _covered = planner_outputs(model)
        items = _items(planned, {"A/250.pdf": _bank(1_000_000)})
        return await evaluate_lot_conciliation(
            model, items=items, abono_group_results=[], registry=reg, excluded=excluded
        )

    conc = asyncio.run(_go())
    assert conc["problems"] == []
    assert conc["excluded_credits"] == ["102", "133"]
    entry = next(e for e in conc["excluded"] if e["credito"] == "133")
    assert entry["cliente"] == "JASP" and entry["tabla_amortizacion_path"] == "T/133.xlsx"
    assert entry["group_key"] == "102+133" and entry["id_pagos"] == ["P1"]
    assert completeness_excluded_pairs(conc) == {("P1", "102"), ("P1", "133")}


def test_exclusion_de_credito_del_lote_no_se_duplica_como_externa():
    outputs = [_out("P1", "PAGO", "2026-09-09", 1_000_000, {"250": ["A/250.pdf"]})]
    reg, _ = add_exclusion(
        _registry(), credits=["250"], clientes={}, id_pagos=["P1"], tablas={},
        motivo_codigo="FALTA_ASIENTO", nota="", quien="operador",
    )
    model = build_lot_model(
        outputs,
        tipo_fn=lambda o: o["tipo"],
        payment_date_fn=lambda o, _t, _c: o["fecha_banco"],
        legacy_paths_fn=lambda o: [],
        legacy_credit_fn=lambda _p: "",
    )
    excluded = apply_exclusions(model, reg)
    assert exclusions_outside_lot(model, reg, excluded) == []
    assert exclusions_outside_lot(model, None, []) == []


def test_grupo_de_dos_fechas_asigna_por_fecha_del_asiento():
    shared = ["A/21jul.pdf", "A/23jul.pdf"]
    outputs = [
        _out("P1", "PAGO", "2026-07-21", 10_000_000, {"248": shared}, "MADERPOL"),
        _out("P2", "PAGO", "2026-07-23", 5_000_000, {"248": shared}, "MADERPOL"),
    ]
    asientos = {"A/21jul.pdf": _bank(10_000_000), "A/23jul.pdf": _bank(5_000_000)}
    dates = {"A/21jul.pdf": "2026-07-21", "A/23jul.pdf": "2026-07-23"}
    model, planned, covered, items, conc = _run(outputs, asientos, asiento_dates=dates)
    assert model.groups[0].date_assigned
    assert covered == []
    by_pago = {o["id_pago"]: o["credit_items"][0]["asiento_pdf_paths"] for o in planned}
    assert by_pago == {"P1": ["A/21jul.pdf"], "P2": ["A/23jul.pdf"]}
    assert conc["problems"] == []
    assert [d["status"] for d in conc["groups"][0]["dates"]] == ["OK", "OK"]
    assert len(items) == 2


def test_grupo_de_dos_fechas_con_asientos_de_fecha_posterior_es_problema_excluible():
    shared = ["A/x.pdf", "A/y.pdf"]
    outputs = [
        _out("P1", "PAGO", "2026-07-21", 10_000_000, {"248": shared}, "MADERPOL"),
        _out("P2", "PAGO", "2026-07-23", 5_000_000, {"248": shared}, "MADERPOL"),
    ]
    asientos = {"A/x.pdf": _bank(10_000_000), "A/y.pdf": _bank(5_000_000)}
    dates = {"A/x.pdf": "2026-07-23", "A/y.pdf": "2026-07-23"}
    _m, _p, _c, items, conc = _run(outputs, asientos, asiento_dates=dates)
    assert _codes(conc) == [ASIENTOS_REQUIEREN_ASIGNACION]
    problem = conc["problems"][0]
    assert problem["excludable"] and not problem["confirmable"]
    assert problem["credits_affected"] == ["248"]
    assert all(it["application_status"] == "ERROR" for it in items)

    reg, _ = add_exclusion(
        _registry(), credits=["248"], clientes={}, id_pagos=["P1", "P2"], tablas={},
        motivo_codigo="ASIENTO_CON_ERROR", nota="", quien="operador",
    )
    _m, planned, _c, items, conc = _run(outputs, asientos, asiento_dates=dates, registry=reg)
    assert conc["problems"] == [] and planned == [] and items == []


def test_asiento_compartido_sin_fecha_legible_requiere_asignacion():
    shared = ["A/x.pdf"]
    outputs = [
        _out("P1", "PAGO", "2026-07-21", 10_000_000, {"248": shared}),
        _out("P2", "PAGO", "2026-07-23", 5_000_000, {"248": shared}),
    ]
    _m, _p, _c, _i, conc = _run(outputs, {"A/x.pdf": _bank(15_000_000)}, asiento_dates={})
    assert _codes(conc) == [ASIENTOS_REQUIEREN_ASIGNACION]
    assert conc["problems"][0]["fechas_banco"] == ["2026-07-21", "2026-07-23"]


def test_asignacion_explicita_del_registro_prevalece():
    shared = ["A/x.pdf"]
    outputs = [
        _out("P1", "PAGO", "2026-07-21", 15_000_000, {"248": shared}),
        _out("P2", "PAGO", "2026-07-23", 0.01, {"248": shared}),
    ]
    reg = _registry()
    reg["assignments"].append(
        {"credito": "248", "asiento_pdf_path": "A/x.pdf", "id_pago": "P1", "status": "active"}
    )
    _m, planned, covered, _i, _conc = _run(
        outputs, {"A/x.pdf": _bank(15_000_000)}, registry=reg, asiento_dates={}
    )
    assert [o["id_pago"] for o in planned] == ["P1"]
    assert [o["id_pago"] for o in covered] == ["P2"]


def test_mismo_pdf_repetido_en_un_pago_genera_una_sola_linea():
    outputs = [_out("P1", "PAGO", "2026-07-21", 1_000_000, {"87": ["A/4621.pdf", "/a/4621.PDF"]})]
    asientos = {"A/4621.pdf": _bank(1_000_000), "/a/4621.PDF": _bank(1_000_000)}
    _m, planned, _c, items, conc = _run(outputs, asientos)
    assert planned[0]["credit_items"][0]["asiento_pdf_paths"] == ["A/4621.pdf"]
    assert len(items) == 1
    assert conc["problems"] == []


def test_asiento_ya_aplicado_en_otro_lote_no_cuenta_como_efectivo():
    outputs = [_out("P1", "PAGO", "2026-07-21", 1_000_000, {"87": ["A/a.pdf", "A/b.pdf"]})]
    asientos = {"A/a.pdf": _bank(1_000_000), "A/b.pdf": _bank(700_000)}

    def _hook(items):
        items[1]["applied_in_id_pago"] = "LOTE_ANTERIOR"

    _m, _p, _c, items, conc = _run(outputs, asientos, items_hook=_hook)
    assert conc["problems"] == []
    assert items[1]["conciliation_cash_note"] == "aplicado_en_otro_lote"


def test_grupo_con_otro_error_no_genera_problema_de_conciliacion():
    outputs = [_out("P1", "PAGO", "2026-07-21", 1_000_000, {"87": ["A/a.pdf"]})]

    def _hook(items):
        items[0]["application_status"] = "ERROR"
        items[0]["error_code"] = "TABLE_PATH_NOT_FOUND"

    _m, _p, _c, items, conc = _run(outputs, {"A/a.pdf": _bank(5)}, items_hook=_hook)
    assert conc["problems"] == []
    assert conc["groups"][0]["status"] == "PENDING_OTHER_PROBLEMS"
    assert items[0]["error_code"] == "TABLE_PATH_NOT_FOUND"


def test_cuadre_exacto_en_pesos_sin_tolerancia():
    outputs = [_out("P1", "PAGO", "2026-07-21", 1_000_000.00, {"87": ["A/a.pdf"]})]
    _m, _p, _c, _i, conc = _run(outputs, {"A/a.pdf": _bank(1_000_000.01)})
    assert _codes(conc) == [CONCILIACION_ASIENTOS_MAYOR_BANCO]
    _m, _p, _c, _i, conc = _run(outputs, {"A/a.pdf": _bank(999_999.99)})
    assert _codes(conc) == [CONCILIACION_BANCO_MAYOR_ASIENTOS]
    assert conc["problems"][0]["monto_sin_aplicar"] == 0.01


# --- el cuadre del grupo reemplaza al cuadre por un solo ID Pago ---------------------


def _warned_by_legacy(seen: list[list[str]]):
    def _hook(items):
        seen.extend(list(it.get("warnings") or []) for it in items)
        assert all(it.get("advisory_code") == BANK_ASIENTOS_NO_CUADRAN for it in items)

    return _hook


def test_247_real_dos_pagos_un_credito_cuadra_en_grupo_y_no_bloquea_apply():
    """Lote sandbox 2026-09-30: los 3 asientos quedan en el pago de 26.950.278."""
    shared = ["A/247.pdf", "A/247-2.pdf", "A/247-3.pdf"]
    outputs = [
        _out("P_CUOTA", "PAGO", "2026-09-25", 26_950_278, {"247": shared}, "RUEDA INVERSIONES"),
        _out("P_OTRO", "PAGO", "2026-09-25", 100_000_000, {"247": shared}, "RUEDA INVERSIONES"),
    ]
    asientos = {
        "A/247.pdf": _bank(26_958_424),
        "A/247-2.pdf": _bank(73_041_576),
        "A/247-3.pdf": _bank(26_950_278),
    }
    seen: list[list[str]] = []
    _m, planned, _c, items, conc = _run(
        outputs, asientos, legacy_check=True, items_hook=_warned_by_legacy(seen)
    )
    assert [o["id_pago"] for o in planned] == ["P_CUOTA"]
    assert len(seen) == 3 and all(len(w) == 1 for w in seen)
    assert conc["problems"] == []
    assert conc["groups"][0]["dates"][0]["diferencia"] == 0.0
    assert all(not it.get("warnings") and not it.get("advisory_code") for it in items)
    assert collect_disallowed_warning_items({"items": items}) == []


def test_322_real_cuatro_pagos_un_asiento_cuadra_en_grupo_y_no_bloquea_apply():
    outputs = [
        _out("P1", "PAGO", "2026-09-25", 3_000_000, {"322": ["A/322.pdf"]}, "SANTIAGO RIVERA MORA"),
        _out("P2", "PAGO", "2026-09-25", 2_000_000, {"322": ["A/322.pdf"]}, "SANTIAGO RIVERA MORA"),
        _out("P3", "PAGO", "2026-09-25", 2_000_000, {"322": ["A/322.pdf"]}, "SANTIAGO RIVERA MORA"),
        _out("P4", "PAGO", "2026-09-25", 2_395_064, {"322": ["A/322.pdf"]}, "SANTIAGO RIVERA MORA"),
    ]
    seen: list[list[str]] = []
    _m, _p, _c, items, conc = _run(
        outputs, {"A/322.pdf": _bank(9_395_064)}, legacy_check=True, items_hook=_warned_by_legacy(seen)
    )
    assert len(seen) == 1 and len(seen[0]) == 1
    assert conc["problems"] == []
    assert items[0]["warnings"] == [] and "advisory_code" not in items[0]
    assert collect_disallowed_warning_items({"items": items}) == []


def test_banco_mayor_confirmado_no_queda_bloqueado_por_el_aviso_por_pago():
    outputs = [_out("P1", "PAGO", "2026-09-23", 22_044_688, {"87": ["A/4621.pdf"]}, "CARBONERA")]
    asientos = {"A/4621.pdf": _bank(22_032_455)}
    reg, _ = add_confirmation(
        _registry(),
        key=conciliation_key("87", "2026-09-23"),
        credits=["87"],
        clientes={"87": "CARBONERA"},
        fecha_banco="2026-09-23",
        monto_banco=22_044_688,
        monto_asientos=22_032_455,
        nota="",
        quien="operador",
    )
    seen: list[list[str]] = []
    _m, _p, _c, items, conc = _run(
        outputs, asientos, registry=reg, legacy_check=True, items_hook=_warned_by_legacy(seen)
    )
    assert len(seen) == 1
    assert conc["problems"] == [] and len(conc["confirmed"]) == 1
    assert items[0]["application_status"] == "WOULD_APPLY"
    assert collect_disallowed_warning_items({"items": items}) == []


def test_grupo_con_problema_sigue_bloqueado_con_su_problema_de_conciliacion():
    outputs = [_out("P1", "PAGO", "2026-09-23", 22_044_688, {"87": ["A/4621.pdf"]}, "CARBONERA")]
    _m, _p, _c, items, conc = _run(outputs, {"A/4621.pdf": _bank(22_032_455)}, legacy_check=True)
    assert _codes(conc) == [CONCILIACION_BANCO_MAYOR_ASIENTOS]
    assert items[0]["error_code"] == CONCILIACION_BANCO_MAYOR_ASIENTOS
    assert items[0]["warnings"] == []


def test_otras_advertencias_del_asiento_se_conservan_y_siguen_bloqueando():
    outputs = [
        _out("P1", "PAGO", "2026-09-25", 3_000_000, {"322": ["A/322.pdf"]}),
        _out("P2", "PAGO", "2026-09-25", 6_395_064, {"322": ["A/322.pdf"]}),
    ]

    def _hook(items):
        items[0]["warnings"] = ["Otra advertencia del asiento", *items[0]["warnings"]]

    _m, _p, _c, items, conc = _run(
        outputs, {"A/322.pdf": _bank(9_395_064)}, legacy_check=True, items_hook=_hook
    )
    assert conc["problems"] == []
    assert items[0]["warnings"] == ["Otra advertencia del asiento"]
    assert collect_disallowed_warning_items({"items": items}) == [items[0]]


def test_sin_cuadre_de_grupo_el_aviso_por_pago_conserva_su_codigo_permitido():
    outputs = [_out("P1", "PAGO", "2026-07-21", 1_000_000, {"87": ["A/a.pdf"]})]

    def _hook(items):
        items[0]["application_status"] = "ERROR"
        items[0]["error_code"] = "TABLE_PATH_NOT_FOUND"

    _m, _p, _c, items, conc = _run(outputs, {"A/a.pdf": _bank(5)}, legacy_check=True, items_hook=_hook)
    assert conc["groups"][0]["status"] == "PENDING_OTHER_PROBLEMS"
    assert items[0]["advisory_code"] == BANK_ASIENTOS_NO_CUADRAN
    assert len(items[0]["warnings"]) == 1


# --- el cuadre del grupo no borra otros avisos permitidos (pago total) ---------------

PAYOFF_MSG = (
    "La operación fue confirmada como Pago total, pero la aplicación "
    "contable no dejaría el crédito cancelado."
)


def _payoff(items):
    from app.application.use_cases.amortization_fill_dry_run import PAYOFF_NOT_ACHIEVED

    for it in items:
        it["warnings"] = [PAYOFF_MSG]
        it["advisory_code"] = PAYOFF_NOT_ACHIEVED


def test_pago_total_sin_saldo_cero_conserva_su_aviso_al_cuadrar_en_grupo():
    from app.application.use_cases.amortization_fill_dry_run import PAYOFF_NOT_ACHIEVED

    outputs = [
        _out("P1", "PAGO", "2026-09-25", 3_000_000, {"322": ["A/322.pdf"]}),
        _out("P2", "PAGO", "2026-09-25", 6_395_064, {"322": ["A/322.pdf"]}),
    ]
    seen: list[str | None] = []
    _m, _p, _c, items, conc = _run(
        outputs,
        {"A/322.pdf": _bank(9_395_064)},
        legacy_check=True,
        pre_legacy_hook=_payoff,
        items_hook=lambda its: seen.extend(it.get("advisory_code") for it in its),
    )
    assert seen == [BANK_ASIENTOS_NO_CUADRAN]
    assert conc["problems"] == []
    assert items[0]["advisory_code"] == PAYOFF_NOT_ACHIEVED
    assert items[0]["warnings"] == [PAYOFF_MSG]
    assert collect_disallowed_warning_items({"items": items}) == []


def test_pago_total_con_banco_mayor_confirmado_en_fase_3_no_vuelve_a_bloquear():
    from app.application.use_cases.amortization_fill_dry_run import PAYOFF_NOT_ACHIEVED

    outputs = [_out("P1", "PAGO", "2026-09-23", 22_044_688, {"87": ["A/4621.pdf"]}, "CARBONERA")]
    reg, _ = add_confirmation(
        _registry(),
        key=conciliation_key("87", "2026-09-23"),
        credits=["87"],
        clientes={"87": "CARBONERA"},
        fecha_banco="2026-09-23",
        monto_banco=22_044_688,
        monto_asientos=22_032_455,
        nota="",
        quien="operador",
    )
    _m, _p, _c, items, conc = _run(
        outputs,
        {"A/4621.pdf": _bank(22_032_455)},
        registry=reg,
        legacy_check=True,
        pre_legacy_hook=_payoff,
    )
    assert conc["problems"] == [] and len(conc["confirmed"]) == 1
    assert items[0]["advisory_code"] == PAYOFF_NOT_ACHIEVED
    assert collect_disallowed_warning_items({"items": items}) == []


def test_aviso_residual_que_bloquea_identifica_el_credito_y_se_puede_excluir():
    from app.application.ui.amortization_operational_issues import (
        build_operational_issues_from_amortization_result,
    )

    outputs = [
        _out("P1", "PAGO", "2026-09-25", 3_000_000, {"322": ["A/322.pdf"]}, "SANTIAGO RIVERA"),
        _out("P2", "PAGO", "2026-09-25", 6_395_064, {"322": ["A/322.pdf"]}, "SANTIAGO RIVERA"),
        _out("P3", "PAGO", "2026-09-25", 1_000_000, {"87": ["A/87.pdf"]}, "CARBONERA"),
    ]

    def _hook(items):
        for it in items:
            if it["credito"] == "322":
                it["warnings"] = ["La fecha del asiento no coincide con la fecha del pago"]

    _m, _p, _c, items, conc = _run(
        outputs,
        {"A/322.pdf": _bank(9_395_064), "A/87.pdf": _bank(1_000_000)},
        legacy_check=True,
        items_hook=_hook,
    )
    assert [it["credito"] for it in collect_disallowed_warning_items({"items": items})] == ["322"]
    result = {
        "status": "preflight_failed",
        "preflight_error_code": "preflight_warnings_not_allowed",
        "can_apply": False,
        "outcome": "requires_correction",
        "items": items,
        "preflight": {"items": items, "conciliation": conc},
    }
    issues = build_operational_issues_from_amortization_result(result)
    assert len(issues) == 1
    issue = issues[0]
    assert issue["location"]["credit"] == "322"
    assert issue["decision"]["excludable"] is True
    assert issue["decision"]["group_credits"] == ["322"]
    assert "fecha del asiento no coincide" in issue["user_message"]
    assert "excluya el crédito" in issue["next_action"]
