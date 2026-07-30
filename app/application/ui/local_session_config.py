"""Configuración de autenticación local_session (fail-closed)."""
from __future__ import annotations

import os
from dataclasses import dataclass

from app.application.ui.password_hash import (
    MIN_SAFE_ITERATIONS,
    PasswordHashError,
    looks_like_placeholder_hash,
    parse_password_hash,
)


def _env(name: str, default: str = "") -> str:
    return (os.getenv(name) or default).strip()


def _env_int(name: str, default: int) -> int:
    raw = _env(name)
    if not raw:
        return default
    return int(raw)


def _env_bool(name: str, default: bool) -> bool:
    raw = _env(name).lower()
    if not raw:
        return default
    return raw in {"1", "true", "yes", "on", "si", "sí"}


@dataclass(frozen=True)
class LocalSessionConfig:
    username: str
    password_hash: str
    role: str
    session_ttl_minutes: int
    session_idle_minutes: int
    login_max_attempts: int
    login_window_seconds: int
    cookie_secure: bool
    cookie_httponly: bool
    cookie_samesite: str


def is_running_on_azure() -> bool:
    return bool(_env("WEBSITE_INSTANCE_ID") or _env("WEBSITE_SITE_NAME"))


def validate_local_session_runtime() -> tuple[bool, str | None]:
    """Devuelve (ok, reason). Si ok=False la UI no debe montarse."""
    username = _env("UI_LOCAL_USERNAME")
    password_hash = _env("UI_LOCAL_PASSWORD_HASH")
    if not username:
        return False, "Falta UI_LOCAL_USERNAME para UI_AUTH_MODE=local_session."
    if not password_hash:
        return False, "Falta UI_LOCAL_PASSWORD_HASH para UI_AUTH_MODE=local_session."
    if looks_like_placeholder_hash(password_hash):
        return False, "UI_LOCAL_PASSWORD_HASH parece un placeholder."
    try:
        _algo, iterations, _salt, _digest = parse_password_hash(password_hash)
    except PasswordHashError as exc:
        return False, f"UI_LOCAL_PASSWORD_HASH inválido: {exc}"
    if iterations < MIN_SAFE_ITERATIONS:
        return False, "UI_LOCAL_PASSWORD_HASH con iteraciones inseguras."

    try:
        ttl = _env_int("UI_SESSION_TTL_MINUTES", 480)
        idle = _env_int("UI_SESSION_IDLE_MINUTES", 60)
        max_attempts = _env_int("UI_LOGIN_MAX_ATTEMPTS", 5)
        window = _env_int("UI_LOGIN_WINDOW_SECONDS", 900)
    except ValueError:
        return False, "Configuración numérica de sesión inválida."
    if ttl < 1 or idle < 1 or max_attempts < 1 or window < 1:
        return False, "TTL/idle/rate-limit de sesión deben ser >= 1."

    cookie_secure = _env_bool("UI_COOKIE_SECURE", True)
    cookie_httponly = _env_bool("UI_COOKIE_HTTPONLY", True)
    samesite = _env("UI_COOKIE_SAMESITE", "strict").lower() or "strict"
    if samesite not in {"strict", "lax", "none"}:
        return False, "UI_COOKIE_SAMESITE inválido."
    if not cookie_httponly:
        return False, "UI_COOKIE_HTTPONLY debe ser true."
    if samesite != "strict":
        return False, "UI_COOKIE_SAMESITE debe ser strict."
    if is_running_on_azure() and not cookie_secure:
        return False, "UI_COOKIE_SECURE=false está prohibido en Azure."

    return True, None


def resolve_local_session_config() -> LocalSessionConfig:
    ok, reason = validate_local_session_runtime()
    if not ok:
        raise RuntimeError(reason or "local_session misconfigured")
    return LocalSessionConfig(
        username=_env("UI_LOCAL_USERNAME"),
        password_hash=_env("UI_LOCAL_PASSWORD_HASH"),
        role=_env("UI_LOCAL_ROLE", "operator") or "operator",
        session_ttl_minutes=_env_int("UI_SESSION_TTL_MINUTES", 480),
        session_idle_minutes=_env_int("UI_SESSION_IDLE_MINUTES", 60),
        login_max_attempts=_env_int("UI_LOGIN_MAX_ATTEMPTS", 5),
        login_window_seconds=_env_int("UI_LOGIN_WINDOW_SECONDS", 900),
        cookie_secure=_env_bool("UI_COOKIE_SECURE", True),
        cookie_httponly=_env_bool("UI_COOKIE_HTTPONLY", True),
        cookie_samesite=_env("UI_COOKIE_SAMESITE", "strict").lower() or "strict",
    )


SESSION_COOKIE_NAME = "__Host-hbi_session"
