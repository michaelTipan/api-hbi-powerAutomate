"""Preflight lógico del bootstrap (sin Graph real)."""

from __future__ import annotations

from app.application.config.extract_index_settings import (
    ExtractIndexMode,
    ExtractIndexSettings,
    get_extract_index_settings,
)
from app.application.services.extract_index.bootstrap_campaign import logical_preflight
from app.application.services.extract_index.bootstrap_models import LogicalPreflightResult


def run_extract_index_preflight(
    *,
    settings: ExtractIndexSettings | None = None,
    has_control_repo: bool = True,
    has_index_repo: bool = True,
    has_lock: bool = True,
    has_scope: bool = True,
    has_readonly_tree: bool = True,
    control_schema_ok: bool = True,
    index_schema_ok: bool = True,
) -> LogicalPreflightResult:
    cfg = settings or get_extract_index_settings()
    return logical_preflight(
        bootstrap_enabled=cfg.bootstrap_enabled,
        mode=cfg.mode.value if isinstance(cfg.mode, ExtractIndexMode) else str(cfg.mode),
        has_control_repo=has_control_repo,
        has_index_repo=has_index_repo,
        has_lock=has_lock,
        has_scope=has_scope,
        has_readonly_tree=has_readonly_tree,
        control_schema_ok=control_schema_ok,
        index_schema_ok=index_schema_ok,
    )
