"""Registro de decisiones: decisiones de fase 3 (consolidar) y su bloqueo al consolidar."""

from __future__ import annotations

from typing import Any

import pytest

from app.application.services.amortization_decisions import (
    FASE_AMORTIZACION,
    FASE_CONSOLIDACION,
    DecisionsRegistryError,
    active_tipo_corrections,
    add_confirmation,
    add_exclusion,
    add_tipo_correction,
    add_unused_asiento,
    empty_registry,
    explicit_assignments,
    group_assignments,
    lock_active_decisions,
    lock_consolidation_decisions,
    normalize_registry,
    set_group_assignments,
    tipo_correction_for_pago,
    undo_confirmation,
    undo_exclusion,
    undo_group_assignments,
    undo_tipo_correction,
    undo_unused_asiento,
    unused_asiento_paths,
    unused_asientos,
)

PK = "payment-validation|banco_bogota|2026-09-25|abc12345-0000"


def _registry() -> dict[str, Any]:
    return empty_registry(process_key=PK, bank_code="banco_bogota", report_date_iso="2026-09-25")


def _items_247() -> list[dict[str, Any]]:
    return [
        {"credito": "247", "asiento_pdf_path": "A/247/4634.pdf", "id_pago": "P-ABONO", "fecha_banco": "2026-09-22"},
        {"credito": "247", "asiento_pdf_path": "A/247/4635.pdf", "id_pago": "P-CUOTA", "fecha_banco": "2026-09-25"},
    ]


def test_empty_registry_has_tipo_corrections_and_normalize_keeps_old_files():
    assert _registry()["tipo_corrections"] == []
    old = {"process_key": PK, "exclusions": [], "confirmations": []}
    norm = normalize_registry(old)
    assert norm["tipo_corrections"] == []
    assert norm["assignments"] == []


def test_exclusion_records_phase_and_folders():
    reg, entry = add_exclusion(
        _registry(),
        credits=["87"],
        clientes={"87": "CARBONERA"},
        id_pagos=["P1"],
        tablas={"87": "T/87.xlsx"},
        motivo_codigo="FALTA_ASIENTO",
        nota="",
        quien="op",
        fase=FASE_CONSOLIDACION,
        asientos_dirs={"87": "/C/87/ASIENTOS/"},
    )
    assert entry["fase"] == FASE_CONSOLIDACION
    assert entry["asientos_dirs"] == {"87": "C/87/ASIENTOS"}


def test_exclusion_default_phase_stays_amortizacion():
    _, entry = add_exclusion(
        _registry(),
        credits=["87"],
        clientes={},
        id_pagos=[],
        tablas={},
        motivo_codigo="FALTA_ASIENTO",
        nota="",
        quien="op",
    )
    assert entry["fase"] == FASE_AMORTIZACION
    assert "asientos_dirs" not in entry


def test_set_group_assignments_replaces_previous_and_keeps_history():
    reg, created = set_group_assignments(_registry(), group_key="247", items=_items_247(), quien="op")
    assert len(created) == 2
    assert {a["fase"] for a in created} == {FASE_CONSOLIDACION}
    assert len({a["assignment_id"] for a in created}) == 1
    swapped = [dict(i) for i in _items_247()]
    swapped[0]["id_pago"], swapped[1]["id_pago"] = "P-CUOTA", "P-ABONO"
    reg2, created2 = set_group_assignments(reg, group_key="247", items=swapped, quien="op2")
    active = group_assignments(reg2, "247")
    assert {(a["asiento_pdf_path"], a["id_pago"]) for a in active} == {
        ("A/247/4634.pdf", "P-CUOTA"),
        ("A/247/4635.pdf", "P-ABONO"),
    }
    assert len(reg2["assignments"]) == 4
    assert sum(1 for a in reg2["assignments"] if a["status"] == "undone") == 2


def test_set_group_assignments_is_idempotent_for_same_mapping():
    reg, first = set_group_assignments(_registry(), group_key="247", items=_items_247(), quien="op")
    reg2, second = set_group_assignments(reg, group_key="247", items=_items_247(), quien="op")
    assert reg2 == reg
    assert [a["assignment_id"] for a in second] == [a["assignment_id"] for a in first]


def test_empty_assignment_rejected():
    with pytest.raises(DecisionsRegistryError) as exc:
        set_group_assignments(_registry(), group_key="247", items=[], quien="op")
    assert exc.value.status_code == 422


def test_undo_group_assignments_and_consumer_view():
    reg, _ = set_group_assignments(_registry(), group_key="247", items=_items_247(), quien="op")
    assert len(explicit_assignments(reg)) == 2
    reg2, undone = undo_group_assignments(reg, group_key="247", quien="op")
    assert len(undone) == 2
    assert explicit_assignments(reg2) == []


def test_unused_asiento_with_reason_and_undo():
    reg, entry = add_unused_asiento(
        _registry(),
        path="/A/322/4158.pdf",
        credito_carpeta="CREDITO # 322",
        nota="",
        quien="op",
        motivo_codigo="OTRO_CREDITO",
        fase=FASE_CONSOLIDACION,
    )
    assert entry["motivo"] == "Asiento de otro crédito"
    assert entry["nota"] == "Asiento de otro crédito"
    assert unused_asiento_paths(reg) == {"a/322/4158.pdf"}
    reg2, undone = undo_unused_asiento(reg, path="A/322/4158.pdf", quien="op")
    assert undone is not None and undone["status"] == "undone"
    assert unused_asientos(reg2) == []
    assert len(reg2["asientos_no_usados"]) == 1


def test_unused_asiento_invalid_reason():
    with pytest.raises(DecisionsRegistryError):
        add_unused_asiento(
            _registry(), path="A/x.pdf", credito_carpeta="1", nota="", quien="op", motivo_codigo="XYZ"
        )


def test_tipo_correction_requires_note_and_replaces():
    with pytest.raises(DecisionsRegistryError) as exc:
        add_tipo_correction(
            _registry(),
            group_key="87",
            id_pago="P1",
            credits=["87"],
            tipo_anterior="PAGO CUOTA",
            tipo_nuevo="PAGO CUOTA + ABONO A CAPITAL",
            nota="  ",
            quien="op",
        )
    assert exc.value.status_code == 422
    reg, entry = add_tipo_correction(
        _registry(),
        group_key="87",
        id_pago="P1",
        credits=["87"],
        tipo_anterior="PAGO CUOTA",
        tipo_nuevo="PAGO CUOTA + ABONO A CAPITAL",
        nota="El asiento trae capital adicional",
        quien="op",
    )
    assert tipo_correction_for_pago(reg, "P1")["tipo_nuevo"] == "PAGO CUOTA + ABONO A CAPITAL"
    reg2, entry2 = add_tipo_correction(
        reg,
        group_key="87",
        id_pago="P1",
        credits=["87"],
        tipo_anterior="PAGO CUOTA",
        tipo_nuevo="PAGO TOTAL",
        nota="Saldo en cero",
        quien="op",
    )
    assert len(active_tipo_corrections(reg2)) == 1
    assert tipo_correction_for_pago(reg2, "P1")["tipo_nuevo"] == "PAGO TOTAL"
    reg3, undone = undo_tipo_correction(reg2, id_pago="P1", quien="op")
    assert undone is not None
    assert tipo_correction_for_pago(reg3, "P1") is None


def _full_phase3_registry() -> dict[str, Any]:
    reg, _ = add_exclusion(
        _registry(),
        credits=["87"],
        clientes={},
        id_pagos=["P87"],
        tablas={},
        motivo_codigo="FALTA_ASIENTO",
        nota="",
        quien="op",
        fase=FASE_CONSOLIDACION,
    )
    reg, _ = add_confirmation(
        reg,
        key="102+133|2026-09-09",
        credits=["102", "133"],
        clientes={},
        fecha_banco="2026-09-09",
        monto_banco="105000000",
        monto_asientos="104990000",
        nota="",
        quien="op",
        fase=FASE_CONSOLIDACION,
    )
    reg, _ = set_group_assignments(reg, group_key="247", items=_items_247(), quien="op")
    reg, _ = add_unused_asiento(
        reg, path="A/322/x.pdf", credito_carpeta="322", nota="", quien="op",
        motivo_codigo="PAGO_ANTERIOR", fase=FASE_CONSOLIDACION,
    )
    reg, _ = add_tipo_correction(
        reg, group_key="1", id_pago="P1", credits=["1"], tipo_anterior="PAGO CUOTA",
        tipo_nuevo="PAGO TOTAL", nota="saldo cero", quien="op",
    )
    return reg


def test_lock_consolidation_decisions_blocks_every_undo():
    reg, changed = lock_consolidation_decisions(_full_phase3_registry(), attempt_id="merge-job-1")
    assert changed
    for fn, kwargs in (
        (undo_exclusion, {"credit": "87"}),
        (undo_confirmation, {"key": "102+133|2026-09-09"}),
        (undo_group_assignments, {"group_key": "247"}),
        (undo_unused_asiento, {"path": "A/322/x.pdf"}),
        (undo_tipo_correction, {"id_pago": "P1"}),
    ):
        with pytest.raises(DecisionsRegistryError) as exc:
            fn(reg, quien="op", **kwargs)
        assert "consolidados ya se generaron" in exc.value.user_message
    _, again = lock_consolidation_decisions(reg, attempt_id="merge-job-2")
    assert again is False


def test_lock_consolidation_ignores_phase4_decisions():
    reg, _ = add_exclusion(
        _registry(), credits=["5"], clientes={}, id_pagos=[], tablas={},
        motivo_codigo="FALTA_ASIENTO", nota="", quien="op",
    )
    reg2, changed = lock_consolidation_decisions(reg, attempt_id="m1")
    assert changed is False
    undone, _ = undo_exclusion(reg2, credit="5", quien="op")
    assert undone["exclusions"][0]["status"] == "undone"


def test_phase4_lock_message_unchanged_for_amortization_decisions():
    reg, entry = add_exclusion(
        _registry(), credits=["5"], clientes={}, id_pagos=[], tablas={},
        motivo_codigo="FALTA_ASIENTO", nota="", quien="op",
    )
    reg, _ = lock_active_decisions(reg, attempt_id="a1")
    with pytest.raises(DecisionsRegistryError) as exc:
        undo_exclusion(reg, credit="5", quien="op")
    assert "amortización ya se procesó" in exc.value.user_message
