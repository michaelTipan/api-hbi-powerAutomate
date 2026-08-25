"""Generate: omitir carpetas CREDITO # sin extracto ni tabla (dormant)."""
from __future__ import annotations

import asyncio

from app.application.use_cases.payment_validation_generate import (
    _discover_operational_credit_units,
)


class _EmptyChildrenGraph:
    async def get(self, endpoint: str, params=None):
        return {"value": []}


class _ChildrenByPathGraph:
    def __init__(self, by_path: dict[str, list[dict]]):
        self.by_path = by_path

    async def get(self, endpoint: str, params=None):
        # .../root:/{encoded_path}:/children
        if ":/children" not in endpoint:
            return {"value": []}
        path = endpoint.split("/root:/", 1)[1].rsplit(":/children", 1)[0]
        from urllib.parse import unquote

        path = unquote(path)
        return {"value": list(self.by_path.get(path, []))}


def test_discover_skips_standard_folder_without_extract_or_table():
    async def run():
        units, skipped_terminal, skipped_dormant = await _discover_operational_credit_units(
            _EmptyChildrenGraph(),
            "site",
            "drive",
            "clientes/CONSTRUMAQUINAS",
            "CONSTRUMAQUINAS",
            [
                {"name": "CREDITO # 335", "folder": {}, "webUrl": "https://sp/335"},
                {"name": "CREDITO # 347", "folder": {}, "webUrl": "https://sp/347"},
            ],
        )
        assert units == []
        assert skipped_terminal is False
        assert skipped_dormant is True

    asyncio.run(run())


def test_discover_keeps_standard_folder_with_amortization_table():
    async def run():
        client = _ChildrenByPathGraph(
            {
                "clientes/FOO/CREDITO # 100": [
                    {
                        "name": "Tabla de amortizacion FOO.xlsx",
                        "file": {},
                        "webUrl": "https://sp/tabla",
                    }
                ]
            }
        )
        units, skipped_terminal, skipped_dormant = await _discover_operational_credit_units(
            client,
            "site",
            "drive",
            "clientes/FOO",
            "FOO",
            [{"name": "CREDITO # 100", "folder": {}, "webUrl": "https://sp/100"}],
        )
        assert skipped_terminal is False
        assert skipped_dormant is False
        assert len(units) == 1
        assert units[0][0] == "CREDITO # 100"

    asyncio.run(run())


def test_discover_terminal_still_skipped_and_flagged():
    async def run():
        units, skipped_terminal, skipped_dormant = await _discover_operational_credit_units(
            _EmptyChildrenGraph(),
            "site",
            "drive",
            "clientes/FOO",
            "FOO",
            [{"name": "CREDITO # 50 PAGADO", "folder": {}}],
        )
        assert units == []
        assert skipped_terminal is True
        assert skipped_dormant is False

    asyncio.run(run())


def test_discover_mix_dormant_and_active():
    async def run():
        client = _ChildrenByPathGraph(
            {
                "clientes/FOO/CREDITO # 1": [],
                "clientes/FOO/CREDITO # 2": [
                    {
                        "name": "Extracto Julio CRED 2.pdf",
                        "file": {},
                        "webUrl": "https://sp/ex",
                    }
                ],
            }
        )
        units, skipped_terminal, skipped_dormant = await _discover_operational_credit_units(
            client,
            "site",
            "drive",
            "clientes/FOO",
            "FOO",
            [
                {"name": "CREDITO # 1", "folder": {}},
                {"name": "CREDITO # 2", "folder": {}},
            ],
        )
        assert skipped_dormant is True
        assert skipped_terminal is False
        assert [u[0] for u in units] == ["CREDITO # 2"]

    asyncio.run(run())
