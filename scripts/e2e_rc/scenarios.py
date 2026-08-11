"""Catálogo E01–E40 del mandato RC (§27)."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class Scenario:
    id: str
    title: str
    critical: bool = True
    layers: tuple[str, ...] = ("B",)  # A=UI Playwright, B=Graph helper
    notes: str = ""
    tags: tuple[str, ...] = ()


SCENARIOS: tuple[Scenario, ...] = (
    Scenario("E01", "PAGO NORMAL", notes="una obligación actual; saldo 0"),
    Scenario("E02", "PAGO PARCIAL OBLIGACIÓN"),
    Scenario("E03", "PAGO ATRASADO"),
    Scenario("E04", "PAGO ADELANTADO"),
    Scenario("E05", "SALDO VENCIDO PARCIAL"),
    Scenario("E06", "SALDO VENCIDO TOTAL"),
    Scenario("E07", "SALDO VENCIDO TOTAL + OBLIGACIÓN ACTUAL PARCIAL"),
    Scenario("E08", "SALDO VENCIDO TOTAL + OBLIGACIÓN ACTUAL COMPLETA"),
    Scenario("E09", "ABONO CAPITAL PURO"),
    Scenario("E10", "OBLIGACIÓN + ABONO CAPITAL"),
    Scenario("E11", "SALDO VENCIDO + ABONO CAPITAL"),
    Scenario("E12", "SALDO VENCIDO + OBLIGACIÓN + ABONO CAPITAL"),
    Scenario("E13", "ÚLTIMA CUOTA → PAGO TOTAL"),
    Scenario("E14", "CANCELACIÓN CON CAPITAL ADICIONAL"),
    Scenario("E15", "PAGO TOTAL SELECCIONADO ERRÓNEAMENTE", notes="dry-run debe bloquear"),
    Scenario("E16", "UN PAGO → DOS CRÉDITOS"),
    Scenario("E17", "UN PAGO → VARIOS CRÉDITOS CON TIPOS DIFERENTES", notes="Merge APLICACION MULTIPLE"),
    Scenario("E18", "EXTRACTO CON APLICACIÓN ANTERIOR A LA DERECHA"),
    Scenario("E19", "EXTRACTO CON SALDO MORA A LA DERECHA"),
    Scenario("E20", "EXTRACTO AMBIGUO", notes="revisión humana permitida"),
    Scenario("E21", "CRÉDITO SIN EXTRACTO"),
    Scenario("E22", "EXTRACTO NO MÁS RECIENTE PERO CORRECTO AS-OF FECHA BANCO"),
    Scenario("E23", "MISMO CLIENTE CON DOS PAGOS DE FECHAS DIFERENTES"),
    Scenario("E24", "REVIEW != ASIENTO POR CRÉDITO PERO TOTAL BANCO CUADRA"),
    Scenario("E25", "BANCO != TOTAL ASIENTOS", notes="bloqueo"),
    Scenario("E26", "ASIENTO CRÉDITO INCORRECTO", notes="bloqueo"),
    Scenario("E27", "ASIENTO FALTANTE", notes="bloqueo"),
    Scenario("E28", "ASIENTO ILEGIBLE", notes="bloqueo"),
    Scenario("E29", "RETRY GENERATE", layers=("A", "B"), critical=False),
    Scenario("E30", "RETRY FINALIZE", layers=("A", "B"), critical=False),
    Scenario("E31", "RETRY NOTIFY", layers=("A", "B"), critical=False),
    Scenario("E32", "RETRY MERGE", layers=("A", "B"), critical=False),
    Scenario("E33", "RETRY AMORTIZACIÓN", layers=("A", "B"), critical=False),
    Scenario("E34", "DOBLE CLICK UI", layers=("A",), critical=False),
    Scenario("E35", "REFRESH DURANTE JOB RUNNING", layers=("A",), critical=False),
    Scenario("E36", "NETWORK ERROR / RECOVERY", layers=("A",), critical=False),
    Scenario("E37", "CANCEL LOTE EN MOMENTO PERMITIDO", layers=("A", "B"), critical=False),
    Scenario("E38", "CANCEL LOTE CUANDO YA NO ESTÁ PERMITIDO", layers=("A", "B"), critical=False),
    Scenario("E39", "FINALIZAR SIN AMORTIZACIÓN SOLO EN FASE CORRECTA", layers=("A", "B"), critical=False),
    Scenario("E40", "TRUE AMORTIZACION_PARCIAL", notes="un crédito OK / otro falla; no reprocesar el primero"),
)


def by_id(scenario_id: str) -> Scenario:
    for s in SCENARIOS:
        if s.id == scenario_id:
            return s
    raise KeyError(scenario_id)


@dataclass
class ScenarioResult:
    id: str
    status: str  # PASS | FAIL | BLOCKED | SKIPPED
    evidence: str = ""
    process_key: str | None = None
    artifacts: list[str] = field(default_factory=list)
    cleanup: str = ""
    detail: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "status": self.status,
            "evidence": self.evidence,
            "process_key": self.process_key,
            "artifacts": self.artifacts,
            "cleanup": self.cleanup,
            "detail": self.detail,
        }
