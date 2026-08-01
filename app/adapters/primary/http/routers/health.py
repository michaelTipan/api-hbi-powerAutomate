from __future__ import annotations

from typing import Any

from fastapi import APIRouter

from app.application.ui.environment import resolve_active_environment
from app.application.ui.feature_flags import get_ui_feature_flags
from app import build_info

router = APIRouter(tags=["health"])


@router.get("/health")
async def health() -> dict[str, Any]:
    """Smoke público: build inequívoco + entorno/UI sin secretos."""
    flags = get_ui_feature_flags()
    env = resolve_active_environment()
    env_name = getattr(env, "environment", None) or str(env)
    return {
        "status": "ok",
        "build": build_info.BUILD_ID,
        "commit": build_info.COMMIT,
        "environment": env_name,
        "ui_enabled": bool(flags.ui_enabled),
    }
