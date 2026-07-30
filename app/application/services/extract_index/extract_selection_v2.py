"""
Selección V2 de extractos — componente puro/compartible (Fase 2A).

Réplica caracterizada de la lógica en payment_validation_generate
(_resolve_extract_pdf_pool / _select_extract_by_max_fecha_limite_v2).

NO está cableada a Generate. Generate sigue usando las funciones originales.
No se “corrigen” comportamientos históricos: la paridad es la meta.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import date
from typing import Any, Callable

# Misma semántica que payment_validation_generate
EXTRACT_SOURCE_CREDIT_ROOT = "credit_root"
EXTRACT_SOURCE_EXTRACTOS = "extractos_folder"

FechaLimiteFn = Callable[[bytes], date | None]


@dataclass(frozen=True, slots=True)
class ExtractSelectionOutcome:
    """Resultado alineado al tuple original de selección V2."""

    item: dict[str, Any] | None
    pdf_bytes: bytes | None
    fecha_limite: date | None
    error_code: str | None
    candidate_meta: dict[str, Any] | None
    selection_reason: str


def is_strict_extract_pdf_file_item(item: dict[str, Any]) -> bool:
    """PDF cuyo nombre contiene 'extracto' (misma regla Generate)."""
    if "folder" in item:
        return False
    name = str(item.get("name", ""))
    if "extracto" not in name.lower():
        return False
    return name.lower().endswith(".pdf")


def find_extractos_folder_item(items: list[dict[str, Any]]) -> dict[str, Any] | None:
    for it in items:
        if "folder" not in it:
            continue
        if str(it.get("name", "")).casefold() == "extractos":
            return it
    return None


def extract_candidate(
    item: dict[str, Any],
    *,
    parent_path: str,
    source_location: str,
) -> dict[str, Any]:
    name = str(item.get("name", "") or "")
    parent = str(parent_path or "").replace("\\", "/").rstrip("/")
    relative = f"{parent}/{name}" if name else parent
    return {
        "item": item,
        "name": name,
        "parent_path": parent,
        "relative_path": relative.replace("//", "/"),
        "source_location": source_location,
    }


def prefer_extractos_candidate(
    current: dict[str, Any],
    challenger: dict[str, Any],
) -> dict[str, Any]:
    if (
        current.get("source_location") != EXTRACT_SOURCE_EXTRACTOS
        and challenger.get("source_location") == EXTRACT_SOURCE_EXTRACTOS
    ):
        return challenger
    return current


def build_extract_pdf_pool_from_listings(
    *,
    credit_path: str,
    credit_folder_items: list[dict[str, Any]],
    extractos_children: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """
    Equivalente puro de _resolve_extract_pdf_pool sin Graph.

    ``extractos_children`` debe ser la lista ya obtenida de la carpeta EXTRACTOS
    (o None/[] si no existe o no se listó).
    """
    credit_norm = str(credit_path or "").replace("\\", "/").rstrip("/")
    candidates: list[dict[str, Any]] = []
    for it in credit_folder_items:
        if is_strict_extract_pdf_file_item(it):
            candidates.append(
                extract_candidate(
                    it,
                    parent_path=credit_norm,
                    source_location=EXTRACT_SOURCE_CREDIT_ROOT,
                )
            )

    extractos_item = find_extractos_folder_item(credit_folder_items)
    if extractos_item is not None and extractos_children is not None:
        ex_name = str(extractos_item.get("name", "EXTRACTOS"))
        extractos_path = f"{credit_norm}/{ex_name}".replace("//", "/")
        for it in extractos_children:
            if is_strict_extract_pdf_file_item(it):
                candidates.append(
                    extract_candidate(
                        it,
                        parent_path=extractos_path,
                        source_location=EXTRACT_SOURCE_EXTRACTOS,
                    )
                )
    return candidates


def select_extract_by_max_fecha_limite_from_bytes(
    pool: list[dict[str, Any]],
    *,
    content_by_relative_path: dict[str, bytes],
    fecha_limite_fn: FechaLimiteFn,
) -> ExtractSelectionOutcome:
    """
    Equivalente puro de _select_extract_by_max_fecha_limite_v2 sin Graph.

    Alineado a Generate (post-fix develop 2026-07-30):
    - PDF no descargable o sin fecha límite legible → falla el pool
      (fecha_limite_extracto_not_readable), no se omite en silencio.
    - Dedup SHA-256 preferiendo EXTRACTOS.
    - Empate de max fecha con hashes distintos → extract_tie_max_fecha_limite.
    """
    if not pool:
        return ExtractSelectionOutcome(
            None, None, None, "extract_not_found", None, "empty_pool"
        )

    scored: list[tuple[dict[str, Any], date, bytes, str]] = []
    damaged: list[dict[str, Any]] = []
    damaged_details: list[dict[str, str]] = []
    for cand in pool:
        fpath = str(cand.get("relative_path") or "")
        name = str(cand.get("name") or "")
        pdf_bytes = content_by_relative_path.get(fpath)
        if pdf_bytes is None:
            damaged.append(cand)
            damaged_details.append(
                {
                    "name": name or fpath or "(sin nombre)",
                    "relative_path": fpath,
                    "source_location": str(cand.get("source_location") or ""),
                    "reason": "download_failed",
                }
            )
            continue
        fe = fecha_limite_fn(pdf_bytes)
        if fe is None:
            damaged.append(cand)
            damaged_details.append(
                {
                    "name": name or fpath or "(sin nombre)",
                    "relative_path": fpath,
                    "source_location": str(cand.get("source_location") or ""),
                    "reason": "fecha_limite_not_readable",
                }
            )
            continue
        digest = hashlib.sha256(pdf_bytes).hexdigest()
        scored.append((cand, fe, pdf_bytes, digest))

    if damaged:
        focus = next(
            (
                c
                for c in damaged
                if str(c.get("source_location") or "") == EXTRACT_SOURCE_EXTRACTOS
            ),
            damaged[0],
        )
        return ExtractSelectionOutcome(
            None,
            None,
            None,
            "fecha_limite_extracto_not_readable",
            {
                "damaged_focus": focus,
                "damaged_count": len(damaged),
                "readable_count": len(scored),
                "archivos_problema": damaged_details,
            },
            "damaged_or_unreadable_fecha_limite",
        )

    if not scored:
        return ExtractSelectionOutcome(
            None,
            None,
            None,
            "fecha_limite_extracto_not_readable",
            {
                "archivos_problema": damaged_details,
                "damaged_count": 0,
                "readable_count": 0,
            },
            "no_readable_fecha_limite",
        )

    by_hash: dict[str, tuple[dict[str, Any], date, bytes, str]] = {}
    preferred_extractos_same_hash = False
    for cand, fe, pdf_bytes, digest in scored:
        prev = by_hash.get(digest)
        if prev is None:
            by_hash[digest] = (cand, fe, pdf_bytes, digest)
            continue
        preferred = prefer_extractos_candidate(prev[0], cand)
        if preferred is cand:
            by_hash[digest] = (cand, fe, pdf_bytes, digest)
            preferred_extractos_same_hash = True

    deduped = list(by_hash.values())
    max_d = max(t[1] for t in deduped)
    winners = [t for t in deduped if t[1] == max_d]
    if len(winners) > 1:
        tied = [
            {
                "name": str(t[0].get("name") or t[0].get("relative_path") or "(sin nombre)"),
                "relative_path": str(t[0].get("relative_path") or ""),
                "source_location": str(t[0].get("source_location") or ""),
                "reason": "tie_max_fecha_limite",
                "fecha_limite": max_d.isoformat(),
            }
            for t in winners
        ]
        return ExtractSelectionOutcome(
            None,
            None,
            None,
            "extract_tie_max_fecha_limite",
            {
                "archivos_problema": tied,
                "fecha_limite_empatada": max_d.isoformat(),
            },
            "tie_max_fecha_limite",
        )

    cand, dt, pdf_bytes, _digest = winners[0]
    item = cand.get("item") if isinstance(cand.get("item"), dict) else cand
    reason = (
        "max_fecha_limite_prefer_extractos_same_hash"
        if preferred_extractos_same_hash
        else "max_fecha_limite"
    )
    return ExtractSelectionOutcome(
        item if isinstance(item, dict) else None,
        pdf_bytes,
        dt,
        None,
        cand,
        reason,
    )


def pool_has_extractos_folder(pool: list[dict[str, Any]]) -> bool:
    return any(
        str(c.get("source_location") or "") == EXTRACT_SOURCE_EXTRACTOS for c in pool
    )


def outcome_as_legacy_tuple(
    outcome: ExtractSelectionOutcome,
) -> tuple[dict[str, Any] | None, bytes | None, date | None, str | None, dict[str, Any] | None]:
    """Misma forma que retorna _select_extract_by_max_fecha_limite_v2."""
    return (
        outcome.item,
        outcome.pdf_bytes,
        outcome.fecha_limite,
        outcome.error_code,
        outcome.candidate_meta,
    )
