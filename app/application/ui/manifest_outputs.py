"""Extracción de PDFs operativos desde el JSON del manifest Merge."""
from __future__ import annotations

from typing import Any

from app.application.ui.ports import UiManifestOutputRef


def _nz(value: Any) -> str | None:
    text = str(value or "").strip()
    return text or None


def credito_from_manifest_output(item: dict[str, Any]) -> str | None:
    credito = _nz(item.get("credito"))
    if credito:
        return credito
    for key in ("creditos_seleccionados", "expected_creditos"):
        raw = item.get(key)
        if not isinstance(raw, list):
            continue
        for entry in raw:
            hit = _nz(entry)
            if hit:
                return hit
    return None


def parse_manifest_output_pdfs(outputs: Any) -> tuple[UiManifestOutputRef, ...]:
    """Extrae todos los PDFs operativos de ``outputs[]`` (nunca el JSON del manifiesto)."""
    if not isinstance(outputs, list):
        return ()
    refs: list[UiManifestOutputRef] = []
    seen: set[str] = set()
    for item in outputs:
        if not isinstance(item, dict):
            continue
        candidate = _nz(
            item.get("output_relative_path")
            or item.get("output_path")
            or item.get("pdf_path")
        )
        if not candidate:
            continue
        # Solo PDFs operativos; nunca el JSON del manifiesto ni otros artefactos.
        if not candidate.lower().endswith(".pdf"):
            continue
        key = candidate.lower()
        if key in seen:
            continue
        seen.add(key)
        refs.append(
            UiManifestOutputRef(
                path=candidate,
                credito=credito_from_manifest_output(item),
                id_pago=_nz(item.get("id_pago")),
                web_url=_nz(item.get("output_web_url")),
            )
        )
    return tuple(refs)
