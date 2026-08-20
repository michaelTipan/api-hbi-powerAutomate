"""
Selección del último extracto de la unidad de crédito.

Misma regla operativa que ui-stable: máxima fecha límite leída del PDF.
Desempate: createdDateTime → lastModifiedDateTime → fecha en nombre → EXTRACTOS.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Any, Callable

from app.application.services.colombia_time import parse_graph_datetime
from app.application.services.extract_snapshot_parser import (
    parse_extract_snapshot,
    prefer_frozen_extract_candidate,
)

EXTRACT_SOURCE_EXTRACTOS = "extractos_folder"

FechaLimiteFn = Callable[[bytes], date | None]

_FILENAME_DATE_RE = re.compile(
    r"(?i)(?:extracto\s+)?"
    r"(?:\d{1,2}\s*[-/]\s*)?"
    r"(\d{1,2})[-/](\d{1,2})[-/](\d{4})"
)


def _unreadable_pdf_reason(pdf_bytes: bytes) -> str:
    """Distingue PDF escaneado sin texto de layout con fecha no reconocida."""
    try:
        probe = parse_extract_snapshot(pdf_bytes)
        if "pdf_no_text" in probe.warnings:
            return "pdf_no_text"
    except Exception:
        pass
    return "fecha_limite_not_readable"


@dataclass(frozen=True)
class ExtractAsOfOutcome:
    candidate: dict[str, Any] | None
    pdf_bytes: bytes | None
    fecha_limite: date | None
    error_code: str | None
    meta: dict[str, Any] | None
    selection_reason: str | None = None


def extract_created_datetime_raw(cand: dict[str, Any]) -> str:
    """createdDateTime de Graph en el candidato. Nunca lastModifiedDateTime."""
    item = cand.get("item") if isinstance(cand.get("item"), dict) else {}
    fsi = item.get("fileSystemInfo") if isinstance(item.get("fileSystemInfo"), dict) else {}
    raw = (
        cand.get("createdDateTime")
        or cand.get("created_datetime")
        or item.get("createdDateTime")
        or fsi.get("createdDateTime")
        or ""
    )
    return str(raw or "").strip()


def _created_utc(cand: dict[str, Any]) -> datetime | None:
    dt = parse_graph_datetime(extract_created_datetime_raw(cand))
    if dt is None:
        return None
    return dt.astimezone(timezone.utc)


def extract_last_modified_datetime_raw(cand: dict[str, Any]) -> str:
    """lastModifiedDateTime de Graph (top-level o fileSystemInfo)."""
    item = cand.get("item") if isinstance(cand.get("item"), dict) else {}
    fsi = item.get("fileSystemInfo") if isinstance(item.get("fileSystemInfo"), dict) else {}
    raw = (
        cand.get("lastModifiedDateTime")
        or cand.get("last_modified_datetime")
        or item.get("lastModifiedDateTime")
        or fsi.get("lastModifiedDateTime")
        or ""
    )
    return str(raw or "").strip()


def _modified_utc(cand: dict[str, Any]) -> datetime | None:
    dt = parse_graph_datetime(extract_last_modified_datetime_raw(cand))
    if dt is None:
        return None
    return dt.astimezone(timezone.utc)


def _filename_sort_date(cand: dict[str, Any]) -> date | None:
    name = str(cand.get("name") or cand.get("relative_path") or "")
    m = _FILENAME_DATE_RE.search(name)
    if not m:
        return None
    try:
        d, mo, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
        return date(y, mo, d)
    except ValueError:
        return None


def _tiebreak_key(cand: dict[str, Any]) -> tuple:
    """Mayor tuple gana (desempate determinista)."""
    created = _created_utc(cand)
    modified = _modified_utc(cand)
    fname = _filename_sort_date(cand)
    in_extractos = 1 if cand.get("source_location") == EXTRACT_SOURCE_EXTRACTOS else 0
    name = str(cand.get("name") or cand.get("relative_path") or "")
    return (
        created or datetime.min.replace(tzinfo=timezone.utc),
        modified or datetime.min.replace(tzinfo=timezone.utc),
        fname or date.min,
        in_extractos,
        name.casefold(),
    )


def _pick_single_winner(
    winners: list[tuple[dict[str, Any], date, bytes, str]],
) -> tuple[list[tuple[dict[str, Any], date, bytes, str]], str | None]:
    """Reduce empates con cadena created → modified → nombre → EXTRACTOS."""
    if len(winners) <= 1:
        return winners, None
    ranked = sorted(winners, key=lambda t: _tiebreak_key(t[0]), reverse=True)
    best_key = _tiebreak_key(ranked[0][0])
    top = [t for t in ranked if _tiebreak_key(t[0]) == best_key]
    if len(top) == 1:
        reason = "max_fecha_limite_tiebreak"
        if _created_utc(top[0][0]) and len({extract_created_datetime_raw(t[0]) for t in winners}) > 1:
            reason = "max_fecha_limite_max_createdDateTime"
        elif _modified_utc(top[0][0]) and len({extract_last_modified_datetime_raw(t[0]) for t in winners}) > 1:
            reason = "max_fecha_limite_max_lastModifiedDateTime"
        elif len({str(_filename_sort_date(t[0])) for t in winners}) > 1:
            reason = "max_fecha_limite_filename_date"
        return top, reason
    return top, None


def _prefer_extractos_candidate(
    current: dict[str, Any],
    challenger: dict[str, Any],
) -> dict[str, Any]:
    if (
        current.get("source_location") != EXTRACT_SOURCE_EXTRACTOS
        and challenger.get("source_location") == EXTRACT_SOURCE_EXTRACTOS
    ):
        return challenger
    return current


def choose_extract_as_of_bank_date(
    scored: list[tuple[dict[str, Any], date, bytes, str]],
    bank_date: date,
) -> ExtractAsOfOutcome:
    """
    Último extracto de la unidad (ui-stable), con desempate en cadena:

    1) Dedup SHA-256 preferiendo carpeta EXTRACTOS.
    2) Gana la mayor fecha_limite leída del PDF (no se descartan meses posteriores).
    3) Misma fecha límite: createdDateTime → lastModifiedDateTime → fecha en nombre
       del archivo → preferir EXTRACTOS → nombre lexicográfico.
    4) Empate real tras toda la cadena → extract_tie_max_fecha_limite.
    """
    _ = bank_date
    if not scored:
        return ExtractAsOfOutcome(None, None, None, "extract_not_found", None, None)

    by_hash: dict[str, tuple[dict[str, Any], date, bytes, str]] = {}
    for cand, fe, pdf_bytes, digest in scored:
        prev = by_hash.get(digest)
        if prev is None:
            by_hash[digest] = (cand, fe, pdf_bytes, digest)
            continue
        preferred = _prefer_extractos_candidate(prev[0], cand)
        if preferred is cand:
            by_hash[digest] = (cand, fe, pdf_bytes, digest)

    deduped = list(by_hash.values())
    max_d = max(t[1] for t in deduped)
    winners = [t for t in deduped if t[1] == max_d]
    reason = "max_fecha_limite"
    if len(winners) > 1:
        winners, tie_reason = _pick_single_winner(winners)
        if tie_reason:
            reason = tie_reason
        if len(winners) > 1:
            tied = [
                {
                    "name": str(t[0].get("name") or t[0].get("relative_path") or "(sin nombre)"),
                    "relative_path": str(t[0].get("relative_path") or ""),
                    "source_location": str(t[0].get("source_location") or ""),
                    "reason": "tie_max_fecha_limite",
                    "fecha_limite": max_d.isoformat(),
                    "createdDateTime": extract_created_datetime_raw(t[0]),
                    "lastModifiedDateTime": extract_last_modified_datetime_raw(t[0]),
                }
                for t in winners
            ]
            return ExtractAsOfOutcome(
                None,
                None,
                None,
                "extract_tie_max_fecha_limite",
                {
                    "archivos_problema": tied,
                    "fecha_limite_empatada": max_d.isoformat(),
                    "bank_date": bank_date.isoformat(),
                },
                "tie",
            )

    cand, dt, pdf_bytes, _digest = winners[0]
    return ExtractAsOfOutcome(cand, pdf_bytes, dt, None, cand, reason)


def select_extract_as_of_bank_date_from_bytes(
    pool: list[dict[str, Any]],
    *,
    bank_date: date,
    content_by_relative_path: dict[str, bytes],
    fecha_limite_fn: FechaLimiteFn,
    frozen_evidence: dict[str, Any] | None = None,
) -> ExtractAsOfOutcome:
    """Equivalente puro (sin Graph) de la selección as-of."""
    if not pool:
        return ExtractAsOfOutcome(None, None, None, "extract_not_found", None, None)

    frozen_cand = prefer_frozen_extract_candidate(pool, frozen_evidence)
    if frozen_cand is not None:
        fpath = str(frozen_cand.get("relative_path") or "")
        pdf_bytes = content_by_relative_path.get(fpath)
        if pdf_bytes is not None:
            fe = fecha_limite_fn(pdf_bytes)
            if fe is not None:
                return ExtractAsOfOutcome(
                    frozen_cand, pdf_bytes, fe, None, frozen_cand, "frozen_evidence"
                )

    scored: list[tuple[dict[str, Any], date, bytes, str]] = []
    damaged_details: list[dict[str, str]] = []
    for cand in pool:
        fpath = str(cand.get("relative_path") or "")
        name = str(cand.get("name") or "")
        pdf_bytes = content_by_relative_path.get(fpath)
        if pdf_bytes is None:
            damaged_details.append(
                {
                    "name": name or fpath or "(sin nombre)",
                    "relative_path": fpath,
                    "source_location": str(cand.get("source_location") or ""),
                    "reason": "missing_bytes",
                }
            )
            continue
        fe = fecha_limite_fn(pdf_bytes)
        if fe is None:
            damaged_details.append(
                {
                    "name": name or fpath or "(sin nombre)",
                    "relative_path": fpath,
                    "source_location": str(cand.get("source_location") or ""),
                    "reason": _unreadable_pdf_reason(pdf_bytes),
                }
            )
            continue
        import hashlib

        digest = hashlib.sha256(pdf_bytes).hexdigest()
        scored.append((cand, fe, pdf_bytes, digest))

    if damaged_details:
        return ExtractAsOfOutcome(
            None,
            None,
            None,
            "fecha_limite_extracto_not_readable",
            {"archivos_problema": damaged_details},
            None,
        )
    return choose_extract_as_of_bank_date(scored, bank_date)
