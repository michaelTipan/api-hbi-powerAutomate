"""Helpers JWT/JWKS locales para tests Entra (sin Internet)."""
from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

import jwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from app.application.ui.entra_jwt import set_jwks_client_factory_for_tests

TENANT = "11111111-2222-3333-4444-555555555555"
AUDIENCE = "api://hbi-operator-ui"
ISSUER = f"https://login.microsoftonline.com/{TENANT}/v2.0"
JWKS_URI = "https://local.test/jwks"  # nunca se llama en red
KID = "test-key-1"


@dataclass
class FakeSigningKey:
    key: Any
    key_id: str = KID


class FakePyJWKClient:
    """Cliente JWKS en memoria (rotación vía kid)."""

    def __init__(self, keys_by_kid: dict[str, Any]) -> None:
        self._keys = keys_by_kid

    def get_signing_key_from_jwt(self, token: str) -> FakeSigningKey:
        header = jwt.get_unverified_header(token)
        kid = str(header.get("kid") or "")
        if kid not in self._keys:
            from jwt.exceptions import PyJWKClientError

            raise PyJWKClientError(f"Unable to find a signing key that matches: {kid}")
        return FakeSigningKey(key=self._keys[kid], key_id=kid)


class FailingPyJWKClient:
    def get_signing_key_from_jwt(self, token: str) -> FakeSigningKey:
        from jwt.exceptions import PyJWKClientError

        raise PyJWKClientError("JWKS endpoint unreachable (test)")


def _make_rsa_pair() -> tuple[Any, Any]:
    private = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    public = private.public_key()
    return private, public


PRIVATE_KEY, PUBLIC_KEY = _make_rsa_pair()
ALT_PRIVATE, ALT_PUBLIC = _make_rsa_pair()


def public_pem(public: Any = PUBLIC_KEY) -> bytes:
    return public.public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )


def install_fake_jwks(*, fail: bool = False, use_alt_public: bool = False) -> None:
    if fail:
        set_jwks_client_factory_for_tests(lambda _uri: FailingPyJWKClient())
        return
    pub = ALT_PUBLIC if use_alt_public else PUBLIC_KEY
    client = FakePyJWKClient({KID: pub})
    set_jwks_client_factory_for_tests(lambda _uri: client)


def install_entra_env(monkeypatch: Any, **overrides: str) -> None:
    values = {
        "UI_ENTRA_TENANT_ID": TENANT,
        "UI_ENTRA_AUDIENCE": AUDIENCE,
        "UI_ENTRA_ISSUER": ISSUER,
        "UI_ENTRA_JWKS_URI": JWKS_URI,
        "UI_ENTRA_REQUIRED_ROLES": "Operator.Read",
        "UI_ENTRA_REQUIRED_SCOPES": "",
        "UI_ENTRA_SPA_CLIENT_ID": "spa-client-id",
        "UI_ENTRA_AUTHORITY": f"https://login.microsoftonline.com/{TENANT}",
        "UI_ENTRA_API_SCOPE": "api://hbi-operator-ui/access_as_user",
    }
    values.update(overrides)
    for k, v in values.items():
        monkeypatch.setenv(k, v)


def mint_token(
    *,
    private: Any = PRIVATE_KEY,
    kid: str = KID,
    aud: str = AUDIENCE,
    iss: str = ISSUER,
    tid: str = TENANT,
    exp_offset: int = 3600,
    nbf_offset: int = -60,
    roles: list[str] | None = None,
    scp: str | None = None,
    extra: dict[str, Any] | None = None,
) -> str:
    now = int(time.time())
    payload: dict[str, Any] = {
        "aud": aud,
        "iss": iss,
        "tid": tid,
        "oid": "oid-operator-1",
        "sub": "sub-operator-1",
        "name": "Operador Test",
        "exp": now + exp_offset,
        "nbf": now + nbf_offset,
        "iat": now,
    }
    if roles is not None:
        payload["roles"] = roles
    else:
        payload["roles"] = ["Operator.Read"]
    if scp is not None:
        payload["scp"] = scp
    if extra:
        payload.update(extra)
    return jwt.encode(payload, private, algorithm="RS256", headers={"kid": kid})
