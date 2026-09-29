"""Problemas de conciliación en el modal de fase 4 y completitud del apply con exclusiones."""

from __future__ import annotations

from typing import Any

from app.application.services.merge_manifest_gate import assess_apply_event_completeness
from app.application.ui.amortization_operational_issues import (
    attach_operational_issues_to_amortization_result,
    build_operational_issues_from_amortization_result,
)


def _conciliation(problems: list[dict[str, Any]], credit_groups: dict[str, list[str]]) -> dict[str, Any]:
    return {
        "enabled": True,
        "problems": problems,
        "confirmed": [],
        "excluded": [],
        "credit_groups": credit_groups,
        "groups": [],
    }


def _carbonera_problem() -> dict[str, Any]:
    return {
        "group_key": "87",
        "credits": ["87"],
        "clientes": {"87": "CARBONERA"},
        "cliente": "CARBONERA",
        "id_pagos": ["P1"],
        "tablas": {"87": "clientes/CARBONERA/T87.xlsx"},
        "problem_id": "CONCILIACION_BANCO_MAYOR_ASIENTOS|87|2026-09-23",
        "code": "CONCILIACION_BANCO_MAYOR_ASIENTOS",
        "fecha_banco": "2026-09-23",
        "monto_banco": 22_044_688.0,
        "monto_asientos": 22_032_455.0,
        "diferencia": 12_233.0,
        "monto_sin_aplicar": 12_233.0,
        "conciliation_key": "87|2026-09-23",
        "confirmable": True,
        "excludable": True,
    }


def _jasp_problem() -> dict[str, Any]:
    return {
        "group_key": "102+133",
        "credits": ["102", "133"],
        "clientes": {"102": "JASP", "133": "JASP"},
        "cliente": "JASP",
        "id_pagos": ["P9"],
        "tablas": {},
        "problem_id": "CONCILIACION_ASIENTOS_MAYOR_BANCO|102+133|2026-09-09",
        "code": "CONCILIACION_ASIENTOS_MAYOR_BANCO",
        "fecha_banco": "2026-09-09",
        "monto_banco": 105_000_000.0,
        "monto_asientos": 110_000_000.0,
        "diferencia": -5_000_000.0,
        "conciliation_key": "102+133|2026-09-09",
        "confirmable": False,
        "excludable": True,
    }


def _blocked_item(credito: str, code: str) -> dict[str, Any]:
    return {
        "id_pago": "P1",
        "credito": credito,
        "cliente": "CLIENTE",
        "application_status": "ERROR",
        "error_code": code,
        "tabla_amortizacion_path": f"T/{credito}.xlsx",
    }


def _by_ref(issues: list[dict[str, Any]], ref: str) -> list[dict[str, Any]]:
    return [i for i in issues if i.get("technical_reference") == ref]


def test_banco_mayor_copy_en_espanol_con_pesos_y_decision_confirmable():
    result = {
        "outcome": "requires_correction",
        "can_apply": False,
        "conciliation": _conciliation([_carbonera_problem()], {"87": ["87"]}),
        "items": [_blocked_item("87", "CONCILIACION_BANCO_MAYOR_ASIENTOS")],
    }
    issues = build_operational_issues_from_amortization_result(result)
    assert len(issues) == 1  # el ítem bloqueado no duplica el problema
    issue = issues[0]
    assert "$22.044.688" in issue["user_message"]
    assert "$22.032.455" in issue["user_message"]
    assert "$12.233 sin aplicar" in issue["user_message"]
    assert "23/09/2026" in issue["user_message"]
    assert "CONCILIACION" not in issue["user_message"]
    assert "continúe con los asientos" in issue["next_action"]
    assert issue["value_found"] == "Asientos $22.032.455"
    assert issue["expected_values"] == ["Banco $22.044.688"]
    dec = issue["decision"]
    assert dec["confirmable"] and dec["excludable"]
    assert dec["conciliation_key"] == "87|2026-09-23"
    assert dec["unapplied_amount"] == 12_233.0
    assert issue["location"]["client_name"] == "CARBONERA"


def test_asientos_mayor_grupo_de_dos_creditos_excluye_ambos():
    result = {
        "outcome": "requires_correction",
        "can_apply": False,
        "conciliation": _conciliation(
            [_jasp_problem()], {"102": ["102", "133"], "133": ["102", "133"]}
        ),
    }
    issue = build_operational_issues_from_amortization_result(result)[0]
    assert issue["title"] == "Créditos 102, 133"
    assert "los créditos 102 y 133" in issue["user_message"]
    assert "$5.000.000" in issue["user_message"]
    assert "No se modificó ninguna tabla" in issue["user_message"]
    assert issue["decision"]["excludable"] is True
    assert issue["decision"]["confirmable"] is False
    assert issue["decision"]["group_credits"] == ["102", "133"]


def test_problema_por_credito_es_excluible_solo_si_el_credito_esta_en_el_lote():
    result = {
        "outcome": "requires_correction",
        "can_apply": False,
        "conciliation": _conciliation([], {"250": ["250", "251"], "251": ["250", "251"]}),
        "items": [
            _blocked_item("250", "TABLE_PATH_NOT_FOUND"),
            _blocked_item("999", "RETENCIONES_COLUMN_MISSING"),
        ],
    }
    issues = build_operational_issues_from_amortization_result(result)
    by_credit = {i["location"]["credit"]: i for i in issues if i.get("location")}
    assert by_credit["250"]["decision"]["excludable"] is True
    assert by_credit["250"]["decision"]["group_credits"] == ["250", "251"]
    assert by_credit["999"]["decision"]["excludable"] is False


def test_sin_modelo_de_lote_no_se_ofrece_excluir():
    result = {
        "outcome": "requires_correction",
        "can_apply": False,
        "items": [_blocked_item("250", "TABLE_PATH_NOT_FOUND")],
    }
    issues = build_operational_issues_from_amortization_result(result)
    assert issues and all(i["decision"]["excludable"] is False for i in issues)


def test_problemas_de_todo_el_lote_nunca_son_excluibles():
    result = {
        "outcome": "requires_correction",
        "can_apply": False,
        "conciliation": _conciliation([], {"250": ["250"]}),
        "decisions_registry_block": {
            "error_code": "DECISIONS_REGISTRY_UNAVAILABLE",
            "user_message": "No se pudo leer el registro de créditos excluidos de este proceso.",
            "next_action": "Actualice e intente de nuevo.",
        },
    }
    issues = build_operational_issues_from_amortization_result(result)
    reg = _by_ref(issues, "DECISIONS_REGISTRY_UNAVAILABLE")
    assert len(reg) == 1
    assert reg[0]["decision"]["excludable"] is False
    assert reg[0]["title"] == "Registro de decisiones no disponible"


def test_parcial_solo_por_exclusiones_no_genera_problema_de_respaldo():
    base = {
        "status": "partial",
        "outcome": "partial",
        "can_apply": True,
        "user_message": "Se actualizaron 1 tabla(s) de amortización. Créditos excluidos: 133 · JASP.",
        "next_action": "Cuando los créditos excluidos estén gestionados, cierre el proceso con amortización incompleta.",
        "tables_uploaded": ["T/250.xlsx"],
        "apply_wrote_changes": True,
    }
    only = {**base, "partial_only_exclusions": True}
    assert build_operational_issues_from_amortization_result(only) == []
    out = attach_operational_issues_to_amortization_result(only)
    assert out["user_message"] == base["user_message"]
    assert "operational_issues" not in out
    assert len(build_operational_issues_from_amortization_result(base)) == 1


# --- completitud ----------------------------------------------------------------------


def _manifest() -> dict[str, Any]:
    return {
        "outputs": [
            {"id_pago": "P1", "credit_items": [{"credito": "102"}, {"credito": "133"}]},
            {"id_pago": "P2", "credit_items": [{"credito": "250"}]},
            {"id_pago": "P3", "credit_items": [{"credito": "250"}]},
        ]
    }


def _applied(id_pago: str, credito: str) -> dict[str, Any]:
    return {"id_pago": id_pago, "credito": credito, "apply_status": "APPLIED"}


def test_completitud_con_pagos_cubiertos_y_creditos_excluidos():
    res = assess_apply_event_completeness(
        _manifest(),
        [_applied("P2", "250")],
        waived_pairs={("P3", "250")},
        excluded_pairs={("P1", "102"), ("P1", "133")},
    )
    assert res["all_expected_events_completed"] is True
    assert res["missing_credit_events"] == []
    assert res["waived_credit_events"] == [{"id_pago": "P3", "credito": "250"}]
    assert {e["credito"] for e in res["excluded_credit_events"]} == {"102", "133"}


def test_completitud_sin_exclusiones_conserva_el_comportamiento_previo():
    res = assess_apply_event_completeness(_manifest(), [_applied("P2", "250")])
    assert res["all_expected_events_completed"] is False
    assert {(m["id_pago"], m["credito"]) for m in res["missing_credit_events"]} == {
        ("P1", "102"), ("P1", "133"), ("P3", "250"),
    }
    assert "waived_credit_events" not in res and "excluded_credit_events" not in res
