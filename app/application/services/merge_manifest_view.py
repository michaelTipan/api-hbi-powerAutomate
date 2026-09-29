"""Vista por ID Pago del manifest de consolidación (formatos 1 y 2).

Formato 1: un output por ID Pago. Formato 2 (un consolidado por grupo y fecha de
pago): un output por PDF con ``payments`` = un registro por ID Pago con la misma forma
del formato 1, que lista solo los asientos asignados a ese pago.

La fase 4, el cierre y la reutilización de PDF leen la vista por ID Pago; la UI enlaza
los PDF desde ``outputs``. Así los lotes en curso con manifest de formato 1 se siguen
leyendo igual.
"""
from __future__ import annotations

from typing import Any


def manifest_version(manifest: dict[str, Any] | None) -> int:
    if not isinstance(manifest, dict):
        return 1
    try:
        return int(manifest.get("manifest_version") or 1)
    except (TypeError, ValueError):
        return 1


def _is_consolidado(output: Any) -> bool:
    return isinstance(output, dict) and isinstance(output.get("payments"), list)


def manifest_payment_outputs(manifest: dict[str, Any] | None) -> list[dict[str, Any]]:
    """Un registro por ID Pago, en el orden del manifest."""
    if not isinstance(manifest, dict):
        return []
    out: list[dict[str, Any]] = []
    for output in manifest.get("outputs") or []:
        if _is_consolidado(output):
            out.extend(p for p in output["payments"] if isinstance(p, dict))
        elif isinstance(output, dict):
            out.append(output)
    return out


def as_payment_manifest(manifest: dict[str, Any]) -> dict[str, Any]:
    """Manifest con ``outputs`` por ID Pago; el de formato 1 se devuelve tal cual."""
    if not isinstance(manifest, dict):
        return manifest
    if not any(_is_consolidado(o) for o in manifest.get("outputs") or []):
        return manifest
    return {**manifest, "outputs": manifest_payment_outputs(manifest)}


__all__ = ["as_payment_manifest", "manifest_payment_outputs", "manifest_version"]
