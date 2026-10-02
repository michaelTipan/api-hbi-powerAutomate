"""Textos del cierre visibles en la UI: lenguaje de operador, sin «API»."""

from __future__ import annotations

import re

from app.application.ui.process_control_capabilities import compute_soft_close_availability
from app.application.ui.process_projection import derive_operational_guidance

_API = re.compile(r"\bAPI\b")


def test_cerrado_sin_amortizar_indica_aplicacion_manual_sin_mencionar_api() -> None:
    title, message, _ = derive_operational_guidance(
        "CERRADO_SIN_AMORTIZAR", control_estado="CERRADO_SIN_AMORTIZAR"
    )
    assert title == "Cerrado sin amortizar"
    assert "de forma manual" in message
    assert not _API.search(message)


def test_cerrado_amortizacion_incompleta_sin_mencionar_api() -> None:
    _, message, _ = derive_operational_guidance(
        "CERRADO_AMORTIZACION_INCOMPLETA",
        control_estado="CERRADO_AMORTIZACION_INCOMPLETA",
    )
    assert not _API.search(message)


def test_motivo_cierre_fuera_de_fase_sin_mencionar_api() -> None:
    availability = compute_soft_close_availability(
        write_allowed=True,
        mutation_active=False,
        control_estado="REVISION_CREADA",
    )
    assert availability.allowed is False
    assert availability.reason
    assert "de forma manual" in availability.reason
    assert not _API.search(availability.reason)
