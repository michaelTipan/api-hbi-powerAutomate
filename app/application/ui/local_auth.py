"""Servicio de login/logout/sesión local_session."""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse

from starlette.requests import Request
from starlette.responses import Response

from app.application.ui.allowed_origins import is_origin_allowed, resolve_allowed_origins
from app.application.ui.local_session_config import (
    SESSION_COOKIE_NAME,
    LocalSessionConfig,
    resolve_local_session_config,
)
from app.application.ui.login_rate_limit import (
    RateLimitConfig,
    get_login_rate_limiter,
)
from app.application.ui.password_hash import verify_password
from app.application.ui.session_repository import (
    SessionRecord,
    get_session_repository,
    hash_session_token,
    mint_csrf_token,
    mint_session_token,
)

logger = logging.getLogger(__name__)

GENERIC_LOGIN_FAILURE = {
    "error_code": "invalid_credentials",
    "user_message": "Usuario o contraseña incorrectos.",
    "next_action": "Verifique sus credenciales e intente de nuevo.",
    "severity": "fatal",
}


@dataclass(frozen=True)
class AuthenticatedLocalUser:
    username: str
    role: str
    auth_mode: str
    expires_at: float
    token_hash: str


def client_ip(request: Request) -> str:
    forwarded = (request.headers.get("x-forwarded-for") or "").split(",")[0].strip()
    if forwarded:
        return forwarded
    if request.client and request.client.host:
        return request.client.host
    return "unknown"


def expected_origins(request: Request) -> set[str]:
    """Orígenes permitidos: el host de la petición (mismo App Service)."""
    url = request.url
    origins = {f"{url.scheme}://{url.netloc}"}
    # Azure a menudo termina en azurewebsites.net; aceptar también https canónico.
    host = url.hostname or ""
    if host:
        origins.add(f"https://{host}")
        if url.port and url.port not in (80, 443):
            origins.add(f"https://{host}:{url.port}")
            origins.add(f"http://{host}:{url.port}")
    return origins


def validate_same_origin(request: Request) -> bool:
    """Valida el header ``Origin`` de peticiones POST (login, logout, escrituras).

    Reglas U3-A:
    - Si ``UI_ALLOWED_ORIGINS`` está configurada (aunque sea inválida/vacía), se usa
      en exclusiva: match exacto tras normalizar (``scheme://netloc``), sin
      startswith ni subdominios. Config inválida/vacía → fail-closed (nunca matchea).
    - Si no está configurada, se cae al detectado por request (mismo host de la
      petición); útil en desarrollo local sin variable definida.
    - El header ``Origin`` ausente siempre se rechaza: en Azure (``is_running_on_azure``)
      y en cualquier endpoint de escritura un fetch same-origin moderno siempre lo
      envía en POST, así que su ausencia es señal de origen no confiable.
    """
    origin = (request.headers.get("origin") or "").strip()
    if not origin:
        return False

    cfg = resolve_allowed_origins()
    if cfg.configured:
        return is_origin_allowed(origin, cfg)

    allowed = expected_origins(request)
    if origin in allowed:
        return True
    # Comparar host sin divergencias de slash.
    try:
        parsed = urlparse(origin)
        origin_norm = f"{parsed.scheme}://{parsed.netloc}"
        return origin_norm in allowed
    except Exception:
        return False


def _ensure_rate_limiter(cfg: LocalSessionConfig) -> None:
    limiter = get_login_rate_limiter()
    limiter._config = RateLimitConfig(  # noqa: SLF001 — ajuste runtime sin vaciar intentos
        max_attempts=cfg.login_max_attempts,
        window_seconds=cfg.login_window_seconds,
    )


def hmac_compare_str(a: str, b: str) -> bool:
    import hmac as _hmac

    a_b = a.encode("utf-8")
    b_b = b.encode("utf-8")
    if len(a_b) != len(b_b):
        _hmac.compare_digest(a_b, a_b)
        return False
    return _hmac.compare_digest(a_b, b_b)


def csrf_token_for_user(user: AuthenticatedLocalUser) -> str | None:
    """CSRF vigente de la sesión del usuario. No rota nada (solo lectura)."""
    repo = get_session_repository()
    rec = repo.get_by_token_hash(user.token_hash)
    return rec.csrf_token if rec is not None else None


def validate_csrf_header(request: Request, user: AuthenticatedLocalUser) -> bool:
    """Compara ``X-CSRF-Token`` contra el de la sesión con ``hmac.compare_digest``."""
    provided = (request.headers.get("x-csrf-token") or "").strip()
    if not provided:
        return False
    expected = csrf_token_for_user(user)
    if not expected:
        return False
    return hmac_compare_str(provided, expected)


def is_login_rate_limited(*, username: str, request: Request) -> bool:
    cfg = resolve_local_session_config()
    _ensure_rate_limiter(cfg)
    return get_login_rate_limiter().is_blocked(
        ip=client_ip(request),
        username=(username or "").strip(),
    )


def authenticate_local_credentials(
    *,
    username: str,
    password: str,
    request: Request,
) -> tuple[str, SessionRecord] | None:
    """Valida credenciales. None = fallo genérico. No distingue usuario/clave."""
    cfg = resolve_local_session_config()
    _ensure_rate_limiter(cfg)
    limiter = get_login_rate_limiter()
    ip = client_ip(request)
    user_norm = (username or "").strip()
    expected_user = cfg.username

    user_ok = hmac_compare_str(user_norm, expected_user)
    pass_ok = verify_password(password or "", cfg.password_hash)
    if not (user_ok and pass_ok):
        limiter.register_failure(ip=ip, username=user_norm)
        logger.info("ui_local_login_failed ip=%s", ip)
        return None

    limiter.clear_success(ip=ip, username=user_norm)
    repo = get_session_repository()
    repo.delete_by_username(expected_user)
    repo.purge_expired()

    now = time.time()
    absolute_exp = now + (cfg.session_ttl_minutes * 60)
    idle_exp = now + (cfg.session_idle_minutes * 60)
    expires_at = min(absolute_exp, idle_exp)

    token = mint_session_token()
    token_hash = hash_session_token(token)
    record = SessionRecord(
        token_hash=token_hash,
        username=expected_user,
        role=cfg.role,
        created_at=now,
        last_activity_at=now,
        expires_at=expires_at,
        csrf_token=mint_csrf_token(),
        auth_mode="local_session",
    )
    repo.create(record)
    return token, record

def set_session_cookie(response: Response, token: str, cfg: LocalSessionConfig) -> None:
    max_age = cfg.session_ttl_minutes * 60
    # __Host- exige Secure, Path=/, sin Domain.
    response.set_cookie(
        key=SESSION_COOKIE_NAME,
        value=token,
        max_age=max_age,
        expires=max_age,
        path="/",
        secure=True if cfg.cookie_secure else False,
        httponly=True,
        samesite="strict",
    )


def clear_session_cookie(response: Response) -> None:
    response.delete_cookie(
        key=SESSION_COOKIE_NAME,
        path="/",
        secure=True,
        httponly=True,
        samesite="strict",
    )


def resolve_session_from_request(request: Request) -> AuthenticatedLocalUser | None:
    token = request.cookies.get(SESSION_COOKIE_NAME)
    if not token:
        return None
    cfg = resolve_local_session_config()
    repo = get_session_repository()
    repo.purge_expired()
    token_hash = hash_session_token(token)
    rec = repo.get_by_token_hash(token_hash)
    if rec is None:
        return None
    now = time.time()
    if rec.expires_at <= now:
        repo.delete(token_hash)
        return None
    # Absolute TTL desde created_at.
    absolute_exp = rec.created_at + (cfg.session_ttl_minutes * 60)
    if absolute_exp <= now:
        repo.delete(token_hash)
        return None
    # Idle: renovar ventana.
    idle_exp = now + (cfg.session_idle_minutes * 60)
    new_exp = min(absolute_exp, idle_exp)
    repo.touch(token_hash, last_activity_at=now, expires_at=new_exp)
    return AuthenticatedLocalUser(
        username=rec.username,
        role=rec.role,
        auth_mode=rec.auth_mode,
        expires_at=new_exp,
        token_hash=token_hash,
    )


def logout_request(request: Request) -> None:
    token = request.cookies.get(SESSION_COOKIE_NAME)
    if not token:
        return
    repo = get_session_repository()
    repo.delete(hash_session_token(token))


def me_payload(user: AuthenticatedLocalUser) -> dict[str, Any]:
    return {
        "authenticated": True,
        "username": user.username,
        "role": user.role,
        "auth_mode": user.auth_mode,
        "expires_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(user.expires_at)),
    }
