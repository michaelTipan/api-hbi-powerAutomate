"""
Selección determinística de extracto as-of fecha banco.

NO elige «máxima fecha límite disponible» a ciegas.
Abril no puede seleccionar un extracto de junio.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any, Callable

from app.application.services.extract_snapshot_parser import prefer_frozen_extract_candidate

EXTRACT_SOURCE_EXTRACTOS = "EXTRACTOS"

FechaLimiteFn = Callable[[bytes], date | None]


@dataclass(frozen=True)
class ExtractAsOfOutcome:
    candidate: dict[str, Any] | None
    pdf_bytes: bytes | None
    fecha_limite: date | None
    error_code: str | None
    meta: dict[str, Any] | None
    selection_reason: str | None = None


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
    Regla determinística (pura, testeable):

    1) Preferir extractos del mismo año-mes que la fecha banco;
       entre ellos, la mayor fecha_limite.
    2) Si no hay del mismo mes: mayor fecha_limite con fecha_limite <= bank_date.
    3) Si no hay elegibles: extract_as_of_not_found (no elegir meses futuros).
    4) Empate misma fecha + hashes distintos → extract_tie_as_of_bank_date.
    """
    if not scored:
        return ExtractAsOfOutcome(None, None, None, "extract_not_found", None, None)

    # Dedup SHA-256 preferiendo EXTRACTOS.
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

    same_month = [
        t
        for t in deduped
        if t[1].year == bank_date.year and t[1].month == bank_date.month
    ]
    if same_month:
        pool = same_month
        reason = "same_month_max_fecha_limite"
    else:
        prior = [t for t in deduped if t[1] <= bank_date]
        if not prior:
            future = [
                {
                    "name": str(t[0].get("name") or t[0].get("relative_path") or ""),
                    "fecha_limite": t[1].isoformat(),
                    "relative_path": str(t[0].get("relative_path") or ""),
                }
                for t in deduped
            ]
            return ExtractAsOfOutcome(
                None,
                None,
                None,
                "extract_as_of_not_found",
                {
                    "bank_date": bank_date.isoformat(),
                    "archivos_problema": future,
                    "reason": "only_future_extracts",
                },
                "no_eligible_as_of",
            )
        pool = prior
        reason = "as_of_max_fecha_limite_le_bank_date"

    max_d = max(t[1] for t in pool)
    winners = [t for t in pool if t[1] == max_d]
    if len(winners) > 1:
        tied = [
            {
                "name": str(t[0].get("name") or t[0].get("relative_path") or "(sin nombre)"),
                "relative_path": str(t[0].get("relative_path") or ""),
                "source_location": str(t[0].get("source_location") or ""),
                "reason": "tie_as_of_bank_date",
                "fecha_limite": max_d.isoformat(),
            }
            for t in winners
        ]
        return ExtractAsOfOutcome(
            None,
            None,
            None,
            "extract_tie_as_of_bank_date",
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
                    "reason": "fecha_limite_not_readable",
                }
            )
            continue
        import hashlib

        digest = hashlib.sha256(pdf_bytes).hexdigest()
        scored.append((cand, fe, pdf_bytes, digest))

    if damaged_details and not scored:
        return ExtractAsOfOutcome(
            None,
            None,
            None,
            "fecha_limite_extracto_not_readable",
            {"archivos_problema": damaged_details},
            None,
        )
    # Si hay legibles, seleccionar as-of entre ellos. Los dañados quedan en meta
    # (no bloquean en silencio ni invalidan el pool entero).
    outcome = choose_extract_as_of_bank_date(scored, bank_date)
    if damaged_details and outcome.meta is not None:
        outcome = ExtractAsOfOutcome(
            outcome.candidate,
            outcome.pdf_bytes,
            outcome.fecha_limite,
            outcome.error_code,
            {**outcome.meta, "archivos_problema_ignorados": damaged_details, "damaged_count": len(damaged_details)},
            outcome.selection_reason,
        )
    elif damaged_details and outcome.error_code is None:
        outcome = ExtractAsOfOutcome(
            outcome.candidate,
            outcome.pdf_bytes,
            outcome.fecha_limite,
            outcome.error_code,
            {"archivos_problema_ignorados": damaged_details, "damaged_count": len(damaged_details)},
            outcome.selection_reason,
        )
    return outcome
