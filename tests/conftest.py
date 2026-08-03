"""Aislamiento de entorno para la suite unitaria.

El ``.env`` local (y ``import application`` → ``app.main.load_dotenv``) inyecta
rutas/flags de deploy reales. Eso rompe mocks de Graph y aserciones de UI cuando
se corre ``pytest tests/`` completo en una máquina con overlay activo.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

_PREFIXES = (
    "GRAPH_",
    "PAYMENT_",
    "UI_",
    "EXTRACT_",
    "AMORTIZATION_",
    "WEBSITE_",
)

_EXACT_KEYS = (
    "ACTIVE_ENVIRONMENT",
    "API_HTTP_KEY",
)


def _dotenv_pollution_keys() -> tuple[str, ...]:
    """Claves presentes en ``.env`` / proceso que no deben filtrarse a unit tests."""
    keys: set[str] = set(_EXACT_KEYS)
    for key in list(os.environ):
        if key.startswith(_PREFIXES) or key in _EXACT_KEYS:
            keys.add(key)
    env_path = Path(__file__).resolve().parents[1] / ".env"
    if env_path.is_file():
        for line in env_path.read_text(encoding="utf-8").splitlines():
            text = line.strip()
            if not text or text.startswith("#") or "=" not in text:
                continue
            name = text.split("=", 1)[0].strip()
            if name.startswith(_PREFIXES) or name in _EXACT_KEYS:
                keys.add(name)
    return tuple(sorted(keys))


@pytest.fixture(autouse=True)
def _isolate_unit_test_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in _dotenv_pollution_keys():
        monkeypatch.delenv(key, raising=False)
