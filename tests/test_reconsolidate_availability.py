"""Reconsolidar: una sola regla de qué problemas lo piden y cuándo está disponible."""

from __future__ import annotations

import asyncio
import json

import pytest

from app.application.services.asiento_format_gate import (
    RECONSOLIDATE_CODES,
    format_recovery_credits_from_attempt_json,
    needs_reconsolidate,
)
from app.application.ui import merge_readiness as readiness_module
from app.application.ui.amortization_attempt import (
    drop_reconsolidate_issues_json,
    parse_last_amortization_attempt_json,
)
from app.application.ui.amortization_operational_issues import (
    attach_operational_issues_to_amortization_result,
    mark_reconsolidate,
)
from app.application.ui.feature_flags import reset_ui_fail_closed_log_for_tests
from app.application.ui.merge_force_rebuild import (
    assess_ui_force_rebuild,
    error_apply_without_writes,
)
from app.application.ui.merge_readiness import MergeReadiness, _format_recheck_result
from app.application.ui.schemas import UiOperationalIssue
from tests.ui_fixtures import make_snap

PK = "payment-validation|banco_bancolombia|2026-09-30|reconsolidar"


@pytest.fixture(autouse=True)
def _ui_writes_on(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("UI_ENABLED", "true")
    monkeypatch.setenv("UI_WRITE_ENABLED", "true")
    monkeypatch.setenv("UI_MERGE_ENABLED", "true")
    monkeypatch.setenv("ACTIVE_ENVIRONMENT", "sandbox")
    monkeypatch.delenv("WEBSITE_INSTANCE_ID", raising=False)
    reset_ui_fail_closed_log_for_tests()


def _issue(code: str, credit: str = "53", **extra: object) -> dict[str, object]:
    return {
        "issue_id": f"i-{code}-{credit}",
        "stage": "amortization",
        "category": "correction_required",
        "severity": "business",
        "recoverable": True,
        "title": f"Crédito {credit}",
        "user_message": "Problema",
        "location": {"credit": credit},
        "technical_reference": code,
        **extra,
    }


def _attempt(
    issues: list[dict[str, object]],
    *,
    applied: dict[str, object] | None = None,
    outcome: str = "partial",
) -> str:
    data: dict[str, object] = {
        "attempt_id": "j1",
        "outcome": outcome,
        "created_at": "2026-09-30T12:00:00-05:00",
        "process_key": PK,
        "operational_issues": issues,
        "affected_payment_ids": [],
    }
    if applied is not None:
        data["plan_summary"] = {"applied_by_credit": applied}
    return json.dumps(data)


def _snap(estado: str, *, attempt: str = "", apply_key: str = "") -> object:
    return make_snap(
        process_key=PK,
        estado_proceso=estado,
        historical_file_path="historico/cartera.xlsx",
        email_pdf_path="correos/x.pdf",
        merge_idempotency_key=PK,
        apply_idempotency_key=apply_key,
        last_amortization_attempt_json=attempt,
    )


# --- Una sola lista de códigos -------------------------------------------------


@pytest.mark.parametrize(
    "code",
    [
        "PDF_TEXT_NOT_EXTRACTABLE",
        "ACCOUNTING_PARSE_FAILED",
        "ABONO_ASIENTOS_NO_CUADRAN",
        "ABONO_ASIENTO_FALTANTE",
        "ASIENTO_DOWNLOAD_FAILED",
        "asiento_download_failed",
    ],
)
def test_problemas_de_asiento_piden_reconsolidar(code: str) -> None:
    assert needs_reconsolidate(code)
    issue = mark_reconsolidate(UiOperationalIssue.model_validate(_issue(code)))
    assert issue.reconsolidate is True


@pytest.mark.parametrize(
    "code", ["DUE_DATE_ROW_NOT_FOUND", "TABLE_HEADERS_NOT_FOUND", "AMORTIZATION_TABLE_NOT_FOUND", ""]
)
def test_problemas_de_tabla_no_piden_reconsolidar(code: str) -> None:
    assert not needs_reconsolidate(code)
    issue = mark_reconsolidate(UiOperationalIssue.model_validate(_issue(code)))
    assert issue.reconsolidate is False


def test_la_regla_de_parcial_usa_la_misma_lista() -> None:
    for code in RECONSOLIDATE_CODES:
        raw = _attempt([_issue(code, "53")])
        assert format_recovery_credits_from_attempt_json(raw) == {"53"}, code
    assert not format_recovery_credits_from_attempt_json(
        _attempt([_issue("DUE_DATE_ROW_NOT_FOUND", "53")])
    )


def test_intento_guardado_sin_marca_se_marca_al_leerlo() -> None:
    attempt = parse_last_amortization_attempt_json(
        _attempt([_issue("PDF_TEXT_NOT_EXTRACTABLE", "53"), _issue("DUE_DATE_ROW_NOT_FOUND", "54")])
    )
    assert attempt is not None
    flags = {i.location.credit: i.reconsolidate for i in attempt.operational_issues}
    assert flags == {"53": True, "54": False}


def test_resultado_del_job_expone_la_marca_por_problema() -> None:
    result = {
        "status": "requires_correction",
        "items": [
            {
                "credito": "53",
                "id_pago": "P1",
                "application_status": "ERROR",
                "error_code": "PDF_TEXT_NOT_EXTRACTABLE",
            },
            {
                "credito": "54",
                "id_pago": "P2",
                "application_status": "ERROR",
                "error_code": "DUE_DATE_ROW_NOT_FOUND",
            },
        ],
    }
    out = attach_operational_issues_to_amortization_result(result)
    flags = {
        (i.get("location") or {}).get("credit"): i.get("reconsolidate")
        for i in out.get("operational_issues") or []
    }
    assert flags.get("53") is True
    assert flags.get("54") is False


# --- Disponibilidad -------------------------------------------------------------


def test_error_apply_sin_tablas_escritas_permite_reconsolidar() -> None:
    snap = _snap("ERROR_APPLY", attempt=_attempt([_issue("PDF_TEXT_NOT_EXTRACTABLE")]))
    assert error_apply_without_writes(snap) is True
    assert assess_ui_force_rebuild(snap).allowed is True


def test_error_apply_con_clave_de_aplicacion_del_proceso_bloquea() -> None:
    snap = _snap(
        "ERROR_APPLY",
        attempt=_attempt([_issue("PDF_TEXT_NOT_EXTRACTABLE")]),
        apply_key=PK,
    )
    gate = assess_ui_force_rebuild(snap)
    assert gate.allowed is False
    assert gate.error_code == "force_rebuild_after_writes"
    assert "reconsolid" not in (gate.next_action or "").lower()


def test_error_apply_con_creditos_aplicados_bloquea() -> None:
    snap = _snap(
        "ERROR_APPLY",
        attempt=_attempt(
            [_issue("PDF_TEXT_NOT_EXTRACTABLE")],
            applied={"60": ["148"]},
        ),
    )
    assert error_apply_without_writes(snap) is False
    assert assess_ui_force_rebuild(snap).allowed is False


def test_error_apply_con_clave_de_otro_proceso_no_cuenta_como_escritura() -> None:
    snap = _snap(
        "ERROR_APPLY",
        attempt=_attempt([_issue("PDF_TEXT_NOT_EXTRACTABLE")]),
        apply_key="payment-validation|banco_bancolombia|2026-09-15|anterior",
    )
    assert assess_ui_force_rebuild(snap).allowed is True


def test_parcial_solo_con_problemas_de_tabla_no_pide_reconsolidar() -> None:
    snap = _snap("AMORTIZACION_PARCIAL", attempt=_attempt([_issue("DUE_DATE_ROW_NOT_FOUND")]))
    gate = assess_ui_force_rebuild(snap)
    assert gate.allowed is False
    assert "reconsolide" not in (gate.next_action or "").lower()


def test_parcial_con_asiento_por_corregir_permite_reconsolidar() -> None:
    snap = _snap("AMORTIZACION_PARCIAL", attempt=_attempt([_issue("ABONO_ASIENTO_FALTANTE")]))
    assert assess_ui_force_rebuild(snap).allowed is True


def test_merge_resolve_acepta_error_apply_solo_con_reconsolidar() -> None:
    from app.application.ui.merge_resolve import resolve_merge_target_from_control

    snap = _snap("ERROR_APPLY", attempt=_attempt([_issue("PDF_TEXT_NOT_EXTRACTABLE")]))
    with_rebuild = resolve_merge_target_from_control(
        snap, bank_code="banco_bancolombia", process_key=PK, allow_force_rebuild=True
    )
    assert with_rebuild.snapshot is snap
    with pytest.raises(Exception):
        resolve_merge_target_from_control(
            snap, bank_code="banco_bancolombia", process_key=PK, allow_force_rebuild=False
        )


# --- Tras reconsolidar desde parcial el botón no reaparece -------------------


def test_reconsolidar_desde_parcial_quita_los_problemas_resueltos() -> None:
    raw = _attempt(
        [_issue("PDF_TEXT_NOT_EXTRACTABLE", "53"), _issue("DUE_DATE_ROW_NOT_FOUND", "54")],
        applied={"60": ["148"]},
    )
    cleaned = drop_reconsolidate_issues_json(raw)
    attempt = parse_last_amortization_attempt_json(cleaned)
    assert attempt is not None
    assert [i.location.credit for i in attempt.operational_issues] == ["54"]
    assert attempt.plan_summary is not None
    assert "60" in attempt.plan_summary.applied_by_credit
    snap = _snap("AMORTIZACION_PARCIAL", attempt=cleaned)
    assert assess_ui_force_rebuild(snap).allowed is False


def test_reconsolidar_sin_aplicados_ni_otros_problemas_vacia_el_intento() -> None:
    raw = _attempt([_issue("PDF_TEXT_NOT_EXTRACTABLE", "53")])
    assert drop_reconsolidate_issues_json(raw) == ""


def test_intento_sin_problemas_de_asiento_queda_igual() -> None:
    raw = _attempt([_issue("DUE_DATE_ROW_NOT_FOUND", "54")])
    assert drop_reconsolidate_issues_json(raw) == raw


# --- Reconsolidar vuelve a revisar el formato del asiento --------------------


def _readiness(missing: list[dict[str, object]], status: str = "incomplete") -> MergeReadiness:
    return MergeReadiness(
        status=status,  # type: ignore[arg-type]
        expected_groups=2,
        ready_groups=1,
        missing_groups=1,
        missing_items=missing,
        checked_at="2026-09-30T12:00:00-05:00",
        user_message="x",
        next_action="y",
    )


def test_recheck_bloquea_si_el_asiento_sigue_ilegible() -> None:
    out = _format_recheck_result(
        _readiness([{"credito": "53", "error_code": "PDF_TEXT_NOT_EXTRACTABLE"}])
    )
    assert out.status == "incomplete"
    assert "53" in (out.user_message or "")
    assert "No se reconsolidó" in (out.user_message or "")


def test_recheck_no_bloquea_por_asientos_ya_archivados() -> None:
    out = _format_recheck_result(
        _readiness([{"credito": "60", "error_code": "asiento_contable_not_found"}])
    )
    assert out.status == "already_merged"
    assert out.missing_items == []


def test_recheck_conserva_no_verificable() -> None:
    out = _format_recheck_result(_readiness([], status="unknown"))
    assert out.status == "unknown"


def test_readiness_ya_consolidado_relee_solo_con_reconsolidar(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[bool] = []

    async def _fake(graph, snap, bank_code, *, already_merged):  # type: ignore[no-untyped-def]
        calls.append(already_merged)
        return _readiness([{"credito": "53", "error_code": "ACCOUNTING_PARSE_FAILED"}])

    monkeypatch.setattr(readiness_module, "_assess_merge_readiness", _fake)
    snap = _snap("CONSOLIDADO")
    monkeypatch.setattr(readiness_module, "control_indicates_already_merged", lambda _s: True)
    out = asyncio.run(
        readiness_module.assess_merge_readiness(None, snap, "banco_bancolombia", recheck_format=True)
    )
    assert calls == [False]
    assert out.status == "incomplete"
    calls.clear()
    asyncio.run(readiness_module.assess_merge_readiness(None, snap, "banco_bancolombia"))
    assert calls == [True]
