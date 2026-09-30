"""Columnas del Excel de carga del banco: alias de Cliente y columna opcional No. Crédito.

Lo usan los dos lectores del Excel de carga: Generate (filas de revisión) y el
correo de validación / consolidación (tabla del correo y fecha mínima).
"""

from __future__ import annotations

import json
import re
from typing import Any

from app.application.services.payment_helpers import _normalize_str

# Prioridad: si vienen ambas columnas, manda «Cliente».
CLIENT_HEADER_ALIASES: tuple[str, ...] = ("Cliente", "Concepto")

_CREDIT_NUMBER_HEADER_KEYS = frozenset(
    {
        "no.credito",
        "nocredito",
        "no.decredito",
        "nodecredito",
        "n.credito",
        "ncredito",
        "ndecredito",
        "nro.credito",
        "nrocredito",
        "nro.decredito",
        "nrodecredito",
        "numerodecredito",
        "numerocredito",
        "#credito",
        "#decredito",
    }
)

CREDIT_ISSUE_INVALID = "invalid"
CREDIT_ISSUE_DECIMAL = "decimal"
CREDIT_ISSUE_NOT_FOUND = "not_found"

BANK_CREDIT_COLUMN_ERROR_CODE = "bank_credit_column_invalid"
BANK_CLIENT_COLUMN_MISSING_CODE = "bank_client_column_missing"

MAX_LISTED_ISSUES = 10
_MAX_ISSUES_IN_PAYLOAD = 50

_SPLIT_RE = re.compile(r"\s*(?:[,;/]|\s+y\s+)\s*", re.IGNORECASE)
_PART_RE = re.compile(r"#?\s*(\d+)")


def normalize_bank_header(value: Any) -> str:
    """Encabezado sin tildes, sin espacios y en minúsculas («No. Crédito» → «no.credito»)."""
    return _normalize_str(str(value or "")).replace(" ", "")


def find_client_column(headers: list[Any] | tuple[Any, ...]) -> int:
    """Índice (base 0) de la columna de cliente; «Cliente» gana sobre «Concepto». -1 si no hay."""
    normalized = [normalize_bank_header(h) for h in headers]
    for alias in CLIENT_HEADER_ALIASES:
        key = normalize_bank_header(alias)
        if key in normalized:
            return normalized.index(key)
    return -1


def is_credit_number_header(value: Any) -> bool:
    """True para «No. Crédito» y variantes; nunca para «Crédito» (el monto)."""
    return normalize_bank_header(value) in _CREDIT_NUMBER_HEADER_KEYS


def find_credit_number_column(headers: list[Any] | tuple[Any, ...]) -> int:
    for idx, header in enumerate(headers):
        if is_credit_number_header(header):
            return idx
    return -1


def parse_credit_number_cell(value: Any) -> tuple[tuple[int, ...], str | None]:
    """Números de crédito pedidos en una celda de «No. Crédito».

    Devuelve ``(números, None)`` si la celda es válida (vacía → sin números) o
    ``((), motivo)`` si no lo es. Varios créditos se separan con «,», «;», «/»
    o la palabra «y». Un número con decimales es inválido: Excel en español
    convierte «247,248» en 247.248.
    """
    if value is None or isinstance(value, bool):
        return ((), None) if value is None else ((), CREDIT_ISSUE_INVALID)
    if isinstance(value, int):
        return ((value,), None) if value > 0 else ((), CREDIT_ISSUE_INVALID)
    if isinstance(value, float):
        if value != value or value in (float("inf"), float("-inf")):
            return (), CREDIT_ISSUE_INVALID
        if not value.is_integer():
            return (), CREDIT_ISSUE_DECIMAL
        number = int(value)
        return ((number,), None) if number > 0 else ((), CREDIT_ISSUE_INVALID)
    if not isinstance(value, str):
        return (), CREDIT_ISSUE_INVALID
    text = value.strip()
    if not text:
        return (), None
    numbers: list[int] = []
    for part in _SPLIT_RE.split(text):
        part = part.strip()
        if not part:
            continue
        match = _PART_RE.fullmatch(part)
        if not match:
            return (), CREDIT_ISSUE_INVALID
        number = int(match.group(1))
        if number <= 0:
            return (), CREDIT_ISSUE_INVALID
        if number not in numbers:
            numbers.append(number)
    if not numbers:
        return (), CREDIT_ISSUE_INVALID
    return tuple(numbers), None


def credit_cell_display(value: Any) -> str:
    """Valor de la celda tal como lo vería el operador en Excel (coma decimal)."""
    if isinstance(value, float):
        if value.is_integer():
            return str(int(value))
        return repr(value).replace(".", ",")
    return str(value if value is not None else "").strip()


def credit_number_from_label(raw: Any) -> int | None:
    """Número de crédito comparable (040 == 40) desde la etiqueta de un candidato."""
    from app.application.services.review_schema import normalize_credito_digits

    digits = normalize_credito_digits(raw)
    return int(digits) if digits.isdigit() else None


class BankUploadInputError(ValueError):
    """Problema del Excel de carga detectado antes de modificar el proceso.

    ``control_untouched`` indica que el Control del banco quedó igual que antes:
    quien atiende el fallo no debe marcarlo como error de Generate.
    """

    control_untouched = True


class BankUploadCreditColumnError(BankUploadInputError):
    """Valores de «No. Crédito» con formato inválido o créditos que no existen."""

    def __init__(
        self,
        issues: list[dict[str, Any]],
        *,
        stage: str,
        mode: str,
    ) -> None:
        self.issues = list(issues)
        self.stage = stage
        self.mode = mode
        # Formato: se detecta antes de tocar nada. Existencia: ya se anunció el progreso.
        self.control_untouched = stage == "format"
        payload = {
            "stage": stage,
            "mode": mode,
            "total": len(self.issues),
            "issues": self.issues[:_MAX_ISSUES_IN_PAYLOAD],
        }
        super().__init__(
            f"{BANK_CREDIT_COLUMN_ERROR_CODE}|{json.dumps(payload, ensure_ascii=False)}"
        )


def parse_credit_column_error_payload(message: str) -> dict[str, Any] | None:
    raw = str(message or "").strip()
    prefix = BANK_CREDIT_COLUMN_ERROR_CODE + "|"
    idx = raw.find(prefix)
    if idx < 0:
        return None
    try:
        parsed = json.loads(raw[idx + len(prefix) :])
    except (TypeError, ValueError):
        return None
    return parsed if isinstance(parsed, dict) else None


def _issue_line(issue: dict[str, Any]) -> str:
    fila = issue.get("fila")
    cliente = str(issue.get("cliente") or "").strip() or "sin cliente"
    motivo = issue.get("motivo")
    where = f"Fila {fila} ({cliente})" if fila else f"({cliente})"
    if motivo == CREDIT_ISSUE_NOT_FOUND:
        return (
            f"· {where}: el crédito {issue.get('credito')} no se encontró entre "
            "los créditos activos del cliente."
        )
    valor = str(issue.get("valor") or "").strip()
    if motivo == CREDIT_ISSUE_DECIMAL:
        return (
            f"· {where}: «{valor}» quedó como un número con decimales. "
            "Si son varios créditos, sepárelos con «y» (por ejemplo: 247 y 248)."
        )
    return f"· {where}: «{valor}» no es un número de crédito válido."


def credit_column_error_copy(payload: dict[str, Any] | None) -> tuple[str, str]:
    """(mensaje, qué hacer) para el operador; sin códigos técnicos."""
    data = payload or {}
    regenerate = str(data.get("mode") or "") == "regenerar"
    issues = [i for i in (data.get("issues") or []) if isinstance(i, dict)]
    total = data.get("total")
    total = total if isinstance(total, int) and total >= len(issues) else len(issues)
    head = (
        "No se pudo regenerar el archivo de revisión."
        if regenerate
        else "No se pudo iniciar la validación."
    )
    lines = [f"{head} Revise la columna No. Crédito del Excel de carga:"]
    lines.extend(_issue_line(i) for i in issues[:MAX_LISTED_ISSUES])
    hidden = total - min(len(issues), MAX_LISTED_ISSUES)
    if hidden > 0:
        lines.append(f"· … y {hidden} más.")
    button = "«Regenerar»" if regenerate else "«Iniciar validación»"
    action = (
        f"Corrija esas filas en el Excel de carga y vuelva a presionar {button}. "
        "Si no conoce el número, deje la celda vacía."
    )
    if regenerate and str(data.get("stage") or "") == "format":
        action += " El archivo de revisión actual no se modificó."
    return "\n".join(lines), action
