"""Asignación lote PDF asiento ↔ ID Pago (sin scoring de filename)."""

from datetime import date

from app.application.services.asiento_lote_assignment import (
    ASIENTO_ASSIGNMENT_AMBIGUOUS,
    ASIENTO_ASSIGNMENT_COMPLEXITY_LIMIT,
    ASIENTO_ASSIGNMENT_NO_MATCH,
    ASIENTO_ASSIGNMENT_PARSE_FAILED,
    AsientoCandidate,
    CandidateParseFailure,
    IdPagoTarget,
    assign_asientos_unique,
)
from app.application.use_cases.merge_composite_validado_pdfs import (
    _classify_asiento_pdf_names,
)


def _c(path: str, credit: str, vp: float, **kwargs) -> AsientoCandidate:
    return AsientoCandidate(
        path=path,
        credit=credit,
        valor_pagado_cliente=vp,
        sha256=kwargs.get("sha256", path),
        etag=kwargs.get("etag", ""),
        ctag=kwargs.get("ctag", ""),
        comprobante=kwargs.get("comprobante", path),
        fecha_asiento=kwargs.get("fecha_asiento", date(2026, 5, 12)),
    )


def test_a_pago_and_abono_words_both_assigned():
    names, rejected = _classify_asiento_pdf_names(
        ["pago-327.pdf", "abono-327.pdf"], "327"
    )
    assert rejected == []
    assert set(names) == {"pago-327.pdf", "abono-327.pdf"}
    out = assign_asientos_unique(
        [IdPagoTarget("P1", 10_000_000, frozenset({"327"}))],
        [
            _c("AS/pago-327.pdf", "327", 6_000_000),
            _c("AS/abono-327.pdf", "327", 4_000_000),
        ],
    )
    assert not out.errors
    assert set(out.assignment["P1"]) == {"AS/pago-327.pdf", "AS/abono-327.pdf"}


def test_b_parte1_parte2_both_assigned():
    names, _ = _classify_asiento_pdf_names(
        ["327-parte1.pdf", "327-parte2.pdf"], "327"
    )
    assert set(names) == {"327-parte1.pdf", "327-parte2.pdf"}
    out = assign_asientos_unique(
        [IdPagoTarget("P1", 1000, frozenset({"327"}))],
        [
            _c("AS/327-parte1.pdf", "327", 400),
            _c("AS/327-parte2.pdf", "327", 600),
        ],
    )
    assert set(out.assignment["P1"]) == {"AS/327-parte1.pdf", "AS/327-parte2.pdf"}


def test_c_cuota_and_abono_capital_words_do_not_exclude():
    names, _ = _classify_asiento_pdf_names(
        ["cuota-327.pdf", "abono-capital-327.pdf", "asdf-327.pdf"],
        "327",
    )
    assert len(names) == 3
    out = assign_asientos_unique(
        [IdPagoTarget("P1", 900, frozenset({"327"}))],
        [
            _c("AS/cuota-327.pdf", "327", 300),
            _c("AS/abono-capital-327.pdf", "327", 300),
            _c("AS/asdf-327.pdf", "327", 300),
        ],
    )
    assert len(out.assignment["P1"]) == 3
    assert not out.errors


def test_d_two_id_pago_same_credit_unique_no_reuse():
    out = assign_asientos_unique(
        [
            IdPagoTarget("A", 10_000_000, frozenset({"327"})),
            IdPagoTarget("B", 20_000_000, frozenset({"327"})),
        ],
        [
            _c("AS/6.pdf", "327", 6_000_000),
            _c("AS/4.pdf", "327", 4_000_000),
            _c("AS/12.pdf", "327", 12_000_000),
            _c("AS/8.pdf", "327", 8_000_000),
        ],
    )
    assert not out.errors
    a = set(out.assignment["A"])
    b = set(out.assignment["B"])
    assert a.isdisjoint(b)
    assert a == {"AS/6.pdf", "AS/4.pdf"}
    assert b == {"AS/12.pdf", "AS/8.pdf"}


def test_e_two_valid_combinations_ambiguous():
    out = assign_asientos_unique(
        [IdPagoTarget("P1", 10, frozenset({"327"}))],
        [
            _c("AS/a.pdf", "327", 6),
            _c("AS/b.pdf", "327", 4),
            _c("AS/c.pdf", "327", 7),
            _c("AS/d.pdf", "327", 3),
        ],
    )
    assert out.errors["P1"] == ASIENTO_ASSIGNMENT_AMBIGUOUS


def test_f_same_pdf_never_in_two_assignments():
    out = assign_asientos_unique(
        [
            IdPagoTarget("A", 10, frozenset({"1"})),
            IdPagoTarget("B", 20, frozenset({"2"})),
        ],
        [
            _c("AS/x.pdf", "1", 10),
            _c("AS/y.pdf", "2", 20),
        ],
    )
    seen: set[str] = set()
    for paths in out.assignment.values():
        for p in paths:
            assert p not in seen
            seen.add(p)


def test_g_procesados_names_are_excluded_from_candidates():
    valid, _ = _classify_asiento_pdf_names(["pago-327.pdf", "abono-327.pdf"], "327")
    processed = {"pago-327.pdf"}
    leftover = [n for n in valid if n.casefold() not in processed]
    assert leftover == ["abono-327.pdf"]
    valid, rejected = _classify_asiento_pdf_names(
        ["pago-327.pdf", "pago-1327.pdf", "pago-3270.pdf"],
        "327",
    )
    assert valid == ["pago-327.pdf"]
    assert set(rejected) == {"pago-1327.pdf", "pago-3270.pdf"}


def test_no_match_when_amounts_do_not_reconcile():
    out = assign_asientos_unique(
        [IdPagoTarget("P1", 1000, frozenset({"327"}))],
        [_c("AS/a.pdf", "327", 10)],
    )
    assert out.errors["P1"] == ASIENTO_ASSIGNMENT_NO_MATCH


def test_global_backtracking_not_local_two_subsets():
    """Los 2 subsets locales 7+13 no deben ocultar A=9+11 / B=7."""
    out = assign_asientos_unique(
        [
            IdPagoTarget("A", 20, frozenset({"327"})),
            IdPagoTarget("B", 7, frozenset({"327"})),
        ],
        [
            _c("AS/a-327.pdf", "327", 7),
            _c("AS/b-327.pdf", "327", 13),
            _c("AS/c-327.pdf", "327", 13),
            _c("AS/d-327.pdf", "327", 9),
            _c("AS/e-327.pdf", "327", 11),
        ],
    )
    assert not out.errors
    assert set(out.assignment["A"]) == {"AS/d-327.pdf", "AS/e-327.pdf"}
    assert out.assignment["B"] == ("AS/a-327.pdf",)


def test_must_cover_every_selected_credit_not_ambiguous_with_single_credit_pdf():
    out = assign_asientos_unique(
        [IdPagoTarget("P1", 100, frozenset({"231", "254"}))],
        [
            _c("AS/231-a.pdf", "231", 100),
            _c("AS/231-b.pdf", "231", 60),
            _c("AS/254-a.pdf", "254", 40),
        ],
    )
    assert not out.errors
    assert set(out.assignment["P1"]) == {"AS/231-b.pdf", "AS/254-a.pdf"}


def test_multi_credit_two_asientos_on_one_credit():
    out = assign_asientos_unique(
        [IdPagoTarget("P1", 100, frozenset({"231", "254"}))],
        [
            _c("AS/231-x.pdf", "231", 30),
            _c("AS/231-y.pdf", "231", 30),
            _c("AS/254-a.pdf", "254", 40),
        ],
    )
    assert not out.errors
    assert set(out.assignment["P1"]) == {
        "AS/231-x.pdf",
        "AS/231-y.pdf",
        "AS/254-a.pdf",
    }


def test_more_than_18_candidates_late_path_still_matches():
    decoys = [_c(f"AS/a{i:02d}.pdf", "327", 1.0) for i in range(24)]
    late = _c("AS/z-late.pdf", "327", 999.0)
    out = assign_asientos_unique(
        [IdPagoTarget("P1", 999.0, frozenset({"327"}))],
        decoys + [late],
    )
    assert not out.errors
    assert out.assignment["P1"] == ("AS/z-late.pdf",)


def test_twenty_unique_payments_and_pdfs_same_credit():
    targets = [
        IdPagoTarget(f"P{i:02d}", float(2**i), frozenset({"327"})) for i in range(20)
    ]
    cands = [_c(f"AS/p{i:02d}.pdf", "327", float(2**i)) for i in range(20)]
    out = assign_asientos_unique(targets, cands)
    assert not out.errors
    seen: set[str] = set()
    for i in range(20):
        paths = out.assignment[f"P{i:02d}"]
        assert paths == (f"AS/p{i:02d}.pdf",)
        assert paths[0] not in seen
        seen.add(paths[0])
    assert len(seen) == 20


def test_complexity_limit_is_not_no_match():
    out = assign_asientos_unique(
        [IdPagoTarget("P1", 1000, frozenset({"327"}))],
        [_c("AS/a.pdf", "327", 1000)],
        node_budget=0,
    )
    assert out.errors["P1"] == ASIENTO_ASSIGNMENT_COMPLEXITY_LIMIT
    assert out.errors["P1"] != ASIENTO_ASSIGNMENT_NO_MATCH


def test_parse_failure_not_disguised_as_no_match():
    out = assign_asientos_unique(
        [IdPagoTarget("P1", 100, frozenset({"327"}))],
        [],
        parse_failures=[
            CandidateParseFailure(
                path="AS/roto.pdf",
                credit="327",
                stage="parser",
                error="AccountingParseError: x",
            )
        ],
    )
    assert out.errors["P1"] == ASIENTO_ASSIGNMENT_PARSE_FAILED
    assert out.parse_failures[0].path == "AS/roto.pdf"
    assert out.assignment["P1"] == ()


def test_a_eligible_parse_failed_blocks_unique_among_parseables():
    out = assign_asientos_unique(
        [IdPagoTarget("P1", 100, frozenset({"327"}))],
        [_c("AS/a-327.pdf", "327", 100)],
        parse_failures=[
            CandidateParseFailure(
                path="AS/b-327.pdf",
                credit="327",
                stage="parser",
                error="AccountingParseError: x",
            )
        ],
    )
    assert out.errors["P1"] == ASIENTO_ASSIGNMENT_PARSE_FAILED
    assert out.assignment["P1"] == ()


def test_b_same_credit_two_targets_parse_failed_blocks_component():
    out = assign_asientos_unique(
        [
            IdPagoTarget("A", 60, frozenset({"327"})),
            IdPagoTarget("B", 40, frozenset({"327"})),
        ],
        [
            _c("AS/a-327.pdf", "327", 60),
            _c("AS/b-327.pdf", "327", 40),
        ],
        parse_failures=[
            CandidateParseFailure(
                path="AS/c-327.pdf",
                credit="327",
                stage="pdf_text",
                error="PdfTextNotExtractableError",
            )
        ],
    )
    assert out.errors["A"] == ASIENTO_ASSIGNMENT_PARSE_FAILED
    assert out.errors["B"] == ASIENTO_ASSIGNMENT_PARSE_FAILED
    assert out.assignment["A"] == ()
    assert out.assignment["B"] == ()


def test_c_parse_failure_other_credit_does_not_contaminate_component():
    out = assign_asientos_unique(
        [
            IdPagoTarget("P327", 100, frozenset({"327"})),
            IdPagoTarget("P999", 50, frozenset({"999"})),
        ],
        [_c("AS/a-327.pdf", "327", 100)],
        parse_failures=[
            CandidateParseFailure(
                path="AS/x-999.pdf",
                credit="999",
                stage="parser",
                error="AccountingParseError",
            )
        ],
    )
    assert out.errors.get("P327") is None
    assert out.assignment["P327"] == ("AS/a-327.pdf",)
    assert out.errors["P999"] == ASIENTO_ASSIGNMENT_PARSE_FAILED
    assert out.assignment["P999"] == ()


def test_d_procesados_are_not_parse_failures():
    valid, _ = _classify_asiento_pdf_names(["a-327.pdf", "b-327.pdf"], "327")
    processed = {"b-327.pdf"}
    pool = [n for n in valid if n.casefold() not in processed]
    assert pool == ["a-327.pdf"]
    out = assign_asientos_unique(
        [IdPagoTarget("P1", 100, frozenset({"327"}))],
        [_c("AS/a-327.pdf", "327", 100)],
        parse_failures=[],
    )
    assert not out.errors
    assert out.assignment["P1"] == ("AS/a-327.pdf",)


def test_complexity_limit_one_solution_does_not_prove_unique():
    """Encuentra 100 exacto; el presupuesto se agota antes de demostrar unicidad.

    Los PDF de 7 no forman otra cubierta de 100, pero el árbol es enorme.
    Hallar la primera solución no autoriza UNIQUE.
    """
    cands = [_c("AS/exact.pdf", "327", 100.0)] + [
        _c(f"AS/t{i:02d}.pdf", "327", 7.0) for i in range(16)
    ]
    out = assign_asientos_unique(
        [IdPagoTarget("P1", 100.0, frozenset({"327"}))],
        cands,
        node_budget=80,
    )
    assert out.errors["P1"] == ASIENTO_ASSIGNMENT_COMPLEXITY_LIMIT
    assert out.assignment["P1"] == ()
    assert out.errors["P1"] != ASIENTO_ASSIGNMENT_AMBIGUOUS
    high = assign_asientos_unique(
        [IdPagoTarget("P1", 100.0, frozenset({"327"}))],
        cands,
    )
    assert not high.errors
    assert high.assignment["P1"] == ("AS/exact.pdf",)


def test_zero_vp_retenciones_attaches_to_same_fecha_not_later_payment():
    out = assign_asientos_unique(
        [
            IdPagoTarget(
                "P21",
                322_558_848.0,
                frozenset({"248"}),
                fecha_banco=date(2026, 7, 21),
            ),
            IdPagoTarget(
                "P23",
                62_852.0,
                frozenset({"248"}),
                fecha_banco=date(2026, 7, 23),
            ),
        ],
        [
            _c(
                "AS/4119.pdf",
                "248",
                322_558_848.0,
                fecha_asiento=date(2026, 7, 21),
            ),
            _c(
                "AS/4120.pdf",
                "248",
                0.0,
                fecha_asiento=date(2026, 7, 21),
            ),
            _c(
                "AS/4147.pdf",
                "248",
                62_852.0,
                fecha_asiento=date(2026, 7, 23),
            ),
        ],
    )
    assert not out.errors
    assert set(out.assignment["P21"]) == {"AS/4119.pdf", "AS/4120.pdf"}
    assert out.assignment["P23"] == ("AS/4147.pdf",)


def test_zero_vp_does_not_make_cash_cover_ambiguous():
    out = assign_asientos_unique(
        [
            IdPagoTarget(
                "P1", 100.0, frozenset({"1"}), fecha_banco=date(2026, 7, 21)
            )
        ],
        [
            _c("AS/cash.pdf", "1", 100.0, fecha_asiento=date(2026, 7, 21)),
            _c("AS/ret.pdf", "1", 0.0, fecha_asiento=date(2026, 7, 21)),
        ],
    )
    assert not out.errors
    assert set(out.assignment["P1"]) == {"AS/cash.pdf", "AS/ret.pdf"}
