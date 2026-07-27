"""Punto de entrada ASGI para Azure App Service (gunicorn + UvicornWorker)."""

import subprocess
import sys
from pathlib import Path

_root = Path(__file__).resolve().parent

# Las dependencias se instalan en .python_packages porque el rol Reader no permite
# configurar el build de Oryx desde el portal.
for _entry in (
    _root,
    _root / ".python_packages" / "lib" / "site-packages",
    _root / "__oryx_packages__",
):
    _path = str(_entry)
    if _path not in sys.path:
        sys.path.insert(0, _path)


def _ensure_deps() -> None:
    """Instala requirements en el arranque en frío si faltan dependencias."""
    try:
        import dotenv  # noqa: F401

        return
    except ImportError:
        pass

    subprocess.check_call(
        [
            sys.executable,
            "-m",
            "pip",
            "install",
            "-r",
            str(_root / "requirements.txt"),
            "-t",
            str(_root / ".python_packages" / "lib" / "site-packages"),
            "-q",
        ],
        timeout=600,
    )


_ensure_deps()

import fastapi  # noqa: F401,E402 — señal de app ASGI para el detector de Oryx

from app.main import app  # noqa: E402
