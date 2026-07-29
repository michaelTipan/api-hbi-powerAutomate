"""Helpers de webUrl de carpeta/archivo consolidado (Flujo 3 / correo PA)."""

from __future__ import annotations

import asyncio

from app.application.use_cases.merge_composite_validado_pdfs import (
    MergeCompositePdfOutput,
    _consolidation_folder_from_manifest,
    _first_consolidation_folder_from_outputs,
    _http_url_only,
    _parent_folder_relative_path,
    _resolve_merge_output_share_links,
)


def test_parent_folder_and_http_url_helpers():
    assert (
        _parent_folder_relative_path(
            "06 ASIENTO CONTABLES GENERADOS/28 JULIO BANCO.pdf"
        )
        == "06 ASIENTO CONTABLES GENERADOS"
    )
    assert _parent_folder_relative_path("solo.pdf") == ""
    assert _http_url_only("https://contoso/x") == "https://contoso/x"
    assert _http_url_only("ruta/sin/url") == ""


def test_first_consolidation_folder_from_outputs_and_manifest():
    outs = [
        MergeCompositePdfOutput(
            id_pago="1",
            output_relative_path="OUT/a.pdf",
            bytes_written=1,
            sources_summary="x",
            output_folder_web_url="https://sp/OUT",
            output_folder_relative_path="OUT",
        )
    ]
    assert _first_consolidation_folder_from_outputs(outs) == ("https://sp/OUT", "OUT")
    assert _consolidation_folder_from_manifest(
        {
            "outputs": [
                {
                    "output_relative_path": "OUT/a.pdf",
                    "output_folder_web_url": "https://sp/OUT",
                }
            ]
        }
    ) == ("https://sp/OUT", "OUT")


def test_resolve_merge_output_share_links_uses_put_response_and_folder_get():
    class G:
        async def get(self, endpoint: str, params=None):
            assert "06 ASIENTO" in endpoint or "ASIENTO" in endpoint
            return {"webUrl": "https://sharepoint.test/folder"}

    async def run():
        file_url, folder_url, folder_rel = await _resolve_merge_output_share_links(
            G(),
            "s1",
            "d1",
            output_relative_path="06 ASIENTO CONTABLES GENERADOS/file.pdf",
            upload_response={"webUrl": "https://sharepoint.test/folder/file.pdf"},
        )
        assert file_url == "https://sharepoint.test/folder/file.pdf"
        assert folder_url == "https://sharepoint.test/folder"
        assert folder_rel == "06 ASIENTO CONTABLES GENERADOS"

    asyncio.run(run())
