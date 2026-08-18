"""Reloj operativo America/Bogota: marcas visibles al usuario y al desarrollador."""

from __future__ import annotations

from datetime import date, datetime, timezone

from app.application.services.colombia_time import (
    COLOMBIA_TZ,
    COLOMBIA_TZ_NAME,
    ensure_colombia,
    format_operator_date,
    format_operator_datetime,
    now_colombia,
    now_colombia_iso,
    now_colombia_wall_clock,
    today_colombia,
    today_colombia_iso,
)
from app.application.use_cases.payment_validation_process_control import utc_now_iso
from app.logging_config import _asctime_colombia


def test_colombia_tz_name() -> None:
    assert COLOMBIA_TZ_NAME == "America/Bogota"
    assert str(COLOMBIA_TZ) == "America/Bogota"


def test_now_colombia_has_bogota_offset() -> None:
    dt = now_colombia()
    assert dt.tzinfo is not None
    assert dt.utcoffset() is not None
    # Colombia fijo UTC-5, sin DST.
    assert dt.utcoffset().total_seconds() == -5 * 3600


def test_now_colombia_iso_offset_suffix() -> None:
    iso = now_colombia_iso()
    assert iso.endswith("-05:00")
    assert "T" in iso
    assert "Z" not in iso


def test_utc_now_iso_alias_is_colombia() -> None:
    """Compat: el nombre histórico no debe devolver UTC."""
    iso = utc_now_iso()
    assert iso.endswith("-05:00")
    parsed = datetime.fromisoformat(iso)
    assert parsed.utcoffset() is not None
    assert parsed.utcoffset().total_seconds() == -5 * 3600


def test_wall_clock_format() -> None:
    wall = now_colombia_wall_clock()
    # YYYY-MM-DD HH:MM:SS
    assert len(wall) == 19
    assert wall[4] == "-" and wall[7] == "-" and wall[10] == " "
    datetime.strptime(wall, "%Y-%m-%d %H:%M:%S")


def test_today_colombia_matches_now_date() -> None:
    assert today_colombia() == now_colombia().date()
    assert today_colombia_iso() == today_colombia().isoformat()


def test_ensure_colombia_from_utc() -> None:
    utc = datetime(2026, 7, 28, 2, 30, 0, tzinfo=timezone.utc)
    local = ensure_colombia(utc)
    assert local.tzinfo == COLOMBIA_TZ
    assert local.hour == 21  # 02:30 UTC → 21:30 día anterior en Bogotá
    assert local.day == 27


def test_ensure_colombia_naive_assumes_bogota() -> None:
    naive = datetime(2026, 7, 27, 16, 0, 0)
    local = ensure_colombia(naive)
    assert local.tzinfo == COLOMBIA_TZ
    assert local.hour == 16


def test_format_operator_date_short() -> None:
    assert format_operator_date(date(2026, 8, 4)) == "4 ago 2026"


def test_format_operator_datetime_graph_utc() -> None:
    assert format_operator_datetime("2026-08-18T17:52:00Z") == "18 ago 2026, 12:52 p. m."
    assert format_operator_datetime("2026-08-11T15:00:00Z") == "11 ago 2026, 10:00 a. m."
    assert format_operator_datetime("2026-08-18T17:52:53.7") == "18 ago 2026, 12:52 p. m."
    assert format_operator_datetime(None) is None


def test_logging_converter_uses_colombia() -> None:
    # 2026-07-28 02:00:00 UTC = 2026-07-27 21:00:00 Bogotá
    epoch = datetime(2026, 7, 28, 2, 0, 0, tzinfo=timezone.utc).timestamp()
    st = _asctime_colombia(epoch)
    assert st.tm_year == 2026
    assert st.tm_mon == 7
    assert st.tm_mday == 27
    assert st.tm_hour == 21
