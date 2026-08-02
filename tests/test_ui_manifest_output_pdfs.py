"""PDFs operativos desde outputs[] del manifest Merge (no el JSON técnico)."""
from __future__ import annotations

from app.application.ui.manifest_outputs import parse_manifest_output_pdfs


def test_parse_manifest_output_pdfs_all_entries_with_credito() -> None:
    refs = parse_manifest_output_pdfs(
        [
            {
                "id_pago": "p1",
                "credito": "265",
                "output_relative_path": "01 TRAZABILIDAD/a.pdf",
                "output_web_url": "https://sp.example/a.pdf",
            },
            {
                "id_pago": "p2",
                "creditos_seleccionados": ["310"],
                "output_relative_path": "01 TRAZABILIDAD/b.pdf",
            },
            {
                # Debe ignorarse: manifiesto JSON técnico.
                "output_relative_path": "01 TRAZABILIDAD/manifest.json",
            },
            {
                # Debe ignorarse: sin extensión .pdf.
                "output_relative_path": "01 TRAZABILIDAD/sin_extension",
            },
        ]
    )
    assert len(refs) == 2
    assert refs[0].path.endswith("a.pdf")
    assert refs[0].credito == "265"
    assert refs[0].web_url == "https://sp.example/a.pdf"
    assert refs[1].path.endswith("b.pdf")
    assert refs[1].credito == "310"
    assert refs[1].web_url is None


def test_parse_manifest_output_pdfs_dedupes_paths() -> None:
    refs = parse_manifest_output_pdfs(
        [
            {"credito": "1", "output_relative_path": "x/out.pdf"},
            {"credito": "2", "output_relative_path": "x/out.pdf"},
        ]
    )
    assert len(refs) == 1
    assert refs[0].credito == "1"


def test_parse_manifest_output_pdfs_only_pdf_extension() -> None:
    refs = parse_manifest_output_pdfs(
        [
            {"output_relative_path": "a.PDF"},
            {"output_relative_path": "b.xlsx"},
            {"output_relative_path": "c.json"},
        ]
    )
    assert [r.path for r in refs] == ["a.PDF"]
