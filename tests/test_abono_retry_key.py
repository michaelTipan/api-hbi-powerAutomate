"""ABONO ya aplicado: la clave del log incluye comprobante y huella del PDF.

Antes de descargar el asiento solo se conoce la clave sin huella; el reconocimiento
debe aceptar la clave completa registrada por Apply (sin confundir eventos).
"""

from __future__ import annotations

from decimal import Decimal

from app.application.services.abono_dry_run import _find_applied_abono_for_retry
from app.application.services.applied_abono_events import (
    APPLIED_ABONO_EVENT_AMBIGUOUS,
    AppliedAbonoEventSnapshot,
)
from app.application.services.amortization_workbook import build_amortization_idempotency_key

ID_PAGO = "p-1"
CREDITO = "CREDITO # 151"
ASIENTO = "clientes/X/CREDITO # 151/ASIENTOS CONTABLES CRED 151/abono.pdf"


def _snap(key: str, *, row: int = 25, log_row: int = 2) -> AppliedAbonoEventSnapshot:
    return AppliedAbonoEventSnapshot(
        idempotency_key=key,
        id_pago=ID_PAGO,
        credito=CREDITO,
        asiento_pdf_path=ASIENTO,
        asiento_pdf_hash="abc123",
        application_row=row,
        accion="APLICADO",
        tipo_aplicacion="ABONO A CAPITAL",
        valor_pagado_cliente=Decimal("1000"),
        log_row=log_row,
    )


def _legacy_key() -> str:
    return build_amortization_idempotency_key(ID_PAGO, CREDITO, ASIENTO, "")


def _full_key(comprobante: str = "77", pdf_hash: str = "abc123") -> str:
    return build_amortization_idempotency_key(ID_PAGO, CREDITO, ASIENTO, comprobante, pdf_hash=pdf_hash)


def _find(snapshots):
    return _find_applied_abono_for_retry(
        snapshots,
        id_pago=ID_PAGO,
        credito=CREDITO,
        asiento_pdf_path=ASIENTO,
        legacy_idempotency_key=_legacy_key(),
    )


def test_clave_completa_con_huella_se_reconoce_antes_de_descargar_el_asiento():
    snap = _snap(_full_key())
    match, err = _find([snap])
    assert err is None
    assert match is snap


def test_clave_historica_sin_huella_sigue_reconociendose():
    snap = _snap(_legacy_key())
    match, err = _find([snap])
    assert err is None
    assert match is snap


def test_dos_eventos_distintos_del_mismo_asiento_son_ambiguos():
    snaps = [_snap(_full_key("77"), row=25, log_row=2), _snap(_full_key("78"), row=26, log_row=3)]
    match, err = _find(snaps)
    assert match is None
    assert err == APPLIED_ABONO_EVENT_AMBIGUOUS


def test_otro_asiento_no_se_confunde():
    other = build_amortization_idempotency_key(ID_PAGO, CREDITO, ASIENTO + "x", "77", pdf_hash="h")
    match, err = _find([_snap(other)])
    assert match is None
    assert err is None
