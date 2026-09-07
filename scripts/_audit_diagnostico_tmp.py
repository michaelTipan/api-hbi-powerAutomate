"""DIAGNÓSTICO TEMPORAL DE AUDITORÍA — NO ES CÓDIGO DE PRODUCTO. NO COMMITAR.

Ejecuta comprobaciones de lectura sobre el working tree actual.
No escribe SharePoint. No modifica app/ ni frontend/src/.
"""
from __future__ import annotations

import inspect
import io
import json
import sys
from dataclasses import asdict
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from openpyxl import Workbook, load_workbook

from app.application.services.accounting_pdf_parser import (
    PaymentApplicationEvent,
    extract_text_from_pdf,
    parse_accounting_text,
)
from app.application.services.amortization_workbook import (
    detect_headers,
    find_application_row_detailed,
    write_payment_application,
    _default_valor_pagado_formula,
)
from app.application.services.extract_selection import choose_extract_as_of_bank_date
from app.application.services.review_schema import (
    TipoAplicacionConfirmado,
    resolve_policy_from_tipo_confirmado,
)
from app.application.use_cases.amortization_fill_dry_run import _policy_requires_ibr
from app.application.use_cases.merge_composite_validado_pdfs import (
    _filename_contains_credit_isolated,
    _pick_asiento_names_for_group,
    _score_asiento_name_for_tipo,
)
from app.application.use_cases.send_validar_extractos_notification import (
    _row_policy_attaches_extract,
)


def section(title: str) -> None:
    print("\n" + "=" * 72)
    print(title)
    print("=" * 72)


def dump(obj) -> None:
    print(json.dumps(obj, ensure_ascii=False, indent=2, default=str))


def main() -> None:
    section("0. POLICY 248 CANCELACIÓN / PAGO TOTAL")
    p = resolve_policy_from_tipo_confirmado(
        TipoAplicacionConfirmado.CANCELACION_PAGO_TOTAL
    )
    dump(asdict(p))
    notify_row = {
        "requiere_extracto": p.requiere_extracto,
        "rol_extracto": str(p.rol_extracto),
        "include_extract_in_composite": p.include_extract_in_composite,
    }
    dump(
        {
            "notify_attaches_extract": _row_policy_attaches_extract(notify_row),
            "notify_usa_requiere_extracto_NO_include_extract_in_composite": True,
            "merge_include_extract_expected": p.include_extract_in_composite,
        }
    )

    section("1. NOMENCLATURA / SCORING / CLAIMED_NAMES")
    iso = {
        "327 in pago-327.pdf": _filename_contains_credit_isolated("pago-327.pdf", "327"),
        "327 in 1327.pdf": _filename_contains_credit_isolated("1327.pdf", "327"),
        "327 in 3270.pdf": _filename_contains_credit_isolated("3270.pdf", "327"),
        "327 in Asiento CRED 327 01.pdf": _filename_contains_credit_isolated(
            "Asiento CRED 327 01.pdf", "327"
        ),
        "327 in asdf-327.pdf": _filename_contains_credit_isolated("asdf-327.pdf", "327"),
    }
    dump(iso)

    tipo_pago_abono = "PAGO Y ABONO A CAPITAL"
    names_a = ["pago-327.pdf", "abono-327.pdf"]
    names_b = ["327-parte1.pdf", "327-parte2.pdf"]
    names_c = [
        "Asiento cuota credito 327.pdf",
        "Asiento abono capital credito 327.pdf",
    ]
    claimed = set()
    dump(
        {
            "scores_pago_abono_libre": {
                n: _score_asiento_name_for_tipo(n, tipo_pago_abono) for n in names_a
            },
            "pick_pago_abono_libre": _pick_asiento_names_for_group(
                names_a, tipo_visible=tipo_pago_abono, claimed_names=set()
            ),
            "scores_parte": {
                n: _score_asiento_name_for_tipo(n, tipo_pago_abono) for n in names_b
            },
            "pick_parte": _pick_asiento_names_for_group(
                names_b, tipo_visible=tipo_pago_abono, claimed_names=set()
            ),
            "scores_cuota_vs_abono_capital": {
                n: _score_asiento_name_for_tipo(n, tipo_pago_abono) for n in names_c
            },
            "pick_cuota_vs_abono_capital": _pick_asiento_names_for_group(
                names_c, tipo_visible=tipo_pago_abono, claimed_names=set()
            ),
            "cancelacion_pago_total_vs_cuota": {
                "scores": {
                    n: _score_asiento_name_for_tipo(n, "CANCELACIÓN / PAGO TOTAL")
                    for n in [
                        "21 JULIO PAGO TOTAL CREDITO 248.pdf",
                        "cuota-248.pdf",
                    ]
                },
                "pick": _pick_asiento_names_for_group(
                    [
                        "21 JULIO PAGO TOTAL CREDITO 248.pdf",
                        "cuota-248.pdf",
                    ],
                    tipo_visible="CANCELACIÓN / PAGO TOTAL",
                    claimed_names=set(),
                ),
            },
        }
    )

    # Dos ID Pago, mismo crédito, claimed_names=set() recreado (como Merge L646/L848)
    folder = ["a-327.pdf", "b-327.pdf", "c-327.pdf", "d-327.pdf"]
    pick_a = _pick_asiento_names_for_group(
        folder, tipo_visible=tipo_pago_abono, claimed_names=set()
    )
    pick_b = _pick_asiento_names_for_group(
        folder, tipo_visible=tipo_pago_abono, claimed_names=set()
    )
    shared = set(pick_a) & set(pick_b)
    dump(
        {
            "id_pago_A_pick": pick_a,
            "id_pago_B_pick": pick_b,
            "intersection": sorted(shared),
            "mismo_pdf_usado_por_ambos": sorted(shared) == sorted(folder)
            or bool(shared),
            "claimed_names_recreado_vacio_como_en_merge": True,
        }
    )
    claimed_shared: set[str] = set()
    pick_a2 = _pick_asiento_names_for_group(
        folder, tipo_visible=tipo_pago_abono, claimed_names=claimed_shared
    )
    pick_b2 = _pick_asiento_names_for_group(
        folder, tipo_visible=tipo_pago_abono, claimed_names=claimed_shared
    )
    dump(
        {
            "SI_claimed_names_fuera_compartido": {
                "A": pick_a2,
                "B": pick_b2,
                "intersection": sorted(set(pick_a2) & set(pick_b2)),
                "nota": "score<=0 conserva TODO el pool y marca claimed; B recibiría [] y cae a available or valid_names (pool=valid_names si available vacío)",
            }
        }
    )

    section("2. PARSER RETENCIONES EJEMPLO OFICIAL + PDFs casos-nuevos")
    official = """3494
Año       Mes      Día
23 4 2026 Fecha  : SIN ENTIDAD Entidad : 0 Soporte :
221,926,895.00 PAGO: No.Rad. 327 Linea 544 1 11100505
163,759,925.00 PAGO: No.Rad. 327 Linea 544 1 13410519
62,545,129.00 PAGO: No.Rad. 327 Linea 544 1 13430501
4,378,159.00 PAGO: No.Rad. 327 Linea 544 1 13551503
"""
    ev = parse_accounting_text(official, {"id_pago": "X", "cliente": "HBI", "credito": "327", "asiento_pdf_path": "x.pdf"})
    dump(
        {
            "capital": ev.capital,
            "intereses": ev.intereses,
            "retenciones": ev.retenciones,
            "valor_pagado_cliente": ev.valor_pagado_cliente,
            "mora": ev.mora,
            "detected_codes": list(ev.detected_codes),
            "parse_warnings": list(ev.parse_warnings),
            "formula_oficial": "163759925+62545129-4378159=221926895",
            "suma_sin_restar_ret": ev.capital + ev.intereses,
            "capital_mas_int_menos_ret": ev.capital + ev.intereses - ev.retenciones,
        }
    )

    casos = ROOT / "casos-nuevos"
    if casos.is_dir():
        for pdf in sorted(casos.glob("*.pdf")):
            try:
                text = extract_text_from_pdf(pdf.read_bytes())
            except Exception as exc:
                dump({"file": pdf.name, "extract_error": str(exc)})
                continue
            try:
                pev = parse_accounting_text(
                    text,
                    {
                        "id_pago": "diag",
                        "cliente": "diag",
                        "credito": pdf.name,
                        "asiento_pdf_path": pdf.name,
                    },
                )
                dump(
                    {
                        "file": pdf.name,
                        "pages_hint": text.count("\f") + 1 if text else 0,
                        "text_len": len(text or ""),
                        "capital": pev.capital,
                        "intereses": pev.intereses,
                        "mora": pev.mora,
                        "retenciones": pev.retenciones,
                        "valor_pagado_cliente": pev.valor_pagado_cliente,
                        "detected_codes": list(pev.detected_codes),
                        "warnings": list(pev.parse_warnings),
                        "has_1355": "1355" in (text or ""),
                    }
                )
            except Exception as exc:
                dump(
                    {
                        "file": pdf.name,
                        "parse_error": type(exc).__name__,
                        "msg": str(exc)[:400],
                        "has_1355": "1355" in (text or ""),
                        "text_preview": (text or "")[:400],
                    }
                )

    section("3. EXTRACT TIE misma Fecha límite")
    bank = date(2026, 8, 15)
    scored = []
    for name, created in [
        ("A.pdf", date(2026, 8, 1)),
        ("B.pdf", date(2026, 8, 10)),
        ("C.pdf", date(2026, 8, 15)),
        ("D.pdf", date(2026, 8, 15)),
    ]:
        cand = {"name": name, "relative_path": name, "createdDateTime": created.isoformat()}
        pdf = f"bytes-{name}".encode()
        digest = name  # hashes distintos
        scored.append((cand, bank, pdf, digest))  # misma fecha_limite = bank
    outcome = choose_extract_as_of_bank_date(scored, bank)
    dump(
        {
            "error_code": outcome.error_code,
            "selection_reason": outcome.selection_reason,
            "winner": None if outcome.candidate is None else outcome.candidate.get("name"),
            "esperado_negocio": "D (último createdDateTime <= Fecha banco)",
            "comportamiento_actual": "extract_tie_as_of_bank_date si hashes distintos",
        }
    )

    section("4. IBR anticipado — policy no mira Fecha banco vs Fecha límite")
    tipos = [
        TipoAplicacionConfirmado.PAGO_OBLIGACION_ACTUAL,
        TipoAplicacionConfirmado.PAGO_PARCIAL_OBLIGACION_ACTUAL,
        TipoAplicacionConfirmado.PAGO_COMBINADO,
        TipoAplicacionConfirmado.PAGO_Y_ABONO_CAPITAL,
        TipoAplicacionConfirmado.ABONO_A_CAPITAL,
        TipoAplicacionConfirmado.CANCELACION_PAGO_TOTAL,
        TipoAplicacionConfirmado.APLICACION_SALDO_VENCIDO,
    ]
    ibr_rows = []
    due = date(2026, 8, 15)
    for tipo in tipos:
        pol = resolve_policy_from_tipo_confirmado(tipo)
        req = _policy_requires_ibr(pol)
        for delta, label in [(-20, "20d_antes"), (-1, "1d_antes"), (0, "igual"), (1, "1d_despues")]:
            ibr_rows.append(
                {
                    "tipo": str(tipo),
                    "scenario": label,
                    "fecha_banco_vs_limite": (due + timedelta(days=delta)).isoformat(),
                    "actualiza_ibr": pol.actualiza_ibr,
                    "cierra_cuota": pol.cierra_cuota,
                    "policy_requires_ibr": req,
                    "fecha_entra_en_funcion": False,
                }
            )
    dump(ibr_rows)
    src = inspect.getsource(_policy_requires_ibr)
    print("SOURCE _policy_requires_ibr:\n" + src)

    section("5. FALLBACK fórmula VP + write retenciones silencioso")
    headers_with = {
        "valor_pagado_cliente": 10,
        "valor_intereses": 6,
        "abono_k": 7,
        "intereses_mora": 8,
        "retenciones": 9,
    }
    headers_without = {
        "valor_pagado_cliente": 9,
        "valor_intereses": 6,
        "abono_k": 7,
        "intereses_mora": 8,
    }
    dump(
        {
            "fallback_con_col_retenciones": _default_valor_pagado_formula(headers_with, 5),
            "fallback_sin_col_retenciones": _default_valor_pagado_formula(headers_without, 5),
            "resta_retenciones": False,
        }
    )

    wb = Workbook()
    ws = wb.active
    ws.append(
        [
            "dia",
            "mes",
            "año",
            "Fecha pago",
            "Valor intereses",
            "Abono a K",
            "intereses mora",
            "Valor pagado cliente",
        ]
    )
    ws.append([15, 8, 2026, None, None, None, None, None])
    hdr = detect_headers(ws)
    ev_w = PaymentApplicationEvent(
        id_pago="A",
        cliente="C",
        credito="327",
        asiento_pdf_path="a.pdf",
        comprobante="1",
        fecha_asiento=date(2026, 8, 15),
        valor_pagado_cliente=221_926_895.0,
        capital=163_759_925.0,
        intereses=62_545_129.0,
        mora=0.0,
        retenciones=4_378_159.0,
        saldos_menores=0.0,
        raw_text="",
        detected_codes=("544111100505", "544113410519", "544113430501", "13551503"),
    )
    plan = write_payment_application(ws, 2, hdr, ev_w)
    dump(
        {
            "headers_detected": hdr,
            "has_retenciones_header": bool(hdr.get("retenciones")),
            "write_plan_keys": plan,
            "retenciones_en_plan": "retenciones" in plan,
            "event_retenciones": ev_w.retenciones,
            "silencio": ev_w.retenciones > 0 and "retenciones" not in plan,
        }
    )

    section("6. 20 PAGOS PARCIALES en memoria (tabla sintética con filas libres)")
    wb2 = Workbook()
    ws2 = wb2.active
    ws2.append(
        [
            "dia",
            "mes",
            "año",
            "IBR +i",
            "Fecha pago",
            "Valor intereses",
            "Abono a K",
            "intereses mora",
            "Valor pagado cliente",
            "Saldos Menores",
        ]
    )
    due = date(2026, 8, 15)
    # fila 2 = cuota; filas 3-25 = aplicación vacía
    ws2.append([due.day, due.month, due.year, None, None, None, None, None, None, None])
    for _ in range(24):
        ws2.append([None] * 10)
    hdr2 = detect_headers(ws2)
    reserved: set[int] = set()
    rows_assigned: list[int] = []
    snapshot_before = [tuple(c.value for c in ws2[2])]
    for i in range(1, 21):
        ev_i = PaymentApplicationEvent(
            id_pago=f"P{i:02d}",
            cliente="X",
            credito="327",
            asiento_pdf_path=f"asiento-{i}.pdf",
            comprobante=str(i),
            fecha_asiento=due,
            valor_pagado_cliente=1_000_000.0,
            capital=900_000.0,
            intereses=100_000.0,
            mora=0.0,
            retenciones=0.0,
            saldos_menores=0.0,
            raw_text="",
            detected_codes=("544111100505", "544113410519", "544113430501"),
        )
        found = find_application_row_detailed(
            ws2,
            hdr2,
            ev_i,
            due_date_row=2,
            exclude_rows=frozenset(reserved),
            header_row=1,
            payment_date=due,
            detected_codes=ev_i.detected_codes,
        )
        if found.row is None:
            dump({"FAIL_row_none_at": i, "suggested": found.suggested_row})
            break
        write_payment_application(ws2, found.row, hdr2, ev_i)
        reserved.add(found.row)
        rows_assigned.append(found.row)
    # retry pago 3
    ev3 = PaymentApplicationEvent(
        id_pago="P03",
        cliente="X",
        credito="327",
        asiento_pdf_path="asiento-3.pdf",
        comprobante="3",
        fecha_asiento=due,
        valor_pagado_cliente=1_000_000.0,
        capital=900_000.0,
        intereses=100_000.0,
        mora=0.0,
        retenciones=0.0,
        saldos_menores=0.0,
        raw_text="",
        detected_codes=("544111100505", "544113410519", "544113430501"),
    )
    retry = find_application_row_detailed(
        ws2,
        hdr2,
        ev3,
        due_date_row=2,
        exclude_rows=frozenset(),
        header_row=1,
        payment_date=due,
        detected_codes=ev3.detected_codes,
    )
    dump(
        {
            "ws.max_row": ws2.max_row,
            "header_row": 1,
            "due_date_row": 2,
            "rows_assigned": rows_assigned,
            "unique_20": len(set(rows_assigned)) == 20 and len(rows_assigned) == 20,
            "cronograma_fila2_inmutada_fecha": [
                ws2.cell(2, 1).value,
                ws2.cell(2, 2).value,
                ws2.cell(2, 3).value,
            ]
            == [due.day, due.month, due.year],
            "retry_pago3_row": retry.row,
            "retry_status": retry.compare_status,
            "retry_no_crea_fila_nueva": retry.row == rows_assigned[2]
            if len(rows_assigned) >= 3
            else False,
            "fecha_pago_fila_pago1": str(ws2.cell(rows_assigned[0], hdr2["fecha_pago"]).value)
            if rows_assigned
            else None,
            "nota": "Tabla SINTÉTICA con 24 filas libres. Tablas reales HBI NO VERIFICADAS (0 xlsx en worktree).",
        }
    )

    section("7. GRAPH METADATA")
    print("NO VERIFICADO: GRAPH_* no está en el proceso de esta auditoría.")
    print("No se cargó api-hbi-powerAutomate.env (secretos). No se llamó Microsoft Graph.")
    print("Código Generate: GET .../children SIN $select (payment_validation_generate._get_drive_folder_children).")
    print("Código UI read: $select=id,name,webUrl,eTag,cTag,size,lastModifiedDateTime (SIN createdDateTime).")

    section("8. XLSX REALES")
    xlsx = list(ROOT.rglob("*.xlsx"))
    xlsx = [p for p in xlsx if "node_modules" not in p.parts and ".venv" not in p.parts]
    dump({"xlsx_en_worktree": [str(p.relative_to(ROOT)) for p in xlsx[:50]], "count": len(xlsx)})


if __name__ == "__main__":
    main()
