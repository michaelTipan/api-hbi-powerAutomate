"""Catálogo de fixtures sandbox PRUEBAS para matriz E01–E40 (CAPA B).

No escribe SharePoint por sí solo: documenta requisitos y genera artefactos
locales (PDF mínimos, plans de upload) para que el harness/E2E provisione
bajo ``AUTHORIZED_CLIENTS_BASE`` cuando corra contra sandbox.
"""
from __future__ import annotations

import io
from dataclasses import dataclass
from typing import Any

from pypdf import PdfWriter

from scripts.e2e_rc.path_guard import AUTHORIZED_CLIENTS_BASE

# Destinatarios permitidos en Notify E2E (nunca @hbi.com.co reales).
SANDBOX_NOTIFY_ALLOWLIST = frozenset(
    {
        "herramientas.jsakedev@gmail.com",
    }
)
HBI_DOMAIN_BLOCK = "@hbi.com.co"


@dataclass(frozen=True)
class FixtureNeed:
    scenario_id: str
    kind: str  # extract | asiento | tabla | correos | multi_credit | dual_amort | capa_a
    detail: str
    client_hint: str = ""
    credit_hint: str = ""
    local_generator: str = ""  # nombre helper en este módulo, si aplica


# Escenarios que hoy quedan BLOCKED sin fixture sandbox.
CRITICAL_FIXTURE_GAPS: tuple[FixtureNeed, ...] = (
    FixtureNeed("E05", "extract", "Saldo vencido parcial medible", "AGRECAR|GEOEXCON", ""),
    FixtureNeed("E06", "extract", "Saldo vencido total en extracto", "", ""),
    FixtureNeed("E07", "extract", "Vencido total + obligación parcial", "", ""),
    FixtureNeed("E08", "extract", "Vencido total + obligación completa", "", ""),
    FixtureNeed("E11", "extract", "Vencido + abono capital mismo crédito", "", ""),
    FixtureNeed("E12", "extract", "A+V+K concurrente multi-panel", "", ""),
    FixtureNeed("E13", "tabla", "Crédito en última cuota (payoff real)", "", ""),
    FixtureNeed("E14", "tabla", "Payoff + capital adicional", "", ""),
    FixtureNeed("E16", "multi_credit", "Un pago → dos créditos reconciliables", "GEOEXCON", "231+254"),
    FixtureNeed("E17", "multi_credit", "Tipos distintos → Merge MULTIPLE", "GEOEXCON", ""),
    FixtureNeed("E18", "extract", "Panel derecho aplicación anterior", "", "", "minimal_text_pdf"),
    FixtureNeed("E19", "extract", "Saldo mora a la derecha", "", "", "minimal_text_pdf"),
    FixtureNeed("E20", "extract", "PDF ambiguo doble panel", "", "", "minimal_text_pdf"),
    FixtureNeed("E22", "extract", "Dos extractos; as-of ≠ más reciente", "", ""),
    FixtureNeed("E23", "multi_credit", "Dos pagos mismo cliente fechas distintas", "GEOEXCON", ""),
    FixtureNeed("E24", "asiento", "Mismatch por crédito; total banco OK", "", ""),
    FixtureNeed("E25", "asiento", "Total asientos ≠ banco (bloqueo amort)", "GEOEXCON", "231"),
    FixtureNeed("E26", "asiento", "Asiento de crédito incorrecto", "", ""),
    FixtureNeed("E27", "asiento", "Asiento faltante post-merge", "", ""),
    FixtureNeed("E28", "asiento", "PDF asiento ilegible (sin texto)", "", "", "blank_image_like_pdf"),
    FixtureNeed("E30", "control", "Retry finalize sobre FINALIZADO estable", "", ""),
    FixtureNeed("E31", "correos", "CORREOS.xlsx solo recipients sandbox", "", "", "assert_sandbox_notify_recipients"),
    FixtureNeed("E32", "asiento", "Retry merge + asientos previos", "", ""),
    FixtureNeed("E33", "tabla", "Retry amort + backup tabla", "", ""),
    FixtureNeed("E34", "capa_a", "Playwright doble click", "", ""),
    FixtureNeed("E35", "capa_a", "Playwright refresh mid-job", "", ""),
    FixtureNeed("E36", "capa_a", "Playwright network fault", "", ""),
    FixtureNeed("E38", "control", "Cancel no permitido post-fase avanzada", "", ""),
    FixtureNeed("E39", "control", "Finalize sin amort en fase correcta", "", ""),
    FixtureNeed("E40", "dual_amort", "AMORTIZACION_PARCIAL true dual-crédito", "", ""),
)


def clients_base() -> str:
    return AUTHORIZED_CLIENTS_BASE


def asientos_folder_rel(client: str, credit_folder: str, credit_num: str) -> str:
    """Ruta relativa PRUEBAS a carpeta ASIENTOS (path-guard la valida en upload)."""
    return (
        f"{AUTHORIZED_CLIENTS_BASE}/{client}/{credit_folder}/"
        f"ASIENTOS CONTABLES CRED {credit_num}"
    )


def minimal_text_pdf(*, title: str = "RC fixture") -> bytes:
    """PDF con texto seleccionable (útil como asiento/extracto mínimo)."""
    from reportlab.pdfgen import canvas  # type: ignore

    buf = io.BytesIO()
    c = canvas.Canvas(buf)
    c.drawString(72, 720, title)
    c.drawString(72, 700, "544111100505 1000000.00")
    c.drawString(72, 680, "544113410519 1000000.00")
    c.save()
    return buf.getvalue()


def blank_image_like_pdf() -> bytes:
    """PDF sin texto extraíble (asiento ilegible E28)."""
    writer = PdfWriter()
    writer.add_blank_page(width=200, height=200)
    buf = io.BytesIO()
    writer.write(buf)
    return buf.getvalue()


def assert_sandbox_notify_recipients(emails: list[str]) -> list[str]:
    """Fail-closed: solo allowlist sandbox; bloquea cualquier @hbi.com.co."""
    cleaned: list[str] = []
    for raw in emails:
        addr = str(raw or "").strip().lower()
        if not addr:
            continue
        if HBI_DOMAIN_BLOCK in addr:
            raise ValueError(f"notify_recipient_blocked_hbi:{addr}")
        if addr not in SANDBOX_NOTIFY_ALLOWLIST:
            raise ValueError(f"notify_recipient_not_sandbox:{addr}")
        cleaned.append(addr)
    if not cleaned:
        raise ValueError("notify_recipients_empty")
    return cleaned


def gaps_by_scenario() -> dict[str, list[FixtureNeed]]:
    out: dict[str, list[FixtureNeed]] = {}
    for need in CRITICAL_FIXTURE_GAPS:
        out.setdefault(need.scenario_id, []).append(need)
    return out


def catalog_as_dicts() -> list[dict[str, Any]]:
    return [
        {
            "scenario_id": n.scenario_id,
            "kind": n.kind,
            "detail": n.detail,
            "client_hint": n.client_hint,
            "credit_hint": n.credit_hint,
            "local_generator": n.local_generator,
            "clients_base": AUTHORIZED_CLIENTS_BASE,
        }
        for n in CRITICAL_FIXTURE_GAPS
    ]
