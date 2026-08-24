"""Store de Control en disco: write atómico e aislamiento por entorno."""

from __future__ import annotations

from pathlib import Path

from app.application.process_control_store import (
    build_store_payload,
    control_store_dir,
    control_store_path,
    load_control_payload,
    persist_control_payload,
    process_control_store_mode,
)


def test_store_mode_defaults_to_dual(monkeypatch) -> None:
    monkeypatch.delenv("PROCESS_CONTROL_STORE", raising=False)
    assert process_control_store_mode() == "dual"
    monkeypatch.setenv("PROCESS_CONTROL_STORE", "local")
    assert process_control_store_mode() == "local"
    monkeypatch.setenv("PROCESS_CONTROL_STORE", "excel")
    assert process_control_store_mode() == "excel"
    monkeypatch.setenv("PROCESS_CONTROL_STORE", "nope")
    assert process_control_store_mode() == "dual"


def test_azure_default_dir_uses_wwwroot(monkeypatch) -> None:
    monkeypatch.delenv("PAYMENT_VALIDATION_CONTROL_STORE_DIR", raising=False)
    monkeypatch.setenv("WEBSITE_INSTANCE_ID", "instance-1")
    assert control_store_dir() == Path("/home/site/wwwroot/.payment_validation_control")


def test_atomic_write_and_load(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("PAYMENT_VALIDATION_CONTROL_STORE_DIR", str(tmp_path))
    monkeypatch.setenv("ACTIVE_ENVIRONMENT", "sandbox")
    payload = build_store_payload(
        environment="sandbox",
        bank_code="banco_bogota",
        control_file_path="control/bogota.xlsx",
        cells={"EstadoProceso": "FINALIZADO", "IsActive": "true", "GenerateJobId": "j-1"},
    )
    assert persist_control_payload(payload) is True
    path = control_store_path(environment="sandbox", bank_code="banco_bogota")
    assert path is not None and path.is_file()
    assert not path.with_name(path.name + ".tmp").exists()
    loaded = load_control_payload(environment="sandbox", bank_code="banco_bogota")
    assert loaded is not None
    assert loaded["cells"]["EstadoProceso"] == "FINALIZADO"
    assert loaded["cells"]["GenerateJobId"] == "j-1"
    assert loaded["bank_code"] == "banco_bogota"


def test_environment_isolation_sandbox_vs_production(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("PAYMENT_VALIDATION_CONTROL_STORE_DIR", str(tmp_path))
    persist_control_payload(
        build_store_payload(
            environment="sandbox",
            bank_code="banco_bogota",
            control_file_path="s.xlsx",
            cells={"EstadoProceso": "GENERANDO"},
        )
    )
    persist_control_payload(
        build_store_payload(
            environment="production",
            bank_code="banco_bogota",
            control_file_path="p.xlsx",
            cells={"EstadoProceso": "FINALIZADO"},
        )
    )
    sand = load_control_payload(environment="sandbox", bank_code="banco_bogota")
    prod = load_control_payload(environment="production", bank_code="banco_bogota")
    assert sand is not None and prod is not None
    assert sand["cells"]["EstadoProceso"] == "GENERANDO"
    assert prod["cells"]["EstadoProceso"] == "FINALIZADO"
    assert (tmp_path / "sandbox" / "banco_bogota.json").is_file()
    assert (tmp_path / "production" / "banco_bogota.json").is_file()
