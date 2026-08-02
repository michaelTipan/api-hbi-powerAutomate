"""
Verifica los overlays de entorno (`config/environments/*.env`).

Sin red ni SharePoint: comprueba que las rutas que el código resuelve con cada
overlay son exactamente las esperadas, que producción no arrastra rutas de sandbox
y que la carpeta de pruebas queda excluida del recorrido de clientes.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.application.config.payment_validation_settings import (
    BANK_CODE_BANCOLOMBIA,
    BANK_CODE_BOGOTA,
    get_payment_validation_paths,
    resolve_bank_control_file_path,
    resolve_bank_input_file_path,
    resolve_client_folder_exclusions,
    resolve_correos_xlsx_path,
    resolve_execution_run_logs_folder_path,
    resolve_ibr_workbook_path,
)
from app.application.sharepoint_resolution import accounting_site_is_configured

OVERLAY_DIR = Path(__file__).resolve().parents[1] / "config" / "environments"

PROD_CLIENTS_BASE = "INFORMACION CREDITOS-CLIENTES"
SANDBOX_CLIENTS_BASE = (
    "INFORMACION CREDITOS-CLIENTES/03 COMWARE PRUEBAS- INFORMACION CREDITOS CLIENTES"
)

# Claves que el .env de runtime puede traer del entorno anterior y que deben quedar
# limpias antes de aplicar un overlay (el script hace lo mismo con UNSET_KEYS).
_ENV_KEYS_TO_CLEAR = (
    "GRAPH_CLIENTS_BASE_PATH",
    "GRAPH_CLIENTS_EXCLUDED_FOLDERS",
    "GRAPH_SHAREPOINT_FILE_PATH",
    "GRAPH_SHAREPOINT_SITE_SEARCH",
    "GRAPH_OPERATIONS_SITE_HOSTNAME",
    "GRAPH_OPERATIONS_SITE_PATH",
    "GRAPH_ACCOUNTING_SITE_HOSTNAME",
    "GRAPH_ACCOUNTING_SITE_PATH",
    "GRAPH_ACCOUNTING_BOGOTA_FOLDER_NAME",
    "GRAPH_ACCOUNTING_BANCOLOMBIA_FOLDER_NAME",
    "GRAPH_MERGE_COMPOSITE_OUTPUT_FOLDER_PATH",
    "GRAPH_VALIDAR_NOTIFY_CORREOS_XLSX_PATH",
    "GRAPH_IBR_DIARIO_PATH",
    "GRAPH_FOLLOWUP_PAGOS_ADELANTADOS_PATH",
    "GRAPH_PAYMENT_VALIDATION_CONTROL_PATH",
    "GRAPH_PAYMENT_VALIDATION_REVIEW_PATH",
    "GRAPH_PAYMENT_VALIDATION_HISTORY_PATH",
    "GRAPH_PAYMENT_VALIDATION_LOGS_PATH",
    "GRAPH_EXECUTION_RUN_LOGS_PATH",
    "PAYMENT_BANK_BOGOTA_INPUT_FILE_PATH",
    "PAYMENT_BANK_BANCOLOMBIA_INPUT_FILE_PATH",
    "PAYMENT_VALIDATION_BASE_FOLDER",
    "PAYMENT_VALIDATION_CONTROL_FOLDER",
    "PAYMENT_VALIDATION_REVIEW_FOLDER",
    "PAYMENT_VALIDATION_HISTORICAL_FOLDER",
    "PAYMENT_VALIDATION_LOGS_FOLDER",
    "PAYMENT_VALIDATION_EXECUTION_LOGS_FOLDER",
    "PAYMENT_VALIDATION_EMAIL_FOLDER",
    "PAYMENT_VALIDATION_ASIENTOS_FOLDER",
    "ACTIVE_ENVIRONMENT",
    "EXECUTION_RUN_LOG_ENABLED",
)


def read_overlay(name: str) -> dict[str, str]:
    """Pares clave=valor del overlay, ignorando comentarios."""
    values: dict[str, str] = {}
    for raw in (OVERLAY_DIR / f"{name}.env").read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        values[key.strip()] = value
    return values


def apply_overlay(monkeypatch: pytest.MonkeyPatch, name: str) -> dict[str, str]:
    """Aplica el overlay al entorno del proceso igual que `switch-env.ps1`."""
    for key in _ENV_KEYS_TO_CLEAR:
        monkeypatch.delenv(key, raising=False)

    overlay = read_overlay(name)
    unset = [k.strip() for k in overlay.pop("UNSET_KEYS", "").split(",") if k.strip()]
    overlay.pop("ENV_READY", None)
    for key in unset:
        monkeypatch.delenv(key, raising=False)
    for key, value in overlay.items():
        if key in unset:
            continue
        monkeypatch.setenv(key, value)
    return overlay


def test_production_overlay_has_no_pending_placeholders():
    overlay = read_overlay("production")
    pending = [k for k, v in overlay.items() if "TODO_SET_" in v]
    assert pending == []
    assert overlay["ENV_READY"] == "true"


def test_production_paths_resolve_under_real_clients_root(monkeypatch: pytest.MonkeyPatch):
    apply_overlay(monkeypatch, "production")

    paths = get_payment_validation_paths()
    base = f"{PROD_CLIENTS_BASE}/02 VALIDACION PAGOS"

    assert paths.base_folder == base
    assert paths.control == f"{base}/90 ACCESO RESTRINGIDO/03 CONTROL TECNICO"
    assert paths.review == f"{base}/01 REVISION"
    assert paths.historical == f"{base}/03 HISTORICO"
    assert paths.logs == f"{base}/90 ACCESO RESTRINGIDO/01 TRAZABILIDAD"
    assert paths.email == f"{base}/04 CORREOS ENVIADOS"
    assert paths.archive == f"{base}/90 ACCESO RESTRINGIDO/04 ARCHIVO PROCESOS"
    assert resolve_execution_run_logs_folder_path() == f"{base}/90 ACCESO RESTRINGIDO/02 LOGS"

    assert resolve_bank_input_file_path(BANK_CODE_BOGOTA) == (
        f"{PROD_CLIENTS_BASE}/01 CARGA TRANSACCIONES BANCO/BANCO_BOGOTA.xlsx"
    )
    assert resolve_bank_input_file_path(BANK_CODE_BANCOLOMBIA) == (
        f"{PROD_CLIENTS_BASE}/01 CARGA TRANSACCIONES BANCO/BANCO_BANCOLOMBIA.xlsx"
    )
    assert resolve_bank_control_file_path(BANK_CODE_BOGOTA) == (
        f"{paths.control}/control_proceso_validacion_pagos_banco_bogota.xlsx"
    )
    assert resolve_correos_xlsx_path() == f"{base}/02 CONTROL OPERATIVO/CORREOS.xlsx"
    assert resolve_ibr_workbook_path() == f"{base}/02 CONTROL OPERATIVO/IBR_DIARIO.xlsx"


def test_production_never_points_to_sandbox_tree(monkeypatch: pytest.MonkeyPatch):
    apply_overlay(monkeypatch, "production")

    paths = get_payment_validation_paths()
    candidates = [
        paths.base_folder,
        paths.control,
        paths.review,
        paths.historical,
        paths.logs,
        paths.email,
        paths.archive,
        resolve_execution_run_logs_folder_path(),
        resolve_bank_input_file_path(BANK_CODE_BOGOTA),
        resolve_bank_input_file_path(BANK_CODE_BANCOLOMBIA),
        resolve_correos_xlsx_path(),
        resolve_ibr_workbook_path(),
    ]
    for path in candidates:
        assert "COMWARE" not in path.upper(), path
        assert "PRUEBAS" not in path.upper(), path
        assert path.startswith(f"{PROD_CLIENTS_BASE}/"), path


def test_production_excludes_sandbox_folder_from_clients(monkeypatch: pytest.MonkeyPatch):
    apply_overlay(monkeypatch, "production")

    exclusions = resolve_client_folder_exclusions(PROD_CLIENTS_BASE)
    assert "01 CARGA TRANSACCIONES BANCO" in exclusions
    assert "02 VALIDACION PAGOS" in exclusions
    assert "03 COMWARE PRUEBAS- INFORMACION CREDITOS CLIENTES" in exclusions


def test_production_sends_consolidated_pdf_to_accounting(monkeypatch: pytest.MonkeyPatch):
    apply_overlay(monkeypatch, "production")

    assert accounting_site_is_configured() is True
    # La carpeta de consolidados del sandbox no debe sobrevivir al cambio de entorno.
    import os

    assert os.getenv("PAYMENT_VALIDATION_ASIENTOS_FOLDER") is None
    assert os.getenv("GRAPH_MERGE_COMPOSITE_OUTPUT_FOLDER_PATH") is None


def test_sandbox_paths_use_renamed_test_folder(monkeypatch: pytest.MonkeyPatch):
    apply_overlay(monkeypatch, "sandbox")

    paths = get_payment_validation_paths()
    base = f"{SANDBOX_CLIENTS_BASE}/02 VALIDACION PAGOS"

    assert paths.base_folder == base
    assert paths.control == f"{base}/90 ACCESO RESTRINGIDO/03 CONTROL TECNICO"
    assert paths.archive == f"{base}/90 ACCESO RESTRINGIDO/04 ARCHIVO PROCESOS"
    assert paths.asientos == f"{base}/99 SOPORTES DE PAGO CONSOLIDADOS - PRUEBAS"
    assert resolve_bank_input_file_path(BANK_CODE_BOGOTA) == (
        f"{SANDBOX_CLIENTS_BASE}/01 CARGA TRANSACCIONES BANCO/BANCO_BOGOTA.xlsx"
    )
    assert accounting_site_is_configured() is False


def test_sandbox_and_production_share_the_same_subfolder_layout(
    monkeypatch: pytest.MonkeyPatch,
):
    """Misma organización interna en los dos entornos (solo cambia la raíz)."""
    layout_keys = (
        "PAYMENT_VALIDATION_CONTROL_FOLDER",
        "PAYMENT_VALIDATION_REVIEW_FOLDER",
        "PAYMENT_VALIDATION_HISTORICAL_FOLDER",
        "PAYMENT_VALIDATION_LOGS_FOLDER",
        "PAYMENT_VALIDATION_EXECUTION_LOGS_FOLDER",
        "PAYMENT_VALIDATION_ARCHIVE_FOLDER",
        "PAYMENT_VALIDATION_EMAIL_FOLDER",
    )
    sandbox = read_overlay("sandbox")
    production = read_overlay("production")
    for key in layout_keys:
        assert sandbox[key] == production[key], key
