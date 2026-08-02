"""Unit tests Fase 2: snapshots de archivo de procesos."""
from __future__ import annotations

from app.application.ui.process_archive import (
    archive_filename,
    archive_relative_path,
    build_snapshot_payload,
    operational_status_for_archive_estado,
    parse_archive_filename,
    snapshot_from_control_snap,
    snapshot_from_dict,
)


class _Snap:
    process_key = "payment-validation|banco_bogota|2026-08-02|abc-1"
    process_id = "abc-1"
    bank_code = "banco_bogota"
    bank_name = "Banco de Bogotá"
    estado_proceso = "AMORTIZACION_APLICADA"
    validation_file_path = "01 REVISION/validacion.xlsx"
    historical_file_path = "03 HISTORICO/cartera.xlsx"
    secretary_file_path = "03 HISTORICO/soporte.xlsx"
    email_pdf_path = "04 CORREOS ENVIADOS/mail.pdf"
    merge_manifest_path = "90 ACCESO RESTRINGIDO/01 TRAZABILIDAD/merge.json"


def test_archive_filename_and_parse(monkeypatch):
    monkeypatch.setenv("PAYMENT_VALIDATION_BASE_FOLDER", "BASE")
    monkeypatch.setenv(
        "PAYMENT_VALIDATION_ARCHIVE_FOLDER",
        "90 ACCESO RESTRINGIDO/04 ARCHIVO PROCESOS",
    )
    name = archive_filename(
        bank_code="banco_bogota",
        process_date="2026-08-02",
        process_id="abc-1",
    )
    assert name == "proceso_banco_bogota_2026-08-02_abc-1.json"
    meta = parse_archive_filename(name)
    assert meta == {
        "bank_code": "banco_bogota",
        "process_date": "2026-08-02",
        "process_id": "abc-1",
    }
    rel = archive_relative_path(
        bank_code="banco_bogota",
        process_date="2026-08-02",
        process_id="abc-1",
    )
    assert rel.endswith("/proceso_banco_bogota_2026-08-02_abc-1.json")
    assert "04 ARCHIVO PROCESOS" in rel


def test_build_snapshot_from_control():
    snap = snapshot_from_control_snap(
        _Snap(),
        archive_reason="amortization_applied",
        control_estado_proceso="AMORTIZACION_APLICADA",
    )
    assert snap is not None
    assert snap.process_key.endswith("abc-1")
    assert snap.operational_status == "COMPLETADO"
    assert snap.paths["historical_file"] == "03 HISTORICO/cartera.xlsx"
    assert snap.archive_reason == "amortization_applied"
    data = snap.to_dict()
    restored = snapshot_from_dict(data, archive_path=snap.archive_path)
    assert restored.process_key == snap.process_key
    assert restored.paths["email_pdf"] == "04 CORREOS ENVIADOS/mail.pdf"


def test_snapshot_skips_empty_process_key():
    class Empty:
        process_key = ""
        process_id = ""
        bank_code = "banco_bogota"
        bank_name = ""
        estado_proceso = "VACIO"
        validation_file_path = ""
        historical_file_path = ""
        secretary_file_path = ""
        email_pdf_path = ""
        merge_manifest_path = ""

    assert snapshot_from_control_snap(Empty(), archive_reason="x") is None


def test_operational_status_mapping():
    assert operational_status_for_archive_estado("AMORTIZACION_APLICADA") == "COMPLETADO"
    assert operational_status_for_archive_estado("ERROR_APPLY") == "ERROR_RECUPERABLE"


def test_build_payload_extracts_date_from_key(monkeypatch):
    monkeypatch.setenv("PAYMENT_VALIDATION_BASE_FOLDER", "BASE")
    monkeypatch.setenv(
        "PAYMENT_VALIDATION_ARCHIVE_FOLDER",
        "90 ACCESO RESTRINGIDO/04 ARCHIVO PROCESOS",
    )
    snap = build_snapshot_payload(
        process_key="payment-validation|banco_bancolombia|2026-07-15|xyz",
        process_id="",
        bank_code="banco_bancolombia",
        bank_name="Bancolombia",
        process_date=None,
        control_estado_proceso="AMORTIZACION_APLICADA",
        archive_reason="generate_overwrite",
        environment="sandbox",
    )
    assert snap.process_date == "2026-07-15"
    assert snap.process_id == "xyz"
    assert snap.environment == "sandbox"
