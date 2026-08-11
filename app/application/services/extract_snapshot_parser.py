"""
Parser estructurado de extractos de crédito → ExtractSnapshot.

Fail-closed: AMBIGUO nunca se convierte en saldo vencido = 0 silencioso.
APLICACION_ANTERIOR → saldo_vencido visible vacío.
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import asdict, dataclass, field
from datetime import date
from enum import Enum
from typing import Any

from app.application.services.payment_helpers import (
    extract_credit_id_from_extract_pdf_text,
    extract_fecha_limite_pago_from_pdf_text,
)


class RightPanelRole(str, Enum):
    SALDO_VENCIDO = "SALDO_VENCIDO"
    APLICACION_ANTERIOR = "APLICACION_ANTERIOR"
    VACIO = "VACIO"
    AMBIGUO = "AMBIGUO"


class ParserStatus(str, Enum):
    OK = "OK"
    PARTIAL = "PARTIAL"
    FAILED = "FAILED"
    AMBIGUOUS_RIGHT_PANEL = "AMBIGUOUS_RIGHT_PANEL"


@dataclass(frozen=True)
class ExtractEvidenceIdentity:
    """Identidad congelada del extracto seleccionado (no cambiar en retries)."""

    item_id: str | None = None
    drive_id: str | None = None
    site_id: str | None = None
    path: str | None = None
    etag: str | None = None
    ctag: str | None = None
    sha256: str | None = None
    fecha_limite: date | None = None
    web_url: str | None = None

    def to_meta_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {}
        for k, v in asdict(self).items():
            if v is None:
                continue
            out[k] = v.isoformat() if isinstance(v, date) else v
        return out


@dataclass
class ExtractSnapshot:
    credito: str | None = None
    fecha_limite: date | None = None
    valor_obligacion_actual: float | None = None
    saldo_vencido: float | None = None
    right_panel_role: RightPanelRole = RightPanelRole.VACIO
    right_panel_label: str | None = None
    selected_path: str | None = None
    item_id: str | None = None
    etag: str | None = None
    sha256: str | None = None
    parser_status: ParserStatus = ParserStatus.FAILED
    warnings: list[str] = field(default_factory=list)
    evidence: ExtractEvidenceIdentity | None = None

    @property
    def saldo_vencido_visible(self) -> float | None:
        """
        Valor para Excel: solo SALDO_VENCIDO muestra importe.
        APLICACION_ANTERIOR / VACIO / AMBIGUO → vacío (None).
        """
        if self.right_panel_role == RightPanelRole.SALDO_VENCIDO:
            return self.saldo_vencido
        return None

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["right_panel_role"] = self.right_panel_role.value
        d["parser_status"] = self.parser_status.value
        d["saldo_vencido_visible"] = self.saldo_vencido_visible
        if self.fecha_limite is not None:
            d["fecha_limite"] = self.fecha_limite.isoformat()
        if self.evidence is not None:
            d["evidence"] = self.evidence.to_meta_dict()
        return d


_MONEY_RE = re.compile(
    r"\$?\s*([\d]{1,3}(?:\.\d{3})*(?:,\d{1,2})?|\d+(?:,\d{1,2})?)"
)
_TOTAL_A_PAGAR_RE = re.compile(
    r"(?is)TOTAL\s+A\s+PAGAR\s*[:\-\s]*\$?\s*([\d\.\,]+)"
)
_APLICACION_ANTERIOR_LABELS = re.compile(
    r"(?is)(?:aplicaci[oó]n\s+anterior|pago\s+anterior|cuota\s+anterior|"
    r"detalle\s+del?\s+pago\s+anterior|valor\s+aplicado\s+anterior)"
)
_SALDO_VENCIDO_LABELS = re.compile(
    r"(?is)(?:saldo\s+vencido|mora\s+causada|intereses?\s+de\s+mora|"
    r"valor\s+en\s+mora|saldo\s+en\s+mora)"
)
_RIGHT_PANEL_HINT = re.compile(
    r"(?is)(?:saldo\s+vencido|aplicaci[oó]n\s+anterior|detalle\s+mora)"
)


def _parse_latin_money(raw: str) -> float | None:
    s = (raw or "").strip()
    if not s:
        return None
    if "," in s:
        s = s.replace(".", "").replace(",", ".")
    else:
        s = s.replace(".", "")
    try:
        return float(s)
    except ValueError:
        return None


def _sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _read_pdf_text(pdf_bytes: bytes) -> str:
    raw = pdf_bytes.decode(errors="ignore")
    if raw.startswith("PDF_MOCK:"):
        return raw[len("PDF_MOCK:") :]
    try:
        from pypdf import PdfReader
    except ImportError:
        from PyPDF2 import PdfReader  # type: ignore[no-redef]
    from io import BytesIO

    reader = PdfReader(BytesIO(pdf_bytes))
    parts: list[str] = []
    for page in reader.pages:
        t = page.extract_text() or ""
        if t:
            parts.append(t)
    text = "\n".join(parts)
    if not text.strip():
        raise ValueError("pdf_no_text")
    return text


def _classify_right_panel(text: str) -> tuple[RightPanelRole, str | None, float | None, list[str]]:
    """
    Clasifica el panel derecho del extracto.

    Reglas fail-closed:
    - Labels de aplicación anterior → APLICACION_ANTERIOR (importe no es deuda).
    - Labels de saldo/mora sin contradicción → SALDO_VENCIDO.
    - Ambos tipos de label → AMBIGUO.
    - Sin panel derecho reconocible → VACIO.
    """
    warnings: list[str] = []
    has_aplicacion = bool(_APLICACION_ANTERIOR_LABELS.search(text))
    has_saldo = bool(_SALDO_VENCIDO_LABELS.search(text))

    if has_aplicacion and has_saldo:
        warnings.append("right_panel_ambiguous_labels")
        return RightPanelRole.AMBIGUO, "AMBIGUO", None, warnings

    if has_aplicacion:
        # Capturar importe solo para auditoría interna; no exponer como saldo vencido.
        m = re.search(
            r"(?is)(?:aplicaci[oó]n\s+anterior|pago\s+anterior)[^\d$]{0,40}"
            r"\$?\s*([\d\.\,]+)",
            text,
        )
        amt = _parse_latin_money(m.group(1)) if m else None
        return RightPanelRole.APLICACION_ANTERIOR, "APLICACION_ANTERIOR", amt, warnings

    if has_saldo:
        m = re.search(
            r"(?is)(?:saldo\s+vencido|mora\s+causada|valor\s+en\s+mora)[^\d$]{0,40}"
            r"\$?\s*([\d\.\,]+)",
            text,
        )
        amt = _parse_latin_money(m.group(1)) if m else None
        if amt is None:
            warnings.append("saldo_vencido_label_without_amount")
            return RightPanelRole.AMBIGUO, "SALDO_VENCIDO_SIN_MONTO", None, warnings
        return RightPanelRole.SALDO_VENCIDO, "SALDO_VENCIDO", amt, warnings

    if _RIGHT_PANEL_HINT.search(text):
        warnings.append("right_panel_hint_without_clear_role")
        return RightPanelRole.AMBIGUO, "HINT_SIN_ROL", None, warnings

    return RightPanelRole.VACIO, None, None, warnings


def parse_extract_snapshot_from_text(
    text: str,
    *,
    evidence: ExtractEvidenceIdentity | None = None,
) -> ExtractSnapshot:
    warnings: list[str] = []
    if not (text or "").strip():
        return ExtractSnapshot(
            parser_status=ParserStatus.FAILED,
            warnings=["empty_text"],
            evidence=evidence,
            selected_path=evidence.path if evidence else None,
            item_id=evidence.item_id if evidence else None,
            etag=evidence.etag if evidence else None,
            sha256=evidence.sha256 if evidence else None,
        )

    credito = extract_credit_id_from_extract_pdf_text(text)
    fecha_limite = extract_fecha_limite_pago_from_pdf_text(text)

    valor_obligacion: float | None = None
    m_total = _TOTAL_A_PAGAR_RE.search(text)
    if m_total:
        valor_obligacion = _parse_latin_money(m_total.group(1))
    else:
        warnings.append("valor_obligacion_not_found")

    role, label, right_amt, role_warnings = _classify_right_panel(text)
    warnings.extend(role_warnings)

    saldo_vencido: float | None = None
    if role == RightPanelRole.SALDO_VENCIDO:
        saldo_vencido = right_amt
    elif role == RightPanelRole.APLICACION_ANTERIOR:
        # Importe histórico retenido solo en warnings/auditoría, no como deuda.
        if right_amt is not None:
            warnings.append(f"aplicacion_anterior_amount_ignored:{right_amt}")
        saldo_vencido = None
    elif role == RightPanelRole.AMBIGUO:
        saldo_vencido = None
        warnings.append("right_panel_ambiguous_not_zeroed")

    if role == RightPanelRole.AMBIGUO:
        status = ParserStatus.AMBIGUOUS_RIGHT_PANEL
    elif valor_obligacion is None or fecha_limite is None:
        status = ParserStatus.PARTIAL
    else:
        status = ParserStatus.OK

    return ExtractSnapshot(
        credito=credito,
        fecha_limite=fecha_limite or (evidence.fecha_limite if evidence else None),
        valor_obligacion_actual=valor_obligacion,
        saldo_vencido=saldo_vencido,
        right_panel_role=role,
        right_panel_label=label,
        selected_path=evidence.path if evidence else None,
        item_id=evidence.item_id if evidence else None,
        etag=evidence.etag if evidence else None,
        sha256=evidence.sha256 if evidence else None,
        parser_status=status,
        warnings=warnings,
        evidence=evidence,
    )


def parse_extract_snapshot(
    pdf_bytes: bytes,
    *,
    evidence: ExtractEvidenceIdentity | None = None,
) -> ExtractSnapshot:
    sha = _sha256_hex(pdf_bytes)
    base_evidence = evidence
    if base_evidence is None:
        base_evidence = ExtractEvidenceIdentity(sha256=sha)
    elif base_evidence.sha256 is None:
        base_evidence = ExtractEvidenceIdentity(
            item_id=base_evidence.item_id,
            drive_id=base_evidence.drive_id,
            site_id=base_evidence.site_id,
            path=base_evidence.path,
            etag=base_evidence.etag,
            ctag=base_evidence.ctag,
            sha256=sha,
            fecha_limite=base_evidence.fecha_limite,
            web_url=base_evidence.web_url,
        )

    try:
        text = _read_pdf_text(pdf_bytes)
    except ValueError as exc:
        return ExtractSnapshot(
            parser_status=ParserStatus.FAILED,
            warnings=[str(exc)],
            evidence=base_evidence,
            selected_path=base_evidence.path,
            item_id=base_evidence.item_id,
            etag=base_evidence.etag,
            sha256=base_evidence.sha256,
        )

    return parse_extract_snapshot_from_text(text, evidence=base_evidence)


def evidence_from_graph_item(
    item: dict[str, Any],
    *,
    path: str | None = None,
    site_id: str | None = None,
    drive_id: str | None = None,
    fecha_limite: date | None = None,
    sha256: str | None = None,
) -> ExtractEvidenceIdentity:
    return ExtractEvidenceIdentity(
        item_id=str(item.get("id") or "") or None,
        drive_id=drive_id or str(item.get("parentReference", {}).get("driveId") or "") or None,
        site_id=site_id,
        path=path or str(item.get("path") or item.get("name") or "") or None,
        etag=str(item.get("eTag") or item.get("etag") or "") or None,
        ctag=str(item.get("cTag") or item.get("ctag") or "") or None,
        sha256=sha256,
        fecha_limite=fecha_limite,
        web_url=str(item.get("webUrl") or item.get("web_url") or "") or None,
    )
