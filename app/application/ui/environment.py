"""Ambiente activo expuesto a la UI (nunca hardcodeado en el frontend)."""
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Literal

ActiveEnvironment = Literal["sandbox", "production", "unknown"]


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
            display_label="SANDBOX / PRUEBAS",
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
