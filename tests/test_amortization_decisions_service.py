"""Servicio de decisiones de fase 4: validación contra el último intento y Control."""

from __future__ import annotations

import asyncio
import json
from typing import Any

import pytest

from app.application.services import amortization_decisions as reg_mod
from app.application.services.amortization_decisions import (
    DecisionsRegistryError,
    empty_registry,
    lock_active_decisions,
    registry_filename,
)
from app.application.ui import amortization_decisions_service as svc
from app.application.ui.schemas import (
    UiAmortizationPlanSummary,
    UiIssueDecision,
    UiIssueLocation,
    UiLastAmortizationAttempt,
    UiLink,
    UiOperationalIssue,
    UiPlanCreditInfo,
)
from app.application.use_cases.payment_validation_process_control import ProcessControlSnapshot
from tests.test_amortization_decisions_registry import FakeDrive

PK = "payment-validation|banco_bogota|2026-08-01|abc12345-0000"
MANIFEST = "LOGS/2026/08/01/merge_manifest_2026-08-01.json"
REG_PATH = f"LOGS/2026/08/01/{registry_filename('banco_bogota', '2026-08-01', PK)}"


def _issue(credit: str, group: list[str], *, confirmable: bool = False, excludable: bool = True,
           key: str | None = None, code: str = "CONCILIACION_ASIENTOS_MAYOR_BANCO") -> UiOperationalIssue:
    return UiOperationalIssue(
        issue_id=f"amort-{code}-{credit}-0",
        stage="amortization",
        category="correction_required",
        title=f"Consignación · Crédito {credit}",
        user_message="Problema de conciliación.",
        location=UiIssueLocation(credit=credit, payment_id="P1", client_name=f"CLIENTE {credit}"),
        links=[UiLink(rel="amortization_table", label="Abrir tabla", path=f"T/{credit}.xlsx")],
        technical_reference=code,
        decision=UiIssueDecision(
            excludable=excludable,
            group_credits=group,
            group_key="+".join(group),
            confirmable=confirmable,
            conciliation_key=key,
            fecha_banco="2026-08-01",
            bank_amount=1004.0 if confirmable else 1000.0,
            asientos_amount=1000.0 if confirmable else 1200.0,
            unapplied_amount=4.0 if confirmable else None,
        ),
    )


def _attempt(*issues: UiOperationalIssue) -> UiLastAmortizationAttempt:
    return UiLastAmortizationAttempt(
        attempt_id="att-1",
        outcome="requires_correction",
        operational_issues=list(issues),
        plan_summary=UiAmortizationPlanSummary(
            lines_by_credit={"102": 2, "133": 1, "250": 3},
            tables_by_credit={"102": ["a"], "133": ["b"], "250": ["c", "d"]},
            credit_info={
                "133": UiPlanCreditInfo(
                    client_name="GRUPO JASP", table_path="T/133.xlsx", payment_ids=["P1"],
                    group_credits=["102", "133"],
                ),
            },
        ),
    )


def _snapshot(**overrides: Any) -> ProcessControlSnapshot:
    base = dict(
        control_file_path="CTL/control.xlsx",
        estado_proceso="CONSOLIDADO",
        is_active=True,
        process_key=PK,
        process_id="abc12345-0000",
        validation_file_path="",
        historical_file_path="",
        secretary_file_path="",
        email_pdf_path="",
        notify_idempotency_key="",
        merge_manifest_path=MANIFEST,
        merge_idempotency_key="",
        apply_idempotency_key="",
        bank_code="banco_bogota",
        bank_name="Banco de Bogotá",
        last_amortization_attempt_json=_attempt(
            _issue("133", ["102", "133"]),
            _issue("250", ["250"], confirmable=True, key="250|2026-08-01",
                   code="CONCILIACION_BANCO_MAYOR_ASIENTOS"),
            _issue("999", ["999"], excludable=False, code="DECISIONS_REGISTRY_UNAVAILABLE"),
        ).model_dump_json(),
    )
    base.update(overrides)
    return ProcessControlSnapshot(**base)


@pytest.fixture
def env(monkeypatch):
    reg_mod.clear_registry_cache()
    drive = FakeDrive()
    state: dict[str, Any] = {"snap": _snapshot(), "control_updates": [], "control_fail": False}

    async def _ctx(_g):
        return "s", "d"

    async def _read(_g, _s, _d, *, bank_code):
        return state["snap"]

    async def _update(_g, _s, _d, *, bank_code, updates):
        if state["control_fail"]:
            raise RuntimeError("control locked")
        state["control_updates"].append(updates)

    monkeypatch.setattr("app.application.use_cases.amortization_fill_dry_run._drive_context", _ctx)
    monkeypatch.setattr(svc, "read_process_control_snapshot", _read)
    monkeypatch.setattr(svc, "update_process_control_row2", _update)
    yield drive, state
    reg_mod.clear_registry_cache()


def _run(coro):
    return asyncio.run(coro)


def test_excluir_crea_registro_guarda_ruta_en_control_y_excluye_el_grupo(env):
    drive, state = env
    view = _run(
        svc.exclude_credit(
            drive, bank_code="banco_bogota", process_key=PK, credit="133",
            motivo_codigo="FALTA_ASIENTO", nota="", quien="ana",
        )
    )
    assert sorted(r.credit for r in view.excluded) == ["102", "133"]
    assert {r.motivo for r in view.excluded} == {"Falta el asiento de Contabilidad"}
    assert all(r.can_undo for r in view.excluded)
    # Planeado sin los excluidos: solo el crédito 250.
    assert (view.planned_lines, view.planned_tables) == (3, 2)
    stored = json.loads(drive.files[REG_PATH].decode("utf-8"))
    exc = stored["exclusions"][0]
    assert exc["credits"] == ["102", "133"]
    assert exc["clientes"]["133"] == "GRUPO JASP"
    assert exc["id_pagos"] == ["P1"]
    assert exc["quien"] == "ana"
    assert state["control_updates"][0]["DecisionsRegistryPath"] == REG_PATH


def test_excluir_credito_sin_problema_excluible_se_rechaza(env):
    drive, _ = env
    for credit in ("777", "999"):
        with pytest.raises(DecisionsRegistryError) as exc:
            _run(
                svc.exclude_credit(
                    drive, bank_code="banco_bogota", process_key=PK, credit=credit,
                    motivo_codigo="FALTA_ASIENTO", nota="", quien="ana",
                )
            )
        assert exc.value.error_code == "exclusion_not_available"
    assert drive.puts == []


def test_process_key_distinto_o_estado_no_permitido(env):
    drive, state = env
    with pytest.raises(DecisionsRegistryError) as exc:
        _run(svc.undo_credit_exclusion(drive, bank_code="banco_bogota", process_key=PK + "x",
                                       credit="133", quien="ana"))
    assert exc.value.error_code == "process_key_mismatch"
    for estado, active in (("AMORTIZACION_APLICADA", True), ("CONSOLIDADO", False),
                           ("CERRADO_AMORTIZACION_INCOMPLETA", True)):
        state["snap"] = _snapshot(estado_proceso=estado, is_active=active)
        with pytest.raises(DecisionsRegistryError) as exc:
            _run(svc.undo_credit_exclusion(drive, bank_code="banco_bogota", process_key=PK,
                                           credit="133", quien="ana"))
        assert exc.value.error_code == "decisions_not_allowed"


@pytest.mark.parametrize("estado", sorted(svc.DECISION_ALLOWED_STATES))
def test_estados_de_fase_4_permiten_decidir(env, estado):
    drive, state = env
    state["snap"] = _snapshot(estado_proceso=estado)
    view = _run(
        svc.exclude_credit(drive, bank_code="banco_bogota", process_key=PK, credit="102",
                           motivo_codigo="TABLA_CON_ERROR", nota="", quien="ana")
    )
    assert {r.credit for r in view.excluded} == {"102", "133"}


def test_fallo_al_guardar_ruta_en_control_es_visible_y_reintentable(env):
    drive, state = env
    state["control_fail"] = True
    with pytest.raises(DecisionsRegistryError) as exc:
        _run(svc.exclude_credit(drive, bank_code="banco_bogota", process_key=PK, credit="133",
                                motivo_codigo="FALTA_ASIENTO", nota="", quien="ana"))
    assert exc.value.error_code == "decisions_control_update_failed"
    assert exc.value.status_code == 503
    state["control_fail"] = False
    view = _run(svc.exclude_credit(drive, bank_code="banco_bogota", process_key=PK, credit="133",
                                   motivo_codigo="FALTA_ASIENTO", nota="", quien="ana"))
    stored = json.loads(drive.files[REG_PATH].decode("utf-8"))
    assert len(stored["exclusions"]) == 1  # idempotente
    assert len(view.excluded) == 2


def test_ruta_heredada_de_otro_proceso_no_se_reutiliza(env):
    drive, state = env
    stale = "LOGS/2026/07/31/decisiones_banco_bogota_2026-07-31_zzz99999.json"
    state["snap"] = _snapshot(decisions_registry_path=stale)
    _run(svc.exclude_credit(drive, bank_code="banco_bogota", process_key=PK, credit="133",
                            motivo_codigo="FALTA_ASIENTO", nota="", quien="ana"))
    assert stale not in drive.files
    assert REG_PATH in drive.files
    assert state["control_updates"][0]["DecisionsRegistryPath"] == REG_PATH


def test_undo_exclusion_y_bloqueo_despues_de_procesar(env):
    drive, state = env
    _run(svc.exclude_credit(drive, bank_code="banco_bogota", process_key=PK, credit="133",
                            motivo_codigo="FALTA_ASIENTO", nota="", quien="ana"))
    state["snap"] = _snapshot(decisions_registry_path=REG_PATH)
    view = _run(svc.undo_credit_exclusion(drive, bank_code="banco_bogota", process_key=PK,
                                          credit="102", quien="ana"))
    assert view.excluded == []
    assert view.planned_lines is None

    _run(svc.exclude_credit(drive, bank_code="banco_bogota", process_key=PK, credit="133",
                            motivo_codigo="FALTA_ASIENTO", nota="", quien="ana"))
    reg = json.loads(drive.files[REG_PATH].decode("utf-8"))
    locked, _ = lock_active_decisions(reg, attempt_id="apply-1")
    drive.files[REG_PATH] = json.dumps(locked).encode("utf-8")
    reg_mod.clear_registry_cache()
    with pytest.raises(DecisionsRegistryError) as exc:
        _run(svc.undo_credit_exclusion(drive, bank_code="banco_bogota", process_key=PK,
                                       credit="133", quien="ana"))
    assert exc.value.error_code == "exclusion_locked"


def test_exclusion_de_fase_3_no_se_deshace_desde_amortizacion(env):
    drive, state = env
    reg, _ = reg_mod.add_exclusion(
        empty_registry(process_key=PK, bank_code="banco_bogota", report_date_iso="2026-08-01"),
        credits=["400"], clientes={"400": "CLIENTE"}, id_pagos=["P9"], tablas={},
        motivo_codigo="FALTA_ASIENTO", nota="", quien="ana", fase="consolidacion",
    )
    drive.files[REG_PATH] = json.dumps(reg).encode("utf-8")
    state["snap"] = _snapshot(decisions_registry_path=REG_PATH)
    view = svc.build_decisions_view(reg, None)
    row = next(r for r in view.excluded if r.credit == "400")
    assert row.can_undo is False
    with pytest.raises(DecisionsRegistryError) as exc:
        _run(svc.undo_credit_exclusion(drive, bank_code="banco_bogota", process_key=PK,
                                       credit="400", quien="ana"))
    assert exc.value.error_code == "exclusion_from_consolidation"


def test_confirmar_solo_la_diferencia_confirmable_del_intento(env):
    drive, _ = env
    with pytest.raises(DecisionsRegistryError) as exc:
        _run(svc.confirm_conciliation(drive, bank_code="banco_bogota", process_key=PK,
                                      conciliation_key="133|2026-08-01", nota="", quien="ana"))
    assert exc.value.error_code == "confirmation_not_available"
    view = _run(svc.confirm_conciliation(drive, bank_code="banco_bogota", process_key=PK,
                                         conciliation_key="250|2026-08-01",
                                         nota="Saldo a favor", quien="ana"))
    assert len(view.confirmations) == 1
    conf = view.confirmations[0]
    assert (conf.bank_amount, conf.asientos_amount, conf.unapplied_amount) == (1004.0, 1000.0, 4.0)
    assert conf.nota == "Saldo a favor" and conf.can_undo
    view = _run(svc.undo_conciliation_confirmation(drive, bank_code="banco_bogota", process_key=PK,
                                                   conciliation_key="250|2026-08-01", quien="ana"))
    assert view.confirmations == []


def test_vista_cerrada_lista_creditos_sin_amortizar_sin_deshacer():
    reg = empty_registry(process_key=PK, bank_code="banco_bogota", report_date_iso="2026-08-01")
    reg["exclusions"].append(
        {
            "exclusion_id": "e1", "status": "active", "credits": ["133"],
            "clientes": {"133": "JASP"}, "tablas": {"133": "T/133.xlsx"},
            "motivo_codigo": "FALTA_ASIENTO", "motivo": "Falta el asiento de Contabilidad",
            "nota": "", "locked_at": "2026-08-01T10:00:00-05:00",
        }
    )
    open_view = svc.build_decisions_view(reg, None)
    assert open_view.excluded[0].can_undo is False  # bloqueada tras Procesar
    closed = svc.build_decisions_view(reg, None, web_urls={"T/133.xlsx": "https://sp/t133"}, closed=True)
    assert closed.excluded == [] and closed.confirmations == []
    row = closed.credits_not_amortized[0]
    assert (row.credit, row.client_name, row.motivo) == ("133", "JASP", "Falta el asiento de Contabilidad")
    assert row.table_link is not None and row.table_link.web_url == "https://sp/t133"
    reg["closure"] = {
        "estado": "CERRADO_AMORTIZACION_INCOMPLETA",
        "creditos_sin_amortizar": [
            {"credito": "133", "cliente": "JASP", "motivo": "Otro motivo", "motivo_codigo": "OTRO",
             "tabla_amortizacion_path": "T/133.xlsx"},
        ],
    }
    closed = svc.build_decisions_view(reg, None, closed=True)
    assert closed.credits_not_amortized[0].motivo == "Otro motivo"


def _partial_attempt(applied: dict[str, list[str]]) -> UiLastAmortizationAttempt:
    base = _attempt()
    plan = base.plan_summary.model_copy(update={"applied_by_credit": applied})
    return base.model_copy(update={"outcome": "partial", "plan_summary": plan})


def test_planeado_tras_parcial_cuenta_solo_lo_pendiente():
    reg = empty_registry(process_key=PK, bank_code="banco_bogota", report_date_iso="2026-08-01")
    view = svc.build_decisions_view(reg, _partial_attempt({"250": ["c", "d"]}))
    # 250 ya quedó registrado: solo 102 y 133 siguen pendientes.
    assert (view.planned_lines, view.planned_tables) == (3, 2)


def test_planeado_tras_parcial_sin_nada_pendiente_es_cero():
    reg = empty_registry(process_key=PK, bank_code="banco_bogota", report_date_iso="2026-08-01")
    reg["exclusions"].append(
        {
            "exclusion_id": "e1", "status": "active", "credits": ["102", "133"],
            "clientes": {}, "tablas": {}, "motivo_codigo": "FALTA_ASIENTO",
            "motivo": "Falta el asiento de Contabilidad", "nota": "",
        }
    )
    view = svc.build_decisions_view(reg, _partial_attempt({"250": ["c", "d"]}))
    assert (view.planned_lines, view.planned_tables) == (0, 0)


def test_planeado_sin_excluidos_ni_aplicados_no_se_informa():
    reg = empty_registry(process_key=PK, bank_code="banco_bogota", report_date_iso="2026-08-01")
    view = svc.build_decisions_view(reg, _attempt())
    assert view.planned_lines is None


def test_detalle_sin_registro_o_ilegible(env):
    drive, _ = env
    snap = _snapshot()
    assert _run(svc.load_decisions_for_detail(drive, site_id="s", drive_id="d", snapshot=snap,
                                              attempt=None, closed=False)) is None
    snap = _snapshot(decisions_registry_path=REG_PATH)
    view = _run(svc.load_decisions_for_detail(drive, site_id="s", drive_id="d", snapshot=snap,
                                              attempt=None, closed=False))
    assert view is not None and view.available is False
    assert "No se pudo leer" in (view.user_message or "")
