"""Regresiones F-01…F-05 (auditoría independencia RC)."""
from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app.adapters.primary.http.api_key_auth import ENV_API_HTTP_KEY
from app.adapters.primary.http.app_factory import create_app
from app.adapters.primary.http.deps import init_graph_client
from app.application.job_manager import JobManager
from app.application.services.review_schema import TipoAplicacion
from app.application.use_cases.amortization_fill_dry_run import (
    BANK_MONTO_BANCO_MISSING,
    _enrich_payment_outputs_monto_from_hist,
    _reconcile_bank_vs_asientos_for_payment_outputs,
)
from app.application.use_cases.merge_composite_validado_pdfs import _group_meta_from_rows
from app.application.use_cases.send_validar_extractos_notification import (
    _control_snap_already_notified,
)


class _MockGraph:
    async def get(self, *a, **k):
        return {}

    async def get_bytes(self, *a, **k):
        return b""

    async def put_bytes(self, *a, **k):
        return {}

    async def delete(self, *a, **k):
        return None

    async def post_json(self, *a, **k):
        return {}, 202


def test_group_meta_uses_positive_monto_from_any_row_not_only_first() -> None:
    rows = [
        {"cliente": "GEO", "monto_banco": None, "fecha_banco": None, "credito_digits": "200"},
        {"cliente": "GEO", "monto_banco": 10_000_000.0, "fecha_banco": None, "credito_digits": "100"},
    ]
    cliente, monto, _fecha, creditos = _group_meta_from_rows(
        rows, tipo_aplicacion=TipoAplicacion.PAGO.value
    )
    assert cliente == "GEO"
    assert monto == 10_000_000.0
    assert creditos == ("100", "200")


def test_payment_reconcile_fail_closed_when_manifest_monto_missing() -> None:
    items = [
        {
            "id_pago": "P1",
            "tipo_aplicacion": TipoAplicacion.PAGO.value,
            "asiento_pdf_path": "A/asiento.pdf",
            "payment_application": {"valor_pagado_cliente": 1_000_000},
            "error_code": None,
        }
    ]
    # Manifest declara el ID pero sin cifra usable.
    out = _reconcile_bank_vs_asientos_for_payment_outputs(
        [{"id_pago": "P1", "monto_banco": None}],
        items,
    )
    assert out[0]["error_code"] == BANK_MONTO_BANCO_MISSING
    assert out[0]["application_status"] == "ERROR"


def test_payment_reconcile_fail_closed_when_id_absent_from_manifest() -> None:
    items = [
        {
            "id_pago": "P9",
            "tipo_aplicacion": TipoAplicacion.PAGO.value,
            "asiento_pdf_path": "A/asiento.pdf",
            "payment_application": {"valor_pagado_cliente": 500_000},
            "error_code": None,
        }
    ]
    out = _reconcile_bank_vs_asientos_for_payment_outputs([], items)
    assert out[0]["error_code"] == BANK_MONTO_BANCO_MISSING


def test_enrich_monto_from_hist_when_manifest_lacks_it() -> None:
    outputs = [{"id_pago": "P1", "monto_banco": None}]
    hist = {("P1", "100"): {"monto_banco": 2_500_000.0}}
    _enrich_payment_outputs_monto_from_hist(outputs, hist)
    assert outputs[0]["monto_banco"] == 2_500_000.0


def test_notify_already_notified_with_idem_key_even_without_email_pdf() -> None:
    snap = SimpleNamespace(
        estado_proceso="PENDIENTE_ASIENTOS",
        notify_idempotency_key="payment-validation|banco_bogota|2026-04-22",
        email_pdf_path="",
    )
    assert _control_snap_already_notified(snap) is True


def test_notify_not_already_notified_without_idem_or_email() -> None:
    snap = SimpleNamespace(
        estado_proceso="GENERADO",
        notify_idempotency_key="",
        email_pdf_path="",
    )
    assert _control_snap_already_notified(snap) is False


def test_job_manager_does_not_treat_applied_control_pending_as_success() -> None:
    JobManager._instance = None
    jm = JobManager()
    assert (
        jm._amortization_job_succeeded(
            {
                "status": "completed",
                "type": "amortization_apply",
                "result": {"outcome": "applied_control_pending", "status": "partial"},
            }
        )
        is False
    )
    assert (
        jm._amortization_job_succeeded(
            {
                "status": "completed",
                "type": "amortization_apply",
                "result": {"outcome": "applied", "status": "ok"},
            }
        )
        is True
    )
    JobManager._instance = None


def test_api_key_fail_closed_in_production_without_key(monkeypatch) -> None:
    monkeypatch.delenv(ENV_API_HTTP_KEY, raising=False)
    monkeypatch.setenv("ACTIVE_ENVIRONMENT", "production")
    init_graph_client(_MockGraph())
    client = TestClient(create_app(), raise_server_exceptions=False)
    assert client.get("/health").status_code == 200
    r = client.get("/graph/diagnostics")
    assert r.status_code == 503
    assert r.json()["detail"] == "api_key_not_configured"


def test_api_key_still_open_outside_production_without_key(monkeypatch) -> None:
    monkeypatch.delenv(ENV_API_HTTP_KEY, raising=False)
    monkeypatch.setenv("ACTIVE_ENVIRONMENT", "sandbox")
    init_graph_client(_MockGraph())
    client = TestClient(create_app(), raise_server_exceptions=False)
    r = client.get("/graph/diagnostics")
    assert r.status_code != 401
    assert r.status_code != 503
