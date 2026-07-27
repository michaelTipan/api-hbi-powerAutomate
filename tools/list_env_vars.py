"""
Inventario de variables de entorno realmente leídas por el código.

Uso: ``python tools/list_env_vars.py``

Sirve para mantener el ``.env`` de cada ambiente alineado con el código, sin variables
sobrantes ni faltantes.
"""

from __future__ import annotations

import re
from pathlib import Path

PATTERNS = (
    re.compile(r"os\.getenv\(\s*['\"]([A-Z0-9_]+)['\"]"),
    re.compile(r"os\.environ\.get\(\s*['\"]([A-Z0-9_]+)['\"]"),
    re.compile(r"_strip_env\(\s*['\"]([A-Z0-9_]+)['\"]"),
    re.compile(r"_env\(\s*['\"]([A-Z0-9_]+)['\"]"),
    re.compile(r"^ENV_[A-Z0-9_]+\s*=\s*['\"]([A-Z0-9_]+)['\"]", re.MULTILINE),
    # Nombres referenciados de forma indirecta (diccionarios de alias, tuplas de fallback).
    re.compile(
        r"['\"]((?:GRAPH|PAYMENT|AMORTIZATION|GENERATE|LOG)_[A-Z0-9_]{3,})['\"]"
    ),
)


def collect(root: Path) -> dict[str, list[str]]:
    found: dict[str, set[str]] = {}
    for path in sorted(root.rglob("*.py")):
        text = path.read_text(encoding="utf-8")
        for pattern in PATTERNS:
            for key in pattern.findall(text):
                found.setdefault(key, set()).add(str(path.as_posix()))
    return {key: sorted(files) for key, files in sorted(found.items())}


def main() -> None:
    inventory = collect(Path("app"))
    print(f"Variables encontradas: {len(inventory)}\n")
    for key, files in inventory.items():
        print(f"{key}")
        for file in files:
            print(f"    {file}")


if __name__ == "__main__":
    main()
