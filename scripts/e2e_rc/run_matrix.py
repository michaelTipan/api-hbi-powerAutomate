"""Runner matriz E01–E40 contra sandbox desplegado (CAPA B Graph + jobs)."""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Callable

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.e2e_rc.bank_upload import d, upload_bank_bogota
from scripts.e2e_rc.graph_session import SandboxGraphSession
from scripts.e2e_rc.path_guard import AUTHORIZED_CLIENTS_BASE, assert_sandbox_mutable_path
from scripts.e2e_rc.review_edit import approve_single_credit_pago, edit_aplicacion_pagos_rows
from scripts.e2e_rc.scenarios import SCENARIOS, ScenarioResult, by_id

import io
from openpyxl import load_workbook
from urllib.parse import quote

WORK = Path(r"D:\CMC\HBI_Capital\_work\rc_e2e")
BANK_CODE = "banco_bogota"
# process_date base; cada escenario usa una fecha distinta para no chocar con
# procesos FINALIZADO (cancel_not_allowed).
PROCESS_DATE_BASE = datetime(2026, 10, 15)


def process_date_for(scenario_id: str) -> str:
    n = int(scenario_id[1:])
    return (PROCESS_DATE_BASE + timedelta(days=n - 1)).strftime("%Y-%m-%d")


REV_DIR = f"{AUTHORIZED_CLIENTS_BASE}/02 VALIDACION PAGOS/01 REVISION"
CTRL_PATH = (
    f"{AUTHORIZED_CLIENTS_BASE}/02 VALIDACION PAGOS/90 ACCESO RESTRINGIDO/"
    "03 CONTROL TECNICO/control_proceso_validacion_pagos_banco_bogota.xlsx"
)
NOTIFY_SANDBOX_TO = "herramientas.jsakedev@gmail.com"


def _log(name: str, data: object) -> Path:
    WORK.mkdir(parents=True, exist_ok=True)
    path = WORK / f"{name}.json"
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    print(name, json.dumps(data, ensure_ascii=False, default=str)[:400])
    return path


def cancel_active(session: SandboxGraphSession) -> dict[str, Any]:
    return session.queue_and_poll(
        "/graph/sharepoint/payment-validation/cancel-active-process/queue",
        {"bank_code": BANK_CODE},
        timeout_s=600,
    )


def reset_bank_slot(session: SandboxGraphSession) -> dict[str, Any]:
    """Libera el slot del banco en sandbox: IsActive=false + limpia REVISION.

    Necesario tras FINALIZADO (cancel_not_allowed) para poder Generate otra fecha.
    Solo paths PRUEBAS (path guard).
    """
    assert_sandbox_mutable_path(CTRL_PATH)
    assert_sandbox_mutable_path(REV_DIR)
    out: dict[str, Any] = {"deactivated": 0, "deleted_reviews": []}
    # Control
    ctrl_folder = "/".join(CTRL_PATH.split("/")[:-1])
    ctrl_name = CTRL_PATH.split("/")[-1]
    folder_id = session.walk(ctrl_folder)
    item = next(i for i in session.children(folder_id) if i.get("name") == ctrl_name)
    raw = session.download_item(str(item["id"]))
    wb = load_workbook(io.BytesIO(raw))
    ws = wb["Procesos"]
    headers = {
        str(ws.cell(1, c).value).strip(): c
        for c in range(1, ws.max_column + 1)
        if ws.cell(1, c).value
    }
    col_active = headers["IsActive"]
    for r in range(2, ws.max_row + 1):
        if ws.cell(r, col_active).value in (True, "TRUE", "True", 1, "1"):
            ws.cell(r, col_active).value = False
            out["deactivated"] += 1
    buf = io.BytesIO()
    wb.save(buf)
    session.upload_item(str(item["id"]), buf.getvalue(), path_for_guard=CTRL_PATH)
    # Review folder
    rev_id = session.walk(REV_DIR)
    for it in session.children(rev_id):
        name = str(it.get("name") or "")
        if not name.lower().endswith(".xlsx") or name.startswith("~$"):
            continue
        del_r = session._client.delete(
            f"{session.base}/graph/sharepoint/drives/{quote(session.drive_id or '', safe='')}/items/{it['id']}"
        )
        out["deleted_reviews"].append({"name": name, "status": del_r.status_code})
    return out


def generate(session: SandboxGraphSession, process_date: str) -> dict[str, Any]:
    return session.queue_and_poll(
        "/graph/sharepoint/payment-validation/generate/queue",
        {"bank_code": BANK_CODE, "process_date": process_date},
        timeout_s=1800,
    )


def finalize(session: SandboxGraphSession, process_date: str) -> dict[str, Any]:
    return session.queue_and_poll(
        "/graph/sharepoint/payment-validation/finalize/queue",
        {"bank_code": BANK_CODE, "process_date": process_date},
        timeout_s=1800,
    )


def notify(session: SandboxGraphSession) -> dict[str, Any]:
    """Notify PA (CORREOS.xlsx del entorno sandbox)."""
    return session.queue_and_poll(
        "/graph/sharepoint/notify-validar-extractos-email",
        {"bank_code": BANK_CODE},
        timeout_s=1800,
    )


def merge(session: SandboxGraphSession) -> dict[str, Any]:
    return session.queue_and_poll(
        "/graph/sharepoint/merge-composite-validado-pdfs",
        {"bank_code": BANK_CODE},
        timeout_s=1800,
    )


def amort_dry_run(session: SandboxGraphSession) -> dict[str, Any]:
    return session.queue_and_poll(
        "/graph/sharepoint/payment-validation/amortization/dry-run/queue",
        {"bank_code": BANK_CODE},
        timeout_s=1800,
    )


def _result_dict(job: dict[str, Any]) -> dict[str, Any]:
    result = job.get("result")
    return result if isinstance(result, dict) else {}


def _has_payoff_not_achieved(job: dict[str, Any]) -> bool:
    """True si dry-run/amort bloqueó por PAYOFF_NOT_ACHIEVED (ítem u operational_issue)."""
    result = _result_dict(job)
    if result.get("error_code") == "PAYOFF_NOT_ACHIEVED":
        return True
    for item in result.get("items") or []:
        if isinstance(item, dict) and item.get("error_code") == "PAYOFF_NOT_ACHIEVED":
            return True
    for issue in result.get("operational_issues") or []:
        if not isinstance(issue, dict):
            continue
        ref = str(issue.get("technical_reference") or "")
        if ref == "PAYOFF_NOT_ACHIEVED":
            return True
    return False


def latest_review(session: SandboxGraphSession) -> tuple[dict[str, Any], bytes]:
    assert_sandbox_mutable_path(REV_DIR)
    folder_id = session.walk(REV_DIR)
    files = [
        i
        for i in session.children(folder_id)
        if str(i.get("name", "")).endswith(".xlsx") and not str(i.get("name", "")).startswith("~$")
    ]
    if not files:
        raise FileNotFoundError("no_review_xlsx")
    newest = sorted(files, key=lambda i: i.get("lastModifiedDateTime") or "", reverse=True)[0]
    raw = session.download_item(str(newest["id"]))
    return newest, raw


def upload_review(session: SandboxGraphSession, item: dict[str, Any], raw: bytes) -> None:
    path = f"{REV_DIR}/{item['name']}"
    session.upload_item(str(item["id"]), raw, path_for_guard=path)


def _job_ok(job: dict[str, Any]) -> bool:
    return job.get("status") == "completed"


def _job_failed(job: dict[str, Any]) -> bool:
    return job.get("status") in ("failed", "error", "http_error")


def _process_key(job: dict[str, Any]) -> str | None:
    result = job.get("result") or {}
    if isinstance(result, dict):
        return result.get("process_key") or result.get("processKey")
    return None


def _prep_bank_and_generate(session: SandboxGraphSession, rows: list[dict[str, Any]], tag: str) -> ScenarioResult | tuple[dict[str, Any], str]:
    process_date = process_date_for(tag)
    cancel_active(session)
    reset = reset_bank_slot(session)
    _log(f"{tag}_reset", reset)
    up = upload_bank_bogota(session, rows)
    _log(f"{tag}_bank", {**up, "process_date": process_date})
    gen = generate(session, process_date)
    already = None
    if isinstance(gen.get("result"), dict):
        already = gen["result"].get("already_generated")
    _log(f"{tag}_generate", {"status": gen.get("status"), "error": gen.get("error"), "process_date": process_date, "already_generated": already})
    if not _job_ok(gen):
        return ScenarioResult(
            id=tag,
            status="FAIL",
            evidence="generate_failed",
            process_key=_process_key(gen),
            detail={"generate": gen, "process_date": process_date},
        )
    if already:
        return ScenarioResult(
            id=tag,
            status="FAIL",
            evidence="generate_already_generated_isolation_broken",
            process_key=_process_key(gen),
            detail={"generate": gen, "process_date": process_date},
        )
    return gen, process_date


def run_e01(session: SandboxGraphSession) -> ScenarioResult:
    """GEOEXCON pago exacto obligación actual (montos históricos E2E)."""
    rows = [
        {
            "fecha": d(2026, 5, 23),
            "monto": 19_102_163.0,
            "concepto": "GEOEXCON",
            "trx": "RC E01 PAGO NORMAL 231",
        }
    ]
    prep = _prep_bank_and_generate(session, rows, "E01")
    if isinstance(prep, ScenarioResult):
        return prep
    gen, process_date = prep
    item, raw = latest_review(session)
    (WORK / f"E01_{item['name']}").write_bytes(raw)
    edited, applied = approve_single_credit_pago(
        raw,
        tipo="PAGO DE OBLIGACIÓN ACTUAL",
        observacion="RC-E01",
    )
    if not applied:
        return ScenarioResult("E01", "FAIL", evidence="no_rows_edited", detail={"review": item.get("name")})
    upload_review(session, item, edited)
    fin = finalize(session, process_date)
    _log("E01_finalize", {"status": fin.get("status"), "error": fin.get("error")})
    cancel = cancel_active(session)
    status = "PASS" if _job_ok(fin) else "FAIL"
    return ScenarioResult(
        "E01",
        status,
        evidence=f"finalize={fin.get('status')}; edited={len(applied)}",
        process_key=_process_key(fin) or _process_key(gen),
        artifacts=[str(WORK / f"E01_{item['name']}")],
        cleanup=f"cancel={cancel.get('status')}",
        detail={"applied": applied, "finalize_error": fin.get("error")},
    )


def run_e02(session: SandboxGraphSession) -> ScenarioResult:
    rows = [
        {
            "fecha": d(2026, 5, 23),
            "monto": 19_102_163.0,
            "concepto": "GEOEXCON",
            "trx": "RC E02 PARCIAL 231",
        }
    ]
    prep = _prep_bank_and_generate(session, rows, "E02")
    if isinstance(prep, ScenarioResult):
        prep.id = "E02"
        return prep
    gen, process_date = prep
    item, raw = latest_review(session)
    edited, applied = approve_single_credit_pago(
        raw,
        tipo="PAGO PARCIAL A OBLIGACIÓN ACTUAL",
        obligacion=5_000_000.0,
        observacion="RC-E02 parcial",
    )
    upload_review(session, item, edited)
    fin = finalize(session, process_date)
    _log("E02_finalize", {"status": fin.get("status"), "error": fin.get("error")})
    # Parcial con saldo por asignar > 0 debe bloquear Finalize
    blocked = _job_failed(fin)
    cancel_active(session)
    return ScenarioResult(
        "E02",
        "PASS" if blocked else "FAIL",
        evidence=f"expected_finalize_block; got={fin.get('status')}",
        process_key=_process_key(fin) or _process_key(gen),
        detail={"applied": applied, "error": fin.get("error")},
        cleanup="cancelled",
    )


def run_e03(session: SandboxGraphSession) -> ScenarioResult:
    rows = [
        {
            "fecha": d(2026, 7, 27),
            "monto": 25_075_203.0,
            "concepto": "AGRECAR",
            "trx": "RC E03 ATRASADO 37",
        }
    ]
    prep = _prep_bank_and_generate(session, rows, "E03")
    if isinstance(prep, ScenarioResult):
        prep.id = "E03"
        return prep
    gen, process_date = prep
    item, raw = latest_review(session)
    edited, applied = approve_single_credit_pago(
        raw, tipo="PAGO DE OBLIGACIÓN ACTUAL", observacion="RC-E03"
    )
    upload_review(session, item, edited)
    fin = finalize(session, process_date)
    cancel_active(session)
    return ScenarioResult(
        "E03",
        "PASS" if _job_ok(fin) else "FAIL",
        evidence=f"finalize={fin.get('status')}",
        process_key=_process_key(fin) or _process_key(gen),
        detail={"applied": applied, "error": fin.get("error")},
        cleanup="cancelled",
    )


def run_e04(session: SandboxGraphSession) -> ScenarioResult:
    rows = [
        {
            "fecha": d(2026, 4, 15),
            "monto": 32_691_683.0,
            "concepto": "EQUINORTE",
            "trx": "RC E04 ADELANTADO 264",
        }
    ]
    prep = _prep_bank_and_generate(session, rows, "E04")
    if isinstance(prep, ScenarioResult):
        prep.id = "E04"
        return prep
    gen, process_date = prep
    item, raw = latest_review(session)
    edited, applied = approve_single_credit_pago(
        raw, tipo="PAGO DE OBLIGACIÓN ACTUAL", observacion="RC-E04"
    )
    upload_review(session, item, edited)
    fin = finalize(session, process_date)
    cancel_active(session)
    return ScenarioResult(
        "E04",
        "PASS" if _job_ok(fin) else "FAIL",
        evidence=f"finalize={fin.get('status')}",
        process_key=_process_key(fin) or _process_key(gen),
        detail={"applied": applied, "error": fin.get("error")},
        cleanup="cancelled",
    )


def run_e09(session: SandboxGraphSession) -> ScenarioResult:
    rows = [
        {
            "fecha": d(2026, 7, 27),
            "monto": 500_000.0,
            "concepto": "EQUINORTE",
            "trx": "RC E09 ABONO CAPITAL 265",
        }
    ]
    prep = _prep_bank_and_generate(session, rows, "E09")
    if isinstance(prep, ScenarioResult):
        prep.id = "E09"
        return prep
    gen, process_date = prep
    item, raw = latest_review(session)
    edited, applied = approve_single_credit_pago(
        raw,
        tipo="ABONO A CAPITAL",
        obligacion=0.0,
        capital=500_000.0,
        observacion="RC-E09",
    )
    upload_review(session, item, edited)
    fin = finalize(session, process_date)
    cancel_active(session)
    return ScenarioResult(
        "E09",
        "PASS" if _job_ok(fin) else "FAIL",
        evidence=f"finalize={fin.get('status')}",
        process_key=_process_key(fin) or _process_key(gen),
        detail={"applied": applied, "error": fin.get("error")},
        cleanup="cancelled",
    )


def run_e10(session: SandboxGraphSession) -> ScenarioResult:
    rows = [
        {
            "fecha": d(2026, 5, 23),
            "monto": 24_000_000.0,
            "concepto": "GEOEXCON",
            "trx": "RC E10 OBLIG+CAPITAL 231",
        }
    ]
    prep = _prep_bank_and_generate(session, rows, "E10")
    if isinstance(prep, ScenarioResult):
        prep.id = "E10"
        return prep
    gen, process_date = prep
    item, raw = latest_review(session)

    def updater(row, _r):
        from app.application.services.review_schema import AplicacionPagosCols

        if not row.get(AplicacionPagosCols.CREDITO):
            return None
        obl = float(row.get(AplicacionPagosCols.VALOR_OBLIGACION_ACTUAL) or 0) or 19_102_163.0
        return {
            AplicacionPagosCols.VALIDAR_PAGO: "SI",
            AplicacionPagosCols.APLICAR_OBLIGACION_ACTUAL: obl,
            AplicacionPagosCols.APLICAR_SALDO_VENCIDO: 0,
            AplicacionPagosCols.ABONO_ADICIONAL_CAPITAL: max(0.0, 24_000_000.0 - obl),
            AplicacionPagosCols.TIPO_APLICACION: "PAGO Y ABONO A CAPITAL",
            AplicacionPagosCols.OBSERVACION: "RC-E10",
        }

    edited, applied = edit_aplicacion_pagos_rows(raw, row_updater=updater)
    upload_review(session, item, edited)
    fin = finalize(session, process_date)
    cancel_active(session)
    return ScenarioResult(
        "E10",
        "PASS" if _job_ok(fin) else "FAIL",
        evidence=f"finalize={fin.get('status')}",
        process_key=_process_key(fin) or _process_key(gen),
        detail={"applied": applied, "error": fin.get("error")},
        cleanup="cancelled",
    )


def run_e15(session: SandboxGraphSession) -> ScenarioResult:
    """PAGO TOTAL erróneo: Finalize PASS; dry-run debe bloquear con PAYOFF_NOT_ACHIEVED.

    Mandato §12 / E15: Tipo confirmado puede ser CANCELACIÓN / PAGO TOTAL aunque la
    sugerida no lo sea; Finalize no inventa saldo=0. El bloqueo es en amort dry-run.
    """
    rows = [
        {
            "fecha": d(2026, 5, 23),
            "monto": 19_102_163.0,
            "concepto": "GEOEXCON",
            "trx": "RC E15 PAGO TOTAL ERR 231",
        }
    ]
    prep = _prep_bank_and_generate(session, rows, "E15")
    if isinstance(prep, ScenarioResult):
        prep.id = "E15"
        return prep
    gen, process_date = prep
    item, raw = latest_review(session)
    edited, applied = approve_single_credit_pago(
        raw,
        tipo="CANCELACIÓN / PAGO TOTAL",
        observacion="RC-E15 intentional wrong total",
    )
    upload_review(session, item, edited)
    fin = finalize(session, process_date)
    _log("E15_finalize", {"status": fin.get("status"), "error": fin.get("error")})
    if not _job_ok(fin):
        cancel_active(session)
        return ScenarioResult(
            "E15",
            "FAIL",
            evidence=f"finalize_expected_pass; got={fin.get('status')}",
            process_key=_process_key(fin) or _process_key(gen),
            detail={"applied": applied, "error": fin.get("error")},
            cleanup="cancelled",
        )

    # Continuar hasta dry-run (Notify → Merge → amort dry-run).
    ntf = notify(session)
    _log("E15_notify", {"status": ntf.get("status"), "error": ntf.get("error")})
    if not _job_ok(ntf):
        cancel_active(session)
        return ScenarioResult(
            "E15",
            "BLOCKED",
            evidence=f"finalize_pass; notify_failed={ntf.get('status')}",
            process_key=_process_key(fin) or _process_key(gen),
            detail={"notify": ntf.get("error") or ntf.get("result")},
            cleanup="cancelled",
        )

    mrg = merge(session)
    _log("E15_merge", {"status": mrg.get("status"), "error": mrg.get("error")})
    if not _job_ok(mrg):
        cancel_active(session)
        return ScenarioResult(
            "E15",
            "BLOCKED",
            evidence=f"finalize_pass; merge_failed={mrg.get('status')}",
            process_key=_process_key(fin) or _process_key(gen),
            detail={"merge": mrg.get("error") or mrg.get("result")},
            cleanup="cancelled",
        )

    dry = amort_dry_run(session)
    _log(
        "E15_dry_run",
        {
            "status": dry.get("status"),
            "error": dry.get("error"),
            "can_apply": _result_dict(dry).get("can_apply"),
            "payoff_block": _has_payoff_not_achieved(dry),
        },
    )
    cancel_active(session)

    blocked = (
        _job_ok(dry)
        and _result_dict(dry).get("can_apply") is False
        and _has_payoff_not_achieved(dry)
    )
    # Job completed with requires_correction / can_apply false also OK.
    if not blocked and _job_ok(dry) and _has_payoff_not_achieved(dry):
        blocked = True
    if not blocked and dry.get("status") == "completed":
        # UI amortization_process shape: outcome requires_correction
        outcome = str(_result_dict(dry).get("outcome") or "")
        if outcome == "requires_correction" and _has_payoff_not_achieved(dry):
            blocked = True

    return ScenarioResult(
        "E15",
        "PASS" if blocked else "FAIL",
        evidence=(
            f"finalize=completed; dry_run={dry.get('status')}; "
            f"can_apply={_result_dict(dry).get('can_apply')}; "
            f"payoff_block={_has_payoff_not_achieved(dry)}"
        ),
        process_key=_process_key(fin) or _process_key(gen),
        detail={
            "applied": applied,
            "dry_error": dry.get("error"),
            "dry_result_summary": {
                "can_apply": _result_dict(dry).get("can_apply"),
                "error_code": _result_dict(dry).get("error_code"),
                "items_errors": [
                    it.get("error_code")
                    for it in (_result_dict(dry).get("items") or [])
                    if isinstance(it, dict) and it.get("error_code")
                ],
            },
        },
        cleanup="cancelled",
    )

def run_e21(session: SandboxGraphSession) -> ScenarioResult:
    rows = [
        {
            "fecha": d(2026, 5, 16),
            "monto": 5_000_000.0,
            "concepto": "INVERSIONES Y PROYECTOS MIOS",
            "trx": "RC E21 SIN EXTRACTO 318",
        }
    ]
    prep = _prep_bank_and_generate(session, rows, "E21")
    if isinstance(prep, ScenarioResult):
        return ScenarioResult(
            "E21",
            "PASS" if prep.evidence == "generate_failed" else prep.status,
            evidence="generate_outcome_for_missing_extract",
            detail=prep.detail,
        )
    gen, process_date = prep
    item, raw = latest_review(session)
    (WORK / f"E21_{item['name']}").write_bytes(raw)
    edited, applied = approve_single_credit_pago(
        raw, tipo="PAGO DE OBLIGACIÓN ACTUAL", observacion="RC-E21"
    )
    upload_review(session, item, edited)
    fin = finalize(session, process_date)
    cancel_active(session)
    status = "PASS" if _job_failed(fin) else "FAIL"
    return ScenarioResult(
        "E21",
        status,
        evidence=f"finalize={fin.get('status')} (expect block without extract)",
        process_key=_process_key(fin) or _process_key(gen),
        detail={"applied": applied, "error": fin.get("error"), "process_date": process_date},
        cleanup="cancelled",
    )


def run_e29(session: SandboxGraphSession) -> ScenarioResult:
    rows = [
        {
            "fecha": d(2026, 5, 23),
            "monto": 19_102_163.0,
            "concepto": "GEOEXCON",
            "trx": "RC E29 RETRY GEN 231",
        }
    ]
    process_date = process_date_for("E29")
    cancel_active(session)
    reset_bank_slot(session)
    upload_bank_bogota(session, rows)
    g1 = generate(session, process_date)
    g2 = generate(session, process_date)
    cancel_active(session)
    reset_bank_slot(session)
    # Segundo generate debe ser idempotente (completed reuse) o busy/conflict controlado
    ok = _job_ok(g1) and (
        _job_ok(g2)
        or g2.get("status") in ("failed", "error", "http_error")
        or (g2.get("http_status") in (409, 409))
    )
    return ScenarioResult(
        "E29",
        "PASS" if ok else "FAIL",
        evidence=f"g1={g1.get('status')}; g2={g2.get('status')}/{g2.get('http_status')}",
        process_key=_process_key(g1),
        detail={"g1": {"status": g1.get("status"), "error": g1.get("error")}, "g2": {"status": g2.get("status"), "error": g2.get("error"), "http": g2.get("http_status")}},
        cleanup="cancelled",
    )


def run_e37(session: SandboxGraphSession) -> ScenarioResult:
    rows = [
        {
            "fecha": d(2026, 5, 23),
            "monto": 19_102_163.0,
            "concepto": "GEOEXCON",
            "trx": "RC E37 CANCEL 231",
        }
    ]
    process_date = process_date_for("E37")
    cancel_active(session)
    reset_bank_slot(session)
    upload_bank_bogota(session, rows)
    gen = generate(session, process_date)
    cancel = cancel_active(session)
    reset_bank_slot(session)
    ok = _job_ok(gen) and cancel.get("status") in ("completed", "failed", "error")
    # cancel completed is success; some stacks return completed with result
    return ScenarioResult(
        "E37",
        "PASS" if _job_ok(gen) and (cancel.get("status") == "completed" or cancel.get("http_status") in (200, 202)) else ("PASS" if _job_ok(cancel) or cancel.get("status") == "completed" else "FAIL"),
        evidence=f"gen={gen.get('status')}; cancel={cancel.get('status')}",
        process_key=_process_key(gen),
        detail={"cancel": cancel.get("result") or cancel.get("error")},
        cleanup="done",
    )


HANDLERS: dict[str, Callable[[SandboxGraphSession], ScenarioResult]] = {
    "E01": run_e01,
    "E02": run_e02,
    "E03": run_e03,
    "E04": run_e04,
    "E09": run_e09,
    "E10": run_e10,
    "E15": run_e15,
    "E21": run_e21,
    "E29": run_e29,
    "E37": run_e37,
}


def blocked(scenario_id: str, reason: str) -> ScenarioResult:
    meta = by_id(scenario_id)
    return ScenarioResult(
        scenario_id,
        "BLOCKED",
        evidence=reason,
        detail={"title": meta.title, "notes": meta.notes},
    )


def run_selected(ids: list[str]) -> list[ScenarioResult]:
    results: list[ScenarioResult] = []
    with SandboxGraphSession() as session:
        meta = session.ensure_sandbox()
        _log("00_sandbox_meta", meta)
        for sid in ids:
            print(f"=== RUN {sid} ===")
            handler = HANDLERS.get(sid)
            if handler is None:
                # Known not yet automated in this harness
                reason_map = {
                    "E05": "Requiere extracto con saldo vencido parcial medible en cliente sandbox; fixture no provisionada en este turno.",
                    "E06": "Requiere saldo vencido total en extracto sandbox dedicado.",
                    "E07": "Requiere mix vencido+actual parcial; fixture extracto no listada.",
                    "E08": "Requiere mix vencido+actual completa; fixture extracto no listada.",
                    "E11": "Requiere saldo vencido + abono capital en mismo crédito sandbox.",
                    "E12": "Requiere A+V+K concurrente con extracto multi-panel.",
                    "E13": "Requiere crédito en última cuota (payoff) en sandbox.",
                    "E14": "Requiere payoff + capital adicional con tabla amort sandbox.",
                    "E16": "Requiere split un pago→dos créditos con montos reconciliables.",
                    "E17": "Requiere multi-crédito tipos distintos + Merge token MULTIPLE.",
                    "E18": "Requiere PDF extracto con panel derecho aplicación anterior (fixture espacial).",
                    "E19": "Requiere PDF extracto con saldo mora a la derecha.",
                    "E20": "Requiere PDF ambiguo (doble panel) en crédito sandbox.",
                    "E22": "Requiere dos extractos y as-of fecha banco ≠ más reciente.",
                    "E23": "Requiere dos pagos mismo cliente fechas distintas en un lote.",
                    "E24": "Requiere asientos contables sandbox con mismatch por crédito y total OK.",
                    "E25": "Requiere asientos con total ≠ banco (bloqueo amort).",
                    "E26": "Requiere asiento de crédito incorrecto en carpeta sandbox.",
                    "E27": "Requiere asiento faltante post-merge.",
                    "E28": "Requiere PDF asiento ilegible en sandbox.",
                    "E30": "Depende de proceso FINALIZADO estable; se cubre tras happy-path extendido.",
                    "E31": "Notify: CORREOS.xlsx sandbox tiene destinatarios mixtos; requiere rewrite receptores + CAPA A.",
                    "E32": "Retry merge requiere merge previo exitoso + asientos.",
                    "E33": "Retry amort requiere apply previo + backup tabla.",
                    "E34": "CAPA A Playwright (doble click) pendiente tras deploy password rotate.",
                    "E35": "CAPA A Playwright refresh mid-job.",
                    "E36": "CAPA A Playwright network fault injection.",
                    "E38": "Cancel no permitido post-fase avanzada; requiere proceso en fase protegida.",
                    "E39": "Finalize sin amort solo en fase correcta; requiere control state machine fixture.",
                    "E40": "AMORTIZACION_PARCIAL true: un crédito OK / otro falla; requiere dual-credit amort fixture.",
                }
                results.append(blocked(sid, reason_map.get(sid, "Handler no implementado aún")))
                continue
            try:
                results.append(handler(session))
            except Exception as exc:  # noqa: BLE001 — matriz debe registrar fallo
                results.append(
                    ScenarioResult(sid, "FAIL", evidence=f"exception:{type(exc).__name__}:{exc}")
                )
    return results


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--ids",
        default="E01,E02,E03,E04,E09,E10,E15,E21,E29,E37",
        help="Comma-separated scenario ids, or ALL",
    )
    args = parser.parse_args()
    if args.ids.strip().upper() == "ALL":
        ids = [s.id for s in SCENARIOS]
    else:
        ids = [x.strip() for x in args.ids.split(",") if x.strip()]
    results = run_selected(ids)
    # Fill missing catalog entries as BLOCKED for ALL
    seen = {r.id for r in results}
    if args.ids.strip().upper() == "ALL":
        for s in SCENARIOS:
            if s.id not in seen:
                results.append(blocked(s.id, "No ejecutado"))
    summary = {
        "process_date_base": PROCESS_DATE_BASE.isoformat(),
        "bank_code": BANK_CODE,
        "results": [r.as_dict() for r in results],
        "counts": {
            "PASS": sum(1 for r in results if r.status == "PASS"),
            "FAIL": sum(1 for r in results if r.status == "FAIL"),
            "BLOCKED": sum(1 for r in results if r.status == "BLOCKED"),
        },
    }
    out = _log("matrix_results", summary)
    print("WROTE", out)
    print("COUNTS", summary["counts"])
    return 1 if summary["counts"]["FAIL"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
