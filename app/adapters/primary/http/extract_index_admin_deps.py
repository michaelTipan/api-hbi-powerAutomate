"""Gates y estado inyectable del router admin extract-index (3A2)."""

from __future__ import annotations

from dataclasses import dataclass

from fastapi import HTTPException, Request

from app.application.config.extract_index_settings import (
    ExtractIndexMode,
    ExtractIndexSettings,
)
from app.application.services.extract_index.bootstrap_campaign import (
    BootstrapCampaignService,
)
from app.application.services.extract_index.bootstrap_wiring import BootstrapWiring
from app.domain.models.extract_index import ExtractIndexEnvironment


@dataclass(slots=True)
class ExtractIndexAdminState:
    """Estado colgado de ``app.state.extract_index_admin`` (tests / integración)."""

    wiring: BootstrapWiring

    @property
    def settings(self) -> ExtractIndexSettings:
        return self.wiring.settings

    @property
    def service(self) -> BootstrapCampaignService:
        return self.wiring.service


def get_extract_index_admin_state(request: Request) -> ExtractIndexAdminState:
    state = getattr(request.app.state, "extract_index_admin", None)
    if state is None or not isinstance(state, ExtractIndexAdminState):
        raise HTTPException(
            status_code=503,
            detail={
                "code": "extract_index_admin_not_wired",
                "message": "Router admin no cableado (pendiente app_factory / integración).",
            },
        )
    return state


def assert_bootstrap_admin_gates(settings: ExtractIndexSettings) -> None:
    """
    Protecciones obligatorias del admin bootstrap remoto.

    - EXTRACT_INDEX_BOOTSTRAP_ENABLED
    - EXTRACT_INDEX_MODE=off
    """
    if not settings.bootstrap_enabled:
        raise HTTPException(
            status_code=403,
            detail={
                "code": "bootstrap_disabled",
                "message": "EXTRACT_INDEX_BOOTSTRAP_ENABLED=false",
            },
        )
    if settings.mode != ExtractIndexMode.OFF:
        raise HTTPException(
            status_code=403,
            detail={
                "code": "extract_index_mode_must_be_off",
                "message": (
                    f"Bootstrap remoto exige EXTRACT_INDEX_MODE=off; actual={settings.mode.value}"
                ),
            },
        )


def parse_environment(raw: str) -> ExtractIndexEnvironment:
    value = (raw or "").strip().lower()
    if value in ("production", "prod"):
        return ExtractIndexEnvironment.PRODUCTION
    if value == "sandbox":
        return ExtractIndexEnvironment.SANDBOX
    raise HTTPException(
        status_code=422,
        detail={"code": "invalid_environment", "message": f"environment inválido: {raw}"},
    )


def assert_environment_matches_runtime(
    requested: ExtractIndexEnvironment, settings: ExtractIndexSettings
) -> None:
    if requested != settings.environment:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "environment_mismatch",
                "message": (
                    f"environment={requested.value} no coincide con "
                    f"ACTIVE_ENVIRONMENT={settings.environment.value}"
                ),
            },
        )


def sanitize_error_text(value: str | None, *, limit: int = 300) -> str:
    text = str(value or "").strip()
    # Evitar filtrar tokens accidentales en mensajes
    lowered = text.lower()
    for needle in ("bearer ", "api_key", "client_secret", "password="):
        if needle in lowered:
            return "error_sanitized"
    return text[:limit]
