"""Consolidar: un PDF por grupo de créditos vinculados y fecha de pago (entrega 3)."""
from __future__ import annotations

from datetime import date
from io import BytesIO
from types import SimpleNamespace
from typing import Any

from openpyxl import Workbook
from pypdf import PdfReader

from app.application.services.amortization_decisions import (
    add_exclusion,
    set_group_assignments,
)
from app.application.services.merge_manifest_view import manifest_payment_outputs
from app.application.services.review_schema import (
    AplicacionPagosCols,
    REVIEW_SCHEMA_VERSION,
    ReviewSheets,
    TipoAplicacionConfirmado as T,
    ValidarPago,
)
from app.application.use_cases import merge_composite_validado_pdfs as m
from tests.test_finalize_validation import make_distrib_row
from tests.test_merge_composite_control_workbook import _MergeGraph, _bank_bytes, _tiny_pdf
from tests.test_merge_phase3_decisions import _manifest, _registry, _run, control  # noqa: F401

CLIENTE = "RUEDA INVERSIONES"


def _folder(cliente: str, cred: str) -> str:
    return f"clientes/{cliente}/CREDITO# {cred}/ASIENTOS CONTABLES CRED {cred}"


def _extract(cliente: str, cred: str) -> str:
    return f"clientes/{cliente}/CREDITO# {cred}/EXTRACTOS/extracto {cred}.pdf"


def _asiento(amount: float, credit: str, fecha: str) -> bytes:
    from reportlab.pdfgen.canvas import Canvas

    buf = BytesIO()
    canvas = Canvas(buf)
    amt = f"{float(amount):,.2f}"
    canvas.drawString(50, 740, f"Comprobante 1 Fecha {fecha}")
    canvas.drawString(50, 720, f"{amt} PAGO: No.Rad. {credit} Linea 544 1 11100505")
    canvas.drawString(50, 700, f"{amt} PAGO: No.Rad. {credit} Linea 544 1 13410519")
    canvas.save()
    return buf.getvalue()


def _fila(id_pago: str, cred: str, tipo: str, fecha: date, monto: float, *, cliente: str = CLIENTE,
          extracto: str | None = None) -> dict[str, Any]:
    return {
        "id_pago": id_pago, "cred": cred, "tipo": tipo, "fecha": fecha, "monto": monto,
        "cliente": cliente, "extracto": _extract(cliente, cred) if extracto is None else extracto,
    }


def _hist(filas: list[dict[str, Any]]) -> bytes:
    wb = Workbook()
    ws = wb.active
    ws.title = ReviewSheets.APLICACION_PAGOS
    ws.append(
        list(AplicacionPagosCols.HEADERS)
        + ["_ruta_extracto", "_ruta_unidad_credito", "_ruta_asientos_contables"]
    )
    for f in filas:
        row, _ = make_distrib_row(
            id_pago=f["id_pago"], validar_pago=ValidarPago.SI, credito=f["cred"],
            cliente=f["cliente"], tipo_aplicacion=f["tipo"], monto_banco=f["monto"],
            fecha_banco=f["fecha"], ruta_pdf_internal=f["extracto"],
        )
        ws.append(list(row) + [_folder(f["cliente"], f["cred"])])
    meta = wb.create_sheet(ReviewSheets.META)
    meta.append(["Campo", "Valor"])
    meta.append(["ReviewSchemaVersion", REVIEW_SCHEMA_VERSION])
    bio = BytesIO()
    wb.save(bio)
    return bio.getvalue()


def _setup(g: _MergeGraph, filas, asientos: dict[tuple[str, str], list[tuple[str, float, str]]]):
    """asientos: (cliente, crédito) → [(nombre, monto, fecha dd/mm/aaaa)]."""
    hist, email = "HIST/e3.xlsx", "EMAIL/mail.pdf"
    g.initial["bank/report.xlsx"] = _bank_bytes()
    g.initial[hist] = _hist(filas)
    g.initial[email] = _tiny_pdf()
    for f in filas:
        if f["extracto"]:
            g.initial.setdefault(f["extracto"], _tiny_pdf())
    for (cliente, cred), items in asientos.items():
        folder = _folder(cliente, cred)
        g.children[folder] = [{"name": _nombre(n, cred), "file": {}} for n, _, _ in items]
        for n, amount, fecha in items:
            g.initial[f"{folder}/{_nombre(n, cred)}"] = _asiento(amount, cred, fecha)
    return hist, email


def _nombre(n: str, cred: str) -> str:
    return f"asiento {cred} {n}"


def _ruta(cliente: str, cred: str, n: str) -> str:
    return f"{_folder(cliente, cred)}/{_nombre(n, cred)}"


def _pendientes(g: _MergeGraph) -> list[Any]:
    return [(x.get("id_pago"), x.get("missing_inputs")) for x in _manifest(g)["incomplete_groups"]]


def _pdfs(g: _MergeGraph) -> dict[str, int]:
    return {
        k.rsplit("/", 1)[-1]: len(PdfReader(BytesIO(v)).pages)
        for k, v in g.uploaded.items()
        if k.endswith(".pdf")
    }


def _asientos_por_pago(manifest: dict[str, Any]) -> dict[str, list[str]]:
    return {
        o["id_pago"]: [p for ci in o["credit_items"] for p in ci.get("asiento_pdf_paths") or []]
        for o in manifest_payment_outputs(manifest)
    }


def test_camino_feliz_1_pago_1_credito_1_asiento_solo_cambia_el_nombre(control):
    g = _MergeGraph()
    filas = [_fila("P1", "264", T.PAGO_OBLIGACION_ACTUAL, date(2026, 9, 25), 1000)]
    hist, email = _setup(g, filas, {(CLIENTE, "264"): [("a.pdf", 1000, "25/09/2026")]})
    result = _run(g, hist, email)
    assert result.merge_control_status == "CONSOLIDADO", _pendientes(g)
    assert _pdfs(g) == {"25 SEPTIEMBRE PAGO CUOTA RUEDA INVERSIONES CRED 264.pdf": 3}
    manifest = _manifest(g)
    assert manifest["manifest_version"] == 2
    assert manifest["consolidados_count"] == 1
    [out] = manifest["outputs"]
    assert out["id_pagos"] == ["P1"]
    assert out["nombre_consolidado"] == "25 SEPTIEMBRE PAGO CUOTA RUEDA INVERSIONES CRED 264.pdf"
    [pago] = out["payments"]
    assert pago["id_pago"] == "P1"
    assert pago["output_relative_path"] == out["output_relative_path"]
    assert pago["credit_items"][0]["asiento_pdf_paths"] == [_ruta(CLIENTE, "264", "a.pdf")]


def test_247_dos_fechas_con_asignacion_genera_dos_pdfs_con_cada_asiento_una_vez(control):
    g = _MergeGraph()
    filas = [
        _fila("P-AB", "247", T.ABONO_A_CAPITAL, date(2026, 9, 22), 100),
        _fila("P-CU", "247", T.PAGO_OBLIGACION_ACTUAL, date(2026, 9, 25), 50),
    ]
    hist, email = _setup(
        g, filas, {(CLIENTE, "247"): [("a1.pdf", 100, "24/09/2026"), ("a2.pdf", 50, "26/09/2026")]}
    )
    reg, _ = set_group_assignments(
        _registry(), group_key="247", quien="op",
        items=[
            {"credito": "247", "asiento_pdf_path": _ruta(CLIENTE, "247", "a1.pdf"), "id_pago": "P-AB", "fecha_banco": "2026-09-22"},
            {"credito": "247", "asiento_pdf_path": _ruta(CLIENTE, "247", "a2.pdf"), "id_pago": "P-CU", "fecha_banco": "2026-09-25"},
        ],
    )
    control["registry"] = reg
    result = _run(g, hist, email)
    assert result.merge_control_status == "CONSOLIDADO", _pendientes(g)
    assert _pdfs(g) == {
        "22 SEPTIEMBRE ABONO A CAPITAL RUEDA INVERSIONES CRED 247.pdf": 3,
        "25 SEPTIEMBRE PAGO CUOTA RUEDA INVERSIONES CRED 247.pdf": 3,
    }
    manifest = _manifest(g)
    assert manifest["consolidados_count"] == 2
    assert _asientos_por_pago(manifest) == {"P-AB": [_ruta(CLIENTE, "247", "a1.pdf")], "P-CU": [_ruta(CLIENTE, "247", "a2.pdf")]}


def test_247_sin_asignacion_queda_pendiente_sin_pdf(control):
    g = _MergeGraph()
    filas = [
        _fila("P-AB", "247", T.ABONO_A_CAPITAL, date(2026, 9, 22), 100),
        _fila("P-CU", "247", T.PAGO_OBLIGACION_ACTUAL, date(2026, 9, 25), 50),
    ]
    hist, email = _setup(
        g, filas, {(CLIENTE, "247"): [("a1.pdf", 100, "24/09/2026"), ("a2.pdf", 50, "26/09/2026")]}
    )
    control["registry"] = _registry()
    result = _run(g, hist, email)
    assert result.merge_control_status == "MERGE_PARCIAL"
    assert _pdfs(g) == {}
    manifest = _manifest(g)
    assert manifest["outputs"] == []
    pend = {x["id_pago"]: x for x in manifest["incomplete_groups"]}
    assert set(pend) == {"P-AB", "P-CU"}
    for item in pend.values():
        assert m.ASIENTO_ASSIGNMENT_REQUIRED in str(item["missing_inputs"])

    from app.application.job_status_enrichment import _merge_completed_enrichment
    from app.application.services.merge_queue_service import _result_to_dict

    user, nxt, _level = _merge_completed_enrichment(
        "merge_composite_validado_pdfs", _result_to_dict(result)
    )
    assert "falta indicar a cuál corresponde" in user
    assert "Asignar asientos a sus pagos" in nxt

    from app.application.ui.merge_operational_issues import build_operational_issues_from_merge_job

    job = SimpleNamespace(
        job_id="job-247-x", payload={"status": "completed", "result": _result_to_dict(result)}
    )
    [issue] = build_operational_issues_from_merge_job(job)
    assert "falta indicar a cuál corresponde" in issue.user_message
    assert "ASIENTO_ASSIGNMENT_REQUIRED" not in issue.user_message + issue.title


def test_ui_muestra_el_nombre_del_consolidado():
    from app.application.ui.manifest_outputs import parse_manifest_output_pdfs
    from app.application.ui.process_projection import ManifestOutputRef, _merge_pdf_operator_labels

    [ref] = parse_manifest_output_pdfs(
        [{"output_relative_path": "c/x.pdf", "nombre_consolidado": "25 SEPTIEMBRE PAGO CUOTA RUEDA CRED 247.pdf"}]
    )
    assert ref.nombre == "25 SEPTIEMBRE PAGO CUOTA RUEDA CRED 247.pdf"
    labels = _merge_pdf_operator_labels(
        [ManifestOutputRef(path=ref.path, nombre=ref.nombre), ManifestOutputRef(path="v1.pdf", credito="10")]
    )
    assert labels == [
        "Abrir PDF consolidado · 25 SEPTIEMBRE PAGO CUOTA RUEDA CRED 247",
        "Abrir PDF consolidado · Crédito 10",
    ]


def test_dos_fechas_asientos_con_la_fecha_de_cada_pago_se_reparten_solos(control):
    g = _MergeGraph()
    filas = [
        _fila("P-AB", "247", T.ABONO_A_CAPITAL, date(2026, 9, 22), 100),
        _fila("P-CU", "247", T.PAGO_OBLIGACION_ACTUAL, date(2026, 9, 25), 50),
    ]
    hist, email = _setup(
        g, filas, {(CLIENTE, "247"): [("a1.pdf", 100, "22/09/2026"), ("a2.pdf", 50, "25/09/2026")]}
    )
    result = _run(g, hist, email)
    assert result.merge_control_status == "CONSOLIDADO", _pendientes(g)
    assert len(_pdfs(g)) == 2
    assert _asientos_por_pago(_manifest(g)) == {"P-AB": [_ruta(CLIENTE, "247", "a1.pdf")], "P-CU": [_ruta(CLIENTE, "247", "a2.pdf")]}


def test_pago_y_abono_misma_fecha_un_pdf_con_tipo_combinado(control):
    g = _MergeGraph()
    filas = [
        _fila("P-AB", "247", T.ABONO_A_CAPITAL, date(2026, 9, 25), 100),
        _fila("P-CU", "247", T.PAGO_OBLIGACION_ACTUAL, date(2026, 9, 25), 50),
    ]
    hist, email = _setup(
        g, filas, {(CLIENTE, "247"): [("a1.pdf", 100, "25/09/2026"), ("a2.pdf", 50, "25/09/2026")]}
    )
    result = _run(g, hist, email)
    assert result.merge_control_status == "CONSOLIDADO", _pendientes(g)
    # 2 asientos + correo + extracto del crédito una sola vez.
    assert _pdfs(g) == {"25 SEPTIEMBRE PAGO CUOTA Y ABONO A CAPITAL RUEDA INVERSIONES CRED 247.pdf": 4}
    por_pago = _asientos_por_pago(_manifest(g))
    assert sorted(por_pago["P-AB"] + por_pago["P-CU"]) == sorted(
        _ruta(CLIENTE, "247", n) for n in ("a1.pdf", "a2.pdf")
    )


def test_fila_pago_cuota_mas_abono_equivale_a_dos_filas(control):
    g = _MergeGraph()
    filas = [_fila("P1", "247", T.PAGO_Y_ABONO_CAPITAL, date(2026, 9, 25), 150)]
    hist, email = _setup(g, filas, {(CLIENTE, "247"): [("a.pdf", 150, "25/09/2026")]})
    _run(g, hist, email)
    assert list(_pdfs(g)) == ["25 SEPTIEMBRE PAGO CUOTA Y ABONO A CAPITAL RUEDA INVERSIONES CRED 247.pdf"]


def test_jasp_pago_total_dos_creditos(control):
    g = _MergeGraph()
    cli = "GRUPO EMPRESARIAL JASP"
    filas = [
        _fila("J1", "102", T.CANCELACION_PAGO_TOTAL, date(2026, 9, 9), 500, cliente=cli),
        _fila("J1", "133", T.CANCELACION_PAGO_TOTAL, date(2026, 9, 9), 500, cliente=cli),
    ]
    hist, email = _setup(
        g, filas,
        {(cli, "102"): [("a.pdf", 500, "09/09/2026")], (cli, "133"): [("b.pdf", 500, "09/09/2026")]},
    )
    result = _run(g, hist, email)
    assert result.merge_control_status == "CONSOLIDADO", _pendientes(g)
    assert list(_pdfs(g)) == ["09 SEPTIEMBRE PAGO TOTAL GRUPO EMPRESARIAL JASP CRED 102 Y 133.pdf"]


def test_transp_pagos_vinculados_por_credito_van_en_un_solo_pdf(control):
    g = _MergeGraph()
    cli = "TRANSP"
    filas = [
        _fila("T1", "95", T.PAGO_OBLIGACION_ACTUAL, date(2026, 9, 15), 300, cliente=cli),
        _fila("T1", "194", T.PAGO_OBLIGACION_ACTUAL, date(2026, 9, 15), 300, cliente=cli),
        _fila("T2", "194", T.ABONO_A_CAPITAL, date(2026, 9, 15), 200, cliente=cli),
    ]
    hist, email = _setup(
        g, filas,
        {
            (cli, "95"): [("a95.pdf", 150, "15/09/2026")],
            (cli, "194"): [("a194.pdf", 150, "15/09/2026"), ("b194.pdf", 200, "15/09/2026")],
        },
    )
    result = _run(g, hist, email)
    assert result.merge_control_status == "CONSOLIDADO", _pendientes(g)
    assert list(_pdfs(g)) == ["15 SEPTIEMBRE PAGO CUOTA Y ABONO A CAPITAL TRANSP CRED 95 Y 194.pdf"]
    [out] = _manifest(g)["outputs"]
    assert out["id_pagos"] == ["T1", "T2"]
    todos = [p for ps in _asientos_por_pago(_manifest(g)).values() for p in ps]
    assert len(todos) == len(set(todos)) == 3


def test_pago_incompleto_bloquea_todo_su_grupo_y_no_otros(control):
    g = _MergeGraph()
    cli = "TRANSP"
    filas = [
        _fila("T1", "95", T.PAGO_OBLIGACION_ACTUAL, date(2026, 9, 15), 300, cliente=cli),
        _fila("T1", "194", T.PAGO_OBLIGACION_ACTUAL, date(2026, 9, 15), 300, cliente=cli),
        _fila("T2", "194", T.PAGO_OBLIGACION_ACTUAL, date(2026, 9, 15), 200, cliente=cli),
        _fila("T2", "300", T.PAGO_OBLIGACION_ACTUAL, date(2026, 9, 15), 200, cliente=cli),
        _fila("O1", "264", T.PAGO_OBLIGACION_ACTUAL, date(2026, 9, 15), 100),
    ]
    hist, email = _setup(
        g, filas,
        {
            (cli, "95"): [("a95.pdf", 150, "15/09/2026")],
            (cli, "194"): [("a194.pdf", 350, "15/09/2026")],
            (CLIENTE, "264"): [("a.pdf", 100, "15/09/2026")],
        },
    )
    result = _run(g, hist, email)
    assert result.merge_control_status == "MERGE_PARCIAL"
    assert list(_pdfs(g)) == ["15 SEPTIEMBRE PAGO CUOTA RUEDA INVERSIONES CRED 264.pdf"]
    pend = {x["id_pago"]: x for x in _manifest(g)["incomplete_groups"]}
    assert set(pend) == {"T1", "T2"}
    assert pend["T1"]["blocked_by_group"] is True
    assert pend["T1"]["group_key"] == pend["T2"]["group_key"]


def test_extracto_que_no_se_puede_descargar_falla_el_consolidado_entero(control):
    g = _MergeGraph()
    cli = "TRANSP"
    filas = [
        _fila("T1", "95", T.PAGO_OBLIGACION_ACTUAL, date(2026, 9, 15), 300, cliente=cli),
        _fila("T1", "194", T.PAGO_OBLIGACION_ACTUAL, date(2026, 9, 15), 300, cliente=cli),
        _fila("T2", "194", T.PAGO_OBLIGACION_ACTUAL, date(2026, 9, 15), 200, cliente=cli,
              extracto="clientes/TRANSP/no existe.pdf"),
        _fila("O1", "264", T.PAGO_OBLIGACION_ACTUAL, date(2026, 9, 15), 100),
    ]
    hist, email = _setup(
        g, filas,
        {
            (cli, "95"): [("a95.pdf", 150, "15/09/2026")],
            (cli, "194"): [("a194.pdf", 350, "15/09/2026")],
            (CLIENTE, "264"): [("a.pdf", 100, "15/09/2026")],
        },
    )
    g.initial.pop("clientes/TRANSP/no existe.pdf", None)
    result = _run(g, hist, email)
    assert result.merge_control_status == "MERGE_PARCIAL"
    assert list(_pdfs(g)) == ["15 SEPTIEMBRE PAGO CUOTA RUEDA INVERSIONES CRED 264.pdf"]
    mf = _manifest(g)
    assert mf["failed_groups_count"] == 1
    assert "id_pago=T1, T2 | reason=extracto_download_failed" in mf["skipped"][0]


def test_nombre_usa_el_tipo_del_excel_aunque_el_registro_traiga_una_correccion_antigua(control):
    g = _MergeGraph()
    filas = [_fila("P1", "40", T.PAGO_OBLIGACION_ACTUAL, date(2026, 9, 22), 1000)]
    hist, email = _setup(g, filas, {(CLIENTE, "40"): [("a.pdf", 1000, "22/09/2026")]})
    reg = _registry()
    reg["tipo_corrections"].append(
        {
            "id": "old", "status": "active", "group_key": "40", "id_pago": "P1", "credits": ["40"],
            "tipo_anterior": "PAGO CUOTA", "tipo_nuevo": "PAGO TOTAL", "nota": "saldo en cero",
        }
    )
    control["registry"] = reg
    _run(g, hist, email)
    assert list(_pdfs(g)) == ["22 SEPTIEMBRE PAGO CUOTA RUEDA INVERSIONES CRED 40.pdf"]


def test_extracto_de_ruta_entra_aunque_el_tipo_no_lo_exija(control):
    g = _MergeGraph()
    filas = [_fila("P1", "40", T.ABONO_A_CAPITAL, date(2026, 9, 22), 1000)]
    hist, email = _setup(g, filas, {(CLIENTE, "40"): [("a.pdf", 1000, "22/09/2026")]})
    _run(g, hist, email)
    assert _pdfs(g) == {"22 SEPTIEMBRE ABONO A CAPITAL RUEDA INVERSIONES CRED 40.pdf": 3}


def test_abono_sin_extracto_consolida_igual(control):
    g = _MergeGraph()
    filas = [_fila("P1", "40", T.ABONO_A_CAPITAL, date(2026, 9, 22), 1000, extracto="")]
    hist, email = _setup(g, filas, {(CLIENTE, "40"): [("a.pdf", 1000, "22/09/2026")]})
    result = _run(g, hist, email)
    assert result.merge_control_status == "CONSOLIDADO", _pendientes(g)
    assert _pdfs(g) == {"22 SEPTIEMBRE ABONO A CAPITAL RUEDA INVERSIONES CRED 40.pdf": 2}


def test_credito_excluido_no_genera_pdf_y_sus_asientos_quedan_para_procesados(control):
    g = _MergeGraph()
    filas = [
        _fila("P1", "258", T.PAGO_OBLIGACION_ACTUAL, date(2026, 9, 22), 100),
        _fila("P2", "265", T.PAGO_OBLIGACION_ACTUAL, date(2026, 9, 22), 100),
    ]
    hist, email = _setup(
        g, filas,
        {(CLIENTE, "258"): [("a.pdf", 100, "22/09/2026")], (CLIENTE, "265"): [("b.pdf", 100, "22/09/2026")]},
    )
    reg, _ = add_exclusion(
        _registry(), credits=["265"], clientes={"265": CLIENTE}, id_pagos=["P2"], tablas={},
        motivo_codigo="FALTA_ASIENTO", nota="", quien="op", fase="consolidacion",
    )
    control["registry"] = reg
    result = _run(g, hist, email)
    assert result.merge_control_status == "CONSOLIDADO", _pendientes(g)
    assert list(_pdfs(g)) == ["22 SEPTIEMBRE PAGO CUOTA RUEDA INVERSIONES CRED 258.pdf"]
    [excl] = _manifest(g)["excluded_groups"]
    assert excl["asiento_items"] == [{"path": _ruta(CLIENTE, "265", "b.pdf"), "credito": "265"}]
