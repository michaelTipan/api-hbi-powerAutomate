"""Asignación lote PDF de asiento ↔ ID Pago por conciliación de montos.

El filename solo aporta el número de crédito aislado. Palabras (pago, cuota,
abono, mora, capital, total) no discriminan. Un PDF entra en a lo sumo un ID Pago.

La búsqueda se detiene al hallar 2 SOLUCIONES GLOBALES del componente
(UNIQUE vs AMBIGUOUS), no 2 subconjuntos locales de un ID Pago.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Any, Iterable, Iterator

ASSIGNMENT_TOLERANCE = 0.02
ASIENTO_ASSIGNMENT_AMBIGUOUS = "ASIENTO_ASSIGNMENT_AMBIGUOUS"
ASIENTO_ASSIGNMENT_NO_MATCH = "ASIENTO_ASSIGNMENT_NO_MATCH"
ASIENTO_ASSIGNMENT_PARSE_FAILED = "ASIENTO_ASSIGNMENT_PARSE_FAILED"
ASIENTO_ASSIGNMENT_COMPLEXITY_LIMIT = "ASIENTO_ASSIGNMENT_COMPLEXITY_LIMIT"

# Protección de explosión combinatoria. NUNCA se traduce a NO_MATCH.
_NODE_BUDGET_DEFAULT = 250_000


class _BudgetExceeded(Exception):
    pass


@dataclass
class _SearchBudget:
    remaining: int

    def tick(self) -> None:
        self.remaining -= 1
        if self.remaining < 0:
            raise _BudgetExceeded()


@dataclass(frozen=True)
class AsientoCandidate:
    path: str
    credit: str
    valor_pagado_cliente: float
    sha256: str = ""
    etag: str = ""
    ctag: str = ""
    comprobante: str = ""
    fecha_asiento: date | None = None
    capital: float = 0.0
    intereses: float = 0.0
    mora: float = 0.0
    retenciones: float = 0.0
    numero_asiento: str = ""


@dataclass(frozen=True)
class IdPagoTarget:
    id_pago: str
    monto_banco: float
    credits: frozenset[str]
    fecha_banco: date | None = None


@dataclass(frozen=True)
class CandidateParseFailure:
    path: str
    credit: str
    stage: str
    error: str


@dataclass(frozen=True)
class AssignmentOutcome:
    """Resultado por ID Pago. Componentes independientes no se contaminan."""

    assignment: dict[str, tuple[str, ...]]
    fingerprints: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    errors: dict[str, str] = field(default_factory=dict)
    parse_failures: tuple[CandidateParseFailure, ...] = ()

    @property
    def status(self) -> str:
        if self.errors:
            if any(c == ASIENTO_ASSIGNMENT_AMBIGUOUS for c in self.errors.values()):
                return "ambiguous"
            if any(
                c == ASIENTO_ASSIGNMENT_COMPLEXITY_LIMIT for c in self.errors.values()
            ):
                return "complexity"
            if any(c == ASIENTO_ASSIGNMENT_PARSE_FAILED for c in self.errors.values()):
                return "parse_failed"
            return "no_match"
        return "unique"


def _amounts_close(a: float, b: float, *, tolerance: float = ASSIGNMENT_TOLERANCE) -> bool:
    return abs(float(a) - float(b)) <= tolerance


def candidate_fingerprint(c: AsientoCandidate) -> dict[str, Any]:
    return {
        "path": c.path,
        "credit": c.credit,
        "sha256": c.sha256,
        "etag": c.etag,
        "ctag": c.ctag,
        "comprobante": c.comprobante,
        "fecha_asiento": c.fecha_asiento.isoformat() if c.fecha_asiento else "",
        "valor_pagado_cliente": c.valor_pagado_cliente,
        "capital": c.capital,
        "intereses": c.intereses,
        "mora": c.mora,
        "retenciones": c.retenciones,
        "numero_asiento": c.numero_asiento,
    }


def _is_recaudo_candidate(
    candidate: AsientoCandidate, *, tolerance: float = ASSIGNMENT_TOLERANCE
) -> bool:
    """Solo el recaudo cubre monto banco. VP≈0 no puede crear una segunda cubierta."""
    return float(candidate.valor_pagado_cliente) > tolerance


def _eligible_indices(
    target: IdPagoTarget,
    candidates: list[AsientoCandidate],
    remaining: frozenset[int],
    *,
    tolerance: float = ASSIGNMENT_TOLERANCE,
) -> list[int]:
    out: list[int] = []
    for i in remaining:
        if candidates[i].credit not in target.credits:
            continue
        if not _is_recaudo_candidate(candidates[i], tolerance=tolerance):
            continue
        out.append(i)
    return out


def _non_recaudo_target_matches(
    candidate: AsientoCandidate,
    target: IdPagoTarget,
) -> bool:
    if candidate.credit not in target.credits:
        return False
    if candidate.fecha_asiento is None or target.fecha_banco is None:
        return False
    return candidate.fecha_asiento == target.fecha_banco


def _attach_non_recaudo_leftovers(
    *,
    uniq: list[AsientoCandidate],
    targets: list[IdPagoTarget],
    sol: dict[int, tuple[int, ...]],
    used_paths: set[str],
    tolerance: float,
) -> dict[int, tuple[int, ...]]:
    """
    Cuelga asientos sin recaudo (retenciones, ajustes) al ID Pago del mismo
    crédito y la misma fecha banco. Si la fecha no casa o hay dos destinos, se
    deja sin asignar (no tumba el recaudo ya único).
    """
    used_idx = {i for subset in sol.values() for i in subset}
    leftovers = [
        i
        for i, c in enumerate(uniq)
        if i not in used_idx and not _is_recaudo_candidate(c, tolerance=tolerance)
    ]
    extra: dict[int, list[int]] = {ti: [] for ti in sol}
    for i in leftovers:
        c = uniq[i]
        matches = [
            ti
            for ti in sol
            if _non_recaudo_target_matches(c, targets[ti])
        ]
        if not matches and c.fecha_asiento is None:
            credit_targets = [
                ti for ti in sol if c.credit in targets[ti].credits
            ]
            if len(credit_targets) == 1:
                matches = credit_targets
        if len(matches) != 1:
            continue
        ti = matches[0]
        key = uniq[i].path.strip().strip("/").casefold()
        if key in used_paths:
            continue
        used_paths.add(key)
        extra[ti].append(i)
    out: dict[int, tuple[int, ...]] = {}
    for ti, subset in sol.items():
        added = tuple(sorted(extra.get(ti, []), key=lambda i: uniq[i].path.casefold()))
        out[ti] = subset + added
    return out


def _iter_covering_subsets(
    idxs: list[int],
    candidates: list[AsientoCandidate],
    monto: float,
    required_credits: frozenset[str],
    *,
    tolerance: float,
    budget: _SearchBudget,
) -> Iterator[tuple[int, ...]]:
    """Subconjuntos que cubren monto Y todos los créditos del target. Lazy."""
    n = len(idxs)
    amounts = [candidates[i].valor_pagado_cliente for i in idxs]
    credits = [candidates[i].credit for i in idxs]
    suffix_sum = [0.0] * (n + 1)
    for k in range(n - 1, -1, -1):
        suffix_sum[k] = suffix_sum[k + 1] + amounts[k]
    suffix_credits: list[set[str]] = [set() for _ in range(n + 1)]
    acc: set[str] = set()
    for k in range(n - 1, -1, -1):
        acc = acc | {credits[k]}
        suffix_credits[k] = set(acc)

    def rec(
        start: int, chosen: list[int], total: float, covered: frozenset[str]
    ) -> Iterator[tuple[int, ...]]:
        budget.tick()
        if _amounts_close(total, monto, tolerance=tolerance) and chosen:
            if not required_credits or required_credits <= covered:
                yield tuple(chosen)
            return
        if start >= n or total > monto + tolerance:
            return
        if total + suffix_sum[start] < monto - tolerance:
            return
        missing = required_credits - covered if required_credits else frozenset()
        if missing and not missing <= (covered | suffix_credits[start]):
            return
        for k in range(start, n):
            i = idxs[k]
            yield from rec(
                k + 1,
                chosen + [i],
                total + amounts[k],
                covered | {credits[k]},
            )

    yield from rec(0, [], 0.0, frozenset())


def _connected_components(
    targets: list[IdPagoTarget],
    candidates: list[AsientoCandidate],
) -> list[list[int]]:
    """Componentes de ID Pago que comparten créditos (y por tanto pool de PDFs)."""
    n = len(targets)
    if n == 0:
        return []
    parent = list(range(n))

    def find(x: int) -> int:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a: int, b: int) -> None:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[rb] = ra

    for i in range(n):
        for j in range(i + 1, n):
            if targets[i].credits & targets[j].credits:
                union(i, j)
    groups: dict[int, list[int]] = {}
    for i in range(n):
        groups.setdefault(find(i), []).append(i)
    return list(groups.values())


def assign_asientos_unique(
    targets: list[IdPagoTarget],
    candidates: list[AsientoCandidate],
    *,
    tolerance: float = ASSIGNMENT_TOLERANCE,
    parse_failures: Iterable[CandidateParseFailure] | None = None,
    node_budget: int = _NODE_BUDGET_DEFAULT,
) -> AssignmentOutcome:
    """
    Asigna cada candidato a lo sumo a un target.

    PDFs no usados se permiten (sobrantes en carpeta).
    Una solución global cubre monto + todos los créditos SI de cada ID Pago.
    Un PARSE_FAILED de candidato elegible (crédito del componente, no PROCESADO)
    bloquea el componente: no hay UNIQUE con el resto parseable.
    0 cubiertas exhaustivas → no_match.
    1 cubierta exhaustiva → unique.
    ≥2 globales → ambiguous.
    Presupuesto de nodos agotado (0 o 1 hallazgo) → COMPLEXITY_LIMIT,
    nunca UNIQUE: la primera solución no demuestra unicidad.
    """
    assignment: dict[str, tuple[str, ...]] = {}
    fingerprints: dict[str, list[dict[str, Any]]] = {}
    errors: dict[str, str] = {}
    failures = tuple(parse_failures or ())

    if not targets:
        return AssignmentOutcome(
            assignment={}, fingerprints={}, errors={}, parse_failures=failures
        )

    by_path: dict[str, AsientoCandidate] = {}
    for c in candidates:
        key = str(c.path or "").strip().strip("/").casefold()
        if key and key not in by_path:
            by_path[key] = c
    uniq = list(by_path.values())
    uniq.sort(key=lambda c: (c.credit, c.path.casefold()))

    for t in targets:
        if t.monto_banco is None or float(t.monto_banco) <= 0:
            errors[t.id_pago] = ASIENTO_ASSIGNMENT_NO_MATCH

    fail_credits = {
        str(f.credit or "").strip() for f in failures if str(f.credit or "").strip()
    }

    def search_component(
        t_idxs: list[int],
        remaining: frozenset[int],
        partial: dict[int, tuple[int, ...]],
        bucket: list[dict[int, tuple[int, ...]]],
        budget: _SearchBudget,
    ) -> None:
        if len(bucket) >= 2:
            return
        if not t_idxs:
            bucket.append(dict(partial))
            return
        ordered = sorted(
            t_idxs,
            key=lambda ti: (
                len(_eligible_indices(targets[ti], uniq, remaining, tolerance=tolerance)),
                ti,
            ),
        )
        ti = ordered[0]
        rest_targets = [x for x in t_idxs if x != ti]
        elig = _eligible_indices(
            targets[ti], uniq, remaining, tolerance=tolerance
        )
        elig.sort(
            key=lambda i: (
                -float(uniq[i].valor_pagado_cliente),
                uniq[i].path.casefold(),
            )
        )
        for subset in _iter_covering_subsets(
            elig,
            uniq,
            float(targets[ti].monto_banco),
            targets[ti].credits,
            tolerance=tolerance,
            budget=budget,
        ):
            if len(bucket) >= 2:
                return
            search_component(
                rest_targets,
                remaining - frozenset(subset),
                {**partial, ti: subset},
                bucket,
                budget,
            )

    for comp in _connected_components(targets, uniq):
        if any(targets[ti].id_pago in errors for ti in comp):
            for ti in comp:
                errors.setdefault(targets[ti].id_pago, ASIENTO_ASSIGNMENT_NO_MATCH)
            continue
        cand_idx = frozenset(
            i
            for i, c in enumerate(uniq)
            if any(c.credit in targets[ti].credits for ti in comp)
        )
        if any(fail_credits & targets[ti].credits for ti in comp):
            for ti in comp:
                errors[targets[ti].id_pago] = ASIENTO_ASSIGNMENT_PARSE_FAILED
            continue
        bucket: list[dict[int, tuple[int, ...]]] = []
        budget = _SearchBudget(node_budget)
        try:
            search_component(comp, cand_idx, {}, bucket, budget)
        except _BudgetExceeded:
            for ti in comp:
                errors[targets[ti].id_pago] = ASIENTO_ASSIGNMENT_COMPLEXITY_LIMIT
                assignment.pop(targets[ti].id_pago, None)
                fingerprints.pop(targets[ti].id_pago, None)
            continue
        if len(bucket) == 0:
            for ti in comp:
                errors[targets[ti].id_pago] = ASIENTO_ASSIGNMENT_NO_MATCH
            continue
        if len(bucket) >= 2:
            for ti in comp:
                errors[targets[ti].id_pago] = ASIENTO_ASSIGNMENT_AMBIGUOUS
            continue
        sol = bucket[0]
        used_paths: set[str] = set()
        ok = True
        for ti, subset in sol.items():
            for i in subset:
                key = uniq[i].path.strip().strip("/").casefold()
                if key in used_paths:
                    ok = False
                    break
                used_paths.add(key)
            if not ok:
                break
        if not ok:
            for ti in comp:
                errors[targets[ti].id_pago] = ASIENTO_ASSIGNMENT_AMBIGUOUS
                assignment.pop(targets[ti].id_pago, None)
                fingerprints.pop(targets[ti].id_pago, None)
            continue
        sol = _attach_non_recaudo_leftovers(
            uniq=uniq,
            targets=targets,
            sol=sol,
            used_paths=used_paths,
            tolerance=tolerance,
        )
        for ti, subset in sol.items():
            assignment[targets[ti].id_pago] = tuple(uniq[i].path for i in subset)
            fingerprints[targets[ti].id_pago] = [
                candidate_fingerprint(uniq[i]) for i in subset
            ]

    for t in targets:
        assignment.setdefault(t.id_pago, ())
        fingerprints.setdefault(t.id_pago, [])

    return AssignmentOutcome(
        assignment=assignment,
        fingerprints=fingerprints,
        errors=errors,
        parse_failures=failures,
    )


def processed_names_casefold(names: Iterable[str]) -> set[str]:
    return {str(n or "").strip().casefold() for n in names if str(n or "").strip()}
