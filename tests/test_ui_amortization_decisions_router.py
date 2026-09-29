"""Endpoints de decisiones de fase 4 (excluir / continuar con los asientos)."""
from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.application.job_manager import get_job_manager
from app.application.services.amortization_decisions import DecisionsRegistryError
from app.application.ui import amortization_decisions_service as svc
from app.application.ui.schemas import UiAmortizationDecisions, UiExcludedCredit
from tests.test_ui_amortization_action import (  # noqa: F401 (fixture autouse)
    ORIGIN,
    PROCESS_KEY,
    _cleanup,
    _client_with_session,
    _enable_local,
    _headers,
)
from tests.ui_test_app import create_ui_test_app

EXCLUDE = "/api/ui/v1/processes/amortization/exclusions"
EXCLUDE_UNDO = "/api/ui/v1/processes/amortization/exclusions/undo"
CONFIRM = "/api/ui/v1/processes/amortization/confirmations"
CONFIRM_UNDO = "/api/ui/v1/processes/amortization/confirmations/undo"


def _view() -> UiAmortizationDecisions:
    return UiAmortizationDecisions(
        excluded=[
            UiExcludedCredit(
                credit="133", client_name="JASP", motivo="Falta el asiento de Contabilidad",
                motivo_codigo="FALTA_ASIENTO", group_credits=["102", "133"], can_undo=True,
            )
        ],
        planned_lines=3,
        planned_tables=2,
    )


@pytest.fixture
def calls(monkeypatch) -> list[tuple[str, dict[str, Any]]]:
    recorded: list[tuple[str, dict[str, Any]]] = []

    def _fake(name):
        async def _fn(graph, **kwargs):
            recorded.append((name, kwargs))
            return _view()

        return _fn

    for name in ("exclude_credit", "undo_credit_exclusion", "confirm_conciliation",
                 "undo_conciliation_confirmation"):
        monkeypatch.setattr(svc, name, _fake(name))
    return recorded


def test_excluir_happy_path_devuelve_decisiones_y_registra_usuario(monkeypatch, calls):
    client, csrf = _client_with_session(monkeypatch)
    res = client.post(
        EXCLUDE,
        json={"bank_code": "banco_bogota", "process_key": PROCESS_KEY, "credit": "133",
              "motivo_codigo": "FALTA_ASIENTO", "nota": ""},
        headers=_headers(csrf),
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["ok"] is True
    assert body["decisions"]["excluded"][0]["credit"] == "133"
    assert body["decisions"]["planned_lines"] == 3
    name, kwargs = calls[0]
    assert name == "exclude_credit"
    assert kwargs["quien"] == "operator"
    assert kwargs["motivo_codigo"] == "FALTA_ASIENTO"


@pytest.mark.parametrize(
    "path,body,expected",
    [
        (EXCLUDE_UNDO, {"credit": "133"}, "undo_credit_exclusion"),
        (CONFIRM, {"conciliation_key": "87|2026-09-23", "nota": "ok"}, "confirm_conciliation"),
        (CONFIRM_UNDO, {"conciliation_key": "87|2026-09-23"}, "undo_conciliation_confirmation"),
    ],
)
def test_resto_de_endpoints_llaman_al_servicio(monkeypatch, calls, path, body, expected):
    client, csrf = _client_with_session(monkeypatch)
    res = client.post(
        path,
        json={"bank_code": "banco_bogota", "process_key": PROCESS_KEY, **body},
        headers=_headers(csrf),
    )
    assert res.status_code == 200, res.text
    assert calls[0][0] == expected


def test_sin_sesion_401(monkeypatch, calls):
    _enable_local(monkeypatch)
    client = TestClient(create_ui_test_app(), base_url=ORIGIN)
    res = client.post(
        EXCLUDE,
        json={"bank_code": "banco_bogota", "process_key": PROCESS_KEY, "credit": "1",
              "motivo_codigo": "FALTA_ASIENTO"},
        headers={"Origin": ORIGIN, "Content-Type": "application/json"},
    )
    assert res.status_code == 401
    assert calls == []


@pytest.mark.parametrize("path", [EXCLUDE, EXCLUDE_UNDO, CONFIRM, CONFIRM_UNDO])
def test_csrf_obligatorio(monkeypatch, calls, path):
    client, _csrf = _client_with_session(monkeypatch)
    res = client.post(
        path,
        json={"bank_code": "banco_bogota", "process_key": PROCESS_KEY, "credit": "1",
              "conciliation_key": "k", "motivo_codigo": "FALTA_ASIENTO"},
        headers={"Origin": ORIGIN, "Content-Type": "application/json"},
    )
    assert res.status_code == 403
    assert res.json()["detail"]["error_code"] == "invalid_csrf_token"
    assert calls == []


def test_flag_de_amortizacion_apagado_bloquea(monkeypatch, calls):
    client, csrf = _client_with_session(monkeypatch, amortization_enabled=False)
    res = client.post(
        EXCLUDE,
        json={"bank_code": "banco_bogota", "process_key": PROCESS_KEY, "credit": "1",
              "motivo_codigo": "FALTA_ASIENTO"},
        headers=_headers(csrf),
    )
    assert res.status_code == 403
    assert res.json()["detail"]["error_code"] == "ui_amortization_disabled"
    assert calls == []


def test_escritura_de_ui_apagada_bloquea(monkeypatch, calls):
    client, csrf = _client_with_session(monkeypatch)
    monkeypatch.setenv("UI_WRITE_ENABLED", "false")
    res = client.post(
        EXCLUDE,
        json={"bank_code": "banco_bogota", "process_key": PROCESS_KEY, "credit": "1",
              "motivo_codigo": "FALTA_ASIENTO"},
        headers=_headers(csrf),
    )
    assert res.status_code == 403
    assert calls == []


@pytest.mark.parametrize(
    "body",
    [
        {"credit": "1", "motivo_codigo": "INVENTADO"},
        {"credit": "1", "motivo_codigo": "OTRO", "nota": "x" * 301},
        {"credit": "1", "motivo_codigo": "FALTA_ASIENTO", "extra": True},
        {"motivo_codigo": "FALTA_ASIENTO"},
    ],
)
def test_validacion_del_cuerpo(monkeypatch, calls, body):
    client, csrf = _client_with_session(monkeypatch)
    res = client.post(
        EXCLUDE,
        json={"bank_code": "banco_bogota", "process_key": PROCESS_KEY, **body},
        headers=_headers(csrf),
    )
    assert res.status_code == 422
    assert calls == []


def test_operacion_en_curso_409(monkeypatch, calls):
    client, csrf = _client_with_session(monkeypatch)
    get_job_manager()._amortization_active = True
    res = client.post(
        EXCLUDE,
        json={"bank_code": "banco_bogota", "process_key": PROCESS_KEY, "credit": "1",
              "motivo_codigo": "FALTA_ASIENTO"},
        headers=_headers(csrf),
    )
    assert res.status_code == 409
    assert res.json()["detail"]["error_code"] == "amortization_busy"
    assert calls == []


def test_error_de_negocio_se_traduce_con_mensaje_para_el_operador(monkeypatch):
    async def _locked(graph, **_k):
        raise DecisionsRegistryError(
            "exclusion_locked",
            "La amortizaciÃ³n ya se procesÃ³ con este crÃ©dito excluido; no se puede deshacer.",
        )

    monkeypatch.setattr(svc, "undo_credit_exclusion", _locked)
    client, csrf = _client_with_session(monkeypatch)
    res = client.post(
        EXCLUDE_UNDO,
        json={"bank_code": "banco_bogota", "process_key": PROCESS_KEY, "credit": "1"},
        headers=_headers(csrf),
    )
    assert res.status_code == 409
    detail = res.json()["detail"]
    assert detail["error_code"] == "exclusion_locked"
    assert "no se puede deshacer" in detail["user_message"]


def test_error_inesperado_no_filtra_detalle_tecnico(monkeypatch):
    async def _boom(graph, **_k):
        raise RuntimeError("graph exploded: token=secret")

    monkeypatch.setattr(svc, "exclude_credit", _boom)
    client, csrf = _client_with_session(monkeypatch)
    res = client.post(
        EXCLUDE,
        json={"bank_code": "banco_bogota", "process_key": PROCESS_KEY, "credit": "1",
              "motivo_codigo": "FALTA_ASIENTO"},
        headers=_headers(csrf),
    )
    assert res.status_code >= 500
    assert "secret" not in res.text
