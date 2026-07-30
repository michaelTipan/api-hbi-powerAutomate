"""Configuración Entra separada: API (validación) vs SPA (bootstrap público)."""
from __future__ import annotations

import os
from dataclasses import dataclass


def _env(name: str) -> str:
    return (os.getenv(name) or "").strip()


@dataclass(frozen=True)
class UiEntraApiConfig:
    """Backend: validación JWT (nunca exponer secretos al browser)."""

    tenant_id: str
    issuer: str
    jwks_uri: str
    audience: str
    required_roles: tuple[str, ...]
    required_scopes: tuple[str, ...]


@dataclass(frozen=True)
class UiEntraSpaConfig:
    """Frontend: datos públicos para MSAL (sin secretos)."""

    authority: str
    spa_client_id: str
    api_scope: str


def _split_csv(raw: str) -> tuple[str, ...]:
    return tuple(p.strip() for p in raw.split(",") if p.strip())


def resolve_entra_api_config() -> UiEntraApiConfig:
    tenant = _env("UI_ENTRA_TENANT_ID")
    audience = _env("UI_ENTRA_AUDIENCE")
    issuer = _env("UI_ENTRA_ISSUER")
    if not issuer and tenant:
        issuer = f"https://login.microsoftonline.com/{tenant}/v2.0"
    jwks = _env("UI_ENTRA_JWKS_URI")
    if not jwks and tenant:
        jwks = f"https://login.microsoftonline.com/{tenant}/discovery/v2.0/keys"
    return UiEntraApiConfig(
        tenant_id=tenant,
        issuer=issuer,
        jwks_uri=jwks,
        audience=audience,
        required_roles=_split_csv(_env("UI_ENTRA_REQUIRED_ROLES")),
        required_scopes=_split_csv(_env("UI_ENTRA_REQUIRED_SCOPES")),
    )


def resolve_entra_spa_config() -> UiEntraSpaConfig:
    tenant = _env("UI_ENTRA_TENANT_ID")
    authority = _env("UI_ENTRA_AUTHORITY")
    if not authority and tenant:
        authority = f"https://login.microsoftonline.com/{tenant}"
    return UiEntraSpaConfig(
        authority=authority,
        spa_client_id=_env("UI_ENTRA_SPA_CLIENT_ID"),
        api_scope=_env("UI_ENTRA_API_SCOPE"),
    )
