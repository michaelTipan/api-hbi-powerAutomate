"""Hash de contraseña UI: PBKDF2-HMAC-SHA256 (stdlib)."""
from __future__ import annotations

import base64
import hashlib
import hmac
import secrets

ALGORITHM = "pbkdf2_sha256"
DEFAULT_ITERATIONS = 600_000
MIN_SAFE_ITERATIONS = 600_000
SALT_BYTES = 16
DIGEST_BYTES = 32

# Placeholders prohibidos en runtime.
_PLACEHOLDER_MARKERS = (
    "changeme",
    "change-me",
    "password",
    "example",
    "placeholder",
    "todo",
    "replace",
    "your_password",
)


class PasswordHashError(ValueError):
    """Formato o parámetros de hash inválidos."""


def generate_salt() -> bytes:
    return secrets.token_bytes(SALT_BYTES)


def hash_password(password: str, *, iterations: int = DEFAULT_ITERATIONS) -> str:
    """Genera ``pbkdf2_sha256$iterations$salt_b64$digest_b64``."""
    if not password:
        raise PasswordHashError("La contraseña no puede estar vacía.")
    if iterations < MIN_SAFE_ITERATIONS:
        raise PasswordHashError(
            f"Iteraciones inseguras: mínimo {MIN_SAFE_ITERATIONS}."
        )
    salt = generate_salt()
    digest = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt,
        iterations,
        dklen=DIGEST_BYTES,
    )
    return (
        f"{ALGORITHM}${iterations}$"
        f"{base64.b64encode(salt).decode('ascii')}$"
        f"{base64.b64encode(digest).decode('ascii')}"
    )


def parse_password_hash(encoded: str) -> tuple[str, int, bytes, bytes]:
    raw = (encoded or "").strip()
    parts = raw.split("$")
    if len(parts) != 4:
        raise PasswordHashError("Formato de hash inválido.")
    algo, iter_s, salt_b64, digest_b64 = parts
    if algo != ALGORITHM:
        raise PasswordHashError("Algoritmo de hash no soportado.")
    try:
        iterations = int(iter_s)
    except ValueError as exc:
        raise PasswordHashError("Iteraciones inválidas.") from exc
    if iterations < MIN_SAFE_ITERATIONS:
        raise PasswordHashError(
            f"Iteraciones inseguras: mínimo {MIN_SAFE_ITERATIONS}."
        )
    try:
        salt = base64.b64decode(salt_b64.encode("ascii"), validate=True)
        digest = base64.b64decode(digest_b64.encode("ascii"), validate=True)
    except Exception as exc:
        raise PasswordHashError("Salt o digest base64 inválido.") from exc
    if len(salt) < 8 or len(digest) < 16:
        raise PasswordHashError("Salt o digest demasiado corto.")
    return algo, iterations, salt, digest


def verify_password(password: str, encoded_hash: str) -> bool:
    """Verifica contraseña contra hash. Comparación constant-time."""
    try:
        _algo, iterations, salt, expected = parse_password_hash(encoded_hash)
    except PasswordHashError:
        return False
    if not password:
        return False
    actual = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt,
        iterations,
        dklen=len(expected),
    )
    return hmac.compare_digest(actual, expected)


def looks_like_placeholder_password(password: str) -> bool:
    normalized = (password or "").strip().lower()
    if not normalized:
        return True
    return any(m in normalized for m in _PLACEHOLDER_MARKERS)


def looks_like_placeholder_hash(encoded: str) -> bool:
    normalized = (encoded or "").strip().lower()
    if not normalized:
        return True
    return any(m in normalized for m in _PLACEHOLDER_MARKERS)
