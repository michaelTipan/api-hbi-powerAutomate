"""PDF de correo Notify: cabecera de tabla con letras blancas (paridad HTML)."""

from __future__ import annotations

from datetime import datetime, timezone
from io import BytesIO

from pypdf import PdfReader
from reportlab.lib import colors

from app.application.use_cases.send_validar_extractos_notification import (
    _cover_pdf_bytes_reportlab,
)


def test_cover_pdf_builds_and_includes_table_headers() -> None:
    pdf = _cover_pdf_bytes_reportlab(
        sender="victor.herrera@hbicapital.com.co",
        sent_at=datetime(2026, 8, 4, 22, 37, tzinfo=timezone.utc),
        to_addr="ops@example.com",
        cc_list=[],
        subject="ABONOS BANCO BANCOLOMBIA",
        attachment_names=["Extracto Abril.pdf"],
        body_intro=(
            "Buen día. El día 23/04/2026 ingresaron a la cuenta "
            "BANCO BANCOLOMBIA los siguientes valores, que corresponden a:"
        ),
        bank_headers=["Fecha", "Crédito", "Concepto", "Tipo Aplicación", "Transacción"],
        bank_rows=[
            [
                "23/04/2026",
                "$50.000.000,00",
                "EQUINORTE",
                "PAGO",
                "Cr Ach Bancolombia",
            ]
        ],
    )
    assert pdf.startswith(b"%PDF")
    text = "".join((p.extract_text() or "") for p in PdfReader(BytesIO(pdf)).pages)
    assert "Fecha" in text
    assert "Tipo Aplicación" in text or "Tipo Aplicacion" in text
    assert "EQUINORTE" in text


def test_cover_pdf_header_paragraph_style_is_white(monkeypatch) -> None:
    """Regression: Paragraph Normal (negro) anulaba TEXTCOLOR del TableStyle."""
    from reportlab.platypus import Paragraph as RealParagraph

    captured: list[colors.Color] = []

    def _spy(text, style, *args, **kwargs):  # type: ignore[no-untyped-def]
        raw = str(text)
        if raw.startswith("<b>") and any(
            h in raw for h in ("Fecha", "Crédito", "Concepto", "Tipo", "Transacción")
        ):
            captured.append(style.textColor)
        return RealParagraph(text, style, *args, **kwargs)

    monkeypatch.setattr("reportlab.platypus.Paragraph", _spy)

    _cover_pdf_bytes_reportlab(
        sender="a@b.com",
        sent_at=datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc),
        to_addr="c@d.com",
        cc_list=[],
        subject="T",
        attachment_names=[],
        body_intro="Buen día. Texto.",
        bank_headers=["Fecha", "Crédito", "Concepto", "Tipo Aplicación", "Transacción"],
        bank_rows=[["01/01/2026", "$1", "X", "PAGO", "tx"]],
    )
    assert captured, "no se capturaron Paragraphs de cabecera"
    for color in captured:
        assert color == colors.white or (
            getattr(color, "red", None) == 1
            and getattr(color, "green", None) == 1
            and getattr(color, "blue", None) == 1
        )
