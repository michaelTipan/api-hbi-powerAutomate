"""Generate neutro: banco sin Tipo Aplicación; workbook Aplicacion_Pagos v3."""

import asyncio
from datetime import date
from unittest import mock

import pytest

from app.application.services.review_schema import (
    AplicacionPagosCols,
    ErroresCols,
    ReviewSheets,
    ValidarPago,
)
from app.application.use_cases.payment_validation_generate import generate_payment_validation
from tests.test_generate_validation import (
    MockGraphClient,
    create_bank_excel,
    create_excel,
    load_generated_workbook,
    make_pdf_extractor_mock,
    set_env_vars,
    setup_client_structure,
    sheet_to_dicts,
)


def _fake_fecha_limite_from_marker_bytes():
    from datetime import date as date_cls

    def _fake(pdf_bytes: bytes):
        text = pdf_bytes.decode(errors="ignore")
        if "FECHA_LIMITE=" in text:
            raw = text.split("FECHA_LIMITE=", 1)[1].split(";", 1)[0].strip()
            return date_cls.fromisoformat(raw)
        return date_cls(2025, 12, 23)

    return _fake


def _run_with_pdf_mock(client):
    extractor = make_pdf_extractor_mock(client)
    return mock.patch(
        "app.application.use_cases.payment_validation_generate.extract_total_a_pagar_from_pdf",
        side_effect=extractor,
    ), mock.patch(
        "app.application.use_cases.payment_validation_generate.extract_fecha_limite_pago_from_pdf",
        side_effect=_fake_fecha_limite_from_marker_bytes(),
    )


def test_bank_without_tipo_aplicacion_generates_v3():
    async def _run():
        set_env_vars()
        client = MockGraphClient()
        client.children = []
        setup_client_structure(client)
        client.downloaded_files["banco.xlsx"] = create_bank_excel(
            [[date(2025, 12, 23), 25443565, "GEOEXCON", "tx-1"]],
        )
        with _run_with_pdf_mock(client)[0], _run_with_pdf_mock(client)[1]:
            result = await generate_payment_validation(client, date(2026, 5, 26), bank_code="banco_bogota")
        assert result["pagos_detectados"] >= 1
        wb = load_generated_workbook(client)
        assert ReviewSheets.APLICACION_PAGOS in wb.sheetnames
        rows = sheet_to_dicts(wb[ReviewSheets.APLICACION_PAGOS])
        assert rows
        assert all(r.get(AplicacionPagosCols.VALIDAR_PAGO) == ValidarPago.NO for r in rows)

    asyncio.run(_run())


def test_bank_legacy_tipo_column_is_ignored_not_required():
    """Si el Excel bancario aún trae la columna, Generate no la exige ni falla."""

    async def _run():
        set_env_vars()
        client = MockGraphClient()
        client.children = []
        setup_client_structure(client)
        client.downloaded_files["banco.xlsx"] = create_excel(
            ["Fecha", "Crédito", "Concepto", "Tipo Aplicación", "Transacción"],
            [[date(2025, 12, 23), 25443565, "GEOEXCON", "PAGO", "tx-1"]],
        )
        with _run_with_pdf_mock(client)[0], _run_with_pdf_mock(client)[1]:
            result = await generate_payment_validation(client, date(2026, 5, 26), bank_code="banco_bogota")
        assert result["distribution_payments_sheet"] == ReviewSheets.APLICACION_PAGOS

    asyncio.run(_run())


def test_generate_does_not_autoselect_validar_si():
    async def _run():
        set_env_vars()
        client = MockGraphClient()
        client.children = []
        setup_client_structure(client)
        client.downloaded_files["banco.xlsx"] = create_bank_excel(
            [[date(2025, 12, 23), 25443565, "GEOEXCON", "tx"]],
        )
        with _run_with_pdf_mock(client)[0], _run_with_pdf_mock(client)[1]:
            await generate_payment_validation(client, date(2026, 5, 26), bank_code="banco_bogota")
        wb = load_generated_workbook(client)
        rows = sheet_to_dicts(wb[ReviewSheets.APLICACION_PAGOS])
        assert rows
        assert ValidarPago.SI not in {r.get(AplicacionPagosCols.VALIDAR_PAGO) for r in rows}

    asyncio.run(_run())


def test_generate_skips_partida_identificar_and_still_flags_unknown_client():
    async def _run():
        set_env_vars()
        client = MockGraphClient()
        client.children = []
        setup_client_structure(client)
        client.downloaded_files["banco.xlsx"] = create_bank_excel(
            [
                [date(2025, 12, 23), 25443565, "GEOEXCON", "tx-ok"],
                [date(2025, 12, 23), 4_600_336, "Partida x identificar", "tx-gold"],
                [date(2025, 12, 23), 3_160_000, "Partida x identificar 1", "tx-gold-1"],
                [date(2025, 12, 23), 1_000_000, "ClienteInventadoTypo", "tx-typo"],
            ],
        )
        with _run_with_pdf_mock(client)[0], _run_with_pdf_mock(client)[1]:
            result = await generate_payment_validation(
                client, date(2026, 5, 26), bank_code="banco_bogota"
            )
        assert result["summary"]["errores"] >= 1
        wb = load_generated_workbook(client)
        aplicacion = sheet_to_dicts(wb[ReviewSheets.APLICACION_PAGOS])
        clientes = {str(r.get(AplicacionPagosCols.CLIENTE) or "") for r in aplicacion}
        joined = " ".join(clientes).lower()
        assert "geoexcon" in joined.lower() or any("GEOEXCON" in c for c in clientes)
        assert "identificar" not in joined.lower()
        errores = sheet_to_dicts(wb[ReviewSheets.ERRORES])
        error_blob = " ".join(
            str(r.get(ErroresCols.CLIENTE) or r.get("Cliente") or "")
            + " "
            + str(r.get(ErroresCols.CODIGO_TECNICO) or r.get("Código técnico") or "")
            for r in errores
        ).lower()
        assert "identificar" not in error_blob
        assert "clienteinventadotypo" in error_blob or "customer_not_found" in error_blob

    asyncio.run(_run())
