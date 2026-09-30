"""Entrega 3: un consolidado por (grupo, fecha de pago), nombre y reparto de asientos."""

from __future__ import annotations

from datetime import date
from typing import Any

import pytest

from app.application.services.consolidation_plan import (
    PagoPreparado,
    agrupar_pagos,
    allocate_consolidado_name,
    asientos_del_grupo,
    consolidado_basename,
    consolidado_tipo,
    credits_phrase,
    destinos_una_fecha,
    repartir,
)
from tests.test_merge_verification import _row


def _folder(credito: str) -> str:
    return f"CLIENTES/X/CREDITO # {credito}/ASIENTOS CONTABLES CRED {credito}"


def _item(credito: str, *names: str) -> dict[str, Any]:
    return {
        "credito": credito,
        "asiento_pdf_paths": [f"{_folder(credito)}/{n}" for n in names],
        "extracto_pdf_paths": [f"CLIENTES/X/CREDITO # {credito}/extracto.pdf"],
    }


def _pago(id_pago: str, rows: list[dict[str, Any]], items: list[dict[str, Any]]) -> PagoPreparado:
    return PagoPreparado(id_pago=id_pago, familia=rows[0]["tipo_aplicacion"], rows=rows, credit_items=items)


def _names(pago: PagoPreparado) -> dict[str, list[str]]:
    return {ci["credito"]: [p.rsplit("/", 1)[-1] for p in ci["asiento_pdf_paths"]] for ci in pago.credit_items}


# --- tipo del nombre ---------------------------------------------------------------


@pytest.mark.parametrize(
    ("tipos", "esperado"),
    [
        (["PAGO CUOTA"], "PAGO CUOTA"),
        (["ABONO A CAPITAL"], "ABONO A CAPITAL"),
        (["PAGO CUOTA Y ABONO A CAPITAL"], "PAGO CUOTA Y ABONO A CAPITAL"),
        (["PAGO CUOTA + ABONO A CAPITAL"], "PAGO CUOTA Y ABONO A CAPITAL"),
        (["PAGO CUOTA", "ABONO A CAPITAL"], "PAGO CUOTA Y ABONO A CAPITAL"),
        (["ABONO A CAPITAL", "PAGO CUOTA"], "PAGO CUOTA Y ABONO A CAPITAL"),
        (["PAGO CUOTA", "ABONO A CUOTAS EN MORA"], "ABONO A CUOTAS EN MORA Y PAGO CUOTA"),
        (
            ["ABONO A CUOTAS EN MORA, PAGO CUOTA Y ABONO A CAPITAL"],
            "ABONO A CUOTAS EN MORA, PAGO CUOTA Y ABONO A CAPITAL",
        ),
        (
            ["ABONO A CUOTAS EN MORA + PAGO CUOTA + ABONO A CAPITAL"],
            "ABONO A CUOTAS EN MORA, PAGO CUOTA Y ABONO A CAPITAL",
        ),
        (
            ["ABONO A CUOTAS EN MORA Y PAGO CUOTA", "PAGO CUOTA Y ABONO A CAPITAL"],
            "ABONO A CUOTAS EN MORA, PAGO CUOTA Y ABONO A CAPITAL",
        ),
        (["PAGO TOTAL", "ABONO A CAPITAL", "PAGO CUOTA"], "PAGO TOTAL"),
        (["APLICACIÓN A SALDO VENCIDO + ABONO A CAPITAL"], "ABONO A CUOTAS EN MORA Y ABONO A CAPITAL"),
        (["APLICACIÓN A SALDO VENCIDO Y ABONO A CAPITAL"], "ABONO A CUOTAS EN MORA Y ABONO A CAPITAL"),
        (["PAGO PARCIAL A OBLIGACIÓN ACTUAL"], "PAGO CUOTA"),
    ],
)
def test_consolidado_tipo_combines_parts_in_fixed_order(tipos: list[str], esperado: str):
    assert consolidado_tipo(tipos) == esperado


def test_consolidado_tipo_without_confirmed_type_falls_back_by_family():
    assert consolidado_tipo([""], familias=["ABONO"]) == "ABONO A CAPITAL"
    assert consolidado_tipo([""], familias=["PAGO"]) == "PAGO CUOTA"


# --- nombre ------------------------------------------------------------------------


def test_basename_examples_from_spec():
    assert (
        consolidado_basename(date(2026, 9, 25), "PAGO CUOTA Y ABONO A CAPITAL", "RUEDA INVERSIONES", ["247"])
        == "25 SEPTIEMBRE PAGO CUOTA Y ABONO A CAPITAL RUEDA INVERSIONES CRED 247.pdf"
    )
    assert (
        consolidado_basename(date(2026, 9, 9), "PAGO TOTAL", "GRUPO EMPRESARIAL JASP", ["133", "102"])
        == "09 SEPTIEMBRE PAGO TOTAL GRUPO EMPRESARIAL JASP CRED 102 Y 133.pdf"
    )


def test_basename_has_no_bank_and_keeps_full_client():
    long_client = "TRANSPORTES Y SERVICIOS LOGISTICOS INTEGRADOS DEL CARIBE Y DEL PACIFICO S.A.S"
    name = consolidado_basename(date(2026, 1, 3), "PAGO CUOTA", long_client, ["95", "194"])
    assert "BANCO" not in name
    assert long_client in name
    assert name.endswith(" CRED 95 Y 194.pdf")
    assert name.startswith("03 ENERO PAGO CUOTA ")


def test_basename_sanitizes_client_characters():
    name = consolidado_basename(date(2026, 9, 1), "PAGO CUOTA", 'ACME/"SAS"', ["1"])
    assert "/" not in name and '"' not in name


def test_credits_phrase_three_or_more():
    assert credits_phrase(["30", "10", "20"]) == "CRED 10, 20 Y 30"
    assert credits_phrase([]) == "CRED SIN CREDITO"


def test_collision_adds_numbered_suffix():
    taken: set[str] = set()
    base = "25 SEPTIEMBRE PAGO CUOTA ACME CRED 1.pdf"
    assert allocate_consolidado_name(base, taken) == base
    assert allocate_consolidado_name(base, taken) == "25 SEPTIEMBRE PAGO CUOTA ACME CRED 1 (2).pdf"
    assert allocate_consolidado_name(base.lower(), taken) == "25 septiembre pago cuota acme cred 1 (3).pdf"


# --- grupos y reparto ----------------------------------------------------------------


def test_happy_path_one_payment_one_credit_one_asiento():
    p = _pago("P1", [_row("10", tipo="PAGO CUOTA", monto=1_000_000, fecha=date(2026, 9, 22))], [_item("10", "a.pdf")])
    (grupo,) = agrupar_pagos([p])
    assert grupo.key == "10" and grupo.needs_asiento_dates is False
    (c,) = repartir(grupo, destinos_una_fecha(grupo))
    assert c.fecha == "2026-09-22" and c.id_pagos == ["P1"] and c.key == "10|2026-09-22"
    assert _names(c.pagos[0]) == {"10": ["a.pdf"]}
    assert c.pagos[0].credit_items[0]["extracto_pdf_paths"] == p.credit_items[0]["extracto_pdf_paths"]


def test_247_two_dates_two_consolidados_each_asiento_once():
    abono = _pago(
        "P-ABONO",
        [_row("247", tipo="ABONO A CAPITAL", monto=100_000_000, fecha=date(2026, 9, 22), cliente="RUEDA")],
        [_item("247", "4634.pdf", "4635.pdf", "4638.pdf")],
    )
    cuota = _pago(
        "P-CUOTA",
        [_row("247", tipo="PAGO CUOTA", monto=26_950_278, fecha=date(2026, 9, 25), cliente="RUEDA")],
        [_item("247", "4634.pdf", "4635.pdf", "4638.pdf")],
    )
    (grupo,) = agrupar_pagos([abono, cuota])
    assert grupo.needs_asiento_dates is True
    assert len(asientos_del_grupo(grupo)) == 3
    f = _folder("247").casefold()
    destinos = {f"{f}/4634.pdf": "P-ABONO", f"{f}/4635.pdf": "P-CUOTA", f"{f}/4638.pdf": "P-CUOTA"}
    c22, c25 = repartir(grupo, destinos)
    assert (c22.fecha, c22.id_pagos, _names(c22.pagos[0])) == ("2026-09-22", ["P-ABONO"], {"247": ["4634.pdf"]})
    assert (c25.fecha, c25.id_pagos, _names(c25.pagos[0])) == (
        "2026-09-25",
        ["P-CUOTA"],
        {"247": ["4635.pdf", "4638.pdf"]},
    )


def test_pago_and_abono_same_date_single_consolidado_asientos_on_pago():
    abono = _pago(
        "A1",
        [_row("247", tipo="ABONO A CAPITAL", monto=100, fecha=date(2026, 9, 25))],
        [_item("247", "x.pdf", "y.pdf")],
    )
    cuota = _pago(
        "B1",
        [_row("247", tipo="PAGO CUOTA", monto=50, fecha=date(2026, 9, 25))],
        [_item("247", "x.pdf", "y.pdf")],
    )
    (grupo,) = agrupar_pagos([abono, cuota])
    assert grupo.needs_asiento_dates is False
    (c,) = repartir(grupo, destinos_una_fecha(grupo))
    assert c.id_pagos == ["A1", "B1"]
    by_id = {p.id_pago: _names(p) for p in c.pagos}
    assert by_id == {"A1": {"247": []}, "B1": {"247": ["x.pdf", "y.pdf"]}}
    tipos = [r["tipo_aplicacion_original"] for p in c.pagos for r in p.rows]
    assert consolidado_tipo(tipos) == "PAGO CUOTA Y ABONO A CAPITAL"


def test_jasp_one_payment_two_credits_one_consolidado():
    rows = [
        _row("102", tipo="PAGO TOTAL", monto=105_000_000, fecha=date(2026, 9, 9), cliente="GRUPO EMPRESARIAL JASP"),
        _row("133", tipo="PAGO TOTAL", monto=105_000_000, fecha=date(2026, 9, 9), cliente="GRUPO EMPRESARIAL JASP"),
    ]
    p = _pago("J1", rows, [_item("102", "a102.pdf"), _item("133", "a133.pdf")])
    (grupo,) = agrupar_pagos([p])
    assert grupo.key == "102+133"
    (c,) = repartir(grupo, destinos_una_fecha(grupo))
    assert _names(c.pagos[0]) == {"102": ["a102.pdf"], "133": ["a133.pdf"]}


def test_transp_linked_credits_across_payments_form_one_group():
    p1 = _pago(
        "T1",
        [
            _row("95", tipo="PAGO CUOTA", monto=10, fecha=date(2026, 9, 10), cliente="TRANSP"),
            _row("194", tipo="PAGO CUOTA", monto=10, fecha=date(2026, 9, 10), cliente="TRANSP"),
        ],
        [_item("95", "a95.pdf"), _item("194", "a194.pdf")],
    )
    p2 = _pago("T2", [_row("194", tipo="PAGO CUOTA", monto=5, fecha=date(2026, 9, 10), cliente="TRANSP")], [_item("194", "a194.pdf")])
    other = _pago("O1", [_row("7", tipo="PAGO CUOTA", monto=1, fecha=date(2026, 9, 10))], [_item("7", "a7.pdf")])
    grupos = agrupar_pagos([p1, p2, other])
    assert [g.key for g in grupos] == ["95+194", "7"]
    (c,) = repartir(grupos[0], destinos_una_fecha(grupos[0]))
    assert {p.id_pago: _names(p) for p in c.pagos} == {
        "T1": {"95": ["a95.pdf"], "194": ["a194.pdf"]},
        "T2": {"194": []},
    }


def test_322_four_payments_same_date_share_asientos_once():
    pagos = [
        _pago(
            f"P{i}",
            [_row("322", tipo="PAGO CUOTA", monto=1_000, fecha=date(2026, 9, 24))],
            [_item("322", "a.pdf", "b.pdf")],
        )
        for i in range(1, 5)
    ]
    (grupo,) = agrupar_pagos(pagos)
    (c,) = repartir(grupo, destinos_una_fecha(grupo))
    total = [n for p in c.pagos for names in _names(p).values() for n in names]
    assert sorted(total) == ["a.pdf", "b.pdf"]
