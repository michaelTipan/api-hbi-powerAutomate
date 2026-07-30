"""Configuración del índice de extractos (flags; sin lógica financiera)."""

from __future__ import annotations

import os
from dataclasses import dataclass
from enum import Enum

from app.domain.models.extract_index import ExtractIndexEnvironment


class ExtractIndexMode(str, Enum):
    OFF = "off"
    SHADOW = "shadow"
    ACTIVE = "active"


def _env_bool(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in ("1", "true", "yes", "on")


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None or not str(raw).strip():
        return default
    try:
        return int(str(raw).strip())
    except ValueError:
        return default


def _env_float(name: str, default: float) -> float:
    raw = os.getenv(name)
    if raw is None or not str(raw).strip():
        return default
    try:
        return float(str(raw).strip())
    except ValueError:
        return default


def resolve_active_environment() -> ExtractIndexEnvironment:
    """Lee ACTIVE_ENVIRONMENT; default sandbox por seguridad."""
    raw = (os.getenv("ACTIVE_ENVIRONMENT") or "sandbox").strip().lower()
    if raw in ("production", "prod"):
        return ExtractIndexEnvironment.PRODUCTION
    return ExtractIndexEnvironment.SANDBOX


def resolve_extract_index_mode() -> ExtractIndexMode:
    raw = (os.getenv("EXTRACT_INDEX_MODE") or "off").strip().lower()
    if raw == ExtractIndexMode.SHADOW.value:
        return ExtractIndexMode.SHADOW
    if raw == ExtractIndexMode.ACTIVE.value:
        return ExtractIndexMode.ACTIVE
    return ExtractIndexMode.OFF


@dataclass(frozen=True, slots=True)
class ExtractIndexSettings:
    """Settings de runtime del índice (Fase 1: sin cablear Generate)."""

    mode: ExtractIndexMode
    environment: ExtractIndexEnvironment
    bootstrap_enabled: bool
    max_clients_per_chunk: int
    max_seconds_per_chunk: int
    shadow_max_credits: int | None
    shadow_sample_pct: float | None
    indice_list_display_name: str
    control_list_display_name: str
    graph_retry_max: int
    graph_retry_base_seconds: float


def get_extract_index_settings() -> ExtractIndexSettings:
    shadow_max_raw = (os.getenv("EXTRACT_INDEX_SHADOW_MAX_CREDITS") or "").strip()
    shadow_pct_raw = (os.getenv("EXTRACT_INDEX_SHADOW_SAMPLE_PCT") or "").strip()
    return ExtractIndexSettings(
        mode=resolve_extract_index_mode(),
        environment=resolve_active_environment(),
        bootstrap_enabled=_env_bool("EXTRACT_INDEX_BOOTSTRAP_ENABLED", False),
        max_clients_per_chunk=max(1, _env_int("BOOTSTRAP_MAX_CLIENTS_PER_CHUNK", 3)),
        max_seconds_per_chunk=max(30, _env_int("BOOTSTRAP_MAX_SECONDS_PER_CHUNK", 180)),
        shadow_max_credits=int(shadow_max_raw) if shadow_max_raw.isdigit() else None,
        shadow_sample_pct=(
            _env_float("EXTRACT_INDEX_SHADOW_SAMPLE_PCT", 0.0)
            if shadow_pct_raw
            else None
        ),
        indice_list_display_name=(
            os.getenv("EXTRACT_INDEX_LIST_NAME") or "INDICE_EXTRACTOS"
        ).strip(),
        control_list_display_name=(
            os.getenv("EXTRACT_INDEX_CONTROL_LIST_NAME") or "CONTROL_INDICE_EXTRACTOS"
        ).strip(),
        graph_retry_max=max(1, _env_int("EXTRACT_INDEX_GRAPH_RETRY_MAX", 4)),
        graph_retry_base_seconds=max(
            0.1, _env_float("EXTRACT_INDEX_GRAPH_RETRY_BASE_SECONDS", 0.5)
        ),
    )
