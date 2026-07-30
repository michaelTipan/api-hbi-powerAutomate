"""Sampling determinista para shadow (sin random por ejecución)."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import date


@dataclass(frozen=True, slots=True)
class ShadowSampleContext:
    environment: str
    bank_code: str
    process_date: date
    credit_key: str


def stable_sample_bucket(
    ctx: ShadowSampleContext,
    *,
    modulus: int = 10_000,
) -> int:
    """
    Bucket determinista en [0, modulus).

    Misma clave → mismo bucket en toda la ventana de validación.
    """
    material = "|".join(
        [
            str(ctx.environment or "").strip().lower(),
            str(ctx.bank_code or "").strip().lower(),
            ctx.process_date.isoformat(),
            str(ctx.credit_key or "").strip(),
        ]
    )
    digest = hashlib.sha256(material.encode("utf-8")).hexdigest()
    return int(digest[:8], 16) % modulus


def is_credit_in_shadow_sample(
    ctx: ShadowSampleContext,
    *,
    sample_pct: float | None,
) -> bool:
    """
    ``sample_pct`` en [0, 100]. None o >= 100 → todos.
    0 → ninguno.
    """
    if sample_pct is None or sample_pct >= 100.0:
        return True
    if sample_pct <= 0.0:
        return False
    threshold = int(sample_pct * 100.0)  # p.ej. 12.5% → 1250 de 10000
    threshold = max(0, min(10_000, threshold))
    return stable_sample_bucket(ctx) < threshold
