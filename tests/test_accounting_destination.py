"""Pruebas del destino contable del PDF consolidado (sitio HBI Capital Contabilidad)."""

from __future__ import annotations

import asyncio
from datetime import date
from typing import Any
from urllib.parse import unquote

import pytest

from app.application.config.payment_validation_settings import (
    BANK_CODE_BANCOLOMBIA,
    BANK_CODE_BOGOTA,
)
from app.application.services.accounting_destination import (
    ERROR_BANK_FOLDER_AMBIGUOUS,
    ERROR_BANK_FOLDER_NOT_FOUND,
    AccountingDestinationError,
    AccountingDestinationResolver,
    build_accounting_month_segments,
    resolve_accounting_bank_folder_name,
)


class _AccountingGraph:
    """Simula el drive de Contabilidad con un árbol de carpetas en memoria."""

    def __init__(self, tree: dict[str, list[str]]) -> None:
        self.tree = {k: list(v) for k, v in tree.items()}
        self.created: list[str] = []
        self.list_calls: list[str] = []

    @staticmethod
    def _path_from_endpoint(endpoint: str) -> str:
        if "/root:/" in endpoint:
            raw = endpoint.split("/root:/", 1)[1].rsplit(":/", 1)[0]
            return unquote(raw)
        return ""

    async def get(self, endpoint: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        path = self._path_from_endpoint(endpoint)
        self.list_calls.append(path)
        names = self.tree.get(path, [])
        return {"value": [{"name": n, "folder": {}} for n in names]}

    async def post_json(self, endpoint: str, body: dict[str, Any]) -> tuple[dict[str, Any], int]:
        path = self._path_from_endpoint(endpoint)
        name = str(body["name"])
        self.tree.setdefault(path, []).append(name)
        full = f"{path}/{name}" if path else name
        self.tree.setdefault(full, [])
        self.created.append(full)
        return {"id": "new"}, 201


def _resolver(tree: dict[str, list[str]]) -> tuple[_AccountingGraph, AccountingDestinationResolver]:
    graph = _AccountingGraph(tree)
    return graph, AccountingDestinationResolver(graph, "site", "drive")


def test_month_segments_use_spanish_month_names() -> None:
    assert build_accounting_month_segments(date(2026, 7, 22)) == (
        "2026",
        "TESORERIA 2026",
        "07 JULIO",
    )
    assert build_accounting_month_segments(date(2026, 1, 5))[2] == "01 ENERO"
    assert build_accounting_month_segments(date(2026, 12, 31))[2] == "12 DICIEMBRE"


def test_default_bank_folder_names_match_sharepoint() -> None:
    assert resolve_accounting_bank_folder_name(BANK_CODE_BOGOTA) == "INGRESOS BANCO BOGOTA"
    assert (
        resolve_accounting_bank_folder_name(BANK_CODE_BANCOLOMBIA)
        == "INGRESOS PA BANCOLOMBIA"
    )


def test_bank_folder_name_is_overridable(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GRAPH_ACCOUNTING_BOGOTA_FOLDER_NAME", "INGRESOS BOGOTA 2026")
    assert resolve_accounting_bank_folder_name(BANK_CODE_BOGOTA) == "INGRESOS BOGOTA 2026"


def test_resolves_existing_chain_without_creating_anything() -> None:
    graph, resolver = _resolver(
        {
            "": ["2026", "2025"],
            "2026": ["TESORERIA 2026", "FACTURACION 2026"],
            "2026/TESORERIA 2026": ["07 JULIO", "06 JUNIO"],
            "2026/TESORERIA 2026/07 JULIO": [
                "INGRESOS BANCO BOGOTA",
                "INGRESOS PA BANCOLOMBIA",
                "DESEMBOLSOS",
            ],
        }
    )
    folder = asyncio.run(resolver.resolve_folder(date(2026, 7, 22), BANK_CODE_BOGOTA))
    assert folder == "2026/TESORERIA 2026/07 JULIO/INGRESOS BANCO BOGOTA"
    assert graph.created == []


def test_creates_missing_month_but_not_the_bank_folder() -> None:
    graph, resolver = _resolver(
        {
            "": ["2026"],
            "2026": ["TESORERIA 2026"],
            "2026/TESORERIA 2026": ["07 JULIO"],
        }
    )
    with pytest.raises(AccountingDestinationError) as err:
        asyncio.run(resolver.resolve_folder(date(2026, 8, 3), BANK_CODE_BOGOTA))

    assert err.value.code == ERROR_BANK_FOLDER_NOT_FOUND
    assert "2026/TESORERIA 2026/08 AGOSTO" in graph.created
    assert "INGRESOS BANCO BOGOTA" in err.value.message


def test_creates_year_and_tesoreria_on_rollover() -> None:
    graph, resolver = _resolver({"": ["2026"]})
    with pytest.raises(AccountingDestinationError):
        asyncio.run(resolver.resolve_folder(date(2027, 1, 9), BANK_CODE_BOGOTA))

    assert graph.created[:3] == [
        "2027",
        "2027/TESORERIA 2027",
        "2027/TESORERIA 2027/01 ENERO",
    ]


def test_reuses_folders_with_different_accents_or_case() -> None:
    graph, resolver = _resolver(
        {
            "": ["2026"],
            "2026": ["Tesorería 2026"],
            "2026/Tesorería 2026": ["07 Julio"],
            "2026/Tesorería 2026/07 Julio": ["Ingresos Banco Bogotá"],
        }
    )
    folder = asyncio.run(resolver.resolve_folder(date(2026, 7, 22), BANK_CODE_BOGOTA))
    assert folder == "2026/Tesorería 2026/07 Julio/Ingresos Banco Bogotá"
    assert graph.created == []


def test_reports_ambiguity_instead_of_guessing() -> None:
    _graph, resolver = _resolver(
        {
            "": ["2026"],
            "2026": ["TESORERIA 2026"],
            "2026/TESORERIA 2026": ["07 JULIO"],
            "2026/TESORERIA 2026/07 JULIO": [
                "Ingresos Banco Bogota",
                "INGRESOS  BANCO  BOGOTA",
            ],
        }
    )
    with pytest.raises(AccountingDestinationError) as err:
        asyncio.run(resolver.resolve_folder(date(2026, 7, 22), BANK_CODE_BOGOTA))
    assert err.value.code == ERROR_BANK_FOLDER_AMBIGUOUS


def test_resolution_is_cached_across_payments() -> None:
    graph, resolver = _resolver(
        {
            "": ["2026"],
            "2026": ["TESORERIA 2026"],
            "2026/TESORERIA 2026": ["07 JULIO"],
            "2026/TESORERIA 2026/07 JULIO": ["INGRESOS BANCO BOGOTA"],
        }
    )

    async def run() -> None:
        for _ in range(5):
            await resolver.resolve_folder(date(2026, 7, 22), BANK_CODE_BOGOTA)

    asyncio.run(run())
    # Cuatro niveles resueltos una sola vez, sin importar cuántos pagos se procesen.
    assert len(graph.list_calls) == 4


def test_payments_in_different_months_go_to_their_own_folder() -> None:
    _graph, resolver = _resolver(
        {
            "": ["2026"],
            "2026": ["TESORERIA 2026"],
            "2026/TESORERIA 2026": ["06 JUNIO", "07 JULIO"],
            "2026/TESORERIA 2026/06 JUNIO": ["INGRESOS BANCO BOGOTA"],
            "2026/TESORERIA 2026/07 JULIO": ["INGRESOS BANCO BOGOTA"],
        }
    )

    async def run() -> tuple[str, str]:
        junio = await resolver.resolve_folder(date(2026, 6, 30), BANK_CODE_BOGOTA)
        julio = await resolver.resolve_folder(date(2026, 7, 1), BANK_CODE_BOGOTA)
        return junio, julio

    junio, julio = asyncio.run(run())
    assert junio.endswith("06 JUNIO/INGRESOS BANCO BOGOTA")
    assert julio.endswith("07 JULIO/INGRESOS BANCO BOGOTA")
