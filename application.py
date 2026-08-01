"""Punto de entrada ASGI para Azure App Service (gunicorn + UvicornWorker).

Estrategia de dependencias (U4-RC-R1):
- Preferir `.python_packages/lib/site-packages` dentro del paquete (Linux wheels).
- Añadir esa ruta a `sys.path` antes de importar la app.
- No depender de `__oryx_packages__` ni de `run.sh` (Oryx los ignora a menudo).
- `__oryx_packages__` se acepta solo como alias opcional si ya existe.
"""

from __future__ import annotations

import sys
from pathlib import Path

_root = Path(__file__).resolve().parent


def _candidate_site_packages() -> list[Path]:
    return [
        _root / ".python_packages" / "lib" / "site-packages",
        _root / "__oryx_packages__",
    ]


def ensure_packaged_site_packages(root: Path | None = None) -> list[str]:
    """Inserta en sys.path las site-packages empaquetadas si existen.

    Returns:
        Rutas añadidas (para tests/diagnóstico).
    """
    base = root if root is not None else _root
    added: list[str] = []
    # Raíz del proyecto primero (imports `app.*`).
    root_s = str(base)
    if root_s not in sys.path:
        sys.path.insert(0, root_s)
        added.append(root_s)

    for entry in (
        base / ".python_packages" / "lib" / "site-packages",
        base / "__oryx_packages__",
    ):
        if not entry.exists():
            continue
        path_s = str(entry.resolve() if entry.is_symlink() or entry.exists() else entry)
        if path_s not in sys.path:
            sys.path.insert(0, path_s)
            added.append(path_s)
    return added


# Side-effect al importar application:app (comando Oryx real).
ensure_packaged_site_packages()

import fastapi  # noqa: F401,E402 — señal ASGI para detector Oryx

from app.main import app  # noqa: E402
