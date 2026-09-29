"""Decisiones de fase 3 (Consolidar): validación del servicio y endpoints /processes/merge/*."""
from __future__ import annotations

from datetime import date
from decimal import Decimal
from types import SimpleNamespace
from typing import Any

import pytest

from app.application.job_manager import get_job_manager
from app.application.services.amortization_decisions import (
    DecisionsRegistryError,
    active_confirmations,
    active_exclusions,
    active_tipo_corrections,
    explicit_assignments,
    unused_asiento_paths,
)
from app.application.services.merge_verification import apply_tipo_corrections, evaluate_verification
from app.application.ui import merge_decisions_service as svc
from app.application.ui.schemas import UiMergeDecisionResponse, UiMergeReadiness
from tests.test_merge_verification import (
    _asiento,
    _asientos_247,
    _ev,
    _groups_247,
    _pago,
    _registry,
    _row,
)
from tests.test_ui_amortization_action import (  # noqa: F401 (fixture autouse)
    ORIGIN,
    PROCESS_KEY,
    _cleanup,
    _client_with_session,
    _headers,
)

D = Decimal
BASE = "/api/ui/v1/processes/merge"


class _State:
    def __init__(self, groups, asientos, *, missing=None, facts=None) -> None:
        self.groups = groups
        self.asientos = asientos
        self.missing = missing or []
        self.facts = facts
        self.reg: dict[str, Any] = _registry()
        self.mutations = 0

    def verification(self) -> dict[str, Any]:
        return evaluate_verification(
            apply_tipo_corrections(self.groups, self.reg),
            asientos=self.asientos,
            missing_items=self.missing,
            registry=self.reg,
            table_facts=self.facts,
        )


def _install(monkeypatch, state: _State) -> None:
    async def _ctx(graph, bank_code, process_key):
        return SimpleNamespace(registry_path="logs/decisiones.json", bank_code=bank_code)

    async def _verification(graph, ctx):
        return state.verification()

    async def _mutate(graph, ctx, fn):
        out, result = fn(state.reg)
        state.reg = out
        state.mutations += 1
        return out, result

    async def _noop(graph, ctx):
        return None

    async def _respond(graph, ctx):
        return state.verification()

    monkeypatch.setattr(svc, "_ctx", _ctx)
    monkeypatch.setattr(svc, "_verification", _verification)
    monkeypatch.setattr(svc, "_mutate", _mutate)
    monkeypatch.setattr(svc, "_save_path_in_control", _noop)
    monkeypatch.setattr(svc, "_respond", _respond)


def _kw(**extra: Any) -> dict[str, Any]:
    return {"bank_code": "banco_bogota", "process_key": PROCESS_KEY, "quien": "operador", **extra}


def _carbonera() -> _State:
    groups = [_pago("P87", [_row("87", tipo="PAGO CUOTA", monto=22_044_688, fecha=date(2026, 9, 23), cliente="CARBONERA")])]
    asientos = [_asiento("87", "4621.pdf", _ev("4621", "2026-09-23", 22_032_455, capital=21_884_233, intereses=148_222))]
    return _State(groups, asientos)


def _happy() -> _State:
    groups = [_pago("P1", [_row("10", tipo="PAGO CUOTA", monto=1_000_000, fecha=date(2026, 9, 22))])]
    asientos = [_asiento("10", "A10.pdf", _ev("4001", "2026-09-22", 1_000_000, capital=800_000, intereses=200_000))]
    return _State(groups, asientos, facts={"10": {"cuota": D("1000000"), "saldo_capital": D("50000000")}})


def _run(coro):
    import asyncio

    return asyncio.run(coro)


# --- excluir --------------------------------------------------------------------------


def test_excluir_credito_con_atencion_registra_fase_consolidacion_y_se_puede_deshacer(monkeypatch):
    state = _carbonera()
    _install(monkeypatch, state)
    v = _run(svc.exclude_credit(None, **_kw(credit="87", motivo_codigo="FALTA_ASIENTO", nota="")))
    assert v["groups"][0]["status"] == "excluded"
    exc = active_exclusions(state.reg)[0]
    assert exc["fase"] == "consolidacion"
    assert exc["id_pagos"] == ["P87"]
    assert "DIFERENCIA_BANCO" in exc["issue_codes"]
    assert exc["asientos_dirs"]["87"].endswith("ASIENTOS CONTABLES CRED 87")

    again = _run(svc.exclude_credit(None, **_kw(credit="87", motivo_codigo="FALTA_ASIENTO", nota="")))
    assert again["groups"][0]["status"] == "excluded"
    assert state.mutations == 1

    v2 = _run(svc.undo_credit_exclusion(None, **_kw(credit="87")))
    assert v2["groups"][0]["status"] == "attention"
    assert active_exclusions(state.reg) == []


def test_no_se_excluye_un_credito_listo(monkeypatch):
    state = _happy()
    _install(monkeypatch, state)
    with pytest.raises(DecisionsRegistryError) as err:
        _run(svc.exclude_credit(None, **_kw(credit="10", motivo_codigo="FALTA_ASIENTO", nota="")))
    assert err.value.error_code == "exclusion_not_available"
    assert state.mutations == 0


def test_credito_que_no_esta_en_el_lote_404(monkeypatch):
    _install(monkeypatch, _happy())
    with pytest.raises(DecisionsRegistryError) as err:
        _run(svc.exclude_credit(None, **_kw(credit="999", motivo_codigo="FALTA_ASIENTO", nota="")))
    assert err.value.status_code == 404


# --- continuar con los asientos ------------------------------------------------------------


def test_continuar_con_los_asientos_deja_listo_y_deshacer_vuelve_a_pedirlo(monkeypatch):
    state = _carbonera()
    _install(monkeypatch, state)
    v = _run(svc.confirm_difference(None, **_kw(conciliation_key="87|2026-09-23", nota="")))
    g = v["groups"][0]
    assert g["status"] == "ready"
    conf = active_confirmations(state.reg)[0]
    assert conf["origen"] == "consolidar" and conf["fase"] == "consolidacion"

    v2 = _run(svc.undo_difference_confirmation(None, **_kw(conciliation_key="87|2026-09-23")))
    assert v2["groups"][0]["status"] == "attention"


def test_continuar_no_disponible_si_los_asientos_superan_al_banco(monkeypatch):
    groups = [_pago("P1", [_row("10", tipo="PAGO CUOTA", monto=1_000_000, fecha=date(2026, 9, 22))])]
    asientos = [
        _asiento("10", "A.pdf", _ev("1", "2026-09-22", 1_000_000, capital=1_000_000)),
        _asiento("10", "B.pdf", _ev("2", "2026-09-22", 500_000, capital=500_000)),
    ]
    state = _State(groups, asientos)
    _install(monkeypatch, state)
    with pytest.raises(DecisionsRegistryError) as err:
        _run(svc.confirm_difference(None, **_kw(conciliation_key="10|2026-09-22", nota="")))
    assert err.value.error_code == "confirmation_not_available"
    assert state.mutations == 0


# --- asignar asientos a sus pagos -----------------------------------------------------------


def _items_247(state: _State, mapping: dict[str, str]) -> list[dict[str, str]]:
    by_name = {a.name: a.path for a in state.asientos}
    return [{"asiento_path": by_name[n], "id_pago": pid} for n, pid in mapping.items()]


def test_asignacion_247_confirmada_deja_listo_y_registra_quien(monkeypatch):
    state = _State(_groups_247(), _asientos_247())
    _install(monkeypatch, state)
    items = _items_247(state, {"4634.pdf": "P-ABONO", "4635.pdf": "P-CUOTA", "4638.pdf": "P-CUOTA"})
    v = _run(svc.save_assignment(None, **_kw(group_key="247", items=items)))
    g = v["groups"][0]
    assert g["status"] == "ready"
    rows = explicit_assignments(state.reg)
    assert {r["id_pago"] for r in rows} == {"P-ABONO", "P-CUOTA"}
    assert all(r.get("created_by") == "operador" or r.get("quien") == "operador" for r in rows)
    assert active_confirmations(state.reg) == []

    v2 = _run(svc.undo_assignment(None, **_kw(group_key="247")))
    assert v2["groups"][0]["primary_action"] == "asignar"


def test_asignacion_incompleta_no_se_guarda(monkeypatch):
    state = _State(_groups_247(), _asientos_247())
    _install(monkeypatch, state)
    items = _items_247(state, {"4634.pdf": "P-ABONO"})
    with pytest.raises(DecisionsRegistryError) as err:
        _run(svc.save_assignment(None, **_kw(group_key="247", items=items)))
    assert err.value.error_code == "assignment_incomplete"
    assert state.mutations == 0


def test_asiento_no_puede_ir_a_un_pago_posterior_a_su_fecha(monkeypatch):
    state = _State(_groups_247(), _asientos_247())
    _install(monkeypatch, state)
    items = _items_247(state, {"4634.pdf": "P-CUOTA", "4635.pdf": "P-CUOTA", "4638.pdf": "P-CUOTA"})
    with pytest.raises(DecisionsRegistryError) as err:
        _run(svc.save_assignment(None, **_kw(group_key="247", items=items)))
    assert err.value.error_code == "assignment_not_eligible"


def test_pago_excedido_no_se_puede_confirmar(monkeypatch):
    state = _State(_groups_247(), _asientos_247())
    _install(monkeypatch, state)
    items = _items_247(state, {"4634.pdf": "P-ABONO", "4635.pdf": "P-ABONO", "4638.pdf": "P-CUOTA"})
    with pytest.raises(DecisionsRegistryError) as err:
        _run(svc.save_assignment(None, **_kw(group_key="247", items=items)))
    assert err.value.error_code == "assignment_exceeds_payment"


def test_faltante_por_pago_queda_como_diferencia_no_aplicada(monkeypatch):
    groups = [
        _pago("P1", [_row("60", tipo="PAGO CUOTA", monto=1_000_000, fecha=date(2026, 9, 22))]),
        _pago("P2", [_row("60", tipo="PAGO CUOTA", monto=1_000_000, fecha=date(2026, 9, 23))]),
    ]
    asientos = [
        _asiento("60", "a.pdf", _ev("1", "2026-09-28", 1_000_000, capital=1_000_000)),
        _asiento("60", "b.pdf", _ev("2", "2026-09-28", 999_000, capital=999_000)),
    ]
    state = _State(groups, asientos)
    _install(monkeypatch, state)
    items = [
        {"asiento_path": asientos[0].path, "id_pago": "P1"},
        {"asiento_path": asientos[1].path, "id_pago": "P2"},
    ]
    v = _run(svc.save_assignment(None, **_kw(group_key="60", items=items)))
    assert v["groups"][0]["status"] == "ready"
    conf = active_confirmations(state.reg)
    assert [c["conciliation_key"] for c in conf] == ["60|2026-09-23"]
    assert conf[0]["nota"] == "Diferencia no aplicada" and conf[0]["origen"] == "asignacion"


def test_asignacion_sobre_verificacion_vieja_pide_verificar_de_nuevo(monkeypatch):
    state = _State(_groups_247(), _asientos_247())
    _install(monkeypatch, state)
    items = [{"asiento_path": "otra/carpeta/x.pdf", "id_pago": "P-ABONO"}]
    with pytest.raises(DecisionsRegistryError) as err:
        _run(svc.save_assignment(None, **_kw(group_key="247", items=items)))
    assert err.value.error_code == "assignment_stale"
    assert "Verifique de nuevo" in err.value.user_message


def test_asignacion_no_requerida_se_rechaza(monkeypatch):
    state = _happy()
    _install(monkeypatch, state)
    items = [{"asiento_path": state.asientos[0].path, "id_pago": "P1"}]
    with pytest.raises(DecisionsRegistryError) as err:
        _run(svc.save_assignment(None, **_kw(group_key="10", items=items)))
    assert err.value.error_code == "assignment_not_required"


# --- no corresponde a este pago ---------------------------------------------------------------


def test_asiento_de_otro_credito_no_corresponde_y_deshacer(monkeypatch):
    groups = [_pago("P322", [_row("322", tipo="PAGO CUOTA", monto=1_000_000, fecha=date(2026, 9, 22))])]
    asientos = [
        _asiento("322", "ok.pdf", _ev("1", "2026-09-22", 1_000_000, capital=1_000_000, rads=["322"])),
        _asiento("322", "otro.pdf", _ev("2", "2026-09-22", 500_000, capital=500_000, rads=["321"])),
    ]
    state = _State(groups, asientos)
    _install(monkeypatch, state)
    v = _run(svc.mark_asiento_unused(None, **_kw(asiento_path=asientos[1].path, motivo_codigo="OTRO_CREDITO")))
    assert v["groups"][0]["status"] == "ready"
    assert asientos[1].path.casefold() in unused_asiento_paths(state.reg)

    v2 = _run(svc.undo_asiento_unused(None, **_kw(asiento_path=asientos[1].path)))
    assert v2["groups"][0]["status"] == "attention"


def test_asiento_ya_aplicado_no_se_puede_marcar(monkeypatch):
    from app.application.services.merge_verification import AsientoRead

    groups = [_pago("P1", [_row("10", tipo="PAGO CUOTA", monto=1_000_000, fecha=date(2026, 9, 22))])]
    asientos = [
        _asiento("10", "ok.pdf", _ev("2", "2026-09-22", 1_000_000, capital=1_000_000)),
        AsientoRead(credito="10", path="x/dup.pdf", name="dup.pdf", processed=True, processed_at="2026-09-20T10:00:00Z"),
    ]
    state = _State(groups, asientos)
    _install(monkeypatch, state)
    with pytest.raises(DecisionsRegistryError) as err:
        _run(svc.mark_asiento_unused(None, **_kw(asiento_path="x/dup.pdf", motivo_codigo="NO_CORRESPONDE")))
    assert err.value.error_code == "asiento_not_available"


def test_motivo_de_no_usado_invalido(monkeypatch):
    from app.application.services.merge_verification import AsientoRead

    groups = [_pago("P1", [_row("10", tipo="PAGO CUOTA", monto=1_000_000, fecha=date(2026, 9, 22))])]
    asientos = [AsientoRead(credito="10", path="x/scan.pdf", name="scan.pdf", format_error="PDF_TEXT_NOT_EXTRACTABLE")]
    state = _State(groups, asientos)
    _install(monkeypatch, state)
    with pytest.raises(DecisionsRegistryError) as err:
        _run(svc.mark_asiento_unused(None, **_kw(asiento_path="x/scan.pdf", motivo_codigo="INVENTADO")))
    assert err.value.status_code == 422


# --- usar el tipo según los asientos ------------------------------------------------------------


def _tipo_state() -> _State:
    groups = [_pago("P1", [_row("40", tipo="PAGO CUOTA", monto=1_700_000, fecha=date(2026, 9, 22))])]
    asientos = [_asiento("40", "a.pdf", _ev("1", "2026-09-22", 1_700_000, capital=1_500_000, intereses=200_000))]
    return _State(groups, asientos, facts={"40": {"cuota": D("1000000"), "saldo_capital": D("90000000")}})


def test_usar_tipo_segun_asientos_registra_anterior_y_nuevo(monkeypatch):
    state = _tipo_state()
    _install(monkeypatch, state)
    v = _run(svc.use_tipo(None, **_kw(id_pago="P1", tipo="PAGO CUOTA + ABONO A CAPITAL", nota="capital adicional")))
    g = v["groups"][0]
    assert g["status"] == "ready"
    corr = active_tipo_corrections(state.reg)[0]
    assert corr["tipo_anterior"] == "PAGO CUOTA"
    assert corr["tipo_nuevo"] == "PAGO CUOTA + ABONO A CAPITAL"

    v2 = _run(svc.undo_tipo(None, **_kw(id_pago="P1")))
    assert v2["groups"][0]["tipo"]["needed"] is True


def test_tipo_incompatible_se_rechaza(monkeypatch):
    state = _tipo_state()
    _install(monkeypatch, state)
    with pytest.raises(DecisionsRegistryError) as err:
        _run(svc.use_tipo(None, **_kw(id_pago="P1", tipo="ABONO A CAPITAL", nota="x")))
    assert err.value.error_code == "tipo_not_compatible"
    assert state.mutations == 0


def test_tipo_exige_nota(monkeypatch):
    state = _tipo_state()
    _install(monkeypatch, state)
    with pytest.raises(DecisionsRegistryError):
        _run(svc.use_tipo(None, **_kw(id_pago="P1", tipo="PAGO CUOTA + ABONO A CAPITAL", nota="  ")))


def test_tipo_no_disponible_si_no_hay_pregunta(monkeypatch):
    _install(monkeypatch, _happy())
    with pytest.raises(DecisionsRegistryError) as err:
        _run(svc.use_tipo(None, **_kw(id_pago="P1", tipo="PAGO CUOTA", nota="x")))
    assert err.value.error_code == "tipo_not_available"


# --- endpoints ------------------------------------------------------------------------------


def _response() -> UiMergeDecisionResponse:
    return UiMergeDecisionResponse(
        ok=True,
        merge_readiness=UiMergeReadiness(
            status="incomplete",
            user_message="12 de 14 créditos listos para consolidar.",
            next_action="Revise los créditos que requieren atención.",
        ),
    )


@pytest.fixture
def merge_calls(monkeypatch) -> list[tuple[str, dict[str, Any]]]:
    monkeypatch.setenv("UI_MERGE_ENABLED", "true")
    recorded: list[tuple[str, dict[str, Any]]] = []

    def _fake(name):
        async def _fn(graph, **kwargs):
            recorded.append((name, kwargs))
            return _response()

        return _fn

    for name in (
        "exclude_credit", "undo_credit_exclusion", "confirm_difference", "undo_difference_confirmation",
        "save_assignment", "undo_assignment", "mark_asiento_unused", "undo_asiento_unused",
        "use_tipo", "undo_tipo",
    ):
        monkeypatch.setattr(svc, name, _fake(name))
    return recorded


_ENDPOINTS = [
    ("/exclusions", {"credit": "87", "motivo_codigo": "FALTA_ASIENTO", "nota": ""}, "exclude_credit"),
    ("/exclusions/undo", {"credit": "87"}, "undo_credit_exclusion"),
    ("/confirmations", {"conciliation_key": "87|2026-09-23", "nota": ""}, "confirm_difference"),
    ("/confirmations/undo", {"conciliation_key": "87|2026-09-23"}, "undo_difference_confirmation"),
    (
        "/assignments",
        {"group_key": "247", "items": [{"asiento_path": "a/4634.pdf", "id_pago": "P-ABONO"}]},
        "save_assignment",
    ),
    ("/assignments/undo", {"group_key": "247"}, "undo_assignment"),
    ("/unused-asientos", {"asiento_path": "a/otro.pdf", "motivo_codigo": "OTRO_CREDITO"}, "mark_asiento_unused"),
    ("/unused-asientos/undo", {"asiento_path": "a/otro.pdf"}, "undo_asiento_unused"),
    ("/tipo", {"id_pago": "P1", "tipo": "PAGO TOTAL", "nota": "saldo en cero"}, "use_tipo"),
    ("/tipo/undo", {"id_pago": "P1"}, "undo_tipo"),
]


@pytest.mark.parametrize("suffix,body,expected", _ENDPOINTS)
def test_endpoints_llaman_al_servicio_con_el_usuario(monkeypatch, merge_calls, suffix, body, expected):
    client, csrf = _client_with_session(monkeypatch)
    res = client.post(
        BASE + suffix,
        json={"bank_code": "banco_bogota", "process_key": PROCESS_KEY, **body},
        headers=_headers(csrf),
    )
    assert res.status_code == 200, res.text
    assert res.json()["merge_readiness"]["user_message"].startswith("12 de 14")
    name, kwargs = merge_calls[0]
    assert name == expected
    assert kwargs["quien"] == "operator"


@pytest.mark.parametrize("suffix,body,_expected", _ENDPOINTS)
def test_endpoints_exigen_csrf(monkeypatch, merge_calls, suffix, body, _expected):
    client, _csrf = _client_with_session(monkeypatch)
    res = client.post(
        BASE + suffix,
        json={"bank_code": "banco_bogota", "process_key": PROCESS_KEY, **body},
        headers={"Origin": ORIGIN, "Content-Type": "application/json"},
    )
    assert res.status_code == 403
    assert merge_calls == []


def test_flag_de_merge_apagado_bloquea(monkeypatch, merge_calls):
    client, csrf = _client_with_session(monkeypatch)
    monkeypatch.setenv("UI_MERGE_ENABLED", "false")
    res = client.post(
        BASE + "/exclusions",
        json={"bank_code": "banco_bogota", "process_key": PROCESS_KEY, "credit": "87",
              "motivo_codigo": "FALTA_ASIENTO"},
        headers=_headers(csrf),
    )
    assert res.status_code == 403
    assert res.json()["detail"]["error_code"] == "ui_merge_disabled"
    assert merge_calls == []


def test_operacion_en_curso_409(monkeypatch, merge_calls):
    client, csrf = _client_with_session(monkeypatch)
    get_job_manager()._amortization_active = True
    try:
        res = client.post(
            BASE + "/assignments/undo",
            json={"bank_code": "banco_bogota", "process_key": PROCESS_KEY, "group_key": "247"},
            headers=_headers(csrf),
        )
    finally:
        get_job_manager()._amortization_active = False
    assert res.status_code == 409
    assert res.json()["detail"]["error_code"] == "merge_busy"
    assert merge_calls == []


@pytest.mark.parametrize(
    "suffix,body",
    [
        ("/unused-asientos", {"asiento_path": "a.pdf", "motivo_codigo": "INVENTADO"}),
        ("/tipo", {"id_pago": "P1", "tipo": "PAGO TOTAL", "nota": ""}),
        ("/assignments", {"group_key": "247", "items": [{"asiento_path": "a", "id_pago": "P", "x": 1}]}),
    ],
)
def test_validacion_del_cuerpo(monkeypatch, merge_calls, suffix, body):
    client, csrf = _client_with_session(monkeypatch)
    res = client.post(
        BASE + suffix,
        json={"bank_code": "banco_bogota", "process_key": PROCESS_KEY, **body},
        headers=_headers(csrf),
    )
    assert res.status_code == 422
    assert merge_calls == []


def test_error_de_negocio_se_traduce_con_mensaje(monkeypatch, merge_calls):
    async def _locked(graph, **_k):
        raise DecisionsRegistryError(
            "assignment_locked",
            "Los consolidados ya se generaron con esta decisión; no se puede deshacer.",
        )

    monkeypatch.setattr(svc, "undo_assignment", _locked)
    client, csrf = _client_with_session(monkeypatch)
    res = client.post(
        BASE + "/assignments/undo",
        json={"bank_code": "banco_bogota", "process_key": PROCESS_KEY, "group_key": "247"},
        headers=_headers(csrf),
    )
    assert res.status_code == 409
    detail = res.json()["detail"]
    assert detail["error_code"] == "assignment_locked"
    assert "no se puede deshacer" in detail["user_message"]


def test_registro_ilegible_falla_cerrado(monkeypatch, merge_calls):
    async def _unavailable(graph, **_k):
        raise DecisionsRegistryError(
            "decisions_registry_unavailable",
            "No se pudo leer el registro de decisiones. Actualice e intente nuevamente.",
            status_code=503,
        )

    monkeypatch.setattr(svc, "exclude_credit", _unavailable)
    client, csrf = _client_with_session(monkeypatch)
    res = client.post(
        BASE + "/exclusions",
        json={"bank_code": "banco_bogota", "process_key": PROCESS_KEY, "credit": "87",
              "motivo_codigo": "FALTA_ASIENTO"},
        headers=_headers(csrf),
    )
    assert res.status_code == 503
    assert res.json()["detail"]["error_code"] == "decisions_registry_unavailable"


def test_error_inesperado_no_filtra_detalle_tecnico(monkeypatch, merge_calls):
    async def _boom(graph, **_k):
        raise RuntimeError("graph exploded: token=secret")

    monkeypatch.setattr(svc, "use_tipo", _boom)
    client, csrf = _client_with_session(monkeypatch)
    res = client.post(
        BASE + "/tipo",
        json={"bank_code": "banco_bogota", "process_key": PROCESS_KEY, "id_pago": "P1",
              "tipo": "PAGO TOTAL", "nota": "x"},
        headers=_headers(csrf),
    )
    assert res.status_code >= 500
    assert "secret" not in res.text
