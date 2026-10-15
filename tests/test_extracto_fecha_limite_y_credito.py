"""Extracto: fecha límite con causa (nunca otra fecha cercana) y número de crédito.

- La primera fecha junto al rótulo decide; si es inexistente o ilegible se informa la
  causa con el texto leído, sin saltar a otra fecha del extracto.
- El número de crédito sale del extracto (texto o nombre), nunca del cliente/carpeta.
"""

from __future__ import annotations

import re
from datetime import date

import pytest

from app.application.services.payment_helpers import (
    FECHA_LIMITE_INVALID_DATE,
    FECHA_LIMITE_LABEL_NOT_FOUND,
    FECHA_LIMITE_UNREADABLE,
    _read_fecha_limite_from_table_rows,
    extract_credit_id_from_extract_pdf_text,
    extract_fecha_limite_pago_from_pdf_text,
    fecha_limite_problem_text,
    parse_statement_name,
    read_fecha_limite_pago_from_pdf_text,
)
from app.application.services.review_error_guide import (
    ERRORES_GUIDE_BY_CODE,
    enrich_errores_guide_texts,
)
from app.application.use_cases.payment_validation_generate import (
    _append_credit_issue_records,
    _resolve_credit_id_for_unit,
)

_TECH_CODE = re.compile(r"fecha_limite_|_not_found|_unreadable|_invalid")


# --- Fecha límite: los 4 casos documentados --------------------------------------------


@pytest.mark.parametrize(
    ("text", "cause", "shown"),
    [
        ("Fecha límite de pago 30/02/2026", FECHA_LIMITE_INVALID_DATE, "30/02/2026"),
        (
            "Fecha límite de pago 30/02/2026 Fecha de corte 15/02/2026",
            FECHA_LIMITE_INVALID_DATE,
            "30/02/2026",
        ),
        ("Fecha máxima para pagar 30/09/2026\nVencimiento 05/10/2026", FECHA_LIMITE_LABEL_NOT_FOUND, None),
        ("Fecha límite de pago 3O/O9/2026", FECHA_LIMITE_UNREADABLE, "3O/O9/2026"),
        ("Fecha límite de pago 30//09/2026", FECHA_LIMITE_UNREADABLE, "30//09/2026"),
    ],
    ids=["inexistente", "inexistente_con_otra_fecha", "sin_rotulo", "ilegible_letras", "ilegible_doble_barra"],
)
def test_fecha_limite_no_salta_a_otra_fecha(text, cause, shown):
    reading = read_fecha_limite_pago_from_pdf_text(text)
    assert reading.fecha is None
    assert reading.cause == cause
    if shown is not None:
        assert reading.text == shown
    assert extract_fecha_limite_pago_from_pdf_text(text) is None


def test_rotulo_sin_fecha_devuelve_el_texto_leido():
    reading = read_fecha_limite_pago_from_pdf_text("Fecha límite de pago: Inmediato\nTotal a pagar $ 1.000")
    assert reading.fecha is None
    assert reading.cause == FECHA_LIMITE_UNREADABLE
    assert reading.text and reading.text.startswith("Inmediato")


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Fecha límite de pago 30/09/2026", date(2026, 9, 30)),
        ("FECHA LIMITE DE PAGO\n30-09-2026", date(2026, 9, 30)),
        ("FECHA DE PAGO 2026-09-30", date(2026, 9, 30)),
        ("Fecha de desembolso 01/01/2025 Fecha límite de pago 30/09/2026", date(2026, 9, 30)),
        ("30/09/2026\nFecha límite de pago", date(2026, 9, 30)),
    ],
)
def test_fecha_limite_legible_sigue_funcionando(text, expected):
    reading = read_fecha_limite_pago_from_pdf_text(text)
    assert reading.fecha == expected
    assert reading.cause is None


def test_tabla_con_fecha_inexistente_decide_sin_buscar_otra():
    tables = [[["Fecha de corte", "15/02/2026"], ["Fecha límite de pago", "30/02/2026"]]]
    reading = _read_fecha_limite_from_table_rows(tables)
    assert reading is not None
    assert reading.fecha is None
    assert reading.cause == FECHA_LIMITE_INVALID_DATE
    ok = _read_fecha_limite_from_table_rows([[["Fecha límite de pago", "30/09/2026"]]])
    assert ok is not None and ok.fecha == date(2026, 9, 30)


@pytest.mark.parametrize(
    ("cause", "text", "fragment"),
    [
        (FECHA_LIMITE_LABEL_NOT_FOUND, None, "no se encontró el rótulo"),
        (FECHA_LIMITE_INVALID_DATE, "30/02/2026", "(30/02/2026) no existe en el calendario"),
        (FECHA_LIMITE_UNREADABLE, "3O/O9/2026", "se leyó «3O/O9/2026»"),
    ],
)
def test_texto_de_causa_para_el_operador(cause, text, fragment):
    msg = fecha_limite_problem_text(cause, text)
    assert fragment in msg
    assert not _TECH_CODE.search(msg)


# --- Errores: mensaje por causa, cliente/crédito y enlace a cada extracto -------------


def _archivo(name: str, cause: str, text: str | None, url: str) -> dict[str, str]:
    out = {"name": name, "reason": "fecha_limite_not_found", "fecha_limite_cause": cause, "link_url": url}
    if text:
        out["fecha_limite_text"] = text
    return out


def test_guia_de_errores_nombra_cliente_credito_archivo_y_causa():
    code = "fecha_limite_extracto_not_readable"
    descr, hacer = ERRORES_GUIDE_BY_CODE[code][1], ERRORES_GUIDE_BY_CODE[code][2]
    rec = {
        "cliente": "INVERSIONES FLOREZ",
        "credito": "148",
        "archivos_problema": [
            _archivo("Extracto sept.pdf", FECHA_LIMITE_INVALID_DATE, "30/02/2026", "https://sp/a"),
            _archivo("Extracto oct.pdf", FECHA_LIMITE_UNREADABLE, "3O/O9/2026", "https://sp/b"),
        ],
    }
    out_descr, out_hacer = enrich_errores_guide_texts(code, descr, hacer, rec)
    assert "cliente «INVERSIONES FLOREZ»" in out_descr
    assert "crédito «148»" in out_descr
    assert "«Extracto sept.pdf»" in out_descr and "no existe en el calendario" in out_descr
    assert "«Extracto oct.pdf»" in out_descr and "se leyó «3O/O9/2026»" in out_descr
    assert "exista en el calendario" in out_hacer
    assert "texto seleccionable" in out_hacer
    assert not _TECH_CODE.search(out_descr + out_hacer)


def test_una_fila_de_errores_por_extracto_con_su_enlace():
    records: list[dict] = []
    archivos = [
        _archivo("a.pdf", FECHA_LIMITE_INVALID_DATE, "30/02/2026", "https://sp/a"),
        _archivo("b.pdf", FECHA_LIMITE_LABEL_NOT_FOUND, None, "https://sp/b"),
    ]
    _append_credit_issue_records(
        records,
        payment_id="P1",
        cliente_folder="INVERSIONES FLOREZ",
        credit_issues=[
            {
                "unidad_credito": "148",
                "code": "fecha_limite_extracto_not_readable",
                "link_extracto_url": "https://sp/a",
                "archivos_problema": archivos,
            }
        ],
    )
    assert [r["link_extracto_url"] for r in records] == ["https://sp/a", "https://sp/b"]
    assert [r["archivos_problema"][0]["name"] for r in records] == ["a.pdf", "b.pdf"]
    assert all(r["credito"] == "148" and r["cliente"] == "INVERSIONES FLOREZ" for r in records)


def test_un_solo_extracto_conserva_una_sola_fila():
    records: list[dict] = []
    _append_credit_issue_records(
        records,
        payment_id="P1",
        cliente_folder="C",
        credit_issues=[
            {
                "unidad_credito": "148",
                "code": "fecha_limite_extracto_not_readable",
                "link_extracto_url": "https://sp/a",
                "archivos_problema": [_archivo("a.pdf", FECHA_LIMITE_INVALID_DATE, "30/02/2026", "https://sp/a")],
            }
        ],
    )
    assert len(records) == 1


# --- Número de crédito (ítem 9) --------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("No. Obligación: GB 1022-203", "203"),
        ("No. Obligación:GB-1022-203", "203"),
        ("No. Obligacion: GB 1022 - 203\nNIT 900123456", "203"),
        ("Obligación: 0265", "265"),
        ("No, Obligación GB-1022-082", "82"),
        ("Obligación # 258", "258"),
        ("Obligación 265", "265"),
        ("NIT 900.123.456-7 Cliente ASFALTOS MEDELLIN", None),
    ],
)
def test_numero_de_credito_desde_texto_del_extracto(text, expected):
    assert extract_credit_id_from_extract_pdf_text(text) == expected


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("Extracto 2026-09-30 CREDITO # 148.pdf", (date(2026, 9, 30), "148")),
        ("Extracto Abril 20-03-2026 Obligacion # 265.pdf", (date(2026, 3, 20), "265")),
        ("extracto_2026-09-30_credito_148.pdf", (date(2026, 9, 30), "148")),
        ("Extracto Crédito No. 0148.pdf", (None, "148")),
        ("EXTRACTO OBLIGACION 265 20-03-2026.pdf", (date(2026, 3, 20), "265")),
        ("Extracto ASFALTOS MEDELLIN.pdf", (None, None)),
        ("Extracto credito 2026-09-30.pdf", (None, None)),
        ("Tabla credito 148.pdf", (None, None)),
    ],
)
def test_nombre_de_extracto_tolerante(name, expected):
    assert parse_statement_name(name) == expected


def _resolve(**kw):
    base = dict(
        credit_name="ASFALTOS MEDELLIN SAS",
        cliente_folder="ASFALTOS MEDELLIN SAS",
        is_flat_unit=True,
        is_root_unit=False,
        statement_filename="Extracto.pdf",
        statement_bytes=None,
    )
    base.update(kw)
    return _resolve_credit_id_for_unit(**base)


def test_numero_de_credito_nunca_es_el_nombre_del_cliente():
    assert _resolve()[0] is None
    assert _resolve(is_flat_unit=False, credit_name="ASFALTOS")[0] is None
    # Solo filas sin extracto muestran la carpeta como referencia visual.
    assert _resolve(allow_folder_label=True)[0] == "ASFALTOS MEDELLIN SAS"


def test_numero_de_credito_desde_extracto_o_carpeta_estandar():
    assert _resolve(statement_bytes=b"PDF_MOCK: No. Obligacion: GB 1022-203")[0] == "203"
    assert _resolve(statement_filename="Extracto 2026-09-30 CREDITO # 148.pdf")[0] == "148"
    assert _resolve(is_flat_unit=False, credit_name="CREDITO # 258")[0] == "CREDITO # 258"


def test_incidencia_unidad_credito_usa_numero_resuelto_en_unidad_raiz():
    """En unidades raíz, si el extracto contiene el número de crédito (ej. 16),
    la incidencia debe usar '16' y nunca el nombre del cliente 'SERVIPETROLEOS'."""
    credit_id, _ = _resolve_credit_id_for_unit(
        credit_name="SERVIPETROLEOS",
        cliente_folder="SERVIPETROLEOS",
        is_flat_unit=False,
        is_root_unit=True,
        statement_filename="Extracto Octubre 15-10-2026 Obligación #16.pdf",
        statement_bytes=None,
    )
    assert credit_id == "16"

    records: list[dict] = []
    _append_credit_issue_records(
        records,
        payment_id="PAY-001",
        cliente_folder="SERVIPETROLEOS",
        credit_issues=[
            {
                "unidad_credito": str(credit_id or "SERVIPETROLEOS"),
                "code": "extract_right_panel_ambiguous",
                "link_extracto_url": "https://sp/extracto.pdf",
                "link_carpeta_credito_url": "https://sp/servipetroleos",
            }
        ],
    )
    assert len(records) == 1
    assert records[0]["credito"] == "16"
    assert records[0]["cliente"] == "SERVIPETROLEOS"
    assert records[0]["id_pago"] == "PAY-001"

