"""
Prevalidación de grupos Merge: créditos esperados vs documentos presentes.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from app.application.services.asiento_format_gate import FORMAT_GATE_CODES
from app.application.services.review_schema import TipoAplicacion, normalize_credito_digits

# Match exacto de tokens (evita que crédito "2" matchee "credito=264").
_RE_CREDIT_NUMBER_EXPECTED = re.compile(
    r"(?:^|[\s|])credit_number_expected=([^\s|]+)"
)
_RE_CREDITO_TOKEN = re.compile(r"(?:^|[\s|])credito=([^\s|]+)")
_RE_CREDITOS_SELECCIONADOS = re.compile(
    r"(?:^|[\s|])creditos_seleccionados=([^|]+)"
)
_RE_ASSIGNMENT_CODE = re.compile(
    r"ASIENTO_ASSIGNMENT_(?:AMBIGUOUS|NO_MATCH|PARSE_FAILED|COMPLEXITY_LIMIT)"
)
_RE_ASIENTO_PDF_FOUND = re.compile(r"(?:^|[\s|])asiento_pdf_found=([^\s|]+)")
_RE_FOUND_CREDIT = re.compile(r"(?:^|[\s|])found_credit=([^\s|]+)")
_RE_CREDITO_IN_FILENAME = re.compile(
    r"credito[\s_\-#]*(?P<digits>\d+)", flags=re.IGNORECASE
)

MERGE_GROUP_PENDING_INPUTS = "PENDING_INPUTS"
MERGE_GROUP_READY_TO_BUILD = "READY_TO_BUILD"
MERGE_GROUP_COMPLETE = "COMPLETE"
MERGE_GROUP_FAILED = "FAILED"

MANIFEST_STATUS_COMPLETE = "COMPLETE"
MANIFEST_STATUS_PARTIAL = "PARTIAL"


@dataclass
class ExpectedMergeCredit:
    credito: str
    has_asiento: bool = False
    has_extracto: bool = False


@dataclass
class ExpectedMergeGroup:
    id_pago: str
    tipo_aplicacion: str
    cliente: str
    monto_banco: float | None
    fecha_banco: str
    expected_creditos: tuple[str, ...]
    credit_items: list[dict[str, Any]] = field(default_factory=list)
    complete_creditos: tuple[str, ...] = ()
    missing_creditos: tuple[str, ...] = ()
    missing_inputs: list[dict[str, Any]] = field(default_factory=list)
    group_status: str = MERGE_GROUP_PENDING_INPUTS
    eligible_for_dry_run: bool = False


@dataclass(frozen=True)
class MergeGroupValidationResult:
    group: ExpectedMergeGroup
    is_complete: bool
    missing_creditos: tuple[str, ...]
    missing_inputs: list[dict[str, Any]]


def expected_creditos_for_id_pago(rows: list[dict[str, Any]]) -> tuple[str, ...]:
    """Créditos esperados desde filas históricas validadas (orden determinista)."""
    creditos: list[str] = []
    seen: set[str] = set()
    for row in sorted(
        rows,
        key=lambda x: (
            str(x.get("credito_digits") or ""),
            int(x.get("excel_row") or 0),
        ),
    ):
        c = str(row.get("credito_digits") or "").strip()
        if not c:
            c = normalize_credito_digits(str(row.get("credito_label") or "")) or ""
        if c and c not in seen:
            seen.add(c)
            creditos.append(c)
    return tuple(creditos)


def _credit_items_complete_creditos(credit_items: list[dict[str, Any]]) -> tuple[str, ...]:
    return tuple(
        sorted(
            {
                str(ci.get("credito") or "").strip()
                for ci in credit_items
                if str(ci.get("credito") or "").strip()
            },
            key=lambda x: (len(x), x),
        )
    )


def credit_items_cover_expected_creditos(
    group_rows: list[dict[str, Any]],
    credit_items: list[dict[str, Any]],
) -> bool:
    """True si credit_items cubre exactamente los créditos SI del grupo."""
    expected = expected_creditos_for_id_pago(group_rows)
    complete = _credit_items_complete_creditos(credit_items)
    return bool(expected) and set(expected) == set(complete)


def credit_items_have_asiento_each(credit_items: list[dict[str, Any]]) -> bool:
    """True si cada crédito resuelto tiene al menos un PDF de asiento (como ui-stable)."""
    if not credit_items:
        return False
    for item in credit_items:
        if len(item.get("asiento_pdf_paths") or []) < 1:
            return False
    return True


def credit_items_have_single_asiento_each(credit_items: list[dict[str, Any]]) -> bool:
    """True si cada crédito resuelto tiene exactamente un PDF de asiento."""
    if not credit_items:
        return False
    for item in credit_items:
        if len(item.get("asiento_pdf_paths") or []) != 1:
            return False
    return True


def credit_hint_from_pdf_filename(filename: str, expected_credito: str) -> str | None:
    """Dígitos de crédito sugeridos por el nombre del PDF (si difieren del esperado)."""
    expected = str(expected_credito or "").strip()
    stem = filename.rsplit(".", 1)[0] if "." in filename else filename
    m = _RE_CREDITO_IN_FILENAME.search(stem)
    if m:
        digits = m.group("digits").strip()
        if digits and digits != expected:
            return digits
    # Fallback: corridas de 2–6 dígitos aisladas distintas del esperado.
    for run in re.findall(r"(?<!\d)\d{2,6}(?!\d)", stem):
        if run != expected:
            return run
    return None


def _credits_from_seleccionados(line: str) -> set[str]:
    """Dígitos de crédito en creditos_seleccionados= (lote / skip pipe)."""
    match = _RE_CREDITOS_SELECCIONADOS.search(str(line or ""))
    if not match:
        return set()
    raw = match.group(1).strip()
    if not raw or raw == "-":
        return set()
    out: set[str] = set()
    for part in raw.split(","):
        digits = normalize_credito_digits(part)
        if digits:
            out.add(digits)
    return out


def _assignment_code_from_skip(line: str) -> str | None:
    match = _RE_ASSIGNMENT_CODE.search(str(line or ""))
    return match.group(0) if match else None


def _skip_line_targets_credit(line: str, credito: str) -> bool:
    """True si la línea de skip apunta exactamente a este crédito."""
    want = str(credito or "").strip()
    if not want:
        return False
    for match in _RE_CREDIT_NUMBER_EXPECTED.finditer(line):
        if match.group(1) == want:
            return True
    for match in _RE_CREDITO_TOKEN.finditer(line):
        # En líneas del job, credito= puede ser etiqueta ("CREDITO # 264");
        # solo aceptar match exacto de dígitos (formato readiness corto).
        if match.group(1) == want:
            return True
    if want in _credits_from_seleccionados(line):
        return True
    return False


def _enrich_mismatch_fields(line: str, base: dict[str, str]) -> dict[str, str]:
    """Añade found_pdf_name / found_credit_hint cuando el skip los trae."""
    out = dict(base)
    pdf_m = _RE_ASIENTO_PDF_FOUND.search(line)
    if pdf_m:
        found_name = pdf_m.group(1).strip()
        if found_name and found_name != "-":
            out["found_pdf_name"] = found_name
            if "found_credit_hint" not in out:
                hint = credit_hint_from_pdf_filename(found_name, out.get("credito", ""))
                if hint:
                    out["found_credit_hint"] = hint
    hint_m = _RE_FOUND_CREDIT.search(line)
    if hint_m:
        hint = hint_m.group(1).strip()
        if hint and hint != "-":
            out["found_credit_hint"] = hint
    return out


def _parse_skip_reason_for_credit(skip_line: str, credito: str) -> dict[str, str] | None:
    line = str(skip_line or "")
    want = str(credito or "").strip()
    if not _skip_line_targets_credit(line, want):
        return None
    if "extract_routes_missing" in line:
        return {
            "credito": want,
            "document_type": "EXTRACTO",
            "error_code": "extract_routes_missing",
        }
    if "asiento_contable_not_found" in line or "abono_accounting_pdf_missing" in line:
        return {
            "credito": want,
            "document_type": "ASIENTO_CONTABLE",
            "error_code": "asiento_contable_not_found",
        }
    if "asiento_contable_credit_mismatch" in line:
        return _enrich_mismatch_fields(
            line,
            {
                "credito": want,
                "document_type": "ASIENTO_CONTABLE",
                "error_code": "asiento_contable_credit_mismatch",
            },
        )
    for fmt_code in FORMAT_GATE_CODES:
        if fmt_code in line:
            return _enrich_mismatch_fields(
                line,
                {
                    "credito": want,
                    "document_type": "ASIENTO_CONTABLE",
                    "error_code": fmt_code,
                },
            )
    if "asiento_download_failed" in line:
        return _enrich_mismatch_fields(
            line,
            {
                "credito": want,
                "document_type": "ASIENTO_CONTABLE",
                "error_code": "asiento_download_failed",
            },
        )
    if "missing_ruta_asientos_contables" in line:
        return {
            "credito": want,
            "document_type": "ASIENTO_CONTABLE",
            "error_code": "missing_ruta_asientos_contables",
        }
    if "asientos_list_failed" in line:
        return {
            "credito": want,
            "document_type": "ASIENTO_CONTABLE",
            "error_code": "asientos_list_failed",
        }
    assignment = _assignment_code_from_skip(line)
    if assignment:
        return {
            "credito": want,
            "document_type": "ASIENTO_CONTABLE",
            "error_code": assignment,
        }
    return {
        "credito": want,
        "document_type": "ASIENTO_CONTABLE",
        "error_code": "document_missing",
    }


def build_missing_inputs(
    missing_creditos: list[str],
    pre_skips: list[str],
    *,
    tipo_aplicacion: str,
    requiere_extracto: bool = True,
) -> list[dict[str, Any]]:
    inputs: list[dict[str, Any]] = []
    for cred in missing_creditos:
        found: dict[str, str] | None = None
        for line in pre_skips:
            parsed = _parse_skip_reason_for_credit(line, cred)
            if parsed:
                found = parsed
                break
        if found is None:
            needs_extract = requiere_extracto and tipo_aplicacion in (
                TipoAplicacion.PAGO.value,
                TipoAplicacion.ABONO.value,
            )
            doc_type = "EXTRACTO" if needs_extract else "ASIENTO_CONTABLE"
            error_code = (
                "extract_routes_missing"
                if doc_type == "EXTRACTO"
                else "asiento_contable_not_found"
            )
            found = {
                "credito": cred,
                "document_type": doc_type,
                "error_code": error_code,
            }
        inputs.append(dict(found))
    return inputs


def validate_merge_group_completeness(
    *,
    id_pago: str,
    tipo_aplicacion: str,
    group_rows: list[dict[str, Any]],
    credit_items: list[dict[str, Any]],
    pre_skips: list[str],
) -> MergeGroupValidationResult:
    """Compara créditos esperados del histórico con credit_items resueltos."""
    ref = group_rows[0] if group_rows else {}
    cliente = str(ref.get("cliente") or "").strip()
    monto = ref.get("monto_banco")
    monto_val = float(monto) if isinstance(monto, (int, float)) else None
    fecha = ref.get("fecha_banco")
    fecha_str = fecha.isoformat() if hasattr(fecha, "isoformat") else str(fecha or "")

    expected = expected_creditos_for_id_pago(group_rows)
    complete = _credit_items_complete_creditos(credit_items)
    missing = tuple(sorted(set(expected) - set(complete)))
    group_requiere_extracto = any(
        bool(r.get("include_extract_in_composite", r.get("requiere_extracto")))
        for r in group_rows
    )
    missing_inputs = build_missing_inputs(
        list(missing),
        pre_skips,
        tipo_aplicacion=tipo_aplicacion,
        requiere_extracto=group_requiere_extracto,
    )

    is_complete = not missing and bool(expected) and set(expected) == set(complete)
    status = MERGE_GROUP_COMPLETE if is_complete else MERGE_GROUP_PENDING_INPUTS

    group = ExpectedMergeGroup(
        id_pago=id_pago,
        tipo_aplicacion=tipo_aplicacion,
        cliente=cliente,
        monto_banco=monto_val,
        fecha_banco=fecha_str,
        expected_creditos=expected,
        credit_items=list(credit_items),
        complete_creditos=complete,
        missing_creditos=missing,
        missing_inputs=missing_inputs,
        group_status=status,
        eligible_for_dry_run=is_complete,
    )
    return MergeGroupValidationResult(
        group=group,
        is_complete=is_complete,
        missing_creditos=missing,
        missing_inputs=missing_inputs,
    )


def incomplete_group_record(
    validation: MergeGroupValidationResult,
    *,
    pre_skips: list[str],
) -> dict[str, Any]:
    g = validation.group
    return {
        "id_pago": g.id_pago,
        "status": MERGE_GROUP_PENDING_INPUTS,
        "tipo_aplicacion": g.tipo_aplicacion,
        "cliente": g.cliente,
        "monto_banco": g.monto_banco,
        "fecha_banco": g.fecha_banco,
        "expected_creditos": list(g.expected_creditos),
        "complete_creditos": list(g.complete_creditos),
        "missing_creditos": list(g.missing_creditos),
        "missing_inputs": list(g.missing_inputs),
        "credit_items": [],
        "output_relative_path": None,
        "eligible_for_dry_run": False,
        "skip_lines": list(pre_skips),
    }


def complete_output_manifest_dict(
    output: Any,
    *,
    expected_creditos: tuple[str, ...],
) -> dict[str, Any]:
    """Serializa un output COMPLETE para el manifest."""
    o = output
    credit_items = [dict(ci) for ci in (o.credit_items or ())]
    return {
        "id_pago": o.id_pago,
        "status": MERGE_GROUP_COMPLETE,
        "cliente": o.cliente,
        "credito": o.credito,
        "tipo_aplicacion": o.tipo_aplicacion,
        "requiere_extracto": o.requiere_extracto,
        "monto_banco": o.monto_banco,
        "fecha_banco": o.fecha_banco,
        "expected_creditos": list(expected_creditos),
        "creditos_seleccionados": list(expected_creditos),
        "email_pdf_path": o.email_pdf_path,
        "asiento_pdf_path": o.asiento_pdf_path,
        "asiento_pdf_paths": list(o.asiento_pdf_paths),
        "extracto_pdf_path": o.extracto_pdf_path,
        "credit_items": credit_items,
        "missing_inputs": [],
        "eligible_for_dry_run": True,
        "output_relative_path": o.output_relative_path,
        "bytes_written": o.bytes_written,
        "sources_summary": o.sources_summary,
        "output_web_url": getattr(o, "output_web_url", "") or "",
        "output_folder_web_url": getattr(o, "output_folder_web_url", "") or "",
        "output_folder_relative_path": getattr(o, "output_folder_relative_path", "")
        or "",
    }


def output_creditos_match_expected(output: dict[str, Any]) -> bool:
    status = str(output.get("status") or MERGE_GROUP_COMPLETE).strip()
    if status not in ("", MERGE_GROUP_COMPLETE):
        return False

    expected = output.get("expected_creditos") or output.get("creditos_seleccionados") or []
    items = output.get("credit_items") or []
    if items:
        exp_set = {str(c).strip() for c in expected if str(c).strip()}
        item_set = {
            str(ci.get("credito") or "").strip()
            for ci in items
            if isinstance(ci, dict)
        }
        item_set.discard("")
        if exp_set:
            return exp_set == item_set
        return bool(item_set)

    has_paths = bool(
        output.get("asiento_pdf_paths")
        or output.get("asiento_pdf_path")
        or output.get("output_relative_path")
    )
    if not expected:
        return has_paths
    return False


def group_can_reuse_existing_pdf(
    *,
    id_pago: str,
    expected_creditos: tuple[str, ...],
    prev_manifest: dict[str, Any] | None,
) -> bool:
    """True solo si el manifest previo demuestra grupo COMPLETE con mismos créditos."""
    if not prev_manifest:
        return False
    for inc in prev_manifest.get("incomplete_groups") or []:
        if isinstance(inc, dict) and str(inc.get("id_pago") or "") == id_pago:
            return False
    for out in prev_manifest.get("outputs") or []:
        if not isinstance(out, dict) or str(out.get("id_pago") or "") != id_pago:
            continue
        status = str(out.get("status") or MERGE_GROUP_COMPLETE).strip()
        if status != MERGE_GROUP_COMPLETE:
            return False
        prev_expected = tuple(
            str(c).strip()
            for c in (out.get("expected_creditos") or out.get("creditos_seleccionados") or [])
            if str(c).strip()
        )
        if prev_expected and tuple(prev_expected) != expected_creditos:
            return False
        return output_creditos_match_expected(out)
    return False
