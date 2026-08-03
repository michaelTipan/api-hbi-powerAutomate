"""Ambiente activo expuesto a la UI (nunca hardcodeado en el frontend)."""
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Literal

ActiveEnvironment = Literal["sandbox", "production", "unknown"]

# Ambientes donde la UI puede ofrecer escrituras (flags + write gate aparte).
_UI_WRITE_ENVIRONMENTS = frozenset({"sandbox", "production"})


@dataclass(frozen=True)
class UiEnvironmentInfo:
    environment: ActiveEnvironment
    display_label: str
    raw_value: str


def resolve_active_environment() -> UiEnvironmentInfo:
    raw = (os.getenv("ACTIVE_ENVIRONMENT") or "").strip().lower()
    if raw == "sandbox":
        return UiEnvironmentInfo(
            environment="sandbox",
            display_label="Entorno de validación",
            raw_value=raw,
        )
    if raw == "production":
        return UiEnvironmentInfo(
            environment="production",
            display_label="PRODUCCIÓN",
            raw_value=raw,
        )
    return UiEnvironmentInfo(
        environment="unknown",
        display_label="AMBIENTE NO CONFIGURADO",
        raw_value=raw or "(no definido)",
    )


def ui_write_environment_allowed(
    environment: ActiveEnvironment | str | None = None,
) -> bool:
    """True si el ambiente admite escrituras UI (sandbox o production)."""
    if environment is None:
        environment = resolve_active_environment().environment
    return str(environment).strip().lower() in _UI_WRITE_ENVIRONMENTS
