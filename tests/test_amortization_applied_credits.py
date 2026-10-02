"""Créditos ya registrados en su tabla: no se excluyen y nunca cuentan como «sin amortizar».

Caso real: el crédito 151 quedó escrito en un primer intento y luego se excluyó; el
cierre lo listó como «sin amortizar» y la pantalla mostró 12 tablas cuando se habían
escrito 13.
"""

from __future__ import annotations

import asyncio
import io
import json
import re
from typing import Any

import httpx
import openpyxl
import pytest

from app.application.services import amortization_decisions as reg_mod
from app.application.services.amortization_applied_credits import (
    applied_credits_in_tables,
    applied_credits_in_workbook,
    applied_tables_by_credit_from_result,
    table_id,
)
from app.application.services.amortization_decisions import (
    DecisionsRegistryError,
    add_exclusion,
    empty_registry,
)
from app.application.services.amortization_workbook import append_automation_log
from app.application.ui import amortization_decisions_service as svc
from app.application.ui.amortization_attempt import (
    build_plan_summary,
    carry_forward_applied_credits,
)
from app.application.ui.schemas import UiAmortizationPlanSummary, UiLastAmortizationAttempt
from app.application.use_cases import payment_validation_soft_close as soft_close
from app.application.use_cases.amortization_fill_apply import _excluded_credits_message
from tests.test_amortization_decisions_service import PK, REG_PATH, _attempt, _issue, _snapshot
from tests.test_amortization_decisions_service import env  # noqa: F401  (fixture)

_TECH_CODE = re.compile(r"\b[A-Z]{3,}_[A-Z_]{3,}\b|exclusion_|_applied")


def _run(coro):
    return asyncio.run(coro)


def _table_with_log(*rows: dict[str, Any]) -> bytes:
    wb = openpyxl.Workbook()
    wb.active.title = "Tabla"
    for row in rows:
        append_automation_log(wb, row)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def _log_row(credito: str, id_pago: str = "P1", estado: str = "APLICADO") -> dict[str, Any]:
    return {
        "id_pago": id_pago,
        "credito": credito,
        "accion": estado,
        "estado": estado,
        "application_row": 25,
        "idempotency_key": f"{id_pago}|{credito}|x|1|h",
    }


# --- Fuentes de «ya aplicado» ---------------------------------------------------------


def test_log_de_la_tabla_marca_aplicado_solo_para_ids_de_pago_del_proceso():
    raw = _table_with_log(
        _log_row("CREDITO # 151"),
        _log_row("CREDITO # 152", estado="ERROR"),
        _log_row("CREDITO # 153", id_pago="OTRO_MES"),
        _log_row("CREDITO # 154", estado="ADOPTADO_EXISTENTE"),
    )
    credits = ["151", "152", "153", "154"]
    assert applied_credits_in_workbook(raw, credits=credits, id_pagos=["P1"]) == {"151", "154"}
    # Sin ID Pago no se puede acotar al proceso: no se marca nada.
    assert applied_credits_in_workbook(raw, credits=credits, id_pagos=[]) == set()


def test_tabla_inexistente_no_tiene_escrituras_y_otros_errores_se_propagan():
    raw = _table_with_log(_log_row("CREDITO # 151"))

    async def download(path: str) -> bytes:
        if path == "T/151.xlsx":
            return raw
        if path == "T/404.xlsx":
            req = httpx.Request("GET", "https://graph.test")
            raise httpx.HTTPStatusError("404", request=req, response=httpx.Response(404, request=req))
        if path == "T/missing.xlsx":
            raise FileNotFoundError(path)
        raise RuntimeError("timeout")

    found = _run(
        applied_credits_in_tables(
            download,
            tablas={"151": "T/151.xlsx", "152": "T/404.xlsx", "153": "T/missing.xlsx"},
            id_pagos=["P1"],
        )
    )
    assert found == {"151"}
    with pytest.raises(RuntimeError):
        _run(applied_credits_in_tables(download, tablas={"9": "T/boom.xlsx"}, id_pagos=["P1"]))


def test_resultado_de_intento_cuenta_aplicados_adoptados_y_ya_aplicados():
    result = {
        "tables_uploaded": ["T/151.xlsx"],
        "items": [
            {"credito": "CREDITO # 151", "apply_status": "APPLIED", "tabla_amortizacion_path": "T/151.xlsx"},
            # Escrito en memoria pero la tabla no se subió (p. ej. archivo bloqueado).
            {"credito": "CREDITO # 160", "apply_status": "APPLIED", "tabla_amortizacion_path": "T/160.xlsx"},
            {"credito": "CREDITO # 161", "apply_status": "ADOPTED", "tabla_amortizacion_path": "T/161.xlsx"},
            {"credito": "CREDITO # 162", "application_status": "ALREADY_APPLIED",
             "tabla_amortizacion_path": "T/162.xlsx"},
            {"credito": "CREDITO # 163", "application_status": "ALREADY_APPLIED",
             "error_code": "X", "tabla_amortizacion_path": "T/163.xlsx"},
            {"credito": "CREDITO # 164", "application_status": "ERROR",
             "tabla_amortizacion_path": "T/164.xlsx"},
        ],
    }
    out = applied_tables_by_credit_from_result(result)
    assert out == {"151": ["T/151.xlsx"], "161": ["T/161.xlsx"], "162": ["T/162.xlsx"]}


def test_resumen_del_plan_guarda_los_aplicados_y_se_conservan_entre_intentos():
    result = {
        "conciliation": {"planned_by_credit": {"133": {"lines": 1, "tables": ["T/133.xlsx"]}}},
        "tables_uploaded": ["T/151.xlsx"],
        "items": [
            {"credito": "151", "apply_status": "APPLIED", "tabla_amortizacion_path": "T/151.xlsx"},
        ],
    }
    plan = build_plan_summary(result, [])
    assert plan is not None
    assert plan.applied_by_credit == {"151": [table_id("T/151.xlsx")]}

    previous = UiLastAmortizationAttempt(attempt_id="a1", outcome="partial", plan_summary=plan)
    # Segundo intento: 151 está excluido, ya no se planea ni aparece en el resultado.
    newer = UiLastAmortizationAttempt(
        attempt_id="a2",
        outcome="partial",
        plan_summary=UiAmortizationPlanSummary(applied_by_credit={"133": ["t133"]}),
    )
    merged = carry_forward_applied_credits(newer, previous)
    assert set(merged.plan_summary.applied_by_credit) == {"133", "151"}
    assert carry_forward_applied_credits(newer, None) is newer


# --- Excluir un crédito ya aplicado (ítem 2) ------------------------------------------


def _attempt_with_applied(applied: dict[str, list[str]]) -> str:
    attempt = _attempt(_issue("133", ["102", "133"]))
    attempt.plan_summary.applied_by_credit = applied
    return attempt.model_dump_json()


def _exclude(drive, credit: str = "133"):
    return _run(
        svc.exclude_credit(
            drive, bank_code="banco_bogota", process_key=PK, credit=credit,
            motivo_codigo="FALTA_ASIENTO", nota="", quien="ana",
        )
    )


def test_no_se_excluye_un_credito_aplicado_en_el_intento(env):  # noqa: F811
    drive, state = env
    state["snap"] = _snapshot(last_amortization_attempt_json=_attempt_with_applied({"133": ["b"]}))
    with pytest.raises(DecisionsRegistryError) as exc:
        _exclude(drive)
    err = exc.value
    assert err.error_code == "exclusion_credit_already_applied"
    msg = str(err.user_message)
    assert "133" in msg and "102" in msg
    assert "cierre el proceso" in msg  # el usuario siempre tiene una salida
    assert not _TECH_CODE.search(msg)
    assert drive.puts == []
    assert state["control_updates"] == []


def test_no_se_excluye_un_credito_registrado_en_el_log_de_su_tabla(env):  # noqa: F811
    drive, state = env
    drive.files["T/133.xlsx"] = _table_with_log(_log_row("CREDITO # 133"))
    drive.etags["T/133.xlsx"] = "e1"
    with pytest.raises(DecisionsRegistryError) as exc:
        _exclude(drive)
    assert exc.value.error_code == "exclusion_credit_already_applied"
    assert REG_PATH not in drive.files


def test_si_no_se_puede_revisar_la_tabla_no_se_excluye_y_se_puede_reintentar(env):  # noqa: F811
    drive, _state = env
    drive.fail_get_bytes = RuntimeError("timeout")
    with pytest.raises(DecisionsRegistryError) as exc:
        _exclude(drive)
    assert exc.value.error_code == "exclusion_applied_check_failed"
    assert exc.value.status_code == 503
    assert "Intente de nuevo" in str(exc.value.user_message)
    assert drive.puts == []
    drive.fail_get_bytes = None
    view = _exclude(drive)
    assert {r.credit for r in view.excluded} == {"102", "133"}


# --- Conteos: vista, cierre y mensaje de Apply (ítem 7) -------------------------------


def _registry_with_exclusion(credits: list[str]) -> dict[str, Any]:
    reg, _ = add_exclusion(
        empty_registry(process_key=PK, bank_code="banco_bogota", report_date_iso="2026-08-01"),
        credits=credits,
        clientes={c: f"CLIENTE {c}" for c in credits},
        id_pagos=["P1"],
        tablas={c: f"T/{c}.xlsx" for c in credits},
        motivo_codigo="FALTA_ASIENTO",
        nota="",
        quien="ana",
    )
    return reg


def test_vista_cerrada_no_lista_como_sin_amortizar_un_credito_aplicado():
    reg = _registry_with_exclusion(["151", "102"])
    attempt = UiLastAmortizationAttempt(
        attempt_id="a",
        outcome="partial",
        plan_summary=UiAmortizationPlanSummary(applied_by_credit={"151": ["t"]}),
    )
    closed = svc.build_decisions_view(reg, attempt, closed=True)
    assert [r.credit for r in closed.credits_not_amortized] == ["102"]
    assert closed.applied_credits == ["151"]
    # Cierre registrado antes de la corrección: tampoco lo muestra.
    reg["closure"] = {
        "estado": "CERRADO_AMORTIZACION_INCOMPLETA",
        "creditos_sin_amortizar": [
            {"credito": "151", "cliente": "ASFALTOS", "motivo": "m"},
            {"credito": "102", "cliente": "DOS", "motivo": "m"},
        ],
    }
    closed = svc.build_decisions_view(reg, attempt, closed=True)
    assert [r.credit for r in closed.credits_not_amortized] == ["102"]


def test_mensaje_de_apply_no_cuenta_excluidos_ya_aplicados():
    excluded = [
        {"credito": "151", "cliente": "ASFALTOS"},
        {"credito": "102", "cliente": "DOS"},
    ]
    msg = _excluded_credits_message(excluded, tables_uploaded_count=13, applied_credits={"151"})
    assert msg.startswith("Se actualizaron 13 tabla(s)")
    assert "Quedan 1 crédito excluido sin amortizar: 102 · DOS." in msg
    assert "151" not in msg
    only_applied = _excluded_credits_message(
        excluded[:1], tables_uploaded_count=13, applied_credits={"151"}
    )
    assert "ya habían quedado registrados" in only_applied
    # Sin aplicados: comportamiento anterior.
    legacy = _excluded_credits_message(excluded, tables_uploaded_count=12)
    assert "Quedan 2 créditos excluidos sin amortizar" in legacy


class _FakeJM:
    def __init__(self, jobs: list[dict[str, Any]]) -> None:
        self.jobs = jobs

    def get_job(self, job_id: str):
        return next((j for j in self.jobs if j.get("job_id") == job_id), None)

    def list_jobs_by_process_key(self, process_key: str):
        return [j for j in self.jobs if j.get("process_key") == process_key]


def _apply_job(job_id: str, result: dict[str, Any], *, status: str = "completed") -> dict[str, Any]:
    return {"job_id": job_id, "type": "amortization_process", "status": status,
            "process_key": PK, "result": result}


def _jobs_13_tables() -> list[dict[str, Any]]:
    first = _apply_job(
        "apply-1",
        {
            "tables_uploaded": ["T/151.xlsx"],
            "items": [{"credito": "151", "apply_status": "APPLIED",
                       "tabla_amortizacion_path": "T/151.xlsx"}],
        },
        status="failed",
    )
    second_paths = [f"T/{n}.xlsx" for n in range(200, 212)]
    second = _apply_job(
        "apply-2",
        {
            "tables_uploaded": second_paths,
            "tables_updated_links": [
                {"label": p, "path": p, "file_url": f"https://sp/{p}"} for p in second_paths
            ],
        },
    )
    return [first, second]


def test_cierre_lista_las_tablas_de_todos_los_intentos(monkeypatch):
    monkeypatch.setattr(
        "app.application.job_manager.get_job_manager", lambda: _FakeJM(_jobs_13_tables())
    )

    async def _build(_client, _site, _drive, paths):
        return [{"label": p, "path": p, "file_url": f"https://sp/{p}"} for p in paths]

    monkeypatch.setattr(
        "app.application.use_cases.amortization_fill_apply._build_tables_updated_links", _build
    )
    links = _run(
        soft_close._resolve_soft_close_amortization_table_links(
            object(), site_id="s", drive_id="d", process_key=PK, apply_job_id="apply-2"
        )
    )
    paths = {link["path"] for link in links}
    assert len(paths) == 13
    assert "T/151.xlsx" in paths


def test_cierre_no_registra_como_sin_amortizar_un_credito_aplicado(monkeypatch):
    monkeypatch.setattr(
        "app.application.job_manager.get_job_manager", lambda: _FakeJM(_jobs_13_tables())
    )
    reg = _registry_with_exclusion(["151"])
    reg, _ = add_exclusion(
        reg, credits=["102"], clientes={"102": "DOS"}, id_pagos=["P2"],
        tablas={"102": "T/102.xlsx"}, motivo_codigo="FALTA_ASIENTO", nota="", quien="ana",
    )
    downloads: list[str] = []

    async def _download(_c, _s, _d, path):
        downloads.append(path)
        raise FileNotFoundError(path)

    monkeypatch.setattr(soft_close, "_graph_download_by_path", _download)
    recorded: dict[str, Any] = {}

    async def _mutate(_client, _site, _drive, *, mutate, **_k):
        out, _ = mutate(reg)
        recorded.update(out)

    monkeypatch.setattr(reg_mod, "mutate_registry", _mutate)
    snap = _snapshot(decisions_registry_path=REG_PATH)
    _run(
        soft_close._record_closure_best_effort(
            object(), site_id="s", drive_id="d", snap=snap, registry=reg,
            terminal_estado="CERRADO_AMORTIZACION_INCOMPLETA", unused_moves=[],
        )
    )
    creditos = [c["credito"] for c in recorded["closure"]["creditos_sin_amortizar"]]
    assert creditos == ["102"]
    assert downloads == ["T/102.xlsx"]  # 151 ya se sabía aplicado por el job


def test_cierre_revisa_el_log_de_la_tabla_cuando_no_hay_jobs(monkeypatch):
    monkeypatch.setattr("app.application.job_manager.get_job_manager", lambda: _FakeJM([]))
    reg = _registry_with_exclusion(["151"])
    raw = _table_with_log(_log_row("CREDITO # 151"))

    async def _download(_c, _s, _d, path):
        assert path == "T/151.xlsx"
        return raw

    monkeypatch.setattr(soft_close, "_graph_download_by_path", _download)
    snap = _snapshot(decisions_registry_path=REG_PATH)
    applied = _run(
        soft_close._applied_excluded_credits_best_effort(
            object(), site_id="s", drive_id="d", snap=snap, registry=reg
        )
    )
    assert applied == {"151"}


def test_registro_json_de_cierre_sigue_listando_excluidos_no_aplicados(monkeypatch):
    """Si no se puede comprobar, el crédito sigue contando como sin amortizar (como antes)."""
    monkeypatch.setattr("app.application.job_manager.get_job_manager", lambda: _FakeJM([]))
    reg = _registry_with_exclusion(["151"])

    async def _download(*_a):
        raise RuntimeError("timeout")

    monkeypatch.setattr(soft_close, "_graph_download_by_path", _download)
    snap = _snapshot(decisions_registry_path=REG_PATH)
    applied = _run(
        soft_close._applied_excluded_credits_best_effort(
            object(), site_id="s", drive_id="d", snap=snap, registry=reg
        )
    )
    assert applied == set()
    assert json.dumps(reg)  # el registro no se alteró
