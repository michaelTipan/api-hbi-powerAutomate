#!/usr/bin/env python3
"""Genera hash PBKDF2 para UI_LOCAL_PASSWORD_HASH (no escribe .env)."""
from __future__ import annotations

import getpass
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.application.ui.password_hash import (  # noqa: E402
    DEFAULT_ITERATIONS,
    hash_password,
    looks_like_placeholder_password,
)


def main() -> int:
    print("Generador de hash UI (PBKDF2-HMAC-SHA256).")
    print("No se guarda la contraseña ni se modifica ningún archivo.")
    password = getpass.getpass("Contraseña: ")
    confirm = getpass.getpass("Confirmar: ")
    if password != confirm:
        print("ERROR: las contraseñas no coinciden.", file=sys.stderr)
        return 1
    if looks_like_placeholder_password(password):
        print(
            "ERROR: la contraseña parece un placeholder inseguro.",
            file=sys.stderr,
        )
        return 1
    encoded = hash_password(password, iterations=DEFAULT_ITERATIONS)
    print()
    print(encoded)
    print()
    print("Copie el valor a UI_LOCAL_PASSWORD_HASH en api-hbi-powerAutomate.env")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
