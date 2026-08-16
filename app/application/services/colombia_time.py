"""
Reloj operativo de la API: America/Bogota (Colombia, UTC-5, sin DST).

Toda marca de tiempo visible al usuario, a la secretaría o al desarrollador
(nombres de archivo por fecha de proceso, Excel de control, logs de automatización,
jobs HTTP, PDFs de correo) debe generarse aquí. Las fechas de negocio que ya
llegan como ``date`` desde extractos/banco no se convierten: son fechas de
calendario colombiano.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo

# Colombia no aplica horario de verano; ZoneInfo cubre el offset oficial.
COLOMBIA_TZ = ZoneInfo("America/Bogota")
COLOMBIA_TZ_NAME = "America/Bogota"


def now_colombia() -> datetime:
    """Instante actual con tz America/Bogota."""
    return datetime.now(COLOMBIA_TZ)


def today_colombia() -> date:
    """Fecha de calendario en Colombia (para process_date por defecto, etc.)."""
    return now_colombia().date()


def now_colombia_iso(*, timespec: str = "seconds") -> str:
    """
    ISO-8601 con offset ``-05:00`` (ej. ``2026-07-27T16:23:16-05:00``).

    Preferido en control Excel, jobs y trazabilidad.
    """
    return now_colombia().isoformat(timespec=timespec)


def now_colombia_wall_clock() -> str:
    """
    Fecha-hora legible en Excel / paneles (sin sufijo Z ni offset).

    Formato: ``YYYY-MM-DD HH:MM:SS`` en hora de Colombia.
    """
    return now_colombia().strftime("%Y-%m-%d %H:%M:%S")


def today_colombia_iso() -> str:
    """``YYYY-MM-DD`` del día calendario en Colombia."""
    return today_colombia().isoformat()


def ensure_colombia(dt: datetime) -> datetime:
    """Normaliza un datetime a America/Bogota (naive se interpreta como Colombia)."""
    if dt.tzinfo is None:
        return dt.replace(tzinfo=COLOMBIA_TZ)
    return dt.astimezone(COLOMBIA_TZ)


def parse_graph_datetime(raw: str | None) -> datetime | None:
    """Parsea un timestamp de Microsoft Graph a datetime aware.

    Graph entrega UTC (sufijo ``Z`` u offset). Un valor naive se trata como UTC
    (no como hora Colombia): no se mezcla naive con aware.
    """
    s = str(raw or "").strip()
    if not s:
        return None
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def graph_datetime_colombia_date(raw: str | None) -> date | None:
    """Fecha de calendario operativa (America/Bogota) de un timestamp Graph."""
    dt = parse_graph_datetime(raw)
    if dt is None:
        return None
    return ensure_colombia(dt).date()
