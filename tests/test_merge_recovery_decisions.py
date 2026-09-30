"""Decisiones de fase 3 al reconsolidar desde amortización parcial (recuperación de formato)."""
from __future__ import annotations

import asyncio
import json
from typing import Any

import pytest

from app.application.services.amortization_decisions import (
    DecisionsRegistryError,
    active_confirmations,
    add_exclusion,
    lock_active_decisions,
)
from app.application.ui import amortization_decisions_service as ads
from app.application.ui import merge_decisions_service as svc
from app.application.use_cases import amortization_fill_dry_run
from tests.test_merge_decisions_service import _carbonera, _kw
from tests.test_ui_amortization_action import PROCESS_KEY
from tests.ui_fixtures import make_snap


def _attempt(credit: str, reference: str) -> str:
    return json.dumps(
        {
            "attempt_id": "j1",
            "outcome": "partial",
            "created_at": "2026-09-23T12:00:00-05:00",
            "operational_issues": [
                {
                    "issue_id": "i1",
                    "stage": "amortization",
                    "category": "correction_required",
                    "severity": "business",
                    "recoverable": True,
                    "title": f"Crédito {credit}",
                    "user_message": "El asiento no se pudo leer.",
                    "location": {"credit": credit},
                    "technical_reference": reference,
                }
            ],
            "affected_payment_ids": [],
        }
    )


def _snap(estado: str, attempt: str = "") -> Any:
    return make_snap(
        estado_proceso=estado,
        process_key=PROCESS_KEY,
        bank_code="banco_bogota",
        historical_file_path="historico/cartera.xlsx",
        email_pdf_path="correos/x.pdf",
        merge_idempotency_key=PROCESS_KEY,
        merge_manifest_path="trazabilidad/manifest.json",
        last_amortization_attempt_json=attempt,
    )


def _install(monkeypatch, snap, state) -> None:
    """Contexto real (estado del Control) con verificación y registro en memoria."""

    async def _drive(graph):
        return "site", "drive"

    async def _read(graph, site_id, drive_id, *, bank_code):
        return snap

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

    monkeypatch.setattr(amortization_fill_dry_run, "_drive_context", _drive)
    monkeypatch.setattr(ads, "read_process_control_snapshot", _read)
    monkeypatch.setattr(svc, "_verification", _verification)
    monkeypatch.setattr(svc, "_mutate", _mutate)
    monkeypatch.setattr(svc, "_save_path_in_control", _noop)
    monkeypatch.setattr(svc, "_respond", _respond)


def _confirm_87():
    return asyncio.run(
        svc.confirm_difference(None, **_kw(conciliation_key=_key_87(), nota="Diferencia no aplicada"))
    )


def _key_87() -> str:
    state = _carbonera()
    return state.verification()["groups"][0]["fechas"][0]["conciliation_key"]


def test_parcial_con_formato_permite_decidir_sobre_el_credito_pendiente(monkeypatch):
    # Antes: la verificación pedía «Continuar con los asientos» y el servicio respondía 409.
    state = _carbonera()
    _install(monkeypatch, _snap("AMORTIZACION_PARCIAL", _attempt("87", "PDF_TEXT_NOT_EXTRACTABLE")), state)
    assert state.verification()["groups"][0]["status"] == "attention"

    v = _confirm_87()

    assert v["groups"][0]["status"] == "ready"
    assert state.mutations == 1
    assert active_confirmations(state.reg)[0]["fase"] == "consolidacion"


def test_parcial_no_permite_decidir_sobre_un_credito_ya_aplicado(monkeypatch):
    state = _carbonera()
    _install(monkeypatch, _snap("AMORTIZACION_PARCIAL", _attempt("53", "PDF_TEXT_NOT_EXTRACTABLE")), state)

    with pytest.raises(DecisionsRegistryError) as err:
        _confirm_87()

    assert err.value.error_code == "credit_already_applied"
    assert "87" in err.value.user_message
    assert "_" not in err.value.user_message
    assert state.mutations == 0


def test_parcial_sin_reconsolidacion_permitida_sigue_bloqueado(monkeypatch):
    state = _carbonera()
    _install(monkeypatch, _snap("AMORTIZACION_PARCIAL", _attempt("87", "AMORTIZATION_TABLE_INVALID")), state)

    with pytest.raises(DecisionsRegistryError) as err:
        _confirm_87()

    assert err.value.error_code == "decisions_not_allowed"
    assert state.mutations == 0


@pytest.mark.parametrize("estado", ["CONSOLIDADO", "AMORTIZACION_APLICADA", "ERROR_APPLY"])
def test_otros_estados_de_fase_4_siguen_sin_decisiones_de_consolidacion(monkeypatch, estado):
    state = _carbonera()
    _install(monkeypatch, _snap(estado, _attempt("87", "PDF_TEXT_NOT_EXTRACTABLE")), state)

    with pytest.raises(DecisionsRegistryError) as err:
        _confirm_87()

    assert err.value.error_code == "decisions_not_allowed"


def _readiness_calls(monkeypatch, snap) -> list[str]:
    from types import SimpleNamespace

    from app.application.ui import process_query
    from app.application.ui.merge_readiness import MergeReadiness

    calls: list[str] = []

    async def _assess(graph, s, bank_code):
        calls.append(s.estado_proceso)
        return MergeReadiness(
            status="incomplete",
            expected_groups=1,
            ready_groups=0,
            missing_groups=0,
            missing_items=[],
            folder_links=[],
            checked_at="2026-09-23T12:00:00Z",
            user_message="0 de 1 créditos listos para consolidar.",
            next_action="",
        )

    monkeypatch.setattr(process_query, "assess_merge_readiness", _assess)
    service = process_query.UiProcessQueryService(SimpleNamespace(), graph=object(), assess_merge=True)
    result = asyncio.run(service._maybe_merge_readiness(SimpleNamespace(snapshot=snap)))
    assert (result is not None) == bool(calls)
    return calls


def test_detalle_en_recuperacion_trae_la_verificacion_para_decidir(monkeypatch):
    snap = _snap("AMORTIZACION_PARCIAL", _attempt("87", "PDF_TEXT_NOT_EXTRACTABLE"))
    assert _readiness_calls(monkeypatch, snap) == ["AMORTIZACION_PARCIAL"]


@pytest.mark.parametrize(
    "estado,attempt",
    [
        ("AMORTIZACION_PARCIAL", _attempt("87", "AMORTIZATION_TABLE_INVALID")),
        ("AMORTIZACION_APLICADA", _attempt("87", "PDF_TEXT_NOT_EXTRACTABLE")),
        ("ERROR_APPLY", ""),
    ],
)
def test_detalle_sin_recuperacion_no_verifica_consolidacion(monkeypatch, estado, attempt):
    assert _readiness_calls(monkeypatch, _snap(estado, attempt)) == []


def test_en_recuperacion_siguen_disponibles_reconsolidar_y_cerrar_sin_amortizar(monkeypatch):
    from app.application.ui.feature_flags import reset_ui_fail_closed_log_for_tests
    from app.application.ui.merge_readiness import MergeReadiness
    from app.application.ui.process_projection import (
        PaymentProcessProjectionService,
        ProjectionSources,
    )

    for key, value in {
        "UI_ENABLED": "true",
        "UI_WRITE_ENABLED": "true",
        "UI_MERGE_ENABLED": "true",
        "ACTIVE_ENVIRONMENT": "sandbox",
    }.items():
        monkeypatch.setenv(key, value)
    monkeypatch.delenv("WEBSITE_INSTANCE_ID", raising=False)
    reset_ui_fail_closed_log_for_tests()
    readiness = MergeReadiness(
        status="incomplete",
        expected_groups=1,
        ready_groups=0,
        missing_groups=0,
        missing_items=[],
        folder_links=[],
        checked_at="2026-09-23T12:00:00Z",
        user_message="0 de 1 créditos listos para consolidar.",
        next_action="",
        verification=_carbonera().verification(),
    )
    snap = _snap("AMORTIZACION_PARCIAL", _attempt("87", "PDF_TEXT_NOT_EXTRACTABLE"))
    detail = PaymentProcessProjectionService().project(
        ProjectionSources(snapshot=snap, merge_readiness=readiness, merge_readiness_status="incomplete")
    )
    actions = detail.available_actions
    assert actions["force_rebuild"].allowed is True
    assert actions["soft_close"].allowed is True
    assert actions["merge"].allowed is False
    assert detail.merge_readiness is not None
    assert detail.merge_readiness.verification["credits_attention"] == 1


def test_parcial_respeta_el_bloqueo_de_exclusiones_de_fase_4(monkeypatch):
    state = _carbonera()
    reg, entry = add_exclusion(
        state.reg,
        credits=["87"],
        clientes={"87": "CARBONERA"},
        id_pagos=["P87"],
        tablas={},
        motivo_codigo="FALTA_ASIENTO",
        nota="",
        quien="op",
        issue_codes=["PDF_TEXT_NOT_EXTRACTABLE"],
        fase="amortizacion",
    )
    state.reg, _ = lock_active_decisions(reg, attempt_id="apply-1")
    _install(monkeypatch, _snap("AMORTIZACION_PARCIAL", _attempt("87", "PDF_TEXT_NOT_EXTRACTABLE")), state)

    with pytest.raises(DecisionsRegistryError) as err:
        asyncio.run(svc.undo_credit_exclusion(None, **_kw(credit="87")))

    assert err.value.error_code == "exclusion_locked"
    assert state.mutations == 0
