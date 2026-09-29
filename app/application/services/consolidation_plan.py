"""Consolidados de fase 3: un PDF por (grupo de créditos vinculados, fecha de pago).

Módulo puro (sin Graph). Agrupa los ID Pago validados con la misma regla que
«Verificar» y la fase 4 (pagos que comparten crédito), reparte cada asiento a un solo
pago y nombra cada PDF ``{DD} {MES} {TIPO} {CLIENTE} CRED {n}[ Y {m}]``:

* TIPO combina las partes de los tipos del consolidado en orden fijo ABONO A CUOTAS EN
  MORA, PAGO CUOTA, ABONO A CAPITAL, unidas con «Y»; PAGO TOTAL prevalece.
* La fecha es la Fecha banco de los pagos del consolidado (nunca la del proceso).
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field, replace
from datetime import date
from typing import Any, Iterable

from app.application.services.amortization_decisions import credit_token
from app.application.services.merge_verification import (
    _Payment,
    build_payments,
    group_key_of,
    group_needs_asiento_dates,
    group_payments,
    single_date_target,
)
from app.application.services.review_schema import (
    TipoAplicacion,
    TipoAplicacionConfirmado,
    normalize_tipo_aplicacion_confirmado,
)
from app.application.use_cases.merge_composite_validado_pdfs import (
    _MESES_ES,
    normalize_sharepoint_path,
)

MANIFEST_VERSION_CONSOLIDADOS = 2

_MORA = "ABONO A CUOTAS EN MORA"
_CUOTA = "PAGO CUOTA"
_CAPITAL = "ABONO A CAPITAL"
_TOTAL = "PAGO TOTAL"
_PARTS_ORDER = (_MORA, _CUOTA, _CAPITAL)

_T = TipoAplicacionConfirmado
_PARTS_BY_TIPO: dict[str, frozenset[str]] = {
    _T.PAGO_OBLIGACION_ACTUAL: frozenset({_CUOTA}),
    _T.PAGO_PARCIAL_OBLIGACION_ACTUAL: frozenset({_CUOTA}),
    _T.APLICACION_SALDO_VENCIDO: frozenset({_MORA}),
    _T.PAGO_COMBINADO: frozenset({_MORA, _CUOTA}),
    _T.PAGO_Y_ABONO_CAPITAL: frozenset({_CUOTA, _CAPITAL}),
    _T.PAGO_COMBINADO_Y_ABONO_CAPITAL: frozenset({_MORA, _CUOTA, _CAPITAL}),
    _T.ABONO_A_CAPITAL: frozenset({_CAPITAL}),
    _T.CANCELACION_PAGO_TOTAL: frozenset({_TOTAL}),
    _T.SALDO_VENCIDO_Y_ABONO_CAPITAL: frozenset({_MORA, _CAPITAL}),
}

_RE_UNSAFE = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


# --- nombre -------------------------------------------------------------------------


def consolidado_tipo(tipos: Iterable[Any], *, familias: Iterable[str] = ()) -> str:
    """TIPO del nombre a partir de los tipos confirmados (ya corregidos en fase 3)."""
    parts: set[str] = set()
    for raw in tipos:
        parts |= _PARTS_BY_TIPO.get(normalize_tipo_aplicacion_confirmado(raw), frozenset())
    if _TOTAL in parts:
        return _TOTAL
    label = " Y ".join(p for p in _PARTS_ORDER if p in parts)
    if label:
        return label
    fams = {str(f or "").strip().upper() for f in familias} - {""}
    return _CAPITAL if fams == {TipoAplicacion.ABONO.value} else _CUOTA


def _credit_sort(tok: str) -> tuple[int, int | str]:
    return (0, int(tok)) if tok.isdigit() else (1, tok)


def credits_phrase(credits: Iterable[Any]) -> str:
    """``CRED 247`` · ``CRED 102 Y 133`` · ``CRED 10, 20 Y 30``."""
    toks = sorted({str(c).strip() for c in credits} - {""}, key=_credit_sort)
    if not toks:
        return "CRED SIN CREDITO"
    if len(toks) == 1:
        return f"CRED {toks[0]}"
    return f"CRED {', '.join(toks[:-1])} Y {toks[-1]}"


def _client_text(cliente: str) -> str:
    return re.sub(r"\s+", " ", _RE_UNSAFE.sub(" ", str(cliente or ""))).strip().strip(".")


def consolidado_basename(fecha: date, tipo: str, cliente: str, credits: Iterable[Any]) -> str:
    cli = _client_text(cliente) or "CLIENTE"
    return f"{fecha.day:02d} {_MESES_ES[fecha.month - 1]} {tipo} {cli} {credits_phrase(credits)}.pdf"


def allocate_consolidado_name(base: str, taken: set[str]) -> str:
    """Nombre libre dentro de la corrida: el segundo igual queda «… (2).pdf»."""
    stem, ext = (base[:-4], base[-4:]) if base.lower().endswith(".pdf") else (base, "")
    candidate = base
    n = 1
    while candidate.casefold() in taken:
        n += 1
        candidate = f"{stem} ({n}){ext}"
    taken.add(candidate.casefold())
    return candidate


# --- grupos y reparto de asientos ----------------------------------------------------


def _norm(path: str) -> str:
    return normalize_sharepoint_path(path) or str(path or "").strip().strip("/").casefold()


@dataclass
class PagoPreparado:
    """ID Pago ya prevalidado (asientos por carpeta de crédito y extractos)."""

    id_pago: str
    familia: str
    rows: list[dict[str, Any]]
    credit_items: list[dict[str, Any]]
    pre_skips: list[str] = field(default_factory=list)


@dataclass
class GrupoPagos:
    key: str
    pagos: list[PagoPreparado]
    payments: list[_Payment]

    @property
    def needs_asiento_dates(self) -> bool:
        return group_needs_asiento_dates(self.payments)

    def fecha_of(self, id_pago: str) -> str:
        return next((p.fecha for p in self.payments if p.id_pago == id_pago), "")


@dataclass
class Consolidado:
    group_key: str
    fecha: str
    pagos: list[PagoPreparado]

    @property
    def key(self) -> str:
        return f"{self.group_key}|{self.fecha}"

    @property
    def id_pagos(self) -> list[str]:
        return [p.id_pago for p in self.pagos]


def agrupar_pagos(pagos: list[PagoPreparado]) -> list[GrupoPagos]:
    """Grupos de ID Pago que comparten crédito, en el orden de ``pagos``."""
    payments = build_payments([(p.id_pago, p.familia, p.rows) for p in pagos])
    by_id = {p.id_pago: p for p in pagos}
    return [
        GrupoPagos(key=group_key_of(grp), pagos=[by_id[x.id_pago] for x in grp], payments=grp)
        for grp in group_payments(payments)
    ]


def asientos_del_grupo(grupo: GrupoPagos) -> list[tuple[str, str]]:
    """(crédito, ruta) de cada asiento del grupo, una sola vez (primer crédito que lo lista)."""
    seen: set[str] = set()
    out: list[tuple[str, str]] = []
    for pago in grupo.pagos:
        for ci in pago.credit_items:
            tok = credit_token(ci.get("credito"))
            for raw in ci.get("asiento_pdf_paths") or []:
                key = _norm(str(raw))
                if key and key not in seen:
                    seen.add(key)
                    out.append((tok, str(raw)))
    return out


def _first_pago_listing(grupo: GrupoPagos, key: str) -> str:
    for pago in grupo.pagos:
        for ci in pago.credit_items:
            if any(_norm(str(p)) == key for p in ci.get("asiento_pdf_paths") or []):
                return pago.id_pago
    return ""


def destinos_una_fecha(grupo: GrupoPagos) -> dict[str, str]:
    """Asiento → ID Pago cuando cada crédito tiene pagos de una sola fecha.

    Mismo pago que elige la fase 4: el de la familia PAGO si en esa fecha hay PAGO y ABONO.
    """
    out: dict[str, str] = {}
    for tok, raw in asientos_del_grupo(grupo):
        key = _norm(raw)
        out[key] = single_date_target(grupo.payments, tok) or _first_pago_listing(grupo, key)
    return out


def repartir(grupo: GrupoPagos, destinos: dict[str, str]) -> list[Consolidado]:
    """Un consolidado por fecha de pago; cada asiento queda solo en el pago asignado.

    ``destinos``: ruta normalizada → ID Pago. Los ``credit_items`` de cada pago conservan
    todos sus créditos (aunque queden sin asientos) para que la fase 4 vea el pago completo.
    """
    owner = {_norm(raw): tok for tok, raw in asientos_del_grupo(grupo)}
    by_fecha: dict[str, list[PagoPreparado]] = {}
    for pago in grupo.pagos:
        items: list[dict[str, Any]] = []
        for ci in pago.credit_items:
            tok = credit_token(ci.get("credito"))
            kept = [
                str(p)
                for p in ci.get("asiento_pdf_paths") or []
                if destinos.get(_norm(str(p))) == pago.id_pago and owner.get(_norm(str(p))) == tok
            ]
            new = dict(ci)
            new["asiento_pdf_paths"] = kept
            new.pop("asiento_pdf_path", None)
            items.append(new)
        by_fecha.setdefault(grupo.fecha_of(pago.id_pago), []).append(replace(pago, credit_items=items))
    return [Consolidado(grupo.key, fecha, ps) for fecha, ps in sorted(by_fecha.items())]


__all__ = [
    "MANIFEST_VERSION_CONSOLIDADOS",
    "Consolidado",
    "GrupoPagos",
    "PagoPreparado",
    "agrupar_pagos",
    "allocate_consolidado_name",
    "asientos_del_grupo",
    "consolidado_basename",
    "consolidado_tipo",
    "credits_phrase",
    "destinos_una_fecha",
    "repartir",
]
