"""Tests helper de jerarquía YYYY/MM/día + id corto."""
from __future__ import annotations

from datetime import date

from app.application.services.dated_artifact_layout import (
    dated_folder_relative,
    join_dated_artifact_path,
    short_process_id,
)


def test_short_process_id_eight_hex():
    assert (
        short_process_id("4df53868-eeb1-428f-9c92-98e0efcad7ec") == "4df53868"
    )
    assert short_process_id("ABCDEF12") == "abcdef12"
    assert short_process_id("") == "unknown"


def test_dated_folder_and_join():
    assert dated_folder_relative(date(2026, 8, 2)) == "2026/08/2026-08-02"
    assert dated_folder_relative("2026-08-02") == "2026/08/2026-08-02"
    path = join_dated_artifact_path(
        "03 HISTORICO",
        "2026-08-02",
        "cartera_validada_banco_bogota_2026-08-02_4df53868.xlsx",
    )
    assert path == (
        "03 HISTORICO/2026/08/2026-08-02/"
        "cartera_validada_banco_bogota_2026-08-02_4df53868.xlsx"
    )
