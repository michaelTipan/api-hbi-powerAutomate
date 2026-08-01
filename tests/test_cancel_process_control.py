"""Cancel/reset de proceso activo (pre-Finalize): control → VACIO sin editar Excel a mano."""

from __future__ import annotations

import asyncio
import io
import os
from datetime import date
from urllib.parse import unquote

import httpx
import openpyxl
import pytest

from app.application.job_status_enrichment import enrich_job_for_http_response
from app.application.use_cases.payment_validation_cancel import cancel_active_payment_validation
from app.application.use_cases.payment_validation_generate import generate_payment_validation
from app.application.use_cases.setup_merge_control_workbook import (
    PROCESS_CONTROL_BANK_FILE_BANCOLOMBIA,
    PROCESS_CONTROL_BANK_FILE_BOGOTA,
    SHEET_NAME,
    _build_process_control_workbook_bytes,
)


def _http_error(status: int) -> httpx.HTTPStatusError:
    req = httpx.Request("GET", "https://graph.microsoft.com/test")
    resp = httpx.Response(status, request=req, text=f"HTTP {status} body")
    return httpx.HTTPStatusError("err", request=req, response=resp)


class MockGraphClientCancel:
    def __init__(self) -> None:
        self.children: list[dict] = []
        self.downloaded_files: dict[str, bytes] = {}
        self.folder_children: dict[str, list[dict]] = {}
        self.put_calls: list[tuple[str, bytes]] = []
        self.delete_calls: list[str] = []
        self.force_404_paths: set[str] = set()

    async def get(self, endpoint: str, params=None):
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
            path = unquote(endpoint.split("/root:/", 1)[1].split(":", 1)[0]).strip("/")
            if path in self.force_404_paths:
                raise _http_error(404)
            return {"id": "item1", "name": path.rsplit("/", 1)[-1], "webUrl": "https://example/item.xlsx"}
        return {"value": []}

    async def get_bytes(self, endpoint: str, params=None):
        if not endpoint.endswith(":/content"):
            raise _http_error(404)
        path = unquote(endpoint.split("/root:/", 1)[1].rsplit(":/content", 1)[0]).strip("/")
        if path in self.downloaded_files:
            return self.downloaded_files[path]
        raise _http_error(404)

    async def put_bytes(self, endpoint: str, content: bytes, content_type: str = ""):
        path = unquote(endpoint.split("/root:/", 1)[1].rsplit(":/content", 1)[0]).strip("/")
        self.put_calls.append((endpoint, content))
        self.downloaded_files[path] = content
        return {"webUrl": "https://example/upload.xlsx"}

    async def delete(self, endpoint: str, params=None):
        self.delete_calls.append(endpoint)
        path = unquote(endpoint.split("/root:/", 1)[1].rstrip(":").split(":", 1)[0]).strip("/")
        if path in self.force_404_paths:
            raise _http_error(404)
        self.force_404_paths.add(path)
        return None


def _set_env() -> None:
    os.environ["GRAPH_SHAREPOINT_SITE_SEARCH"] = "SITIO"
    os.environ["GRAPH_SHAREPOINT_DRIVE_NAME"] = "DRIVE"
    os.environ["GRAPH_PAYMENT_VALIDATION_REVIEW_PATH"] = "revision"
    os.environ["GRAPH_CLIENTS_BASE_PATH"] = "clientes"
    os.environ["GRAPH_VALIDATION_FILE_PREFIX"] = "val"
    os.environ["GRAPH_BANK_PAYMENTS_FILE_PATH"] = "banco.xlsx"
    os.environ["GRAPH_BANK_PAYMENTS_FILE_PATH_BANCOLOMBIA"] = "banco.xlsx"


def _minimal_bank_xlsx() -> bytes:
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(["Fecha", "Crédito", "Concepto", "Tipo Aplicación", "Transacción"])
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def _control_with_active_revision(
    *,
    bank_code: str = "banco_bogota",
    bank_name: str = "Banco de Bogotá",
    process_key: str = "payment-validation|banco_bogota|2026-06-01|abc",
    validation_path: str = "revision/gone.xlsx",
    estado: str = "REVISION_CREADA",
) -> bytes:
    raw = _build_process_control_workbook_bytes(bank_code, bank_name)
    wb = openpyxl.load_workbook(io.BytesIO(raw), data_only=False)
    try:
        ws = wb[SHEET_NAME]
        headers = [ws.cell(1, c).value for c in range(1, ws.max_column + 1)]
        col = {h: i + 1 for i, h in enumerate(headers)}
        ws.cell(2, col["ProcessKey"], value=process_key)
        ws.cell(2, col["EstadoProceso"], value=estado)
        ws.cell(2, col["IsActive"], value=True)
        ws.cell(2, col["ValidationFilePath"], value=validation_path)
        buf = io.BytesIO()
        wb.save(buf)
        return buf.getvalue()
    finally:
        wb.close()


def _read_control_row(raw: bytes) -> dict[str, object]:
    wb = openpyxl.load_workbook(io.BytesIO(raw), data_only=True)
    try:
        ws = wb[SHEET_NAME]
        headers = [ws.cell(1, c).value for c in range(1, ws.max_column + 1)]
        col = {h: i + 1 for i, h in enumerate(headers) if h}
        return {name: ws.cell(2, idx).value for name, idx in col.items()}
    finally:
        wb.close()


def test_cancel_resets_revision_creada_to_vacio_and_deletes_review_file():
    _set_env()
    client = MockGraphClientCancel()
    client.downloaded_files[PROCESS_CONTROL_BANK_FILE_BOGOTA] = _control_with_active_revision()
    client.downloaded_files["revision/gone.xlsx"] = b"fake-xlsx"

    res = asyncio.run(
        cancel_active_payment_validation(client, bank_code="banco_bogota")
    )
    assert res["already_cancelled"] is False
    assert res["process_control_updated"] is True
    assert res["process_control_estado"] == "VACIO"
    assert res["process_key_cleared"]
    assert res["review_file_cleanup"]["deleted"] is True
    assert client.delete_calls

    row = _read_control_row(client.downloaded_files[PROCESS_CONTROL_BANK_FILE_BOGOTA])
    assert row["EstadoProceso"] == "VACIO"
    assert str(row["IsActive"]).strip().lower() in ("false", "falso", "0")
    assert not (row.get("ProcessKey") or "")
    assert not (row.get("ValidationFilePath") or "")
    assert row["BankCode"] == "banco_bogota"
    assert row["LastCompletedStep"] == "CANCEL"


def test_cancel_idempotent_when_already_idle():
    _set_env()
    client = MockGraphClientCancel()
    client.downloaded_files[PROCESS_CONTROL_BANK_FILE_BOGOTA] = (
        _build_process_control_workbook_bytes("banco_bogota", "Banco de Bogotá")
    )

    res = asyncio.run(
        cancel_active_payment_validation(client, bank_code="banco_bogota")
    )
    assert res["already_cancelled"] is True
    assert res["process_control_updated"] is False
    assert not client.put_calls


def test_cancel_auto_detects_single_active_bank_without_bank_code():
    _set_env()
    client = MockGraphClientCancel()
    client.downloaded_files[PROCESS_CONTROL_BANK_FILE_BOGOTA] = (
        _build_process_control_workbook_bytes("banco_bogota", "Banco de Bogotá")
    )
    client.downloaded_files[PROCESS_CONTROL_BANK_FILE_BANCOLOMBIA] = _control_with_active_revision(
        bank_code="banco_bancolombia",
        bank_name="Bancolombia",
        process_key="payment-validation|banco_bancolombia|2026-07-29|x",
        validation_path="revision/bc.xlsx",
    )
    client.downloaded_files["revision/bc.xlsx"] = b"fake"

    res = asyncio.run(cancel_active_payment_validation(client, bank_code=None))
    assert res["already_cancelled"] is False
    assert res["bank_code"] == "banco_bancolombia"
    assert res["bank_code_source"] == "auto_detected"
    assert res["ready_banks_detected"] == ["banco_bancolombia"]
    assert res["process_control_estado"] == "VACIO"


def test_cancel_auto_detect_raises_when_both_banks_active():
    _set_env()
    client = MockGraphClientCancel()
    client.downloaded_files[PROCESS_CONTROL_BANK_FILE_BOGOTA] = _control_with_active_revision()
    client.downloaded_files[PROCESS_CONTROL_BANK_FILE_BANCOLOMBIA] = _control_with_active_revision(
        bank_code="banco_bancolombia",
        bank_name="Bancolombia",
        process_key="payment-validation|banco_bancolombia|2026-07-29|x",
    )
    with pytest.raises(ValueError, match="MULTIPLE_READY_PROCESSES"):
        asyncio.run(cancel_active_payment_validation(client, bank_code=None))


def test_cancel_auto_detect_both_idle_is_idempotent():
    _set_env()
    client = MockGraphClientCancel()
    client.downloaded_files[PROCESS_CONTROL_BANK_FILE_BOGOTA] = (
        _build_process_control_workbook_bytes("banco_bogota", "Banco de Bogotá")
    )
    client.downloaded_files[PROCESS_CONTROL_BANK_FILE_BANCOLOMBIA] = (
        _build_process_control_workbook_bytes("banco_bancolombia", "Bancolombia")
    )
    res = asyncio.run(cancel_active_payment_validation(client, bank_code=None))
    assert res["already_cancelled"] is True
    assert res["bank_code_source"] == "auto_detected"
    assert res["process_control_updated"] is False


def test_cancel_refuses_finalizado():
    _set_env()
    client = MockGraphClientCancel()
    client.downloaded_files[PROCESS_CONTROL_BANK_FILE_BOGOTA] = _control_with_active_revision(
        estado="FINALIZADO"
    )
    with pytest.raises(ValueError, match="cancel_not_allowed\\|FINALIZADO"):
        asyncio.run(cancel_active_payment_validation(client, bank_code="banco_bogota"))


def test_cancel_process_key_mismatch():
    _set_env()
    client = MockGraphClientCancel()
    client.downloaded_files[PROCESS_CONTROL_BANK_FILE_BOGOTA] = _control_with_active_revision(
        process_key="payment-validation|banco_bogota|2026-06-01|abc"
    )
    with pytest.raises(ValueError, match="process_key_mismatch"):
        asyncio.run(
            cancel_active_payment_validation(
                client,
                bank_code="banco_bogota",
                process_key="payment-validation|banco_bogota|2026-06-02|xyz",
            )
        )


def test_cancel_then_generate_no_longer_blocked_by_active_process():
    """Tras cancel, Generate del mismo día no debe caer en active_process_exists."""
    _set_env()
    client = MockGraphClientCancel()
    client.children = []
    client.folder_children["clientes"] = []
    client.downloaded_files["banco.xlsx"] = _minimal_bank_xlsx()
    client.downloaded_files[PROCESS_CONTROL_BANK_FILE_BOGOTA] = _control_with_active_revision(
        process_key="payment-validation|banco_bogota|2026-05-31|old",
        validation_path="revision/old.xlsx",
    )
    # Simula Excel ya borrado en SharePoint.
    client.force_404_paths.add("revision/old.xlsx")

    cancel_res = asyncio.run(
        cancel_active_payment_validation(client, bank_code="banco_bogota")
    )
    assert cancel_res["process_control_estado"] == "VACIO"

    gen = asyncio.run(
        generate_payment_validation(client, date(2026, 6, 1), bank_code="banco_bogota")
    )
    assert gen["already_generated"] is False
    assert gen["process_control_estado"] == "REVISION_CREADA"
    assert gen["validation_file"].startswith("val_banco_bogota_2026-06-01")


def test_enrichment_cancel_completed_and_failed():
    completed = enrich_job_for_http_response(
        {
            "job_id": "c1",
            "type": "cancel_active_process",
            "status": "completed",
            "result": {
                "already_cancelled": False,
                "bank_code": "banco_bancolombia",
                "bank_name": "Bancolombia",
            },
        }
    )
    assert completed["severity"] == "success"
    assert "cancel" in completed["user_message"].lower() or "libre" in completed["user_message"].lower()
    assert "Generate" in completed["next_action"] or "gener" in completed["next_action"].lower()

    failed = enrich_job_for_http_response(
        {
            "job_id": "c2",
            "type": "cancel_active_process",
            "status": "failed",
            "error": {"type": "ValueError", "message": "cancel_not_allowed|FINALIZADO|pk"},
        }
    )
    assert failed["severity"] == "error"
    assert failed["error"]["error_code"] == "cancel_not_allowed"
    assert "protegido" in failed["error"]["next_action"].lower() or "soporte" in failed["error"]["next_action"].lower()


def test_enrichment_active_process_mentions_resume_not_manual_edit():
    failed = enrich_job_for_http_response(
        {
            "job_id": "g1",
            "type": "generate",
            "status": "failed",
            "error": {
                "type": "ValueError",
                "message": "active_process_exists|payment-validation|banco_bogota|2026-07-29|x",
            },
        }
    )
    assert failed["error"]["error_code"] == "active_process_exists"
    um = failed["error"]["user_message"].lower()
    na = failed["error"]["next_action"].lower()
    assert "validación activa" in um or "proceso existente" in um
    assert "retomar" in na
    assert "protegido" in na
    assert "|" not in failed["error"]["user_message"]
    assert "PENDIENTE_ASIENTOS" not in failed["error"]["user_message"]
