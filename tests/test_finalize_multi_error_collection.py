"""U4-A3: prevalidación colecciona TODOS los problemas corregibles de
Distribucion_Pagos antes de abortar Finalize (en vez de fallar en el primero).
"""
from __future__ import annotations

import asyncio
import json
from datetime import date

import pytest

from app.application.services.review_schema import (
    DistribucionCols,
    apply_legacy_estado_migration,
)
from app.application.ui.job_read import JobReadResult
from app.application.ui.last_attempt import build_operational_issues_from_finalize_job
from app.application.use_cases.payment_validation_finalize import (
    _check_single_distribucion_pago_row,
    _collect_distribucion_pago_issues,
    finalize_payment_validation,
)
from tests.test_finalize_validation import (
    MockGraphClient,
    create_review_workbook,
    make_distrib_row,
    set_env_vars,
)


def _dist_dict(excel_row: int, **overrides) -> dict:
    """Fila de Distribucion_Pagos ya migrada (misma tubería que usa Finalize real)."""
    row_vals, _ = make_distrib_row(**overrides)
    row_dict = dict(zip(DistribucionCols.HEADERS, row_vals))
    apply_legacy_estado_migration(row_dict)
    row_dict["_excel_row"] = excel_row
    return row_dict


def _run(coro):
    return asyncio.run(coro)


def test_collect_returns_empty_list_when_no_issues():
    distributions = [_dist_dict(2), _dist_dict(3, id_pago="ID2")]
    issues = _collect_distribucion_pago_issues(distributions)
    assert issues == []


def test_collect_two_rows_empty_estado_pago_returns_two_issues():
    distributions = [
        _dist_dict(2, estado="", id_pago="ID1"),
        _dist_dict(3, estado="", id_pago="ID2"),
    ]
    issues = _collect_distribucion_pago_issues(distributions)
    assert len(issues) == 2
    assert all(i["error_code"] == "empty_estado_pago" for i in issues)
    assert {i["excel_row"] for i in issues} == {2, 3}
    assert {i["id_pago"] for i in issues} == {"ID1", "ID2"}


def test_collect_single_invalid_row_returns_single_issue():
    distributions = [
        _dist_dict(2, estado="VALIDAR_PARCIAL", id_pago="ID1"),
    ]
    issues = _collect_distribucion_pago_issues(distributions)
    assert len(issues) == 1
    assert issues[0]["error_code"] == "invalid_estado_pago"
    assert issues[0]["excel_row"] == 2


def test_check_single_row_returns_none_for_valid_row():
    assert _check_single_distribucion_pago_row(_dist_dict(2)) is None


def test_finalize_raises_single_detail_when_one_issue():
    async def run_test():
        set_env_vars()
        client = MockGraphClient()
        r, _ = make_distrib_row(estado="VALIDAR_PARCIAL")
        client.downloaded_files["revision/val_latest.xlsx"] = create_review_workbook(
            distrib_specs=[(r, None)]
        )
        with pytest.raises(ValueError) as exc_info:
            await finalize_payment_validation(client, "val_latest.xlsx")
        msg = str(exc_info.value)
        assert msg.startswith("invalid_estado_pago|")
        assert "multiple_review_errors" not in msg
        code, payload = msg.split("|", 1)
        details = json.loads(payload)
        assert details["excel_row"] == 2
        assert details["sheet"] == "Distribucion_Pagos"

    _run(run_test())


def test_finalize_raises_multiple_review_errors_when_two_rows_bad():
    async def run_test():
        set_env_vars()
        client = MockGraphClient()
        r1, _ = make_distrib_row(id_pago="ID1", estado="", credito="CRED_A")
        r2, _ = make_distrib_row(id_pago="ID2", estado="", credito="CRED_B")
        client.downloaded_files["revision/val_latest.xlsx"] = create_review_workbook(
            distrib_specs=[(r1, None), (r2, None)]
        )
        with pytest.raises(ValueError) as exc_info:
            await finalize_payment_validation(client, "val_latest.xlsx")
        msg = str(exc_info.value)
        assert msg.startswith("multiple_review_errors|")
        _, payload = msg.split("|", 1)
        details = json.loads(payload)
        assert details["count"] == 2
        assert len(details["issues"]) == 2
        assert all(i["error_code"] == "empty_estado_pago" for i in details["issues"])
        # Fail-fast: no debe haber escrituras en SharePoint cuando quedan errores.
        assert client.put_calls == []
        assert client.uploaded_files == {}

    _run(run_test())


def test_finalize_still_fails_fast_zero_graph_writes_on_multi_error():
    async def run_test():
        set_env_vars()
        client = MockGraphClient()
        posts_before = len(client.dynamic_folder_children)
        r1, _ = make_distrib_row(id_pago="ID1", estado="")
        r2, _ = make_distrib_row(id_pago="ID2", estado="INCOMPLETO")
        client.downloaded_files["revision/val_latest.xlsx"] = create_review_workbook(
            distrib_specs=[(r1, None), (r2, None)]
        )
        with pytest.raises(ValueError, match="multiple_review_errors"):
            await finalize_payment_validation(client, "val_latest.xlsx")
        assert client.put_calls == []
        assert client.uploaded_files == {}
        assert len(client.dynamic_folder_children) == posts_before

    _run(run_test())


def test_existing_single_error_finalize_still_succeeds_when_valid():
    async def run_test():
        set_env_vars()
        client = MockGraphClient()
        r, _ = make_distrib_row(mora=0, valor_int=100, abono_k=0)
        client.downloaded_files["revision/val_latest.xlsx"] = create_review_workbook(
            distrib_specs=[(r, None)]
        )
        res = await finalize_payment_validation(
            client, "val_latest.xlsx", process_date=date(2026, 5, 10), bank_code="banco_bogota"
        )
        assert res["status"] == "success"

    _run(run_test())


def test_projection_expands_multiple_review_errors_into_several_operational_issues():
    message = "multiple_review_errors|" + json.dumps(
        {
            "issues": [
                {
                    "error_code": "empty_estado_pago",
                    "excel_row": 2,
                    "sheet": "Distribucion_Pagos",
                    "field": DistribucionCols.ESTADO_PAGO,
                    "id_pago": "ID1",
                },
                {
                    "error_code": "empty_estado_pago",
                    "excel_row": 3,
                    "sheet": "Distribucion_Pagos",
                    "field": DistribucionCols.ESTADO_PAGO,
                    "id_pago": "ID2",
                },
            ],
            "count": 2,
        },
        ensure_ascii=False,
    )
    job = JobReadResult(
        job_id="fin-multi-1",
        store="job_manager",
        payload={
            "job_id": "fin-multi-1",
            "type": "finalize",
            "status": "failed",
            "error": {
                "type": "ValueError",
                "message": message,
                "error_code": "multiple_review_errors",
                "user_message": "Se encontraron 2 problemas en la revisión.",
                "next_action": "Corrija todos los puntos listados, guarde y vuelva a verificar.",
                "severity": "warning",
            },
        },
    )
    issues = build_operational_issues_from_finalize_job(job)
    assert len(issues) >= 2
    assert {i.location.row for i in issues if i.location} == {2, 3}
    assert all(i.stage == "finalize" for i in issues)
    assert all(i.category == "correction_required" for i in issues)
    # Cada issue trae su propio mensaje operativo (no el genérico del contenedor).
    assert all("Estado Pago" in (i.user_message or "") for i in issues)


def test_projection_keeps_single_issue_for_non_multiple_codes():
    job = JobReadResult(
        job_id="fin-single-1",
        store="job_manager",
        payload={
            "job_id": "fin-single-1",
            "type": "finalize",
            "status": "failed",
            "error": {
                "type": "ValueError",
                "message": 'invalid_estado_pago|{"excel_row":8,"field":"Estado Pago","value_found":"PAGADO"}',
                "error_code": "invalid_estado_pago",
                "user_message": "Hay un Estado Pago no permitido.",
                "next_action": "Use la lista desplegable.",
                "severity": "warning",
            },
        },
    )
    issues = build_operational_issues_from_finalize_job(job)
    assert len(issues) == 1
    assert issues[0].location is not None
    assert issues[0].location.row == 8
