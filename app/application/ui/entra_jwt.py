"""Validación JWT Entra con JWKS (firma, iss, aud, tid, exp, nbf, roles/scopes)."""
from __future__ import annotations

import logging
from typing import Any, Callable

import jwt
from jwt import PyJWKClient
from jwt.exceptions import (
    ExpiredSignatureError,
    ImmatureSignatureError,
    InvalidAudienceError,
    InvalidIssuerError,
    InvalidTokenError,
    PyJWKClientError,
)

from app.application.ui.entra_config import UiEntraApiConfig, resolve_entra_api_config

logger = logging.getLogger(__name__)

# Inyectable en tests (JWKS local/fake). None → PyJWKClient(uri).
_jwks_client_factory: Callable[[str], Any] | None = None
_jwks_clients: dict[str, Any] = {}


def set_jwks_client_factory_for_tests(factory: Callable[[str], Any] | None) -> None:
    """Solo tests: reemplaza el cliente JWKS (sin Internet)."""
    global _jwks_client_factory, _jwks_clients
    _jwks_client_factory = factory
    _jwks_clients = {}


def reset_jwks_clients_for_tests() -> None:
    global _jwks_clients
    _jwks_clients = {}


def _get_jwks_client(jwks_uri: str) -> Any:
    if jwks_uri in _jwks_clients:
        return _jwks_clients[jwks_uri]
    if _jwks_client_factory is not None:
        client = _jwks_client_factory(jwks_uri)
    else:
        client = PyJWKClient(jwks_uri, cache_keys=True, lifespan=300)
    _jwks_clients[jwks_uri] = client
    return client


class EntraTokenError(Exception):
    def __init__(self, error_code: str, user_message: str, next_action: str) -> None:
        self.error_code = error_code
        self.user_message = user_message
        self.next_action = next_action
        super().__init__(error_code)


def _roles_from_payload(payload: dict[str, Any]) -> tuple[str, ...]:
    raw = payload.get("roles") or []
    if isinstance(raw, str):
        return (raw,) if raw.strip() else ()
    if isinstance(raw, list):
        return tuple(str(r) for r in raw if str(r).strip())
    return ()


def _scopes_from_payload(payload: dict[str, Any]) -> tuple[str, ...]:
    scp = payload.get("scp") or payload.get("scope") or ""
    if isinstance(scp, list):
        return tuple(str(s) for s in scp if str(s).strip())
    return tuple(p for p in str(scp).split() if p.strip())


def _assert_roles_or_scopes(payload: dict[str, Any], cfg: UiEntraApiConfig) -> None:
    if not cfg.required_roles and not cfg.required_scopes:
        return
    roles = set(_roles_from_payload(payload))
    scopes = set(_scopes_from_payload(payload))
    role_ok = bool(cfg.required_roles) and bool(roles.intersection(cfg.required_roles))
    scope_ok = bool(cfg.required_scopes) and bool(scopes.intersection(cfg.required_scopes))
    # Si solo hay un tipo configurado, exige ese; si ambos, OR.
    if cfg.required_roles and cfg.required_scopes:
        ok = role_ok or scope_ok
    elif cfg.required_roles:
        ok = role_ok
    else:
        ok = scope_ok
    if not ok:
        raise EntraTokenError(
            "insufficient_scope_or_role",
            "Su cuenta no tiene permisos para la interfaz operativa.",
            "Solicite el rol u scope de operador a TI.",
        )


def validate_entra_access_token(
    token: str,
    *,
    config: UiEntraApiConfig | None = None,
) -> dict[str, Any]:
    """Valida firma JWKS + claims. Fail-closed ante cualquier fallo."""
    cfg = config or resolve_entra_api_config()
    if not (cfg.tenant_id and cfg.issuer and cfg.jwks_uri and cfg.audience):
        raise EntraTokenError(
            "entra_misconfigured",
            "La autenticación Entra no está configurada en el servidor.",
            "Configure tenant, issuer/JWKS y audience de la API.",
        )
    if not token or token.count(".") < 2:
        raise EntraTokenError(
            "invalid_bearer",
            "Token Entra inválido.",
            "Inicie sesión de nuevo en la UI.",
        )

    try:
        jwks = _get_jwks_client(cfg.jwks_uri)
        signing_key = jwks.get_signing_key_from_jwt(token)
        payload = jwt.decode(
            token,
            signing_key.key,
            algorithms=["RS256"],
            audience=cfg.audience,
            issuer=cfg.issuer,
            options={
                "require": ["exp", "aud", "iss"],
                "verify_signature": True,
                "verify_exp": True,
                "verify_nbf": True,
                "verify_aud": True,
                "verify_iss": True,
            },
            leeway=30,
        )
    except PyJWKClientError as exc:
        logger.warning("entra_jwks_unavailable: %s", type(exc).__name__)
        raise EntraTokenError(
            "jwks_unavailable",
            "No se pudo validar la sesión (JWKS inaccesible).",
            "Reintente más tarde o contacte a soporte.",
        ) from exc
    except ExpiredSignatureError as exc:
        raise EntraTokenError(
            "token_expired",
            "La sesión ha expirado.",
            "Inicie sesión de nuevo en la UI.",
        ) from exc
    except ImmatureSignatureError as exc:
        raise EntraTokenError(
            "token_not_yet_valid",
            "El token aún no es válido (nbf).",
            "Sincronice el reloj del equipo e inicie sesión de nuevo.",
        ) from exc
    except InvalidAudienceError as exc:
        raise EntraTokenError(
            "invalid_audience",
            "El token no corresponde a esta API.",
            "Verifique la app registration / audience.",
        ) from exc
    except InvalidIssuerError as exc:
        raise EntraTokenError(
            "invalid_issuer",
            "El emisor del token no es válido.",
            "Use una cuenta del tenant de HBI Capital.",
        ) from exc
    except InvalidTokenError as exc:
        raise EntraTokenError(
            "invalid_signature",
            "Token Entra con firma o estructura inválida.",
            "Inicie sesión de nuevo en la UI.",
        ) from exc
    except Exception as exc:
        logger.warning("entra_validate_unexpected: %s", type(exc).__name__)
        raise EntraTokenError(
            "invalid_bearer",
            "No se pudo validar el token Entra.",
            "Inicie sesión de nuevo o contacte a soporte.",
        ) from exc

    if not isinstance(payload, dict):
        raise EntraTokenError(
            "invalid_bearer",
            "Token Entra sin payload.",
            "Inicie sesión de nuevo.",
        )

    tid = str(payload.get("tid") or payload.get("tenant_id") or "")
    if tid != cfg.tenant_id:
        raise EntraTokenError(
            "invalid_tenant",
            "El token no pertenece al tenant configurado.",
            "Use una cuenta del tenant de HBI Capital.",
        )

    _assert_roles_or_scopes(payload, cfg)
    return payload
