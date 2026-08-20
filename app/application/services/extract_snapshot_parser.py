"""
Parser espacial de extractos de crédito → ExtractSnapshot.

Orden obligatorio: 1) separar paneles LEFT/RIGHT por coordenadas;
2) clasificar semántica del panel derecho.
«Intereses de mora» en panel izquierdo NUNCA implica saldo vencido.

Fail-closed: AMBIGUO nunca se convierte en saldo vencido = 0 silencioso.
APLICACION_ANTERIOR → saldo_vencido visible vacío.
Fallback lineal solo si no hay coords; status explícito + conservador.
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import asdict, dataclass, field, replace
from datetime import date
from enum import Enum
from io import BytesIO
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
    LINEAR_FALLBACK = "LINEAR_FALLBACK"


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
    created_datetime: str | None = None

    def to_meta_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {}
        for k, v in asdict(self).items():
            if v is None:
                continue
            out[k] = v.isoformat() if isinstance(v, date) else v
        return out


@dataclass(frozen=True)
class TextSpan:
    """Fragmento de texto con bounding box (coords PDF)."""

    text: str
    x0: float
    x1: float
    y0: float
    y1: float

    @property
    def x_mid(self) -> float:
        return (self.x0 + self.x1) / 2.0


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
    layout_mode: str = "unknown"  # spatial | linear_fallback | mock_panels

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

# Panel derecho: familias de mora / saldo vencido (NO incluye «Intereses de mora»).
_SALDO_VENCIDO_LABELS = re.compile(
    r"(?is)(?:"
    r"saldo\s+vencido|"
    r"saldo\s+en\s+mora|"
    r"saldo\s+mora|"
    r"total\s+en\s+mora|"
    r"cuotas?\s+en\s+mora|"
    r"cuota\s+mora|"
    r"mora\s+causada|"
    r"valor\s+en\s+mora"
    r")"
)

# Panel derecho: aplicación / pago anterior (importe histórico, no deuda).
_APLICACION_ANTERIOR_LABELS = re.compile(
    r"(?is)(?:"
    r"aplicaci[oó]n\s+anterior|"
    r"pago\s+anterior|"
    r"cuota\s+anterior|"
    r"detalle\s+del?\s+pago\s+anterior|"
    r"valor\s+aplicado\s+anterior|"
    r"aplicaci[oó]n\s+(?:de\s+)?pago\s+cuota|"
    r"aplicaci[oó]n\s+abono\s+capital|"
    r"abono\s+capital\s+e\s+intereses|"
    r"total\s+pagado|"
    r"total\s+aplicado|"
    r"pago\s+total|"
    r"valor\s+pagado"
    r")"
)

# Solo en panel IZQUIERDO: no usarlo para clasificar rol derecho.
_LEFT_MORA_INTEREST_LABEL = re.compile(r"(?is)intereses?\s+de\s+mora")

_RIGHT_PANEL_HINT = re.compile(
    r"(?is)(?:saldo\s+vencido|aplicaci[oó]n\s+anterior|detalle\s+mora|saldo\s+mora)"
)

# Mock espacial: PDF_MOCK_SPATIAL:\nL|text\nR|text  o  SPAN|x0|x1|y0|y1|text
_MOCK_SPATIAL_PREFIX = "PDF_MOCK_SPATIAL:"
_MOCK_TEXT_PREFIX = "PDF_MOCK:"


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


_NIT_OR_ACCOUNT_NOISE = re.compile(
    r"(?is)(?:\bnit\b|\bcuenta\b|040000\d+|830[,.]?\d{3}|901[,.]?\d{3})"
)
_COLOMBIAN_THOUSANDS_MONEY = re.compile(r"\d{1,3}(?:\.\d{3})+")


def _money_match_is_noise(raw_match: str, context: str) -> bool:
    """Descarta fragmentos de NIT, cuentas bancarias o enteros largos sin miles."""
    token = str(raw_match or "").strip()
    if not token:
        return True
    if _NIT_OR_ACCOUNT_NOISE.search(context):
        # Cuenta tipo 04000012256: muchos dígitos seguidos sin separador de miles.
        digits_only = re.sub(r"\D", "", token)
        if len(digits_only) >= 8 and not _COLOMBIAN_THOUSANDS_MONEY.fullmatch(token):
            return True
        # NIT 901,600 → 901.6 si el contexto es Nit.
        if len(digits_only) <= 4 and "nit" in context.lower():
            return True
    return False


def _plausible_saldo_amount(raw_match: str, context: str, amount: float | None) -> bool:
    if amount is None:
        return False
    if _money_match_is_noise(raw_match, context):
        return False
    token = str(raw_match or "").strip()
    if _COLOMBIAN_THOUSANDS_MONEY.search(token):
        return amount >= 1_000
    # Montos pequeños solo si no parecen cuenta/NIT.
    return amount >= 1_000


def _money_candidates(text: str) -> list[tuple[float, str, int]]:
    out: list[tuple[float, str, int]] = []
    for m in _MONEY_RE.finditer(text or ""):
        raw = m.group(1)
        amt = _parse_latin_money(raw)
        if amt is not None:
            out.append((amt, raw, m.start()))
    return out


def _extract_saldo_vencido_amount(text: str, label_re: re.Pattern[str]) -> float | None:
    """
    Saldo mora: preferir importe con miles (48.796.722) y evitar NIT/cuenta bancaria.
    Algunos layouts ponen el monto antes de «SALDO MORA» (columna mora); otros, después.
    """
    m = label_re.search(text)
    if not m:
        return None
    before = text[max(0, m.start() - 90) : m.start()]
    after = text[m.end() : m.end() + 90]

    after_cands = _money_candidates(after)
    for amt, raw, _pos in after_cands:
        ctx = after[max(0, after.find(raw) - 15) : after.find(raw) + len(raw) + 15]
        if _plausible_saldo_amount(raw, ctx, amt):
            return amt

    before_cands = _money_candidates(before)
    for amt, raw, _pos in reversed(before_cands):
        ctx = before[max(0, before.rfind(raw) - 15) : before.rfind(raw) + len(raw) + 15]
        if _plausible_saldo_amount(raw, ctx, amt):
            return amt

    return None


def _extract_amount_near_label(text: str, label_re: re.Pattern[str]) -> float | None:
    m = label_re.search(text)
    if not m:
        return None
    if label_re is _SALDO_VENCIDO_LABELS:
        saldo = _extract_saldo_vencido_amount(text, label_re)
        if saldo is not None:
            return saldo
    tail = text[m.end() : m.end() + 80]
    m_amt = _MONEY_RE.search(tail)
    if not m_amt:
        # Importe puede estar en la misma línea antes/después en layouts densos.
        window = text[max(0, m.start() - 40) : m.end() + 80]
        m_amt = _MONEY_RE.search(window)
    if not m_amt:
        return None
    return _parse_latin_money(m_amt.group(1))


def _classify_right_panel_text(
    right_text: str,
) -> tuple[RightPanelRole, str | None, float | None, list[str]]:
    """Clasifica ÚNICAMENTE texto del panel derecho."""
    warnings: list[str] = []
    text = right_text or ""
    if not text.strip():
        return RightPanelRole.VACIO, None, None, warnings

    has_aplicacion = bool(_APLICACION_ANTERIOR_LABELS.search(text))
    has_saldo = bool(_SALDO_VENCIDO_LABELS.search(text))

    if has_aplicacion and has_saldo:
        warnings.append("right_panel_ambiguous_labels")
        return RightPanelRole.AMBIGUO, "AMBIGUO", None, warnings

    if has_aplicacion:
        amt = _extract_amount_near_label(text, _APLICACION_ANTERIOR_LABELS)
        return RightPanelRole.APLICACION_ANTERIOR, "APLICACION_ANTERIOR", amt, warnings

    if has_saldo:
        amt = _extract_amount_near_label(text, _SALDO_VENCIDO_LABELS)
        if amt is None:
            warnings.append("saldo_vencido_label_without_amount")
            return RightPanelRole.AMBIGUO, "SALDO_VENCIDO_SIN_MONTO", None, warnings
        label_m = _SALDO_VENCIDO_LABELS.search(text)
        label = label_m.group(0).upper().replace("  ", " ") if label_m else "SALDO_VENCIDO"
        return RightPanelRole.SALDO_VENCIDO, label, amt, warnings

    if _RIGHT_PANEL_HINT.search(text):
        warnings.append("right_panel_hint_without_clear_role")
        return RightPanelRole.AMBIGUO, "HINT_SIN_ROL", None, warnings

    return RightPanelRole.VACIO, None, None, warnings


def _classify_linear_conservative(
    full_text: str,
) -> tuple[RightPanelRole, str | None, float | None, list[str]]:
    """
    Fallback sin coordenadas: conservador.
    «Intereses de mora» solo NO implica SALDO_VENCIDO.
    """
    warnings = ["linear_fallback_no_coordinates"]
    text = full_text or ""
    has_aplicacion = bool(_APLICACION_ANTERIOR_LABELS.search(text))
    # Exigir familia explícita de mora/saldo (no intereses de mora izquierdos).
    has_saldo = bool(_SALDO_VENCIDO_LABELS.search(text))

    if has_aplicacion and has_saldo:
        warnings.append("right_panel_ambiguous_labels")
        return RightPanelRole.AMBIGUO, "AMBIGUO", None, warnings
    if has_aplicacion:
        amt = _extract_amount_near_label(text, _APLICACION_ANTERIOR_LABELS)
        return RightPanelRole.APLICACION_ANTERIOR, "APLICACION_ANTERIOR", amt, warnings
    if has_saldo:
        amt = _extract_amount_near_label(text, _SALDO_VENCIDO_LABELS)
        if amt is None:
            warnings.append("saldo_vencido_label_without_amount")
            return RightPanelRole.AMBIGUO, "SALDO_VENCIDO_SIN_MONTO", None, warnings
        return RightPanelRole.SALDO_VENCIDO, "SALDO_VENCIDO", amt, warnings

    if _LEFT_MORA_INTEREST_LABEL.search(text) and not has_saldo:
        warnings.append("left_intereses_de_mora_ignored_without_right_saldo")
        return RightPanelRole.VACIO, None, None, warnings

    return RightPanelRole.VACIO, None, None, warnings


def extract_text_spans_from_pdf(pdf_bytes: bytes) -> tuple[list[TextSpan], float, str]:
    """
    Extrae spans con coords vía visitor_text de pypdf.
    Retorna (spans, page_width_max, full_text).
    """
    try:
        from pypdf import PdfReader
    except ImportError:
        from PyPDF2 import PdfReader  # type: ignore[no-redef]

    reader = PdfReader(BytesIO(pdf_bytes))
    spans: list[TextSpan] = []
    texts: list[str] = []
    page_width = 0.0

    for page in reader.pages:
        mediabox = getattr(page, "mediabox", None)
        if mediabox is not None:
            try:
                page_width = max(page_width, float(mediabox.width))
            except Exception:
                pass

        def visitor_text(
            text: str,
            _cm: Any,
            tm: Any,
            _font_dict: Any,
            font_size: Any,
        ) -> None:
            if not text or not str(text).strip():
                return
            try:
                x = float(tm[4])
                y = float(tm[5])
            except (TypeError, IndexError, ValueError):
                return
            try:
                size = float(font_size) if font_size is not None else 10.0
            except (TypeError, ValueError):
                size = 10.0
            w = max(size * max(len(str(text)) * 0.45, 1.0), 1.0)
            spans.append(
                TextSpan(
                    text=str(text),
                    x0=x,
                    x1=x + w,
                    y0=y,
                    y1=y + size,
                )
            )

        try:
            page_text = page.extract_text(visitor_text=visitor_text) or ""
        except TypeError:
            # pypdf antiguo sin visitor
            page_text = page.extract_text() or ""
        if page_text:
            texts.append(page_text)

    full_text = "\n".join(texts)
    if page_width <= 0 and spans:
        page_width = max(s.x1 for s in spans)
    return spans, page_width, full_text


def split_panels_by_spans(
    spans: list[TextSpan],
    page_width: float,
) -> tuple[str, str, float]:
    """Parte texto en LEFT/RIGHT por umbral x (mitad de página o mediana)."""
    if not spans:
        return "", "", 0.0
    width = page_width if page_width > 0 else max(s.x1 for s in spans)
    # Umbral: 55% del ancho (panel derecho suele ser columna estrecha a la derecha).
    threshold = width * 0.55
    left_parts: list[str] = []
    right_parts: list[str] = []
    # Ordenar por Y descendente (PDF y crece hacia arriba), luego X.
    ordered = sorted(spans, key=lambda s: (-round(s.y0, 1), s.x0))
    for sp in ordered:
        if sp.x_mid >= threshold:
            right_parts.append(sp.text)
        else:
            left_parts.append(sp.text)
    left = " ".join(left_parts)
    right = " ".join(right_parts)
    return left, right, threshold


def _supplement_snapshot_from_linear_text(
    snap: ExtractSnapshot,
    full_text: str,
) -> ExtractSnapshot:
    """Completa fecha/total desde texto lineal cuando el corte espacial los pierde."""
    if not full_text.strip():
        return snap

    fecha = snap.fecha_limite
    valor = snap.valor_obligacion_actual
    warnings = list(snap.warnings)
    changed = False

    if fecha is None:
        fecha = extract_fecha_limite_pago_from_pdf_text(full_text)
        if fecha is not None:
            warnings.append("fecha_limite_from_linear_full_text")
            changed = True

    if valor is None:
        m_total = _TOTAL_A_PAGAR_RE.search(full_text)
        if m_total:
            parsed = _parse_latin_money(m_total.group(1))
            if parsed is not None:
                valor = parsed
                if "valor_obligacion_not_found" in warnings:
                    warnings.remove("valor_obligacion_not_found")
                warnings.append("valor_obligacion_from_linear_full_text")
                changed = True

    if not changed:
        return snap

    status = snap.parser_status
    if snap.right_panel_role != RightPanelRole.AMBIGUO:
        if valor is not None and fecha is not None:
            status = ParserStatus.OK
        elif valor is None or fecha is None:
            status = ParserStatus.PARTIAL

    return replace(
        snap,
        fecha_limite=fecha,
        valor_obligacion_actual=valor,
        parser_status=status,
        warnings=warnings,
    )


def parse_extract_snapshot_from_panels(
    left_text: str,
    right_text: str,
    *,
    evidence: ExtractEvidenceIdentity | None = None,
    layout_mode: str = "spatial",
) -> ExtractSnapshot:
    """API de prueba/producto: clasifica con paneles ya separados."""
    warnings: list[str] = []
    full = f"{left_text}\n{right_text}".strip()
    if not full:
        return ExtractSnapshot(
            parser_status=ParserStatus.FAILED,
            warnings=["empty_text"],
            evidence=evidence,
            selected_path=evidence.path if evidence else None,
            item_id=evidence.item_id if evidence else None,
            etag=evidence.etag if evidence else None,
            sha256=evidence.sha256 if evidence else None,
            layout_mode=layout_mode,
        )

    credito = extract_credit_id_from_extract_pdf_text(full)
    fecha_limite = extract_fecha_limite_pago_from_pdf_text(full)

    valor_obligacion: float | None = None
    m_total = _TOTAL_A_PAGAR_RE.search(left_text) or _TOTAL_A_PAGAR_RE.search(full)
    if m_total:
        valor_obligacion = _parse_latin_money(m_total.group(1))
    else:
        warnings.append("valor_obligacion_not_found")

    if _LEFT_MORA_INTEREST_LABEL.search(left_text) and not _SALDO_VENCIDO_LABELS.search(
        right_text
    ):
        warnings.append("left_intereses_de_mora_ignored")

    role, label, right_amt, role_warnings = _classify_right_panel_text(right_text)
    warnings.extend(role_warnings)

    saldo_vencido: float | None = None
    if role == RightPanelRole.SALDO_VENCIDO:
        saldo_vencido = right_amt
    elif role == RightPanelRole.APLICACION_ANTERIOR:
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
        layout_mode=layout_mode,
    )


def parse_extract_snapshot_from_text(
    text: str,
    *,
    evidence: ExtractEvidenceIdentity | None = None,
) -> ExtractSnapshot:
    """
    Entrada texto plano (fixtures / fallback).
    Si el texto trae marcadores L:/R: usa paneles; si no, fallback lineal conservador.
    """
    raw = text or ""
    if "---RIGHT---" in raw or "\nR|" in raw or raw.startswith("L|"):
        left, right = _split_marked_panels(raw)
        return parse_extract_snapshot_from_panels(
            left, right, evidence=evidence, layout_mode="mock_panels"
        )

    warnings: list[str] = []
    if not raw.strip():
        return ExtractSnapshot(
            parser_status=ParserStatus.FAILED,
            warnings=["empty_text"],
            evidence=evidence,
            layout_mode="linear_fallback",
        )

    credito = extract_credit_id_from_extract_pdf_text(raw)
    fecha_limite = extract_fecha_limite_pago_from_pdf_text(raw)
    valor_obligacion: float | None = None
    m_total = _TOTAL_A_PAGAR_RE.search(raw)
    if m_total:
        valor_obligacion = _parse_latin_money(m_total.group(1))
    else:
        warnings.append("valor_obligacion_not_found")

    role, label, right_amt, role_warnings = _classify_linear_conservative(raw)
    warnings.extend(role_warnings)

    saldo_vencido: float | None = None
    if role == RightPanelRole.SALDO_VENCIDO:
        saldo_vencido = right_amt
    elif role == RightPanelRole.APLICACION_ANTERIOR and right_amt is not None:
        warnings.append(f"aplicacion_anterior_amount_ignored:{right_amt}")
    elif role == RightPanelRole.AMBIGUO:
        warnings.append("right_panel_ambiguous_not_zeroed")

    if role == RightPanelRole.AMBIGUO:
        status = ParserStatus.AMBIGUOUS_RIGHT_PANEL
    else:
        status = ParserStatus.LINEAR_FALLBACK
        if valor_obligacion is None or fecha_limite is None:
            status = ParserStatus.PARTIAL

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
        layout_mode="linear_fallback",
    )


def _split_marked_panels(raw: str) -> tuple[str, str]:
    if "---RIGHT---" in raw:
        left, right = raw.split("---RIGHT---", 1)
        left = left.replace("---LEFT---", "").strip()
        return left, right.strip()
    left_lines: list[str] = []
    right_lines: list[str] = []
    for line in raw.splitlines():
        if line.startswith("L|"):
            left_lines.append(line[2:])
        elif line.startswith("R|"):
            right_lines.append(line[2:])
        else:
            left_lines.append(line)
    return "\n".join(left_lines), "\n".join(right_lines)


def _parse_mock_spatial_payload(payload: str) -> ExtractSnapshot | None:
    """PDF_MOCK_SPATIAL con L|/R| o SPAN|x0|x1|y0|y1|text."""
    lines = [ln for ln in payload.splitlines() if ln.strip()]
    if not lines:
        return None
    if any(ln.startswith("SPAN|") for ln in lines):
        spans: list[TextSpan] = []
        for ln in lines:
            if not ln.startswith("SPAN|"):
                continue
            parts = ln.split("|", 5)
            if len(parts) < 6:
                continue
            try:
                x0, x1, y0, y1 = map(float, parts[1:5])
            except ValueError:
                continue
            spans.append(TextSpan(text=parts[5], x0=x0, x1=x1, y0=y0, y1=y1))
        left, right, _ = split_panels_by_spans(spans, page_width=max((s.x1 for s in spans), default=100.0))
        return parse_extract_snapshot_from_panels(left, right, layout_mode="spatial")
    left, right = _split_marked_panels(payload)
    return parse_extract_snapshot_from_panels(left, right, layout_mode="mock_panels")


def _read_pdf_bytes_payload(pdf_bytes: bytes) -> tuple[str | None, bytes | None]:
    """Detecta mocks de texto; si no, retorna bytes PDF reales."""
    raw = pdf_bytes.decode(errors="ignore")
    if raw.startswith(_MOCK_SPATIAL_PREFIX):
        return raw[len(_MOCK_SPATIAL_PREFIX) :], None
    if raw.startswith(_MOCK_TEXT_PREFIX):
        return raw[len(_MOCK_TEXT_PREFIX) :], None
    return None, pdf_bytes


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
        base_evidence = replace(base_evidence, sha256=sha)

    mock_payload, real_bytes = _read_pdf_bytes_payload(pdf_bytes)
    if mock_payload is not None:
        if pdf_bytes.decode(errors="ignore").startswith(_MOCK_SPATIAL_PREFIX):
            snap = _parse_mock_spatial_payload(mock_payload)
            if snap is None:
                return ExtractSnapshot(
                    parser_status=ParserStatus.FAILED,
                    warnings=["empty_mock_spatial"],
                    evidence=base_evidence,
                    layout_mode="mock_panels",
                )
            snap.evidence = base_evidence
            snap.selected_path = base_evidence.path
            snap.item_id = base_evidence.item_id
            snap.etag = base_evidence.etag
            snap.sha256 = base_evidence.sha256
            return snap
        return parse_extract_snapshot_from_text(mock_payload, evidence=base_evidence)

    assert real_bytes is not None
    try:
        spans, page_width, full_text = extract_text_spans_from_pdf(real_bytes)
    except Exception as exc:  # noqa: BLE001 — fail-closed a fallback
        return ExtractSnapshot(
            parser_status=ParserStatus.FAILED,
            warnings=[f"pdf_extract_failed:{exc}"],
            evidence=base_evidence,
            selected_path=base_evidence.path,
            item_id=base_evidence.item_id,
            etag=base_evidence.etag,
            sha256=base_evidence.sha256,
            layout_mode="unknown",
        )

    if not full_text.strip() and not spans:
        return ExtractSnapshot(
            parser_status=ParserStatus.FAILED,
            warnings=["pdf_no_text"],
            evidence=base_evidence,
            selected_path=base_evidence.path,
            item_id=base_evidence.item_id,
            etag=base_evidence.etag,
            sha256=base_evidence.sha256,
            layout_mode="unknown",
        )

    # Coordenadas útiles: al menos 2 spans con x distintos.
    xs = {round(s.x_mid, 0) for s in spans}
    if len(spans) >= 2 and len(xs) >= 2 and page_width > 0:
        left, right, _thr = split_panels_by_spans(spans, page_width)
        # Si el «panel derecho» quedó vacío pero el texto completo tiene labels
        # de mora solo en la mitad derecha de líneas — ya separado.
        snap = parse_extract_snapshot_from_panels(
            left, right, evidence=base_evidence, layout_mode="spatial"
        )
        return _supplement_snapshot_from_linear_text(snap, full_text)

    # Sin coords utilizables → fallback lineal explícito.
    snap = parse_extract_snapshot_from_text(full_text, evidence=base_evidence)
    if "linear_fallback_no_coordinates" not in snap.warnings:
        snap.warnings.append("linear_fallback_no_coordinates")
    if snap.parser_status == ParserStatus.OK:
        snap.parser_status = ParserStatus.LINEAR_FALLBACK
    snap.layout_mode = "linear_fallback"
    return snap


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
        created_datetime=str(
            item.get("createdDateTime")
            or item.get("created_datetime")
            or (
                (item.get("fileSystemInfo") or {}).get("createdDateTime")
                if isinstance(item.get("fileSystemInfo"), dict)
                else ""
            )
            or ""
        )
        or None,
    )


# Cabeceras canónicas de evidencia en _Meta (pipe-separated).
EVIDENCE_META_FIELDS: tuple[str, ...] = (
    "row",
    "item_id",
    "drive_id",
    "site_id",
    "path",
    "etag",
    "ctag",
    "sha256",
    "fecha_limite",
    "web_url",
    "right_panel_role",
    "parser_status",
    "created_datetime",
)

EVIDENCE_HEADERS_LABEL = "EvidenceHeaders"
EVIDENCE_ROW_PREFIX = "EvidenceRow"


def serialize_evidence_meta_value(
    *,
    row_idx: int,
    evidence: dict[str, Any] | ExtractEvidenceIdentity | None,
    right_panel_role: str = "",
    parser_status: str = "",
) -> str:
    """Serializa identidad congelada para una fila de _Meta."""
    ev: dict[str, Any]
    if evidence is None:
        ev = {}
    elif isinstance(evidence, ExtractEvidenceIdentity):
        ev = evidence.to_meta_dict()
    else:
        ev = dict(evidence)
    values = {
        "row": str(row_idx),
        "item_id": str(ev.get("item_id") or ""),
        "drive_id": str(ev.get("drive_id") or ""),
        "site_id": str(ev.get("site_id") or ""),
        "path": str(ev.get("path") or ""),
        "etag": str(ev.get("etag") or ""),
        "ctag": str(ev.get("ctag") or ""),
        "sha256": str(ev.get("sha256") or ""),
        "fecha_limite": str(ev.get("fecha_limite") or ""),
        "web_url": str(ev.get("web_url") or ev.get("webUrl") or ""),
        "right_panel_role": str(right_panel_role or ""),
        "parser_status": str(parser_status or ""),
        "created_datetime": str(
            ev.get("created_datetime") or ev.get("createdDateTime") or ""
        ),
    }
    return "|".join(values[k] for k in EVIDENCE_META_FIELDS)


def parse_evidence_meta_value(raw: str) -> dict[str, str]:
    """Parsea valor EvidenceRow* (soporta formato corto legacy y completo)."""
    parts = str(raw or "").split("|")
    # Formato legacy: row|item_id|path|etag|sha256|fecha_limite|role|status (8)
    if len(parts) == 8:
        keys = (
            "row",
            "item_id",
            "path",
            "etag",
            "sha256",
            "fecha_limite",
            "right_panel_role",
            "parser_status",
        )
        out = {k: "" for k in EVIDENCE_META_FIELDS}
        for k, v in zip(keys, parts, strict=True):
            out[k] = v
        return out
    out = {k: "" for k in EVIDENCE_META_FIELDS}
    for idx, key in enumerate(EVIDENCE_META_FIELDS):
        if idx < len(parts):
            out[key] = parts[idx]
    return out


def parse_frozen_evidence_from_meta_sheet(ws_meta: Any) -> list[dict[str, str]]:
    """Lee filas EvidenceRow* desde hoja _Meta."""
    rows: list[dict[str, str]] = []
    if ws_meta is None:
        return rows
    for row in ws_meta.iter_rows(min_row=1, max_row=ws_meta.max_row or 1, values_only=True):
        if not row or len(row) < 2:
            continue
        campo = str(row[0] or "").strip()
        if not campo.startswith(EVIDENCE_ROW_PREFIX):
            continue
        parsed = parse_evidence_meta_value(str(row[1] or ""))
        if parsed.get("path") or parsed.get("item_id") or parsed.get("sha256"):
            rows.append(parsed)
    return rows


def prefer_frozen_extract_candidate(
    pool: list[dict[str, Any]],
    frozen: dict[str, Any] | None,
) -> dict[str, Any] | None:
    """
    Si hay evidencia congelada, reutiliza el candidato del pool que coincida
    por item_id, path o sha256. No cambia silenciosamente a un extracto nuevo.
    """
    if not frozen or not pool:
        return None
    item_id = str(frozen.get("item_id") or "").strip()
    path = str(frozen.get("path") or "").replace("\\", "/").strip().casefold()
    sha = str(frozen.get("sha256") or "").strip().casefold()

    if item_id:
        for cand in pool:
            if str(cand.get("id") or cand.get("item_id") or "").strip() == item_id:
                return cand
    if path:
        for cand in pool:
            cand_path = str(cand.get("relative_path") or cand.get("path") or "").replace("\\", "/")
            if cand_path.strip().casefold() == path:
                return cand
    if sha:
        for cand in pool:
            cand_sha = str(cand.get("sha256") or cand.get("hash") or "").strip().casefold()
            if cand_sha and cand_sha == sha:
                return cand
    return None
