"""Detección schema v3 (Aplicacion_Pagos) — sin compat v1/v2."""

import pytest

from app.application.services.review_schema import (
    REVIEW_SCHEMA_VERSION,
    AplicacionPagosCols,
    detect_aplicacion_pagos_schema_version,
)


def test_schema_v3_canonical_headers():
    assert detect_aplicacion_pagos_schema_version(list(AplicacionPagosCols.HEADERS)) == REVIEW_SCHEMA_VERSION


def test_schema_incomplete_headers_not_v3():
    assert detect_aplicacion_pagos_schema_version(["ID Pago", "Cliente"]) == 0


@pytest.mark.parametrize("missing", list(AplicacionPagosCols.HEADERS)[:3])
def test_missing_any_required_column_fails_v3(missing: str):
    headers = [h for h in AplicacionPagosCols.HEADERS if h != missing]
    assert detect_aplicacion_pagos_schema_version(headers) == 0
