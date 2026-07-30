"""Construcción determinista de CREDIT_KEY y DOC_KEY."""

from __future__ import annotations

from app.domain.exceptions import ExtractIndexError
from app.domain.models.extract_index import (
    CreditKey,
    DocKey,
    ExtractIndexEnvironment,
)


def parse_environment(value: str | ExtractIndexEnvironment) -> ExtractIndexEnvironment:
    if isinstance(value, ExtractIndexEnvironment):
        return value
    raw = str(value or "").strip().lower()
    if raw in ("production", "prod"):
        return ExtractIndexEnvironment.PRODUCTION
    if raw in ("sandbox", "test", "pruebas"):
        return ExtractIndexEnvironment.SANDBOX
    raise ExtractIndexError(f"ENVIRONMENT inválido: {value!r}")


def _require_non_empty(label: str, value: str) -> str:
    cleaned = str(value or "").strip()
    if not cleaned:
        raise ExtractIndexError(f"{label} vacío; requerido para clave de índice")
    if "|" in cleaned:
        raise ExtractIndexError(f"{label} no puede contener '|': {cleaned!r}")
    return cleaned


def build_credit_key(
    *,
    environment: str | ExtractIndexEnvironment,
    drive_id: str,
    credit_folder_item_id: str,
) -> CreditKey:
    """CREDIT_KEY = {environment}|{drive_id}|{credit_folder_item_id}."""
    env = parse_environment(environment)
    return CreditKey(
        environment=env,
        drive_id=_require_non_empty("drive_id", drive_id),
        credit_folder_item_id=_require_non_empty(
            "credit_folder_item_id", credit_folder_item_id
        ),
    )


def build_doc_key(
    *,
    environment: str | ExtractIndexEnvironment,
    drive_id: str,
    item_id: str,
) -> DocKey:
    """DOC_KEY = {environment}|{drive_id}|{item_id}."""
    env = parse_environment(environment)
    return DocKey(
        environment=env,
        drive_id=_require_non_empty("drive_id", drive_id),
        item_id=_require_non_empty("item_id", item_id),
    )


def parse_credit_key(value: str) -> CreditKey:
    parts = str(value or "").split("|")
    if len(parts) != 3:
        raise ExtractIndexError(f"CREDIT_KEY malformada: {value!r}")
    return build_credit_key(
        environment=parts[0],
        drive_id=parts[1],
        credit_folder_item_id=parts[2],
    )


def parse_doc_key(value: str) -> DocKey:
    parts = str(value or "").split("|")
    if len(parts) != 3:
        raise ExtractIndexError(f"DOC_KEY malformada: {value!r}")
    return build_doc_key(
        environment=parts[0],
        drive_id=parts[1],
        item_id=parts[2],
    )


def assert_same_environment_and_drive(
    *,
    environment: ExtractIndexEnvironment,
    drive_id: str,
    credit_key: CreditKey,
    doc_key: DocKey,
) -> None:
    """Impide mezclar ambientes o drives en una misma operación."""
    if credit_key.environment != environment or doc_key.environment != environment:
        raise ExtractIndexError(
            "ENVIRONMENT del candidato no coincide con el ambiente activo"
        )
    if credit_key.drive_id != drive_id or doc_key.drive_id != drive_id:
        raise ExtractIndexError("DRIVE_ID del candidato no coincide con el drive activo")
    if credit_key.environment != doc_key.environment:
        raise ExtractIndexError("CREDIT_KEY y DOC_KEY con ENVIRONMENT distinto")
    if credit_key.drive_id != doc_key.drive_id:
        raise ExtractIndexError("CREDIT_KEY y DOC_KEY con DRIVE_ID distinto")
