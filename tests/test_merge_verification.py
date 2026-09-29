"""Verificación de fase 3: casos reales reproducidos con datos sintéticos."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any

import pytest

from app.application.services.accounting_pdf_parser import parse_accounting_text
from app.application.services.amortization_decisions import (
    add_confirmation,
    add_exclusion,
    add_tipo_correction,
    add_unused_asiento,
    empty_registry,
    set_group_assignments,
)
from app.application.services.historical_application_rows import _policy_fields_from_row
from app.application.services.merge_verification import (
    ASIGNAR_ASIENTOS,
    AsientoRead,
    apply_tipo_corrections,
    consolidation_targets,
    evaluate_verification,
    event_facts,
    group_key_of,
    group_needs_asiento_dates,
    group_payments,
    propose_assignment,
    build_payments,
    rad_credits_from_text,
    single_date_target,
    table_fact_requests,
)
from app.application.services.review_schema import resolve_policy_from_tipo_confirmado

PK = "payment-validation|banco_bogota|2026-09-25|abc12345-0000"
D = Decimal


def _registry() -> dict[str, Any]:
    return empty_registry(process_key=PK, bank_code="banco_bogota", report_date_iso="2026-09-25")


def _row(credito: str, *, tipo: str, monto: float, fecha: date, cliente: str = "CLIENTE") -> dict[str, Any]:
    policy = resolve_policy_from_tipo_confirmado(tipo)
    return {
        **_policy_fields_from_row(policy),
        "credito_digits": credito,
        "credito_label": f"CREDITO # {credito}",
        "cliente": cliente,
        "monto_banco": monto,
        "fecha_banco": fecha,
        "fecha_limite": date(2026, 9, 30),
        "observacion": "",
        "ruta_asientos_cell": f"CLIENTES/{cliente}/CREDITO # {credito}/ASIENTOS CONTABLES CRED {credito}",
        "ruta_tabla_amortizacion": f"CLIENTES/{cliente}/CREDITO # {credito}/TABLA {credito}.xlsx",
    }


def _pago(id_pago: str, rows: list[dict[str, Any]]) -> tuple[str, str, list[dict[str, Any]]]:
    return (id_pago, rows[0]["tipo_aplicacion"], rows)


def _ev(
    numero: str,
    fecha: str,
    cash: float,
    *,
    capital: float = 0,
    intereses: float = 0,
    mora: float = 0,
    retenciones: float = 0,
    saldos: float = 0,
    rads: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "numero": numero,
        "fecha": fecha,
        "cash": D(str(cash)).quantize(D("0.01")),
        "capital": D(str(capital)),
        "intereses": D(str(intereses)),
        "mora": D(str(mora)),
        "retenciones": D(str(retenciones)),
        "saldos_menores": D(str(saldos)),
        "rad_credits": rads if rads is not None else [],
    }


def _asiento(credito: str, name: str, *events: dict[str, Any], **kw: Any) -> AsientoRead:
    kw.setdefault("events", list(events))
    return AsientoRead(
        credito=credito,
        path=f"CLIENTES/X/CREDITO # {credito}/ASIENTOS CONTABLES CRED {credito}/{name}",
        name=name,
        web_url=f"https://sp/{name}",
        **kw,
    )


def _one(v: dict[str, Any]) -> dict[str, Any]:
    assert len(v["groups"]) == 1
    return v["groups"][0]


def _codes(g: dict[str, Any]) -> list[str]:
    return [m["code"] for m in g["motivos"]]


# --- happy path y casos normales -------------------------------------------------------


def test_happy_path_one_payment_one_credit_one_asiento_is_ready():
    groups = [_pago("P1", [_row("10", tipo="PAGO CUOTA", monto=1_000_000, fecha=date(2026, 9, 22))])]
    asientos = [_asiento("10", "A10.pdf", _ev("4001", "2026-09-22", 1_000_000, capital=800_000, intereses=200_000))]
    v = evaluate_verification(
        groups,
        asientos=asientos,
        missing_items=[],
        registry=None,
        table_facts={"10": {"cuota": D("1000000"), "saldo_capital": D("50000000")}},
    )
    g = _one(v)
    assert g["status"] == "ready"
    assert g["motivos"] == []
    assert g["consignado"] == 1_000_000 and g["segun_asientos"] == 1_000_000 and g["pendiente"] == 0
    assert g["fechas"][0]["status"] == "OK"
    assert g["fechas"][0]["conciliation_key"] == "10|2026-09-22"
    assert g["tipo"] is None
    assert v["credits_total"] == 1 and v["credits_ready"] == 1 and v["consolidados"] == 1


def test_abono_normal_is_ready_and_type_is_not_questioned():
    groups = [_pago("P1", [_row("11", tipo="ABONO A CAPITAL", monto=5_000_000, fecha=date(2026, 9, 22))])]
    asientos = [_asiento("11", "A11.pdf", _ev("4002", "2026-09-22", 5_000_000, capital=5_000_000))]
    g = _one(evaluate_verification(groups, asientos=asientos, missing_items=[], registry=None))
    assert g["status"] == "ready"
    assert g["tipo"] is None


def test_unreadable_amounts_keep_previous_behavior():
    """Si los asientos no se pudieron leer (sin datos) no se inventa un cuadre."""
    groups = [_pago("P1", [_row("10", tipo="PAGO CUOTA", monto=1_000_000, fecha=date(2026, 9, 22))])]
    asientos = [AsientoRead(credito="10", path="x/A10.pdf", name="A10.pdf", events=None)]
    g = _one(evaluate_verification(groups, asientos=asientos, missing_items=[], registry=None))
    assert g["status"] == "ready"
    assert g["segun_asientos"] is None
    assert g["fechas"] == []


def test_missing_items_become_reasons():
    groups = [
        _pago("P1", [_row("10", tipo="PAGO CUOTA", monto=1, fecha=date(2026, 9, 22))]),
        _pago("P2", [_row("20", tipo="PAGO CUOTA", monto=1, fecha=date(2026, 9, 22))]),
        _pago("P3", [_row("30", tipo="PAGO CUOTA", monto=1, fecha=date(2026, 9, 22))]),
    ]
    missing = [
        {"id_pago": "P1", "credito": "10", "error_code": "asiento_contable_not_found"},
        {"id_pago": "P2", "credito": "20", "error_code": "ACCOUNTING_PARSE_FAILED"},
        {"id_pago": "P3", "credito": "30", "error_code": "extract_routes_missing"},
    ]
    v = evaluate_verification(groups, asientos=[], missing_items=missing, registry=None)
    assert [_codes(g) for g in v["groups"]] == [["FALTA_ASIENTO"], ["ASIENTO_ILEGIBLE"], ["FALTA_EXTRACTO"]]
    assert v["credits_attention"] == 3
    assert all(g["primary_action"] == "revisar" for g in v["groups"])


# --- casos reales --------------------------------------------------------------------


def test_carbonera_87_bank_greater_needs_continue_then_ready_when_confirmed():
    groups = [_pago("P87", [_row("87", tipo="PAGO CUOTA", monto=22_044_688, fecha=date(2026, 9, 23))])]
    asientos = [_asiento("87", "4621.pdf", _ev("4621", "2026-09-23", 22_032_455, capital=21_884_233, intereses=148_222))]
    g = _one(evaluate_verification(groups, asientos=asientos, missing_items=[], registry=None))
    assert _codes(g) == ["DIFERENCIA_BANCO"]
    assert g["fechas"][0]["status"] == "BANK_GREATER"
    assert g["pendiente"] == 12_233
    assert g["actions"]["continuar"] is True

    reg, _ = add_confirmation(
        _registry(),
        key="87|2026-09-23",
        credits=["87"],
        clientes={},
        fecha_banco="2026-09-23",
        monto_banco="22044688",
        monto_asientos="22032455",
        nota="",
        quien="op",
        fase="consolidacion",
    )
    g2 = _one(evaluate_verification(groups, asientos=asientos, missing_items=[], registry=reg))
    assert g2["status"] == "ready"
    assert g2["fechas"][0]["status"] == "CONFIRMED"
    assert g2["fechas"][0]["confirmation"]["can_undo"] is True


def test_asientos_greater_than_bank_is_a_problem_without_continue():
    groups = [_pago("P1", [_row("10", tipo="PAGO CUOTA", monto=1_000_000, fecha=date(2026, 9, 22))])]
    asientos = [
        _asiento("10", "A.pdf", _ev("1", "2026-09-22", 1_000_000, capital=1_000_000)),
        _asiento("10", "B.pdf", _ev("2", "2026-09-22", 500_000, capital=500_000)),
    ]
    g = _one(evaluate_verification(groups, asientos=asientos, missing_items=[], registry=None))
    assert _codes(g) == ["DIFERENCIA_BANCO"]
    assert g["fechas"][0]["status"] == "ASIENTOS_GREATER"
    assert g["actions"]["continuar"] is False
    assert g["actions"]["no_corresponde"] is True


def test_intramaq_retentions_inside_asiento_cuadra_and_type_is_kept():
    groups = [_pago("P19", [_row("19", tipo="PAGO CUOTA", monto=15_894_345, fecha=date(2026, 2, 19))])]
    asientos = [
        _asiento(
            "19",
            "INTRAMAQ.pdf",
            _ev("3900", "2026-02-19", 15_894_345, capital=10_223_390, intereses=6_099_158, retenciones=428_203),
        )
    ]
    g = _one(
        evaluate_verification(
            groups,
            asientos=asientos,
            missing_items=[],
            registry=None,
            table_facts={"19": {"cuota": D("16322548"), "saldo_capital": D("200000000")}},
        )
    )
    assert g["status"] == "ready"
    assert g["has_retenciones"] is True
    assert g["tipo"] is None


@pytest.mark.parametrize(
    ("credito", "saldo"),
    [("111", 4), ("97", 2_516)],
    ids=["ABIBE_4", "CROIL_2516"],
)
def test_minor_balance_asiento_without_bank_line_is_not_money(credito: str, saldo: float):
    groups = [_pago("P", [_row(credito, tipo="PAGO CUOTA", monto=3_000_000, fecha=date(2026, 9, 22))])]
    asientos = [
        _asiento(credito, "cuota.pdf", _ev("4145", "2026-09-22", 3_000_000, capital=2_000_000, intereses=1_000_000)),
        _asiento(credito, "saldo.pdf", _ev("4146", "2026-09-22", 0, capital=saldo, saldos=saldo)),
    ]
    g = _one(evaluate_verification(groups, asientos=asientos, missing_items=[], registry=None))
    assert g["status"] == "ready"
    assert g["segun_asientos"] == 3_000_000
    assert g["has_saldos_menores"] is True
    saldo_row = next(a for a in g["asientos"] if a["name"] == "saldo.pdf")
    assert saldo_row["cash"] == 0


def test_maderpol_4120_retention_without_money_does_not_block():
    groups = [_pago("P248", [_row("248", tipo="PAGO TOTAL", monto=322_558_848, fecha=date(2026, 7, 21))])]
    asientos = [
        _asiento("248", "4119.pdf", _ev("4119", "2026-07-21", 322_558_848, capital=314_986_062, intereses=7_556_842)),
        _asiento("248", "4120.pdf", _ev("4120", "2026-07-23", 0, capital=574_411, retenciones=574_411)),
    ]
    g = _one(evaluate_verification(groups, asientos=asientos, missing_items=[], registry=None))
    assert g["status"] == "ready"
    assert g["tipo"] is None


def test_jasp_one_payment_two_credits():
    groups = [
        _pago(
            "PJASP",
            [
                _row("102", tipo="PAGO TOTAL", monto=105_000_000, fecha=date(2026, 9, 9), cliente="JASP"),
                _row("133", tipo="PAGO TOTAL", monto=105_000_000, fecha=date(2026, 9, 9), cliente="JASP"),
            ],
        )
    ]
    asientos = [
        _asiento("102", "102.pdf", _ev("5001", "2026-09-09", 60_000_000, capital=60_000_000, rads=["102"])),
        _asiento("133", "133.pdf", _ev("5002", "2026-09-09", 45_000_000, capital=45_000_000, rads=["133"])),
    ]
    v = evaluate_verification(groups, asientos=asientos, missing_items=[], registry=None)
    g = _one(v)
    assert g["group_key"] == "102+133"
    assert g["status"] == "ready"
    assert v["credits_total"] == 2 and v["credits_ready"] == 2 and v["consolidados"] == 1


def test_transp_95_194_shared_payment_with_shortfall():
    groups = [
        _pago(
            "PT",
            [
                _row("95", tipo="PAGO CUOTA", monto=50_000_000, fecha=date(2026, 9, 15), cliente="TRANSP"),
                _row("194", tipo="PAGO CUOTA", monto=50_000_000, fecha=date(2026, 9, 15), cliente="TRANSP"),
            ],
        )
    ]
    asientos = [
        _asiento("95", "95.pdf", _ev("1", "2026-09-15", 30_000_000, capital=25_000_000, intereses=5_000_000)),
        _asiento("194", "194.pdf", _ev("2", "2026-09-15", 19_990_000, capital=15_000_000, intereses=4_990_000)),
    ]
    g = _one(evaluate_verification(groups, asientos=asientos, missing_items=[], registry=None))
    assert g["group_key"] == "95+194"
    assert _codes(g) == ["DIFERENCIA_BANCO"]
    assert g["fechas"][0]["conciliation_key"] == "95+194|2026-09-15"
    assert g["tipo"] is None


def _groups_247() -> list[tuple[str, str, list[dict[str, Any]]]]:
    return [
        _pago("P-ABONO", [_row("247", tipo="ABONO A CAPITAL", monto=100_000_000, fecha=date(2026, 9, 22), cliente="RUEDA")]),
        _pago("P-CUOTA", [_row("247", tipo="PAGO CUOTA", monto=26_950_278, fecha=date(2026, 9, 25), cliente="RUEDA")]),
    ]


def _asientos_247() -> list[AsientoRead]:
    return [
        _asiento("247", "4634.pdf", _ev("4634", "2026-09-23", 100_000_000, capital=100_000_000)),
        _asiento("247", "4635.pdf", _ev("4635", "2026-09-25", 26_950_278, capital=20_000_000, intereses=7_000_000, retenciones=49_722)),
        _asiento("247", "4638.pdf", _ev("4638", "2026-09-25", 0, capital=10, saldos=10)),
    ]


def test_247_two_payments_later_dated_asiento_requires_assignment_with_unique_proposal():
    v = evaluate_verification(_groups_247(), asientos=_asientos_247(), missing_items=[], registry=None)
    g = _one(v)
    assert _codes(g) == [ASIGNAR_ASIENTOS]
    assert g["primary_action"] == "asignar"
    a = g["assignment"]
    assert a["required"] is True and a["tie"] is False and a["impossible"] is False
    by_name = {x.rsplit("/", 1)[-1]: pid for x, pid in a["proposal"].items()}
    assert by_name == {"4634.pdf": "P-ABONO", "4635.pdf": "P-CUOTA", "4638.pdf": "P-CUOTA"}
    rows = {x["name"]: x for x in g["asientos"]}
    assert rows["4634.pdf"]["eligible_id_pagos"] == ["P-ABONO"]
    assert rows["4635.pdf"]["eligible_id_pagos"] == ["P-ABONO", "P-CUOTA"]
    assert g["tipo"] is None
    assert g["fechas"] == []


def test_247_ready_after_explicit_assignment_and_no_type_question():
    asientos = _asientos_247()
    items = [
        {"credito": "247", "asiento_pdf_path": asientos[0].path, "id_pago": "P-ABONO", "fecha_banco": "2026-09-22"},
        {"credito": "247", "asiento_pdf_path": asientos[1].path, "id_pago": "P-CUOTA", "fecha_banco": "2026-09-25"},
        {"credito": "247", "asiento_pdf_path": asientos[2].path, "id_pago": "P-CUOTA", "fecha_banco": "2026-09-25"},
    ]
    reg, _ = set_group_assignments(_registry(), group_key="247", items=items, quien="op")
    g = _one(evaluate_verification(_groups_247(), asientos=asientos, missing_items=[], registry=reg))
    assert g["status"] == "ready"
    assert g["assignment"]["explicit"] is True and g["assignment"]["can_undo"] is True
    assert [f["status"] for f in g["fechas"]] == ["OK", "OK"]


def test_new_asiento_after_assignment_asks_again():
    asientos = _asientos_247()
    items = [
        {"credito": "247", "asiento_pdf_path": asientos[0].path, "id_pago": "P-ABONO", "fecha_banco": "2026-09-22"},
        {"credito": "247", "asiento_pdf_path": asientos[1].path, "id_pago": "P-CUOTA", "fecha_banco": "2026-09-25"},
    ]
    reg, _ = set_group_assignments(_registry(), group_key="247", items=items, quien="op")
    g = _one(evaluate_verification(_groups_247(), asientos=asientos, missing_items=[], registry=reg))
    assert ASIGNAR_ASIENTOS in _codes(g)
    assert g["assignment"]["can_undo"] is True


def test_two_date_payments_with_matching_asiento_dates_assign_automatically():
    groups = [
        _pago("P1", [_row("50", tipo="PAGO CUOTA", monto=1_000_000, fecha=date(2026, 9, 22))]),
        _pago("P2", [_row("50", tipo="PAGO CUOTA", monto=2_000_000, fecha=date(2026, 9, 24))]),
    ]
    asientos = [
        _asiento("50", "a.pdf", _ev("1", "2026-09-22", 1_000_000, capital=1_000_000)),
        _asiento("50", "b.pdf", _ev("2", "2026-09-24", 2_000_000, capital=2_000_000)),
    ]
    g = _one(evaluate_verification(groups, asientos=asientos, missing_items=[], registry=None))
    assert g["status"] == "ready"
    assert [f["status"] for f in g["fechas"]] == ["OK", "OK"]


def test_two_date_payments_with_later_asientos_tie_gives_no_proposal():
    groups = [
        _pago("P1", [_row("60", tipo="PAGO CUOTA", monto=1_000_000, fecha=date(2026, 9, 22))]),
        _pago("P2", [_row("60", tipo="PAGO CUOTA", monto=1_000_000, fecha=date(2026, 9, 23))]),
    ]
    asientos = [
        _asiento("60", "a.pdf", _ev("1", "2026-09-28", 1_000_000, capital=1_000_000)),
        _asiento("60", "b.pdf", _ev("2", "2026-09-28", 1_000_000, capital=1_000_000)),
    ]
    g = _one(evaluate_verification(groups, asientos=asientos, missing_items=[], registry=None))
    assert _codes(g) == [ASIGNAR_ASIENTOS]
    assert g["assignment"]["tie"] is True
    assert g["assignment"]["proposal"] == {}


def test_asiento_covering_two_dates_is_impossible_to_assign():
    groups = [
        _pago("P1", [_row("70", tipo="PAGO CUOTA", monto=10_000_000, fecha=date(2026, 9, 22))]),
        _pago("P2", [_row("70", tipo="PAGO CUOTA", monto=10_000_000, fecha=date(2026, 9, 25))]),
    ]
    asientos = [_asiento("70", "a.pdf", _ev("1", "2026-09-26", 20_000_000, capital=20_000_000))]
    g = _one(evaluate_verification(groups, asientos=asientos, missing_items=[], registry=None))
    assert g["assignment"]["impossible"] is True
    assert g["assignment"]["proposal"] == {}


def test_322_four_payments_same_date_share_asientos_without_assignment():
    groups = [
        _pago(f"P{i}", [_row("322", tipo="PAGO CUOTA", monto=1_000_000, fecha=date(2026, 9, 22))])
        for i in range(4)
    ]
    asientos = [
        _asiento("322", "4157.pdf", _ev("4157", "2026-09-22", 4_000_000, capital=3_000_000, intereses=1_000_000)),
        _asiento("322", "4158.pdf", _ev("4158", "2026-09-22", 0, capital=2_731, saldos=2_731)),
    ]
    v = evaluate_verification(groups, asientos=asientos, missing_items=[], registry=None)
    g = _one(v)
    assert g["status"] == "ready"
    assert g["assignment"]["required"] is False
    # Un solo consolidado: mismo grupo y misma fecha de pago (Entrega 3).
    assert v["consolidados"] == 1 and v["credits_total"] == 1


def test_asiento_of_other_credit_blocks_until_marked_unused():
    groups = [_pago("P322", [_row("322", tipo="PAGO CUOTA", monto=1_000_000, fecha=date(2026, 9, 22))])]
    asientos = [
        _asiento("322", "ok.pdf", _ev("1", "2026-09-22", 1_000_000, capital=1_000_000, rads=["322"])),
        _asiento("322", "otro.pdf", _ev("2", "2026-09-22", 500_000, capital=500_000, rads=["321"])),
    ]
    g = _one(evaluate_verification(groups, asientos=asientos, missing_items=[], registry=None))
    assert _codes(g) == ["ASIENTO_OTRO_CREDITO"]
    otro = next(a for a in g["asientos"] if a["name"] == "otro.pdf")
    assert otro["state_label"] == "Asiento de otro crédito"
    assert g["segun_asientos"] == 1_000_000

    reg, _ = add_unused_asiento(
        _registry(), path=asientos[1].path, credito_carpeta="322", nota="", quien="op",
        motivo_codigo="OTRO_CREDITO", fase="consolidacion",
    )
    g2 = _one(evaluate_verification(groups, asientos=asientos, missing_items=[], registry=reg))
    assert g2["status"] == "ready"
    otro2 = next(a for a in g2["asientos"] if a["name"] == "otro.pdf")
    assert otro2["state"] == "no_usado" and otro2["can_undo_unused"] is True


def test_asiento_dated_before_all_lot_payments_is_previous_payment():
    groups = [_pago("P1", [_row("10", tipo="PAGO CUOTA", monto=1_000_000, fecha=date(2026, 9, 22))])]
    asientos = [
        _asiento("10", "ok.pdf", _ev("2", "2026-09-22", 1_000_000, capital=1_000_000)),
        _asiento("10", "viejo.pdf", _ev("1", "2026-08-20", 1_000_000, capital=1_000_000)),
    ]
    g = _one(evaluate_verification(groups, asientos=asientos, missing_items=[], registry=None))
    assert _codes(g) == ["ASIENTO_PAGO_ANTERIOR"]
    assert g["segun_asientos"] == 1_000_000


def test_already_processed_asiento_is_gray_and_not_counted():
    groups = [_pago("P1", [_row("10", tipo="PAGO CUOTA", monto=1_000_000, fecha=date(2026, 9, 22))])]
    asientos = [
        _asiento("10", "ok.pdf", _ev("2", "2026-09-22", 1_000_000, capital=1_000_000)),
        AsientoRead(credito="10", path="x/dup.pdf", name="dup.pdf", processed=True, processed_at="2026-09-20T10:00:00Z"),
    ]
    g = _one(evaluate_verification(groups, asientos=asientos, missing_items=[], registry=None))
    assert g["status"] == "ready"
    dup = next(a for a in g["asientos"] if a["name"] == "dup.pdf")
    assert dup["state_label"] == "Ya aplicado el 20/09"
    assert dup["can_mark_unused"] is False


def test_unreadable_pdf_blocks_and_can_be_marked_unused():
    groups = [_pago("P1", [_row("10", tipo="PAGO CUOTA", monto=1_000_000, fecha=date(2026, 9, 22))])]
    asientos = [AsientoRead(credito="10", path="x/scan.pdf", name="scan.pdf", format_error="PDF_TEXT_NOT_EXTRACTABLE")]
    g = _one(evaluate_verification(groups, asientos=asientos, missing_items=[], registry=None))
    assert _codes(g) == ["ASIENTO_ILEGIBLE"]
    assert g["asientos"][0]["can_mark_unused"] is True


def test_excluded_group_and_summary():
    groups = [
        _pago("P1", [_row("10", tipo="PAGO CUOTA", monto=1, fecha=date(2026, 9, 22), cliente="A")]),
        _pago("P2", [_row("20", tipo="PAGO CUOTA", monto=1, fecha=date(2026, 9, 22), cliente="B")]),
    ]
    reg, _ = add_exclusion(
        _registry(), credits=["20"], clientes={"20": "B"}, id_pagos=["P2"], tablas={},
        motivo_codigo="FALTA_ASIENTO", nota="", quien="op", fase="consolidacion",
    )
    missing = [{"id_pago": "P2", "error_code": "asiento_contable_not_found"}]
    v = evaluate_verification(groups, asientos=[], missing_items=missing, registry=reg)
    statuses = {g["credits"][0]: g["status"] for g in v["groups"]}
    assert statuses == {"10": "ready", "20": "excluded"}
    assert v["credits_excluded"] == 1 and v["consolidados"] == 1
    assert v["excluded"] == [{"credito": "20", "cliente": "B", "motivo": "Falta el asiento de Contabilidad"}]
    assert v["all_excluded"] is False
    ex = next(g for g in v["groups"] if g["status"] == "excluded")
    assert ex["exclusion"]["can_undo"] is True


def test_all_excluded_flag():
    groups = [_pago("P1", [_row("10", tipo="PAGO CUOTA", monto=1, fecha=date(2026, 9, 22))])]
    reg, _ = add_exclusion(
        _registry(), credits=["10"], clientes={}, id_pagos=["P1"], tablas={},
        motivo_codigo="FALTA_ASIENTO", nota="", quien="op", fase="consolidacion",
    )
    v = evaluate_verification(groups, asientos=[], missing_items=[], registry=reg)
    assert v["all_excluded"] is True and v["consolidados"] == 0


# --- tipo según asientos ------------------------------------------------------------------


def _tipo_case(tipo: str, ev: dict[str, Any], facts: dict[str, Any] | None, registry=None):
    groups = [_pago("P1", [_row("40", tipo=tipo, monto=float(ev["cash"]), fecha=date(2026, 9, 22))])]
    return _one(
        evaluate_verification(
            groups,
            asientos=[_asiento("40", "a.pdf", ev)],
            missing_items=[],
            registry=registry,
            table_facts={"40": facts} if facts else None,
        )
    )


def test_extra_capital_suggests_cuota_plus_capital():
    g = _tipo_case(
        "PAGO CUOTA",
        _ev("1", "2026-09-22", 1_700_000, capital=1_500_000, intereses=200_000),
        {"cuota": D("1000000"), "saldo_capital": D("90000000")},
    )
    assert _codes(g) == ["CONFIRMAR_TIPO"]
    assert g["tipo"]["sugerido"] == "PAGO CUOTA + ABONO A CAPITAL"
    assert "PAGO CUOTA" in g["tipo"]["opciones"]
    assert "ABONO A CAPITAL" not in g["tipo"]["opciones"]


def test_rounding_of_one_peso_is_not_extra_capital():
    g = _tipo_case(
        "PAGO CUOTA",
        _ev("1", "2026-09-22", 1_000_001, capital=800_001, intereses=200_000),
        {"cuota": D("1000000"), "saldo_capital": D("90000000")},
    )
    assert g["status"] == "ready"


def test_mora_in_asiento_suggests_mora_plus_cuota():
    g = _tipo_case("PAGO CUOTA", _ev("1", "2026-09-22", 1_050_000, capital=800_000, intereses=200_000, mora=50_000), None)
    assert g["tipo"]["sugerido"] == "ABONO A CUOTAS EN MORA + PAGO CUOTA"


def test_declared_mora_without_mora_suggests_pago_cuota():
    g = _tipo_case("ABONO A CUOTAS EN MORA", _ev("1", "2026-09-22", 1_000_000, capital=800_000, intereses=200_000), None)
    assert g["tipo"]["sugerido"] == "PAGO CUOTA"


def test_balance_to_zero_suggests_pago_total():
    g = _tipo_case(
        "PAGO CUOTA",
        _ev("1", "2026-09-22", 5_100_000, capital=5_000_000, intereses=100_000),
        {"cuota": D("1000000"), "saldo_capital": D("5000000")},
    )
    assert g["tipo"]["sugerido"] == "PAGO TOTAL"


def test_type_correction_resolves_question():
    reg, _ = add_tipo_correction(
        _registry(), group_key="40", id_pago="P1", credits=["40"], tipo_anterior="PAGO CUOTA",
        tipo_nuevo="PAGO CUOTA + ABONO A CAPITAL", nota="capital adicional", quien="op",
    )
    groups = apply_tipo_corrections(
        [_pago("P1", [_row("40", tipo="PAGO CUOTA", monto=1_700_000, fecha=date(2026, 9, 22))])], reg
    )
    g = _one(
        evaluate_verification(
            groups,
            asientos=[_asiento("40", "a.pdf", _ev("1", "2026-09-22", 1_700_000, capital=1_500_000, intereses=200_000))],
            missing_items=[],
            registry=reg,
            table_facts={"40": {"cuota": D("1000000"), "saldo_capital": D("90000000")}},
        )
    )
    assert g["status"] == "ready"
    assert g["tipo"]["needed"] is False
    assert g["tipo"]["actual"] == "PAGO CUOTA + ABONO A CAPITAL"
    assert g["tipo"]["declarado"] == "PAGO CUOTA"
    assert g["tipo"]["correction"]["can_undo"] is True


def test_apply_tipo_corrections_changes_name_and_extract_never_family():
    row = _row("40", tipo="PAGO CUOTA", monto=1, fecha=date(2026, 9, 22))
    reg, _ = add_tipo_correction(
        _registry(), group_key="40", id_pago="P1", credits=["40"], tipo_anterior="PAGO CUOTA",
        tipo_nuevo="PAGO TOTAL", nota="saldo en cero", quien="op",
    )
    [(_, _, rows)] = apply_tipo_corrections([_pago("P1", [row])], reg)
    assert rows[0]["tipo_aplicacion_original"] == "PAGO TOTAL"
    assert rows[0]["include_extract_in_composite"] is False
    assert rows[0]["tipo_aplicacion_declarado"] == "PAGO CUOTA"
    assert rows[0]["monto_banco"] == 1

    reg2, _ = add_tipo_correction(
        _registry(), group_key="40", id_pago="P1", credits=["40"], tipo_anterior="PAGO CUOTA",
        tipo_nuevo="ABONO A CAPITAL", nota="x", quien="op",
    )
    [(_, _, rows2)] = apply_tipo_corrections([_pago("P1", [row])], reg2)
    assert rows2[0]["tipo_aplicacion_original"] == "PAGO CUOTA"


def test_table_fact_requests_only_single_credit_single_payment_pago_family():
    groups = _groups_247() + [
        _pago("P9", [_row("9", tipo="PAGO CUOTA", monto=1, fecha=date(2026, 9, 22))]),
        _pago("P8", [_row("8", tipo="ABONO A CAPITAL", monto=1, fecha=date(2026, 9, 22))]),
    ]
    req = table_fact_requests(groups)
    assert set(req) == {"9"}
    assert req["9"][1] == "2026-09-30"


# --- lectura -------------------------------------------------------------------------------


def test_rad_credits_and_event_facts_from_parser():
    text = """4634
    Año       Mes      Día
23 9 2026 Fecha  : SIN ENTIDAD Entidad : 0 Soporte :
900111222-1 Nº Identificación : RUEDA INVERSIONES Nombre :
100,000,000.00 PAGO: No.Rad. 247 Linea 544 1 11100505
100,000,000.00 PAGO: No.Rad. 247 Linea 544 1 13410519
"""
    ev = parse_accounting_text(text, {"credito": "247"})
    facts = event_facts(ev)
    assert facts["numero"] == "4634"
    assert facts["fecha"] == "2026-09-23"
    assert facts["cash"] == D("100000000.00")
    assert facts["rad_credits"] == ["247"]
    assert rad_credits_from_text("PAGO: No.Rad. 102 ... No. Rad 133") == ["102", "133"]


def test_propose_assignment_places_zero_cash_on_latest_eligible_payment():
    payments = build_payments(_groups_247())
    proposal, tie, impossible = propose_assignment(payments, _asientos_247())
    assert not tie and not impossible
    assert proposal[_asientos_247()[2].path] == "P-CUOTA"


# --- asignación reutilizable para consolidar (Entrega 3) -----------------------------


def test_consolidation_targets_247_requires_assignment_until_operator_assigns():
    group = group_payments(build_payments(_groups_247()))[0]
    asientos = _asientos_247()
    assert group_key_of(group) == "247"
    assert group_needs_asiento_dates(group) is True
    assert consolidation_targets(group, asientos, None) is None
    items = [
        {"credito": "247", "asiento_pdf_path": asientos[0].path, "id_pago": "P-ABONO", "fecha_banco": "2026-09-22"},
        {"credito": "247", "asiento_pdf_path": asientos[1].path, "id_pago": "P-CUOTA", "fecha_banco": "2026-09-25"},
        {"credito": "247", "asiento_pdf_path": asientos[2].path, "id_pago": "P-CUOTA", "fecha_banco": "2026-09-25"},
    ]
    reg, _ = set_group_assignments(_registry(), group_key="247", items=items, quien="op")
    targets = consolidation_targets(group, asientos, reg)
    assert targets == {asientos[0].path: "P-ABONO", asientos[1].path: "P-CUOTA", asientos[2].path: "P-CUOTA"}


def test_consolidation_targets_by_matching_date_and_unreadable_blocks():
    groups = [
        _pago("P1", [_row("50", tipo="PAGO CUOTA", monto=1_000_000, fecha=date(2026, 9, 22))]),
        _pago("P2", [_row("50", tipo="PAGO CUOTA", monto=2_000_000, fecha=date(2026, 9, 24))]),
    ]
    group = group_payments(build_payments(groups))[0]
    a = _asiento("50", "a.pdf", _ev("1", "2026-09-22", 1_000_000, capital=1_000_000))
    b = _asiento("50", "b.pdf", _ev("2", "2026-09-24", 2_000_000, capital=2_000_000))
    assert consolidation_targets(group, [a, b], None) == {a.path: "P1", b.path: "P2"}
    unreadable = _asiento("50", "c.pdf", events=None)
    assert consolidation_targets(group, [a, b, unreadable], None) is None
    assert consolidation_targets(group, [], None) == {}


def test_single_date_target_prefers_pago_over_abono_same_date():
    groups = [
        _pago("P-AB", [_row("80", tipo="ABONO A CAPITAL", monto=5_000_000, fecha=date(2026, 9, 25))]),
        _pago("P-PC", [_row("80", tipo="PAGO CUOTA", monto=1_000_000, fecha=date(2026, 9, 25))]),
    ]
    group = group_payments(build_payments(groups))[0]
    assert group_needs_asiento_dates(group) is False
    assert single_date_target(group, "80") == "P-PC"
    assert single_date_target(group, "999") == ""


def test_two_dates_count_two_consolidados():
    groups = [
        _pago("P1", [_row("50", tipo="PAGO CUOTA", monto=1_000_000, fecha=date(2026, 9, 22))]),
        _pago("P2", [_row("50", tipo="PAGO CUOTA", monto=2_000_000, fecha=date(2026, 9, 24))]),
    ]
    asientos = [
        _asiento("50", "a.pdf", _ev("1", "2026-09-22", 1_000_000, capital=1_000_000)),
        _asiento("50", "b.pdf", _ev("2", "2026-09-24", 2_000_000, capital=2_000_000)),
    ]
    v = evaluate_verification(groups, asientos=asientos, missing_items=[], registry=None)
    assert v["consolidados"] == 2
