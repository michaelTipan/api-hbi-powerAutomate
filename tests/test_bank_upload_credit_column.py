"""Columna opcional «No. Crédito» del Excel de carga del banco."""

from __future__ import annotations

import asyncio
import io
from datetime import date, datetime
from unittest import mock

import openpyxl
import pytest

from app.application.job_status_enrichment import enrich_job_for_http_response
from app.application.services.bank_upload_columns import (
    BankUploadCreditColumnError,
    credit_cell_display,
    credit_column_error_copy,
    find_credit_number_column,
    is_credit_number_header,
    parse_credit_number_cell,
)
from app.application.services.review_schema import ErroresCols, ReviewSheets
from app.application.use_cases.payment_validation_generate import (
    _candidate_credit_number,
    _is_bank_header_row,
    _parse_bank_sheet_headers,
    announce_control_generate_failed,
    generate_payment_validation,
)
from app.application.use_cases.payment_validation_process_control import (
    parse_process_control_row2,
)
from app.application.use_cases.send_validar_extractos_notification import (
    _parse_bank_report_table_and_min_date,
)
from app.application.use_cases.setup_merge_control_workbook import (
    PROCESS_CONTROL_BANK_FILE_BOGOTA,
)
from tests.bank_upload_scenarios import (
    BASE_ROWS,
    PROCESS_DATE,
    build_bank_excel,
    load_golden,
    run_generate_snapshot,
)
from tests.test_cancel_process_control import (
    MockGraphClientCancel,
    _control_with_active_revision,
    _read_control_row,
)
from tests.test_generate_validation import (
    _fake_fecha_limite_from_marker_bytes,
    create_excel,
    make_item,
    make_pdf_extractor_mock,
    set_env_vars,
    setup_client_structure,
    setup_triple_credit_client,
    sheet_to_dicts,
)

HEADERS_WITH_CREDIT = ["Fecha", "Crédito", "Concepto", "Transacción", "No. Crédito"]


# ─── Parseo de la celda ──────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "raw,expected",
    [
        (None, ()),
        ("", ()),
        ("   ", ()),
        (247, (247,)),
        (247.0, (247,)),
        ("247", (247,)),
        (" 247 ", (247,)),
        ("#247", (247,)),
        ("# 247", (247,)),
        ("040", (40,)),
        ("247,248", (247, 248)),
        ("247, 248", (247, 248)),
        ("247;248", (247, 248)),
        ("247 / 248", (247, 248)),
        ("247 y 248", (247, 248)),
        ("247 Y 248", (247, 248)),
        ("247, 248 y 249", (247, 248, 249)),
        ("247, 247", (247,)),
        ("040 y 40", (40,)),
        ("247,", (247,)),
    ],
)
def test_parse_credit_number_cell_valid(raw, expected):
    assert parse_credit_number_cell(raw) == (expected, None)


@pytest.mark.parametrize(
    "raw,reason",
    [
        ("27a", "invalid"),
        ("247.248", "invalid"),
        ("247-248", "invalid"),
        ("247 248", "invalid"),
        ("247y248", "invalid"),
        (",", "invalid"),
        ("0", "invalid"),
        (0, "invalid"),
        (-5, "invalid"),
        (True, "invalid"),
        (datetime(2026, 9, 1), "invalid"),
        (247.248, "decimal"),
        (12.5, "decimal"),
        ("247, abc", "invalid"),
    ],
)
def test_parse_credit_number_cell_invalid(raw, reason):
    assert parse_credit_number_cell(raw) == ((), reason)


def test_credit_cell_display_uses_spanish_decimal_comma():
    assert credit_cell_display(247.248) == "247,248"
    assert credit_cell_display(247.0) == "247"
    assert credit_cell_display(" 27a ") == "27a"


def test_candidate_credit_number_normalizes_leading_zeros():
    assert _candidate_credit_number({"credito_normalizado": "040"}) == 40
    assert _candidate_credit_number({"credito": "CREDITO # 99 VIGENTE"}) == 99
    assert _candidate_credit_number({"credito": "GEOEXCON"}) is None


# ─── Encabezados: sin colisión con «Crédito» (monto) ─────────────────────────


@pytest.mark.parametrize(
    "header",
    [
        "No. Crédito",
        "No Crédito",
        "No.Crédito",
        "Nº Crédito",
        "N° Crédito",
        "Nro. Crédito",
        "Nro Crédito",
        "Número de crédito",
        "Numero credito",
        "NO. CREDITO",
        "No. de crédito",
    ],
)
def test_credit_number_header_variants(header):
    assert is_credit_number_header(header)


@pytest.mark.parametrize(
    "header", ["Crédito", "Credito", "CRÉDITO", "Monto", "Concepto", "Cliente", "Fecha", None, ""]
)
def test_credit_number_header_never_matches_amount_or_others(header):
    assert not is_credit_number_header(header)


def _sheet(headers, rows=()):
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(headers)
    for r in rows:
        ws.append(r)
    return ws


@pytest.mark.parametrize(
    "headers,expected_amount,expected_number",
    [
        (["Fecha", "No. Crédito", "Crédito", "Concepto", "Transacción"], 2, 1),
        (["Fecha", "Crédito", "Concepto", "Transacción", "Nº Crédito"], 1, 4),
        (["Fecha", "Número de crédito", "Monto", "Concepto"], 2, 1),
        (["Fecha", "Crédito", "Concepto", "Transacción"], 1, -1),
    ],
)
def test_generate_headers_amount_column_stays_exact(headers, expected_amount, expected_number):
    col_map, start_row, _, header_row = _parse_bank_sheet_headers(_sheet(headers))
    assert col_map["credito"] == expected_amount
    assert col_map["no_credito"] == expected_number
    assert header_row == 1 and start_row == 2
    assert find_credit_number_column(headers) == expected_number


def test_missing_bank_headers_is_rejected_before_touching_control():
    from app.application.services.bank_upload_columns import BankUploadInputError

    with pytest.raises(BankUploadInputError, match="^bank_headers_not_found$") as excinfo:
        _parse_bank_sheet_headers(_sheet(["Fecha", "Valor", "Concepto"]))
    assert excinfo.value.control_untouched is True


def test_header_row_with_only_credit_number_is_not_a_bank_header():
    # Sin «Crédito»/«Monto» exactos no hay fila de encabezados de banco.
    assert not _is_bank_header_row(["Fecha", "No. Crédito", "Concepto"])
    assert _is_bank_header_row(["Fecha", "No. Crédito", "Crédito", "Concepto"])


# ─── Regresión: sin la columna, Generate produce exactamente lo mismo ────────


@pytest.mark.parametrize("bank_code", ["banco_bogota", "banco_bancolombia"])
def test_generate_without_credit_column_matches_golden(bank_code):
    assert run_generate_snapshot(build_bank_excel(), bank_code=bank_code) == load_golden()[bank_code]


@pytest.mark.parametrize("bank_code", ["banco_bogota", "banco_bancolombia"])
def test_generate_with_empty_credit_column_matches_golden(bank_code):
    rows = [list(r) + [None] for r in BASE_ROWS]
    snap = run_generate_snapshot(build_bank_excel(HEADERS_WITH_CREDIT, rows), bank_code=bank_code)
    assert snap == load_golden()[bank_code]


# ─── Filtro por créditos pedidos ─────────────────────────────────────────────


def _run_generate_client(bank_bytes, *, setup=setup_client_structure, client=None):
    async def _run():
        set_env_vars()
        c = client or _MockClient()
        c.children = []
        setup(c)
        c.downloaded_files["banco.xlsx"] = bank_bytes
        with mock.patch(
            "app.application.use_cases.payment_validation_generate.extract_total_a_pagar_from_pdf",
            side_effect=make_pdf_extractor_mock(c),
        ), mock.patch(
            "app.application.use_cases.payment_validation_generate.extract_fecha_limite_pago_from_pdf",
            side_effect=_fake_fecha_limite_from_marker_bytes(),
        ):
            result = await generate_payment_validation(c, PROCESS_DATE, bank_code="banco_bogota")
        return c, result

    return asyncio.run(_run())


class _MockClient(MockGraphClientCancel):
    """Graph falso con escrituras persistentes (Control, revisión) y 404 reales."""


def _credits_by_payment(wb) -> list[tuple[str, str]]:
    rows = sheet_to_dicts(wb[ReviewSheets.APLICACION_PAGOS], marker="ID Pago")
    return [(str(r["Cliente"]), str(r["Crédito"])) for r in rows]


def _review_workbook(client):
    for path, blob in client.downloaded_files.items():
        if path.startswith("revision/") and path.endswith(".xlsx"):
            return openpyxl.load_workbook(io.BytesIO(blob))
    raise AssertionError("no se subió Excel de revisión")


def test_generate_filters_candidates_to_requested_credit():
    rows = [
        [datetime(2025, 12, 23), 18826879, "GEOEXCON", "PAGO", "231"],
        [datetime(2025, 12, 30), 5000000, "EQUINORTE", "PAGO", None],
    ]
    client, _ = _run_generate_client(build_bank_excel(HEADERS_WITH_CREDIT, rows))
    assert _credits_by_payment(_review_workbook(client)) == [
        ("GEOEXCON", "231"),
        ("EQUINORTE", "900"),
    ]


def test_generate_several_requested_credits_and_shared_cache():
    rows = [
        [datetime(2025, 12, 23), 6500739, "GEOEXCON", "PAGO", "254"],
        [datetime(2025, 12, 23), 18826879, "GEOEXCON", "PAGO", "231 y 254"],
        [datetime(2025, 12, 23), 100, "GEOEXCON", "PAGO", None],
    ]
    client, _ = _run_generate_client(build_bank_excel(HEADERS_WITH_CREDIT, rows))
    creditos = [c for _, c in _credits_by_payment(_review_workbook(client))]
    # Fila 1 solo 254; fila 2 ambos (orden de la carpeta); fila 3 sin filtro = todos.
    assert creditos == ["254", "254", "231", "254", "231"]


def test_generate_requested_credit_matches_leading_zero_folder():
    def _setup(c):
        setup_triple_credit_client(c, cliente="MULTICRED", credits=("040", "265", "270"))

    rows = [[datetime(2025, 12, 23), 100, "MULTICRED", "PAGO", 40]]
    client, _ = _run_generate_client(build_bank_excel(HEADERS_WITH_CREDIT, rows), setup=_setup)
    assert _credits_by_payment(_review_workbook(client)) == [("MULTICRED", "040")]


def _setup_with_broken_credit(c):
    setup_client_structure(c)
    c.folder_children["clientes/GEOEXCON"].append(make_item("300", is_folder=True))
    c.folder_children["clientes/GEOEXCON/300"] = [make_item("Tabla amortizacion GEOEXCON 300.xlsx")]
    c.downloaded_files["clientes/GEOEXCON/300/Tabla amortizacion GEOEXCON 300.xlsx"] = create_excel(
        ["Fecha límite", "Cuota"], [[date(2025, 12, 23), 10.0]]
    )


def _errores_creditos(wb) -> list[str]:
    rows = sheet_to_dicts(wb[ReviewSheets.ERRORES], marker=ErroresCols.ID_PAGO)
    return [str(r.get(ErroresCols.CREDITO) or "") for r in rows]


def test_errores_only_lists_requested_credits_issues():
    rows = [[datetime(2025, 12, 23), 6500739, "GEOEXCON", "PAGO", "254"]]
    client, _ = _run_generate_client(
        build_bank_excel(HEADERS_WITH_CREDIT, rows), setup=_setup_with_broken_credit
    )
    assert "300" not in _errores_creditos(_review_workbook(client))


def test_errores_without_filter_keeps_all_issues():
    rows = [[datetime(2025, 12, 23), 6500739, "GEOEXCON", "PAGO", None]]
    client, _ = _run_generate_client(
        build_bank_excel(HEADERS_WITH_CREDIT, rows), setup=_setup_with_broken_credit
    )
    assert "300" in _errores_creditos(_review_workbook(client))


def test_requested_credit_with_issue_is_not_reported_as_missing():
    rows = [[datetime(2025, 12, 23), 6500739, "GEOEXCON", "PAGO", "300"]]
    client, _ = _run_generate_client(
        build_bank_excel(HEADERS_WITH_CREDIT, rows), setup=_setup_with_broken_credit
    )
    assert "300" in _errores_creditos(_review_workbook(client))


def test_issue_filter_records_each_credit_once_across_rows():
    rows = [
        [datetime(2025, 12, 23), 6500739, "GEOEXCON", "PAGO", "254"],
        [datetime(2025, 12, 23), 10, "GEOEXCON", "PAGO", "300"],
        [datetime(2025, 12, 23), 11, "GEOEXCON", "PAGO", None],
    ]
    client, _ = _run_generate_client(
        build_bank_excel(HEADERS_WITH_CREDIT, rows), setup=_setup_with_broken_credit
    )
    assert _errores_creditos(_review_workbook(client)).count("300") == 1


def test_partida_por_identificar_ignores_credit_column():
    rows = [
        [datetime(2025, 12, 30), 1200000, "Partida x identificar", "", "27a"],
        [datetime(2025, 12, 30), 5000000, "EQUINORTE", "PAGO", None],
    ]
    client, _ = _run_generate_client(build_bank_excel(HEADERS_WITH_CREDIT, rows))
    assert _credits_by_payment(_review_workbook(client)) == [("EQUINORTE", "900")]


# ─── Formato inválido: nada cambia (Iniciar y Regenerar) ─────────────────────


def _control_writes(client) -> list[str]:
    out = []
    for endpoint, content in client.put_calls:
        if PROCESS_CONTROL_BANK_FILE_BOGOTA.split("/")[-1] not in endpoint.replace("%20", " "):
            continue
        snap = parse_process_control_row2(content, control_file_path="control.xlsx")
        out.append(snap.estado_proceso)
    return out


def test_iniciar_with_invalid_format_leaves_everything_untouched():
    rows = [
        [datetime(2025, 12, 23), 6500739, "GEOEXCON", "PAGO", "27a"],
        [datetime(2025, 12, 30), 5000000, "EQUINORTE", "PAGO", 247.248],
    ]
    client = _MockClient()
    with pytest.raises(BankUploadCreditColumnError) as excinfo:
        _run_generate_client(build_bank_excel(HEADERS_WITH_CREDIT, rows), client=client)
    err = excinfo.value
    assert err.stage == "format" and err.mode == "iniciar"
    assert err.control_untouched is True
    assert [(i["fila"], i["cliente"], i["valor"], i["motivo"]) for i in err.issues] == [
        (2, "GEOEXCON", "27a", "invalid"),
        (3, "EQUINORTE", "247,248", "decimal"),
    ]
    assert client.put_calls == []
    assert client.delete_calls == []


def _setup_active_lote(c):
    setup_client_structure(c)
    c.children = [{"name": "val_banco_bogota_2025-12-31_old.xlsx", "id": "old"}]
    c.downloaded_files["revision/val_banco_bogota_2025-12-31_old.xlsx"] = b"old"
    c.downloaded_files[PROCESS_CONTROL_BANK_FILE_BOGOTA] = _control_with_active_revision(
        process_key="payment-validation|banco_bogota|2025-12-31|old12345",
        validation_path="revision/val_banco_bogota_2025-12-31_old.xlsx",
    )


def _run_regenerate(client, bank_bytes):
    async def _run():
        set_env_vars()
        client.downloaded_files["banco.xlsx"] = bank_bytes
        with mock.patch(
            "app.application.use_cases.payment_validation_generate.extract_total_a_pagar_from_pdf",
            side_effect=make_pdf_extractor_mock(client),
        ), mock.patch(
            "app.application.use_cases.payment_validation_generate.extract_fecha_limite_pago_from_pdf",
            side_effect=_fake_fecha_limite_from_marker_bytes(),
        ):
            return await generate_payment_validation(
                client, PROCESS_DATE, bank_code="banco_bogota", force_regenerate=True
            )

    return asyncio.run(_run())


def test_regenerar_with_invalid_format_keeps_previous_lote():
    client = _MockClient()
    _setup_active_lote(client)
    control_before = client.downloaded_files[PROCESS_CONTROL_BANK_FILE_BOGOTA]
    rows = [[datetime(2025, 12, 23), 6500739, "GEOEXCON", "PAGO", "27a"]]
    with pytest.raises(BankUploadCreditColumnError) as excinfo:
        _run_regenerate(client, build_bank_excel(HEADERS_WITH_CREDIT, rows))
    assert excinfo.value.mode == "regenerar"
    assert client.put_calls == []
    assert client.delete_calls == []
    assert client.downloaded_files[PROCESS_CONTROL_BANK_FILE_BOGOTA] == control_before
    assert "revision/val_banco_bogota_2025-12-31_old.xlsx" in client.downloaded_files


# ─── Crédito inexistente: sin archivo de revisión y con salida ───────────────


def _missing_credit_rows():
    return [
        [datetime(2025, 12, 23), 6500739, "GEOEXCON", "PAGO", "254"],
        [datetime(2025, 12, 23), 18826879, "GEOEXCON", "PAGO", "2477"],
    ]


def _fixed_rows():
    return [
        [datetime(2025, 12, 23), 6500739, "GEOEXCON", "PAGO", "254"],
        [datetime(2025, 12, 23), 18826879, "GEOEXCON", "PAGO", None],
    ]


def _fail_like_queue(client):
    """Lo que hace la cola ante un fallo que no preserva el Control."""
    asyncio.run(announce_control_generate_failed(client, bank_code="banco_bogota"))


def _review_files(client) -> list[str]:
    return [p for p in client.downloaded_files if p.startswith("revision/")]


def test_iniciar_missing_credit_fails_without_review_and_allows_retry():
    client = _MockClient()
    with pytest.raises(BankUploadCreditColumnError) as excinfo:
        _run_generate_client(build_bank_excel(HEADERS_WITH_CREDIT, _missing_credit_rows()), client=client)
    err = excinfo.value
    assert err.stage == "existence" and err.control_untouched is False
    assert err.issues == [
        {"fila": 3, "cliente": "GEOEXCON", "credito": 2477, "motivo": "not_found"}
    ]
    assert _review_files(client) == []
    assert _control_writes(client) == ["GENERANDO"]

    _fail_like_queue(client)
    row = _read_control_row(client.downloaded_files[PROCESS_CONTROL_BANK_FILE_BOGOTA])
    assert row["EstadoProceso"] == "ERROR_GENERATE"

    # Iniciar de nuevo con el Excel corregido.
    client.put_calls.clear()

    async def _retry():
        client.downloaded_files["banco.xlsx"] = build_bank_excel(HEADERS_WITH_CREDIT, _fixed_rows())
        with mock.patch(
            "app.application.use_cases.payment_validation_generate.extract_total_a_pagar_from_pdf",
            side_effect=make_pdf_extractor_mock(client),
        ), mock.patch(
            "app.application.use_cases.payment_validation_generate.extract_fecha_limite_pago_from_pdf",
            side_effect=_fake_fecha_limite_from_marker_bytes(),
        ):
            return await generate_payment_validation(client, PROCESS_DATE, bank_code="banco_bogota")

    result = asyncio.run(_retry())
    assert result["process_control_estado"] == "REVISION_CREADA"
    assert len(_review_files(client)) == 1


def test_iniciar_missing_credit_then_regenerar_from_error_state():
    client = _MockClient()
    with pytest.raises(BankUploadCreditColumnError):
        _run_generate_client(build_bank_excel(HEADERS_WITH_CREDIT, _missing_credit_rows()), client=client)
    _fail_like_queue(client)
    result = _run_regenerate(client, build_bank_excel(HEADERS_WITH_CREDIT, _fixed_rows()))
    assert result["process_control_estado"] == "REVISION_CREADA"


def test_regenerar_missing_credit_leaves_retryable_state():
    client = _MockClient()
    _setup_active_lote(client)
    with pytest.raises(BankUploadCreditColumnError) as excinfo:
        _run_regenerate(client, build_bank_excel(HEADERS_WITH_CREDIT, _missing_credit_rows()))
    assert excinfo.value.stage == "existence" and excinfo.value.mode == "regenerar"
    # El lote previo ya se canceló (Regenerar lo reemplaza) y no quedó revisión nueva.
    assert "CANCELADO" in _control_writes(client)
    assert _control_writes(client)[-1] == "GENERANDO"
    assert _review_files(client) == []

    _fail_like_queue(client)
    row = _read_control_row(client.downloaded_files[PROCESS_CONTROL_BANK_FILE_BOGOTA])
    assert row["EstadoProceso"] == "ERROR_GENERATE"

    result = _run_regenerate(client, build_bank_excel(HEADERS_WITH_CREDIT, _fixed_rows()))
    assert result["process_control_estado"] == "REVISION_CREADA"
    assert len(_review_files(client)) == 1


# ─── Cola: solo el fallo de formato conserva el Control ──────────────────────


class _FakeJobs:
    def __init__(self):
        self.jobs: dict[str, dict] = {}
        self.finished = False

    async def set_job(self, job_id, data):
        self.jobs.setdefault(job_id, {}).update(data)

    def finish_generate(self):
        self.finished = True


@pytest.mark.parametrize(
    "stage,expect_announce",
    [("format", False), ("existence", True)],
)
def test_queue_skips_error_generate_only_when_control_untouched(stage, expect_announce):
    from app.application.services import generate_queue_service as gqs

    jobs = _FakeJobs()
    svc = gqs.GenerateQueueService(jobs)
    announced: list[str] = []

    async def _boom(*_a, **_k):
        raise BankUploadCreditColumnError(
            [{"fila": 7, "cliente": "RUEDA", "valor": "27a", "motivo": "invalid"}],
            stage=stage,
            mode="iniciar",
        )

    async def _announce(*_a, **_k):
        announced.append("ERROR_GENERATE")

    async def _noop(*_a, **_k):
        return {}

    with mock.patch.object(gqs, "generate_payment_validation", _boom), mock.patch.object(
        gqs, "try_record_step_event", _noop
    ), mock.patch(
        "app.application.use_cases.payment_validation_generate.announce_control_generate_failed",
        _announce,
    ):
        asyncio.run(svc._run_generate_job("job-1", object(), PROCESS_DATE, "banco_bogota"))

    assert jobs.jobs["job-1"]["status"] == "failed"
    assert jobs.finished is True
    assert announced == (["ERROR_GENERATE"] if expect_announce else [])


# ─── Mensaje al operador ─────────────────────────────────────────────────────


def _failed_job(err: BankUploadCreditColumnError) -> dict:
    return enrich_job_for_http_response(
        {
            "job_id": "j",
            "type": "generate",
            "status": "failed",
            "error": {"type": type(err).__name__, "message": str(err)},
        }
    )["error"]


def test_operator_message_lists_rows_without_codes():
    err = BankUploadCreditColumnError(
        [
            {"fila": 7, "cliente": "RUEDA INVERSIONES", "valor": "27a", "motivo": "invalid"},
            {"fila": 9, "cliente": "RUEDA INVERSIONES", "valor": "247,248", "motivo": "decimal"},
        ],
        stage="format",
        mode="iniciar",
    )
    e = _failed_job(err)
    assert e["error_code"] == "bank_credit_column_invalid"
    assert e["user_message"] == (
        "No se pudo iniciar la validación. Revise la columna No. Crédito del Excel de carga:\n"
        "· Fila 7 (RUEDA INVERSIONES): «27a» no es un número de crédito válido.\n"
        "· Fila 9 (RUEDA INVERSIONES): «247,248» quedó como un número con decimales. "
        "Si son varios créditos, sepárelos con «y» (por ejemplo: 247 y 248)."
    )
    assert e["next_action"] == (
        "Corrija esas filas en el Excel de carga y vuelva a presionar «Iniciar validación». "
        "Si no conoce el número, deje la celda vacía."
    )
    for text in (e["user_message"], e["next_action"]):
        assert "bank_credit" not in text and "{" not in text and "_" not in text


def test_operator_message_missing_credit_and_regenerar():
    err = BankUploadCreditColumnError(
        [{"fila": 12, "cliente": "RUEDA INVERSIONES", "credito": 2477, "motivo": "not_found"}],
        stage="existence",
        mode="regenerar",
    )
    e = _failed_job(err)
    assert e["user_message"] == (
        "No se pudo regenerar el archivo de revisión. Revise la columna No. Crédito del Excel de carga:\n"
        "· Fila 12 (RUEDA INVERSIONES): el crédito 2477 no se encontró entre los créditos activos del cliente."
    )
    assert "«Regenerar»" in e["next_action"]
    assert "no se modificó" not in e["next_action"]


def test_operator_message_regenerar_format_says_review_file_kept():
    _, action = credit_column_error_copy(
        {"mode": "regenerar", "stage": "format", "issues": [], "total": 0}
    )
    assert action.endswith("El archivo de revisión actual no se modificó.")


def test_operator_message_caps_listed_rows():
    issues = [
        {"fila": i, "cliente": "X", "valor": "a", "motivo": "invalid"} for i in range(2, 16)
    ]
    e = _failed_job(BankUploadCreditColumnError(issues, stage="format", mode="iniciar"))
    lines = e["user_message"].split("\n")
    assert len(lines) == 1 + 10 + 1
    assert lines[-1] == "· … y 4 más."


# ─── Correo: la columna no entra ni descarta filas ───────────────────────────


def test_email_table_excludes_credit_column_and_keeps_rows():
    raw = create_excel(
        ["Fecha", "Crédito", "Concepto", "Transacción", "No. Crédito"],
        [
            [datetime(2026, 9, 1), 100, "RUEDA", "PSE", "247"],
            [datetime(2026, 9, 2), 200, "JASP", "PSE", None],
            [datetime(2026, 9, 3), 300, "COLPAO", "SUC", ""],
        ],
    )
    report_d, headers, rows = _parse_bank_report_table_and_min_date(raw)
    assert report_d == date(2026, 9, 1)
    assert headers == ["Fecha", "Crédito", "Concepto", "Transacción"]
    assert len(rows) == 3
    assert all(len(r) == 4 for r in rows)


def test_email_table_without_credit_column_unchanged():
    raw = create_excel(
        ["Fecha", "Crédito", "Concepto", "Transacción"],
        [[datetime(2026, 9, 1), 100, "RUEDA", "PSE"]],
    )
    _, headers, rows = _parse_bank_report_table_and_min_date(raw)
    assert headers == ["Fecha", "Crédito", "Concepto", "Transacción"]
    assert len(rows) == 1
