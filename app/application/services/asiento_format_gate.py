"""Criterio único de formato ERP para asientos (fase 3 y fase 4).

Reutiliza ``accounting_pdf_parser``: no hay un segundo parser.
``None`` = el PDF se puede usar para amortizar; un código = mismo
``error_code`` que dry-run/Apply.
"""
from __future__ import annotations

from typing import Any

from app.application.services.accounting_pdf_parser import (
    AccountingParseError,
    PdfTextNotExtractableError,
    parse_accounting_pdf_events,
)

PDF_TEXT_NOT_EXTRACTABLE = "PDF_TEXT_NOT_EXTRACTABLE"
ACCOUNTING_PARSE_FAILED = "ACCOUNTING_PARSE_FAILED"
MISSING_BANK_VALUE_BUT_HAS_ACCOUNTING_LINES = (
    "MISSING_BANK_VALUE_BUT_HAS_ACCOUNTING_LINES"
)

# Fallos de formato/ilegible: no consolidar ni amortizar ese PDF.
FORMAT_GATE_CODES = frozenset(
    {
        PDF_TEXT_NOT_EXTRACTABLE,
        ACCOUNTING_PARSE_FAILED,
        MISSING_BANK_VALUE_BUT_HAS_ACCOUNTING_LINES,
    }
)

# Familia UI de recuperación (reconsolidar): formato + cuadre ABONO.
RECOVERY_FAMILY_CODES = FORMAT_GATE_CODES | {"ABONO_ASIENTOS_NO_CUADRAN"}


def classify_asiento_pdf_bytes(
    pdf_bytes: bytes,
    *,
    credit: str = "",
    path: str = "",
) -> str | None:
    """Devuelve código amort si el PDF no es asiento ERP; ``None`` si parsea."""
    context: dict[str, Any] = {
        "id_pago": "",
        "cliente": "",
        "credito": str(credit or "").strip(),
        "asiento_pdf_path": str(path or "").strip(),
    }
    try:
        events = parse_accounting_pdf_events(pdf_bytes, context)
    except PdfTextNotExtractableError:
        return PDF_TEXT_NOT_EXTRACTABLE
    except AccountingParseError as exc:
        code = str(getattr(exc, "error_code", "") or "").strip().upper()
        if code in FORMAT_GATE_CODES:
            return code
        return ACCOUNTING_PARSE_FAILED
    except Exception:
        return ACCOUNTING_PARSE_FAILED
    if not events:
        return ACCOUNTING_PARSE_FAILED
    return None


def format_recovery_credits_from_attempt_json(raw: str | None) -> frozenset[str]:
    """Créditos con fallo de formato en el último intento de amortización."""
    from app.application.ui.amortization_attempt import parse_last_amortization_attempt_json

    attempt = parse_last_amortization_attempt_json(raw)
    if attempt is None:
        return frozenset()
    credits: set[str] = set()
    for issue in attempt.operational_issues:
        ref = str(issue.technical_reference or "").strip().upper()
        if ref not in RECOVERY_FAMILY_CODES:
            continue
        loc = issue.location
        cred = str(loc.credit if loc is not None else "").strip()
        if cred:
            credits.add(cred)
    return frozenset(credits)


__all__ = [
    "ACCOUNTING_PARSE_FAILED",
    "FORMAT_GATE_CODES",
    "MISSING_BANK_VALUE_BUT_HAS_ACCOUNTING_LINES",
    "PDF_TEXT_NOT_EXTRACTABLE",
    "RECOVERY_FAMILY_CODES",
    "classify_asiento_pdf_bytes",
    "format_recovery_credits_from_attempt_json",
]
