import asyncio
import contextlib
import io
import os
import re
from datetime import date, datetime
from unittest import mock
from urllib.parse import unquote

import openpyxl
import pytest
from openpyxl.utils import get_column_letter

from app.application.services.review_schema import (
    AplicacionPagosCols,
    ErroresCols,
    ReviewSheets,
    ValidarPago,
)
from app.application.config.payment_validation_settings import (
    BANK_CODE_BANCOLOMBIA,
    BANK_CODE_BOGOTA,
    resolve_bank_control_file_path)
from app.application.use_cases.setup_merge_control_workbook import (
    _build_process_control_workbook_bytes)

from app.application.use_cases.payment_validation_generate import (
    generate_payment_validation,
    _extract_pending_installment,
    _distrib_freeze_panes_cell,
)

class MockGraphClient:
    def __init__(self):
        self.children = []
        self.downloaded_files = {}
        self.folder_children = {}
        self.folder_web_urls: dict[str, str] = {}
        self.uploaded_files = {}
        self.requested_endpoints = []
        self.put_calls = []

    async def get(self, endpoint, params=None):
        if endpoint == "/sites":
            return {"value": [{"id": "dummy_site"}]}
        if endpoint == "/sites/dummy_site/drives":
            return {"value": [{"id": "dummy_drive", "name": "DRIVE"}]}
        if endpoint.endswith(":/children"):
            path = endpoint.split("/root:/", 1)[1].rsplit(":/children", 1)[0]
            path = unquote(path)
            if path == "revision":
                return {"value": self.children}
            return {"value": self.folder_children.get(path, [])}
        if "/root:/" in endpoint and ":/children" not in endpoint and ":/content" not in endpoint:
            path = unquote(endpoint.split("/root:/", 1)[1].split(":", 1)[0])
            web = self.folder_web_urls.get(path)
            if web:
                return {"webUrl": web}
            return {}
        return {}

    async def get_bytes(self, endpoint, params=None):
        self.requested_endpoints.append(endpoint)
        file_path = endpoint.split("/root:/", 1)[1].rsplit(":/content", 1)[0]
        file_path = unquote(file_path)
        if file_path not in self.downloaded_files:
            if file_path == resolve_bank_control_file_path(BANK_CODE_BOGOTA):
                return _build_process_control_workbook_bytes("banco_bogota", "Banco de Bogotá")
            if file_path == resolve_bank_control_file_path(BANK_CODE_BANCOLOMBIA):
                return _build_process_control_workbook_bytes("banco_bancolombia", "Bancolombia")
        return self.downloaded_files.get(file_path, b"")

    async def put_bytes(self, endpoint, content, content_type):
        self.put_calls.append((endpoint, content_type))
        file_path = endpoint.split("/root:/", 1)[1].rsplit(":/content", 1)[0]
        file_path = unquote(file_path)
        self.uploaded_files[file_path] = content
        return {"id": "new_file_id"}

    async def delete(self, endpoint: str) -> None:
        return None

class MockGraphClientPutReturnsWebUrl(MockGraphClient):
    """Simula Graph: put_bytes devuelve driveItem con webUrl."""

    def __init__(self, web_url: str = "https://comwareec.sharepoint.com/sites/x/file.xlsx"):
        super().__init__()
        self._web_url = web_url

    async def put_bytes(self, endpoint, content, content_type):
        self.put_calls.append((endpoint, content_type))
        file_path = endpoint.split("/root:/", 1)[1].rsplit(":/content", 1)[0]
        file_path = unquote(file_path)
        self.uploaded_files[file_path] = content
        return {"id": "new_file_id", "webUrl": self._web_url}

class MockGraphClientPutCustomReturn(MockGraphClient):
    """put_bytes devuelve un valor configurable (dict sin webUrl, None, etc.)."""

    def __init__(self, put_return):
        super().__init__()
        self._put_return = put_return

    async def put_bytes(self, endpoint, content, content_type):
        self.put_calls.append((endpoint, content_type))
        file_path = endpoint.split("/root:/", 1)[1].rsplit(":/content", 1)[0]
        file_path = unquote(file_path)
        self.uploaded_files[file_path] = content
        return self._put_return

def make_item(name, is_folder=False, web_url=None):
    item = {"name": name}
    if is_folder:
        item["folder"] = {}
    if web_url:
        item["webUrl"] = web_url
    return item

def create_excel(headers, data, sheet_name="Sheet"):
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = sheet_name
    ws.append(headers)
    for row in data:
        ws.append(row)
    out = io.BytesIO()
    wb.save(out)
    return out.getvalue()

STANDARD_BANK_HEADERS = ["Fecha", "Crédito", "Concepto", "Transacción"]

def with_tipo_aplicacion_rows(rows, default_tipo="PAGO"):
    """Compat tests: si la fila trae Tipo Aplicación (5 cols), se elimina (banco v3 sin tipo)."""
    _ = default_tipo
    out = []
    for row in rows:
        row = list(row)
        if len(row) == 5:
            # Fecha, Monto, Concepto, Tipo, Transaccion -> drop Tipo
            out.append([row[0], row[1], row[2], row[4]])
        elif len(row) == 4:
            out.append(row)
        else:
            out.append(row)
    return out

def create_bank_excel(data_rows, headers=None, default_tipo="PAGO"):
    hdrs = list(headers or STANDARD_BANK_HEADERS)
    # Si un test aún pasa headers con Tipo Aplicación, normalizar a v3.
    tipo_aliases = {"tipo aplicación", "tipo aplicacion", "tipoaplicacion"}
    filtered = []
    drop_idxs = []
    for i, h in enumerate(hdrs):
        key = str(h or "").strip().lower()
        if key in tipo_aliases or key.replace(" ", "") == "tipoaplicacion":
            drop_idxs.append(i)
        else:
            filtered.append(h)
    rows = with_tipo_aplicacion_rows(data_rows, default_tipo=default_tipo)
    if drop_idxs:
        cleaned = []
        for row in rows:
            cleaned.append([v for i, v in enumerate(row) if i not in drop_idxs])
        rows = cleaned
        hdrs = filtered
    return create_excel(hdrs, rows)

def create_amortization_excel(rows):
    return create_excel(
        ["Fecha límite", "Fecha pago", "Total pagado", "Cuota", "Intereses de mora"],
        rows)

# Mapa global: path_del_pdf -> valor TOTAL A PAGAR (usado por el mock de extract_total_a_pagar_from_pdf)
_PDF_AMOUNT_REGISTRY: dict[str, float] = {}

def create_pdf_bytes(
    total_a_pagar: str,
    fecha_limite: date | None = None,
    *,
    skip_fecha_fake: bool = False) -> bytes:
    """
    Genera bytes marcadores para un PDF de test. Estos bytes NO son un PDF real.
    El mock de extract_total_a_pagar_from_pdf lee TOTAL A PAGAR;
    el mock de extract_fecha_limite_pago_from_pdf lee FECHA_LIMITE=YYYY-MM-DD si está presente.
    Si no hay marcador de fecha, el fake de tests usa una fecha fija (un solo extracto).
    skip_fecha_fake: el fake de fecha en tests devuelve None (simula PDF sin fecha legible).
    """
    sk = "SKIP_FECHA;" if skip_fecha_fake else ""
    fl = ""
    if fecha_limite is not None:
        fl = f"FECHA_LIMITE={fecha_limite.isoformat()};"
    if not total_a_pagar:
        return f"PDF_MOCK:{sk}{fl}sin_total".encode()
    return f"PDF_MOCK:{sk}{fl}TOTAL A PAGAR {total_a_pagar}".encode()

def create_pdf_no_total() -> bytes:
    """PDF sin TOTAL A PAGAR (marcador)."""
    return b"PDF_MOCK:sin_total"

def make_pdf_extractor_mock(client: "MockGraphClient"):
    """
    Devuelve una función que reemplaza extract_total_a_pagar_from_pdf.
    Lee los bytes que el mock guardó y parsea el marcador PDF_MOCK.
    """
    def _fake_extract(pdf_bytes: bytes) -> float:
        text = pdf_bytes.decode(errors="ignore")
        if not text.startswith("PDF_MOCK:"):
            raise ValueError("extract_amount_not_found")
        # Formato: "PDF_MOCK:TOTAL A PAGAR 18.826.879" o "PDF_MOCK:sin_total"
        if "TOTAL A PAGAR" not in text:
            raise ValueError("extract_amount_not_found")
        raw = text.split("TOTAL A PAGAR", 1)[1].strip()
        if not raw:
            raise ValueError("extract_amount_not_found")
        # Parsear formato latino
        if "," in raw:
            raw = raw.replace(".", "").replace(",", ".")
        else:
            raw = raw.replace(".", "")
        try:
            return float(raw)
        except ValueError:
            raise ValueError("extract_amount_not_found")
    return _fake_extract

def set_env_vars():
    os.environ["GRAPH_BANK_PAYMENTS_FILE_PATH"] = "banco.xlsx"
    os.environ["GRAPH_BANK_PAYMENTS_FILE_PATH_BANCOLOMBIA"] = "banco.xlsx"
    os.environ["GRAPH_CLIENTS_BASE_PATH"] = "clientes"
    os.environ["GRAPH_SHAREPOINT_SITE_SEARCH"] = "SITIO"
    os.environ["GRAPH_SHAREPOINT_DRIVE_NAME"] = "DRIVE"
    os.environ["GRAPH_PAYMENT_VALIDATION_REVIEW_PATH"] = "revision"
    os.environ["GRAPH_VALIDATION_FILE_PREFIX"] = "val"

def setup_client_structure(client, include_web_urls=False):
    # Control oficial por banco (Phase 1): Generate ahora lo lee siempre.
    # Para los tests, basta con el control de Bogotá (bank_code explícito en cada llamada).
    client.downloaded_files[resolve_bank_control_file_path(BANK_CODE_BOGOTA)] = (
        _build_process_control_workbook_bytes("banco_bogota", "Banco de Bogotá")
    )

    client.folder_children["clientes"] = [
        make_item("GEOEXCON", is_folder=True),
        make_item("EQUINORTE", is_folder=True),
    ]
    folder_url_254 = "https://contoso/folder/254" if include_web_urls else None
    folder_url_231 = "https://contoso/folder/231" if include_web_urls else None
    folder_url_900 = "https://contoso/folder/900" if include_web_urls else None
    client.folder_children["clientes/GEOEXCON"] = [
        make_item("254", is_folder=True, web_url=folder_url_254),
        make_item("231", is_folder=True, web_url=folder_url_231),
    ]
    client.folder_children["clientes/EQUINORTE"] = [
        make_item("900", is_folder=True, web_url=folder_url_900),
    ]

    geo_254_pdf = "clientes/GEOEXCON/254/Extracto 2025-12-23 CREDITO # 254.pdf"
    geo_254_tabla = "clientes/GEOEXCON/254/Tabla amortizacion GEOEXCON 254.xlsx"
    geo_231_pdf = "clientes/GEOEXCON/231/Extracto 2025-12-23 CREDITO # 231.pdf"
    geo_231_tabla = "clientes/GEOEXCON/231/Tabla amortizacion GEOEXCON 231.xlsx"
    eq_900_pdf = "clientes/EQUINORTE/900/Extracto 2025-12-30 CREDITO # 900.pdf"
    eq_900_tabla = "clientes/EQUINORTE/900/Tabla amortizacion EQUINORTE 900.xlsx"

    client.folder_children["clientes/GEOEXCON/254"] = [
        make_item(
            "Extracto 2025-12-23 CREDITO # 254.pdf",
            web_url="https://contoso/254.pdf" if include_web_urls else None),
        make_item(
            "Tabla amortizacion GEOEXCON 254.xlsx",
            web_url="https://contoso/254.xlsx" if include_web_urls else None),
    ]
    client.folder_children["clientes/GEOEXCON/231"] = [
        make_item(
            "Extracto 2025-12-23 CREDITO # 231.pdf",
            web_url="https://contoso/231.pdf" if include_web_urls else None),
        make_item(
            "Tabla amortizacion GEOEXCON 231.xlsx",
            web_url="https://contoso/231.xlsx" if include_web_urls else None),
    ]
    client.folder_children["clientes/EQUINORTE/900"] = [
        make_item(
            "Extracto 2025-12-30 CREDITO # 900.pdf",
            web_url="https://contoso/900.pdf" if include_web_urls else None),
        make_item(
            "Tabla amortizacion EQUINORTE 900.xlsx",
            web_url="https://contoso/900.xlsx" if include_web_urls else None),
    ]

    client.downloaded_files[geo_254_tabla] = create_amortization_excel([
        [date(2025, 12, 23), None, None, 6734920.07, None],
    ])
    client.downloaded_files[geo_231_tabla] = create_amortization_excel([
        [date(2025, 12, 23), None, None, 19540684.91, None],
    ])
    client.downloaded_files[eq_900_tabla] = create_amortization_excel([
        [date(2025, 12, 30), None, None, 5000000, None],
    ])
    # PDFs con TOTAL A PAGAR real (valores correctos, distintos de Cuota en tabla)
    client.downloaded_files[geo_254_pdf] = create_pdf_bytes("6.500.739", date(2025, 12, 23))
    client.downloaded_files[geo_231_pdf] = create_pdf_bytes("18.826.879", date(2025, 12, 23))
    client.downloaded_files[eq_900_pdf] = create_pdf_bytes("5.000.000", date(2025, 12, 30))

    return {
        "geo_254_pdf": geo_254_pdf,
        "geo_254_tabla": geo_254_tabla,
        "geo_231_pdf": geo_231_pdf,
        "geo_231_tabla": geo_231_tabla,
        "eq_900_pdf": eq_900_pdf,
        "eq_900_tabla": eq_900_tabla,
    }

def setup_triple_credit_client(client, cliente: str = "MULTICRED", credits: tuple[str, ...] = ("258", "265", "270")):
    """Cliente con varios créditos candidatos para un mismo pago (misma fecha límite)."""
    client.downloaded_files[resolve_bank_control_file_path(BANK_CODE_BOGOTA)] = (
        _build_process_control_workbook_bytes("banco_bogota", "Banco de Bogotá")
    )
    client.folder_children["clientes"] = [make_item(cliente, is_folder=True)]
    client.folder_children[f"clientes/{cliente}"] = [make_item(c, is_folder=True) for c in credits]
    due = date(2025, 12, 23)
    for credit in credits:
        pdf_path = f"clientes/{cliente}/{credit}/Extracto 2025-12-23 CREDITO # {credit}.pdf"
        tabla_path = f"clientes/{cliente}/{credit}/Tabla amortizacion {cliente} {credit}.xlsx"
        client.folder_children[f"clientes/{cliente}/{credit}"] = [
            make_item(f"Extracto 2025-12-23 CREDITO # {credit}.pdf"),
            make_item(f"Tabla amortizacion {cliente} {credit}.xlsx"),
        ]
        client.downloaded_files[tabla_path] = create_amortization_excel([[due, None, None, 100.0, None]])
        client.downloaded_files[pdf_path] = create_pdf_bytes("100", due)

def load_generated_workbook(client):
    assert client.uploaded_files, "Generate no subió ningún workbook"
    for blob in client.uploaded_files.values():
        wb = openpyxl.load_workbook(io.BytesIO(blob))
        if ReviewSheets.APLICACION_PAGOS in wb.sheetnames:
            return wb
    uploaded_key = list(client.uploaded_files.keys())[0]
    return openpyxl.load_workbook(io.BytesIO(client.uploaded_files[uploaded_key]))

def _header_row_index(ws, marker: str = "ID Pago") -> int:
    for i, row in enumerate(ws.iter_rows(values_only=True), start=1):
        if row and str(row[0]).strip() == marker:
            return i
    return 1

def _first_data_row(ws, marker: str = "ID Pago") -> int:
    return _header_row_index(ws, marker) + 1

def sheet_to_dicts(ws, marker: str | None = None):
    m = marker or AplicacionPagosCols.ID_PAGO
    rows = list(ws.iter_rows(values_only=True))
    hidx = next((i for i, r in enumerate(rows) if r and str(r[0]).strip() == m), None)
    if hidx is None:
        raise AssertionError(f"No se encontró fila de encabezados con primera columna {m!r}")
    headers = list(rows[hidx])
    width = len(headers)
    out = []
    for row in rows[hidx + 1 :]:
        if not any(row):
            continue
        d = {}
        for idx in range(min(width, len(row) if row else 0)):
            h = headers[idx]
            if h is None or str(h).strip() == "":
                continue
            d[h] = row[idx] if idx < len(row) else None
        out.append(d)
    return out

def run_generate(bank_rows, process_date, include_web_urls=False):
    if generate_payment_validation is None:
        pytest.fail("Not implemented")

    async def _run():
        set_env_vars()
        client = MockGraphClient()
        client.children = []
        setup_client_structure(client, include_web_urls=include_web_urls)
        client.downloaded_files["banco.xlsx"] = create_bank_excel(bank_rows)
        extractor = make_pdf_extractor_mock(client)
        fake_fecha = _fake_fecha_limite_from_marker_bytes()
        with mock.patch(
            "app.application.use_cases.payment_validation_generate.extract_total_a_pagar_from_pdf",
            side_effect=extractor), mock.patch(
            "app.application.use_cases.payment_validation_generate.extract_fecha_limite_pago_from_pdf",
            side_effect=fake_fecha):
            result = await generate_payment_validation(client, process_date, bank_code="banco_bogota")
        workbook = load_generated_workbook(client)
        return client, result, workbook

    return asyncio.run(_run())

def test_generate_review_folder_not_empty():
    if generate_payment_validation is None:
        pytest.fail("Not implemented")

    async def run_test():
        set_env_vars()
        client = MockGraphClient()
        client.children = [{"name": "archivo_viejo.xlsx"}]

        with pytest.raises(ValueError, match="review_folder_not_empty"):
            await generate_payment_validation(client, date(2026, 5, 10), bank_code="banco_bogota")

    asyncio.run(run_test())

def test_generate_mock_graph_contract_has_no_legacy_methods():
    client = MockGraphClient()
    assert not hasattr(client, "get_file_content")
    assert not hasattr(client, "upload_file")

def test_generate_ignores_temp_files():
    if generate_payment_validation is None:
        pytest.fail("Not implemented")

    async def run_test():
        set_env_vars()
        client = MockGraphClient()
        client.children = [{"name": "~$archivo.xlsx"}]
        setup_client_structure(client)
        client.downloaded_files["banco.xlsx"] = create_bank_excel( [])

        result = await generate_payment_validation(client, date(2026, 5, 10), bank_code="banco_bogota")
        assert result["process_id"] is not None
        assert any(endpoint.endswith("/banco.xlsx:/content") for endpoint in client.requested_endpoints)
        expected_suffix = f"/revision/val_banco_bogota_2026-05-10_{result['process_id']}.xlsx:/content"
        assert any(endpoint.endswith(expected_suffix) for endpoint, _ in client.put_calls)

    asyncio.run(run_test())










# ─── Tests: Valor extracto debe venir exclusivamente del PDF ─────────────────

def _make_single_client_setup(client, credit_id: str, tabla_cuota: float, pdf_total_str: str, due_date: date, banco_date: date):
    """Helper: configura un cliente TESTCLIENT con un solo crédito."""
    client.folder_children["clientes"] = [make_item("TESTCLIENT", is_folder=True)]
    client.folder_children["clientes/TESTCLIENT"] = [make_item(credit_id, is_folder=True)]
    fecha_str = due_date.strftime("%Y-%m-%d")
    pdf_name = f"Extracto {fecha_str} CREDITO # {credit_id}.pdf"
    tabla_name = f"Tabla amortizacion TESTCLIENT {credit_id}.xlsx"
    client.folder_children[f"clientes/TESTCLIENT/{credit_id}"] = [
        make_item(pdf_name),
        make_item(tabla_name),
    ]
    client.downloaded_files[f"clientes/TESTCLIENT/{credit_id}/{tabla_name}"] = create_excel(
        ["Fecha límite", "Cuota", "Intereses de mora", "Fecha de pago"],
        [[due_date, tabla_cuota, tabla_cuota * 0.05, None]])
    # Registrar PDF como marcador — el mock_extractor lo parseará
    client.downloaded_files[f"clientes/TESTCLIENT/{credit_id}/{pdf_name}"] = create_pdf_bytes(
        pdf_total_str, due_date
    )
    client.downloaded_files["banco.xlsx"] = create_bank_excel(
        [[banco_date, 500000, "TESTCLIENT", ""]])

def _fake_fecha_limite_from_marker_bytes():
    """Lee FECHA_LIMITE=YYYY-MM-DD del marcador PDF_MOCK; si falta, fecha fija para un solo extracto."""

    def _inner(pdf_bytes: bytes):
        text = pdf_bytes.decode(errors="ignore")
        if "SKIP_FECHA;" in text:
            return None
        m = re.search(r"FECHA_LIMITE=([0-9]{4}-[0-9]{2}-[0-9]{2})", text)
        if m:
            return date.fromisoformat(m.group(1))
        return date(2000, 1, 1)

    return _inner

@contextlib.contextmanager
def _run_with_pdf_mock(client):
    """Parchea extract_total_a_pagar_from_pdf y extract_fecha_limite_pago_from_pdf (marcadores PDF_MOCK)."""
    with mock.patch(
        "app.application.use_cases.payment_validation_generate.extract_total_a_pagar_from_pdf",
        side_effect=make_pdf_extractor_mock(client)), mock.patch(
        "app.application.use_cases.payment_validation_generate.extract_fecha_limite_pago_from_pdf",
        side_effect=_fake_fecha_limite_from_marker_bytes()):
        yield

def _get_dist_col_idx(wb, col_name: str) -> int:
    ws = wb[ReviewSheets.APLICACION_PAGOS]
    hr = _header_row_index(ws, AplicacionPagosCols.ID_PAGO)
    headers = [c.value for c in ws[hr]]
    return headers.index(col_name)






def test_extract_fecha_limite_pago_from_pdf_text_iso_and_european():
    from app.application.services.payment_helpers import extract_fecha_limite_pago_from_pdf_text

    assert extract_fecha_limite_pago_from_pdf_text(
        "Texto Fecha Limite de pago 2026-04-15 más texto"
    ) == date(2026, 4, 15)
    assert extract_fecha_limite_pago_from_pdf_text(
        "Fecha Limite de pago 23/04/2026"
    ) == date(2026, 4, 23)
    assert extract_fecha_limite_pago_from_pdf_text(
        "Fecha Limite de pago 23-04-2026"
    ) == date(2026, 4, 23)
    assert extract_fecha_limite_pago_from_pdf_text(
        "Fecha desembolso 23/10/2025  ...  Fecha Limite de pago 23/04/2026  fin"
    ) == date(2026, 4, 23)
    assert extract_fecha_limite_pago_from_pdf_text(
        "TOTAL A PAGAR $ 100\nTOTAL PAGADO $ 0\nFecha Limite de pago 23/04/2026\n"
    ) == date(2026, 4, 23)



















def _errores_link_cell(ws, row: int, col_name: str):
    col = ErroresCols.HEADERS.index(col_name) + 1
    return ws.cell(row=row, column=col)
















def _find_control_value_cell(ws_ctrl, label: str):
    for r_idx, row in enumerate(ws_ctrl.iter_rows(max_col=2, values_only=False), start=1):
        if row and row[0].value == label:
            return row[1]
    raise AssertionError(f"No se encontró label en Control: {label}")




def _dist_col(name: str) -> int:
    return AplicacionPagosCols.HEADERS.index(name) + 1

def _fill_rgb(cell) -> str | None:
    fill = cell.fill
    if fill is None or fill.fill_type != "solid":
        return None
    color = fill.fgColor
    if color is None:
        return None
    return getattr(color, "rgb", None)








def _top_border_style(cell) -> str | None:
    top = cell.border.top
    if top is None:
        return None
    return top.style

def _bottom_border_style(cell) -> str | None:
    bottom = cell.border.bottom
    if bottom is None:
        return None
    return bottom.style

def _distrib_rows_by_cliente(ws, dr: int) -> list[tuple[int, str]]:
    cliente_col = _dist_col(AplicacionPagosCols.CLIENTE)
    rows: list[tuple[int, str]] = []
    for row in range(dr, ws.max_row + 1):
        cliente = str(ws.cell(row=row, column=cliente_col).value or "").strip()
        if not cliente:
            continue
        rows.append((row, cliente))
    return rows

























def test_dedupe_credit_candidates_by_ruta():
    from app.application.use_cases.payment_validation_generate import _dedupe_credit_candidates

    cands = [
        {
            "credito": "100",
            "ruta_extracto_pdf": "clientes/X/a.pdf",
            "fecha_limite": date(2026, 3, 1),
            "valor_extracto": 2000.0,
            "link_extracto": "http://x/a.pdf",
        },
        {
            "credito": "ROOT",
            "ruta_extracto_pdf": "clientes\\X\\a.pdf",
            "fecha_limite": date(2026, 3, 1),
            "valor_extracto": 2000.0,
            "link_extracto": "http://x/a.pdf",
        },
    ]
    assert len(_dedupe_credit_candidates(cands)) == 1












def _medium_border_color(cell, side: str = "top") -> str | None:
    edge = getattr(cell.border, side, None)
    if edge is None or edge.style != "medium":
        return None
    rgb = edge.color.rgb if edge.color else None
    if rgb is None:
        return None
    s = str(rgb).upper()
    return s[-6:] if len(s) > 6 else s




