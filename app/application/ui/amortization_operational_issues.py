"""Proyección de problemas operativos para amortización requires_correction.

Convierte rechazos de prepare/dry-run (abono, merge, preflight, ítems) en
``UiOperationalIssue`` serializables para job.result y result_summary HTTP.
"""
from __future__ import annotations

import re
from typing import Any

from app.application.job_status_enrichment import finalize_message_for_code
from app.application.ui.schemas import UiIssueLocation, UiLink, UiOperationalIssue

_STAGE = "amortization"
_CATEGORY = "correction_required"
_SNAKE_CODE = re.compile(r"^[a-z][a-z0-9_]*$", re.IGNORECASE)
# Fragmentos que no deben llegar al mensaje del operador.
_TECH_LEAK = re.compile(
    r"parser_mode|detected_codes|c[oó]digos\s+detectados|ReportLab|regex|"
    r"BANK_[A-Z0-9_]+|ACCOUNTING_PARSE|PDF_TEXT_NOT|MISSING_BANK|"
    r"amounts_before_code|text_preview|Traceback|Exception\b|"
    r"split_code_|token.?per.?line|OCR\b",
    re.IGNORECASE,
)

# Familia formato/parse de asiento: corregir en SharePoint → reconsolidar → amortizar.
_FORMAT_FAMILY_CODES = frozenset(
    {
        "ACCOUNTING_PARSE_FAILED",
        "PDF_TEXT_NOT_EXTRACTABLE",
        "MISSING_BANK_VALUE_BUT_HAS_ACCOUNTING_LINES",
    }
)

# Errores de tabla Excel: enlazar tabla, no carpeta ASIENTOS.
_TABLE_LINK_CODES = frozenset(
    {
        "TABLE_PATH_NOT_FOUND",
        "TABLE_DOWNLOAD_FAILED",
        "AMORTIZATION_SHEET_NOT_FOUND",
        "FECHA_LIMITE_NOT_FOUND",
        "DUE_DATE_ROW_NOT_FOUND",
        "REQUIRES_APPLICATION_ROW",
        "APPLICATION_ROW_NOT_FOUND",
        "ABONO_TABLA_AMORTIZACION_MISSING",
    }
)

# (user_message, next_action) — español operativo, sin códigos ni jerga.
_AMORTIZATION_ITEM_MESSAGES: dict[str, tuple[str, str]] = {
    "ASIENTO_PATH_MISSING": (
        "Falta la ruta del PDF del asiento contable para este movimiento.",
        "Suba el PDF en la carpeta ASIENTOS del crédito, reconsolide (fase 3) "
        "y luego procese la amortización.",
    ),
    "TABLE_PATH_NOT_FOUND": (
        "No se encontró la tabla de amortización del crédito en SharePoint.",
        "Verifique que el Excel de amortización exista en la carpeta del crédito y vuelva a procesar.",
    ),
    "PDF_TEXT_NOT_EXTRACTABLE": (
        "El PDF no trae texto que se pueda leer automáticamente (puede ser solo imagen).",
        "Exporte de nuevo el asiento desde el ERP como PDF con texto seleccionable, "
        "reemplácelo en la carpeta ASIENTOS, reconsolide el PDF (fase 3) "
        "y luego procese la amortización.",
    ),
    "ASIENTO_DOWNLOAD_FAILED": (
        "No fue posible descargar el PDF del asiento contable.",
        "Verifique que el archivo exista en SharePoint y no esté bloqueado; luego reintente.",
    ),
    "ACCOUNTING_PARSE_FAILED": (
        "El PDF no tiene el formato de asiento contable esperado "
        "(montos y cuentas en el mismo renglón como en el ERP).",
        "Abra el PDF en ASIENTOS y compare con un asiento que sí funcione: "
        "cada movimiento debe verse en una sola línea (cuenta + monto). "
        "Si el archivo se armó o convirtió de otra forma, vuelva a exportarlo desde el ERP "
        "y reemplace el PDF; luego reconsolide (fase 3) y procese la amortización.",
    ),
    "MISSING_BANK_VALUE_BUT_HAS_ACCOUNTING_LINES": (
        "Se vieron movimientos contables, pero falta la línea del recaudo del banco.",
        "Revise el PDF en ASIENTOS: debe aparecer el renglón del banco "
        "(recaudo Bogotá o Bancolombia) con su monto. Corrija o reemplace el asiento, "
        "reconsolide (fase 3) y luego procese la amortización.",
    ),
    "TABLE_DOWNLOAD_FAILED": (
        "No fue posible descargar la tabla de amortización del crédito.",
        "Verifique que el Excel exista y no esté abierto en otro equipo; luego reintente.",
    ),
    "AMORTIZATION_SHEET_NOT_FOUND": (
        "La tabla de amortización no tiene la hoja o estructura esperada.",
        "Abra el Excel de amortización y ajuste hojas o encabezados según el formato habitual.",
    ),
    "FECHA_LIMITE_NOT_FOUND": (
        "No se encontró la fecha límite de pago en la tabla de amortización.",
        "Revise el cronograma en el Excel de amortización y vuelva a procesar.",
    ),
    "DUE_DATE_ROW_NOT_FOUND": (
        "No hay una cuota pendiente clara en la tabla de amortización para aplicar el pago.",
        "Revise las cuotas pendientes en el Excel de amortización del crédito.",
    ),
    "REQUIRES_APPLICATION_ROW": (
        "La tabla de amortización necesita ampliar el bloque de aplicación del pago.",
        "Agregue filas al bloque Aplicación del Pago en el Excel y vuelva a procesar.",
    ),
    "APPLICATION_ROW_NOT_FOUND": (
        "No hay fila libre en el bloque Aplicación del Pago de la tabla de amortización.",
        "Revise el Excel de amortización y libere o amplíe filas de aplicación.",
    ),
    "FECHA_BANCO_REQUIRED": (
        "Falta la fecha bancaria necesaria para registrar el pago en la tabla.",
        "Complete la fecha bancaria en el histórico o manifest y vuelva a procesar.",
    ),
    "MERGE_INCOMPLETE_NOT_APPLICABLE": (
        "La unión de documentos quedó incompleta y no es posible continuar con la amortización.",
        "Revise Asientos_Pendientes, cargue los PDF faltantes y vuelva a ejecutar Unir PDFs.",
    ),
    "MERGE_GROUP_PENDING_INPUTS": (
        "Faltan documentos contables para completar la consolidación de un grupo.",
        "Cargue los PDF en las carpetas ASIENTOS indicadas y vuelva a ejecutar Unir PDFs.",
    ),
    "MERGE_EXPECTED_CREDITS_MISMATCH": (
        "El PDF consolidado no coincide con los créditos esperados del grupo.",
        "Revise el consolidado y los créditos del manifest; corrija y vuelva a unir PDFs.",
    ),
    "ABONO_ASIENTOS_NO_CUADRAN": (
        "Los asientos del abono no cuadran con el monto bancario.",
        "Revise montos en Distribucion_Abonos y los PDF en ASIENTOS; corrija y vuelva a procesar.",
    ),
    "ABONO_ASIENTO_FALTANTE": (
        "Falta el PDF del asiento contable para un crédito del abono.",
        "Cargue el asiento en la carpeta ASIENTOS del crédito y vuelva a procesar.",
    ),
    "ABONO_ASIENTO_DUPLICADO": (
        "Hay un asiento repetido dentro del mismo grupo de abono.",
        "Deje un solo PDF por asiento en ASIENTOS y vuelva a procesar.",
    ),
    "ABONO_TABLA_AMORTIZACION_MISSING": (
        "Un crédito del abono no tiene ruta de tabla de amortización.",
        "Verifique la tabla en SharePoint o ejecute Generate de nuevo y vuelva a procesar.",
    ),
    "ABONO_SCHEDULE_RULE_NOT_CONFIGURED": (
        "Los asientos cuadran, pero falta la regla de fila contractual e IBR del abono.",
        "Espere la configuración contable del abono antes de volver a procesar.",
    ),
}


def _nz(value: object) -> str:
    return str(value or "").strip()


def _looks_operator_unsafe(text: str) -> bool:
    """True si el texto parece jerga técnica o código interno."""
    t = _nz(text)
    if not t:
        return True
    if _SNAKE_CODE.fullmatch(t):
        return True
    if _TECH_LEAK.search(t):
        return True
    # Códigos ALL_CAPS con guiones bajos embebidos (p. ej. en excepciones).
    if re.search(r"\b[A-Z]{3,}(?:_[A-Z0-9]+)+\b", t):
        return True
    return False


def _file_basename(path_or_name: str) -> str | None:
    p = _nz(path_or_name).strip("/")
    if not p:
        return None
    name = p.rsplit("/", 1)[-1]
    return name or None


def _with_affected_file(message: str, file_name: str | None) -> str:
    """Añade «Archivo afectado: …» si hay nombre y aún no está en el mensaje."""
    msg = _nz(message)
    fn = _nz(file_name)
    if not fn or not msg:
        return msg
    if fn.lower() in msg.lower() or "archivo afectado" in msg.lower():
        return msg
    return f"{msg} Archivo afectado: {fn}."


def _lookup_amortization_messages(code: str) -> tuple[str, str] | None:
    c = _nz(code)
    if not c:
        return None
    if c in _AMORTIZATION_ITEM_MESSAGES:
        return _AMORTIZATION_ITEM_MESSAGES[c]
    upper = c.upper()
    if upper in _AMORTIZATION_ITEM_MESSAGES:
        return _AMORTIZATION_ITEM_MESSAGES[upper]
    return None


def _first_plain_warning(warnings: object) -> str | None:
    """Primera advertencia en español usable; descarta jerga y códigos."""
    if not isinstance(warnings, list):
        return None
    for raw in warnings:
        t = _nz(raw)
        if not t or _looks_operator_unsafe(t):
            continue
        # Reescrituras mínimas de avisos legacy del dry-run.
        low = t.lower()
        if "sin texto extraíble" in low or "posible escaneo" in low:
            mapped = _lookup_amortization_messages("PDF_TEXT_NOT_EXTRACTABLE")
            return mapped[0] if mapped else t
        if "no se encontró recaudo bancario" in low and "códigos con monto" in low:
            mapped = _lookup_amortization_messages(
                "MISSING_BANK_VALUE_BUT_HAS_ACCOUNTING_LINES"
            )
            return mapped[0] if mapped else t
        if "no se encontró recaudo bancario" in low:
            mapped = _lookup_amortization_messages("ACCOUNTING_PARSE_FAILED")
            return mapped[0] if mapped else t
        return t
    return None


def _humanize_code(code: str, *, fallback_message: str = "") -> tuple[str, str]:
    """Devuelve (user_message, next_action) sin exponer snake_case crudo."""
    c = _nz(code)
    local = _lookup_amortization_messages(c)
    if local:
        return local
    if c:
        for candidate in (c, c.lower(), c.upper()):
            user, nxt = finalize_message_for_code(candidate)
            if user and "inconveniente técnico" not in user.lower():
                return user, nxt
    msg = _nz(fallback_message)
    if msg and not _looks_operator_unsafe(msg):
        return msg, ""
    return (
        "Se encontró un problema que impide continuar con la amortización.",
        "Revise los documentos del crédito en SharePoint y vuelva a procesar la amortización.",
    )


def _resolve_item_messages(
    code: str,
    *,
    warnings: object = None,
    fallback_message: str = "",
) -> tuple[str, str]:
    """Mensaje de ítem: código conocido → copy fijo; si no, warning humano o fallback."""
    local = _lookup_amortization_messages(code)
    if local:
        return local
    plain = _first_plain_warning(warnings)
    if plain:
        return plain, _humanize_code(code)[1]
    return _humanize_code(code, fallback_message=fallback_message)


def _asientos_folder_path(raw_path: str) -> str | None:
    p = _nz(raw_path).strip("/")
    if not p:
        return None
    if p.lower().endswith(".pdf"):
        parts = p.rsplit("/", 1)
        return parts[0] if len(parts) == 2 else None
    return p


def _collect_web_urls(result: dict[str, Any]) -> dict[str, str]:
    urls: dict[str, str] = {}
    for key in (
        "asiento_web_urls",
        "folder_web_urls",
        "web_urls",
        "link_urls",
    ):
        raw = result.get(key)
        if isinstance(raw, dict):
            for k, v in raw.items():
                if v:
                    urls[_nz(k).strip("/")] = _nz(v)
    for item in result.get("items") or []:
        if not isinstance(item, dict):
            continue
        for path_key, url_key in (
            ("asiento_pdf_path", "asiento_web_url"),
            ("tabla_amortizacion_path", "tabla_web_url"),
            ("ruta_asientos_contables", "asientos_web_url"),
        ):
            path = _nz(item.get(path_key)).strip("/")
            url = _nz(item.get(url_key))
            if path and url:
                urls[path] = url
    return urls


def _build_asientos_links(
    *paths: str | None,
    web_urls: dict[str, str] | None = None,
) -> list[UiLink]:
    links: list[UiLink] = []
    seen: set[str] = set()
    for raw in paths:
        folder = _asientos_folder_path(_nz(raw))
        if not folder or folder in seen:
            continue
        seen.add(folder)
        norm = folder.strip("/")
        links.append(
            UiLink(
                rel="asientos",
                label="Abrir carpeta ASIENTOS",
                path=norm,
                web_url=(web_urls or {}).get(norm) or (web_urls or {}).get(folder),
                open_mode="sharepoint",
            )
        )
    return links


def _tabla_link_target(raw_path: str) -> str | None:
    """Ruta del Excel o de su carpeta padre para abrir en SharePoint."""
    p = _nz(raw_path).strip("/")
    if not p:
        return None
    low = p.lower()
    if low.endswith(".xlsx") or low.endswith(".xlsm") or low.endswith(".xls"):
        return p
    return p


def _build_tabla_links(
    *paths: str | None,
    web_urls: dict[str, str] | None = None,
) -> list[UiLink]:
    links: list[UiLink] = []
    seen: set[str] = set()
    for raw in paths:
        target = _tabla_link_target(_nz(raw))
        if not target or target in seen:
            continue
        seen.add(target)
        norm = target.strip("/")
        links.append(
            UiLink(
                rel="amortization_table",
                label="Abrir tabla de amortización",
                path=norm,
                web_url=(web_urls or {}).get(norm) or (web_urls or {}).get(target),
                open_mode="sharepoint",
            )
        )
    return links


def _links_for_item_code(
    code: str,
    *,
    asiento: str,
    tabla: str,
    web_urls: dict[str, str],
) -> list[UiLink]:
    c = _nz(code).upper()
    if c in _TABLE_LINK_CODES:
        return _build_tabla_links(tabla, web_urls=web_urls)
    # Formato/asiento: solo carpeta ASIENTOS (no mezclar con ruta de tabla).
    return _build_asientos_links(asiento, web_urls=web_urls)


def _issue_dict(issue: UiOperationalIssue) -> dict[str, Any]:
    return issue.model_dump(mode="json")


def _credit_label(credito: str, *, cliente: str = "") -> str:
    cred = _nz(credito)
    if cred:
        return f"Crédito {cred}"
    return _nz(cliente) or "Movimiento"


def _issues_from_merge_block(
    merge_block: dict[str, Any],
    result: dict[str, Any],
    *,
    web_urls: dict[str, str],
    start_index: int,
) -> list[UiOperationalIssue]:
    issues: list[UiOperationalIssue] = []
    code = _nz(merge_block.get("error_code")) or "MERGE_INCOMPLETE_NOT_APPLICABLE"
    base_user, base_next = _humanize_code(
        code,
        fallback_message=_nz(merge_block.get("user_message")),
    )

    incomplete = [
        g for g in (merge_block.get("incomplete_groups") or []) if isinstance(g, dict)
    ]
    output_issues = [
        o for o in (merge_block.get("output_issues") or []) if isinstance(o, dict)
    ]

    if incomplete:
        for idx, group in enumerate(incomplete):
            id_pago = _nz(group.get("id_pago"))
            missing = [
                _nz(c) for c in (group.get("missing_creditos") or []) if _nz(c)
            ]
            credito = missing[0] if missing else ""
            title = "Consolidación incompleta"
            if credito:
                title = f"{title} · {_credit_label(credito)}"
            elif id_pago:
                title = f"{title} · Pago {id_pago}"

            if missing:
                user = (
                    f"Faltan documentos para el/los crédito(s): {', '.join(missing)}."
                )
            else:
                user = base_user
            issues.append(
                UiOperationalIssue(
                    issue_id=f"amort-{code}-{id_pago or credito or 'merge'}-{start_index + idx}",
                    stage=_STAGE,
                    category=_CATEGORY,
                    severity="business",
                    recoverable=True,
                    title=title,
                    user_message=user,
                    location=UiIssueLocation(
                        credit=credito or None,
                        payment_id=id_pago or None,
                    ),
                    next_action=_nz(merge_block.get("next_action")) or base_next,
                    links=[],
                    technical_reference=code,
                )
            )
        return issues

    if output_issues:
        for idx, out in enumerate(output_issues):
            id_pago = _nz(out.get("id_pago"))
            out_code = _nz(out.get("error_code")) or code
            user, nxt = _humanize_code(out_code)
            issues.append(
                UiOperationalIssue(
                    issue_id=f"amort-{out_code}-{id_pago or 'out'}-{start_index + idx}",
                    stage=_STAGE,
                    category=_CATEGORY,
                    severity="business",
                    recoverable=True,
                    title=f"Consolidación · Pago {id_pago}" if id_pago else "Consolidación",
                    user_message=user,
                    location=UiIssueLocation(payment_id=id_pago or None),
                    next_action=nxt or _nz(merge_block.get("next_action")) or base_next,
                    links=[],
                    technical_reference=out_code,
                )
            )
        return issues

    issues.append(
        UiOperationalIssue(
            issue_id=f"amort-{code}-merge-{start_index}",
            stage=_STAGE,
            category=_CATEGORY,
            severity="business",
            recoverable=True,
            title="Consolidación incompleta",
            user_message=base_user,
            next_action=_nz(merge_block.get("next_action")) or base_next,
            links=[],
            technical_reference=code,
        )
    )
    return issues


def _issues_from_abono_group(
    group: dict[str, Any],
    index: int,
    *,
    web_urls: dict[str, str],
) -> UiOperationalIssue:
    id_pago = _nz(group.get("id_pago"))
    creditos = [_nz(c) for c in (group.get("creditos_seleccionados") or []) if _nz(c)]
    credito = creditos[0] if creditos else ""
    blocking = [
        e for e in (group.get("blocking_errors") or []) if isinstance(e, dict)
    ]

    messages: list[str] = []
    next_actions: list[str] = []
    paths: list[str] = []
    tech_codes: list[str] = []

    for err in blocking:
        code = _nz(err.get("error_code"))
        raw_msg = _nz(err.get("message"))
        # Preferir copy operativo del código; no volcar excepciones técnicas.
        local = _lookup_amortization_messages(code) if code else None
        if local:
            messages.append(local[0])
            if local[1]:
                next_actions.append(local[1])
        elif raw_msg and not _looks_operator_unsafe(raw_msg):
            messages.append(raw_msg)
        elif code:
            user, nxt = _humanize_code(code, fallback_message=raw_msg)
            messages.append(user)
            if nxt:
                next_actions.append(nxt)
        if code:
            tech_codes.append(code)
        err_cred = _nz(err.get("credito"))
        if err_cred and err_cred not in creditos:
            creditos.append(err_cred)
        for p in err.get("paths") or []:
            if _nz(p):
                paths.append(_nz(p))

    if not messages:
        recon = _nz(group.get("reconciliation_status"))
        if recon and recon != "PASSED":
            messages.append(
                "Los asientos del abono no cuadran con el monto bancario registrado."
            )
        else:
            schedule = _nz(group.get("schedule_resolution_status"))
            if schedule and schedule not in ("", "RESOLVED", "NOT_REQUIRED"):
                messages.append(
                    "El abono requiere configuración de regla de fila contractual e IBR."
                )
            else:
                messages.append(
                    "Hay un grupo de abono con errores documentales o de cuadre."
                )

    if len(creditos) == 1:
        title = f"Abono · {_credit_label(creditos[0])}"
    elif creditos:
        title = f"Abono · Créditos {', '.join(creditos[:3])}"
    elif id_pago:
        title = f"Abono · Pago {id_pago}"
    else:
        title = "Abono bloqueado"

    file_name = None
    for p in paths:
        bn = _file_basename(p)
        if bn and bn.lower().endswith(".pdf"):
            file_name = bn
            break

    user_message = _with_affected_file(
        " ".join(dict.fromkeys(messages)),
        file_name,
    )
    primary_code = tech_codes[0] if tech_codes else "abono_apply_blocked"
    next_action = next_actions[0] if next_actions else (
        "Revise los asientos y montos en Distribucion_Abonos; corrija los PDF en ASIENTOS "
        "y vuelva a procesar la amortización."
    )

    return UiOperationalIssue(
        issue_id=f"amort-{primary_code}-{id_pago or credito or 'abono'}-{index}",
        stage=_STAGE,
        category=_CATEGORY,
        severity="business",
        recoverable=True,
        title=title,
        user_message=user_message,
        location=UiIssueLocation(
            file_name=file_name or None,
            credit=credito or (creditos[0] if creditos else None),
            payment_id=id_pago or None,
        ),
        next_action=next_action,
        links=_build_asientos_links(*paths, web_urls=web_urls),
        technical_reference=primary_code,
    )


def _item_has_issue(item: dict[str, Any]) -> bool:
    if _nz(item.get("error_code")):
        return True
    if str(item.get("application_status") or "").strip().upper() == "ERROR":
        return True
    if str(item.get("application_status") or "").strip().upper() == "REVISION_MANUAL":
        return True
    return False


def _file_snapshot_from_item(item: dict[str, Any]) -> dict[str, Any]:
    """Metadata del PDF al fallar (para comparar en recovery verify)."""
    etag = _nz(item.get("asiento_pdf_etag"))
    last_mod = _nz(item.get("asiento_pdf_last_modified"))
    size_raw = item.get("asiento_pdf_size")
    size: int | None = None
    if isinstance(size_raw, int):
        size = size_raw
    elif isinstance(size_raw, str) and size_raw.strip().isdigit():
        size = int(size_raw.strip())
    return {
        "file_etag": etag or None,
        "file_size": size,
        "file_last_modified": last_mod or None,
    }


def _issue_from_dry_run_item(
    item: dict[str, Any],
    index: int,
    *,
    web_urls: dict[str, str],
) -> UiOperationalIssue:
    id_pago = _nz(item.get("id_pago"))
    credito = _nz(item.get("credito"))
    cliente = _nz(item.get("cliente"))
    code = _nz(item.get("error_code")) or "preflight_item_error"
    status = _nz(item.get("application_status")).upper()

    if status == "REVISION_MANUAL":
        code = code or "preflight_revision_manual"
        user, nxt = _resolve_item_messages(code, warnings=item.get("warnings"))
        user = user or (
            "Este movimiento requiere revisión manual antes de aplicar la amortización."
        )
    else:
        user, nxt = _resolve_item_messages(code, warnings=item.get("warnings"))

    asiento = _nz(item.get("asiento_pdf_path"))
    tabla = _nz(item.get("tabla_amortizacion_path"))
    # Preferir carpeta ASIENTOS explícita si el ítem la trae.
    asientos_folder = _nz(item.get("ruta_asientos_contables")) or asiento
    file_name = _file_basename(asiento) or _file_basename(_nz(item.get("file_name")))
    snap = _file_snapshot_from_item(item)

    title = "Documento contable"
    if credito:
        title = f"{title} · {_credit_label(credito)}"
    elif id_pago:
        title = f"{title} · Pago {id_pago}"

    return UiOperationalIssue(
        issue_id=f"amort-{code}-{credito or id_pago or 'item'}-{index}",
        stage=_STAGE,
        category=_CATEGORY,
        severity="business",
        recoverable=True,
        title=title,
        user_message=_with_affected_file(user, file_name),
        location=UiIssueLocation(
            file_name=file_name or None,
            credit=credito or None,
            payment_id=id_pago or None,
            client_name=cliente or None,
            file_etag=snap["file_etag"],
            file_size=snap["file_size"],
            file_last_modified=snap["file_last_modified"],
        ),
        next_action=nxt
        or "Revise el asiento, la tabla de amortización o el extracto en SharePoint y vuelva a procesar.",
        links=_links_for_item_code(
            code, asiento=asientos_folder, tabla=tabla, web_urls=web_urls
        ),
        technical_reference=code or None,
    )


def _fallback_issue(result: dict[str, Any]) -> UiOperationalIssue:
    code = (
        _nz(result.get("error_code"))
        or _nz(result.get("preflight_error_code"))
        or "requires_correction"
    )
    user, nxt = _humanize_code(code, fallback_message=_nz(result.get("user_message")))
    return UiOperationalIssue(
        issue_id=f"amort-{code}-summary-0",
        stage=_STAGE,
        category=_CATEGORY,
        severity="business",
        recoverable=True,
        title="Amortización requiere corrección",
        user_message=user,
        next_action=nxt or _nz(result.get("next_action")),
        links=[],
        technical_reference=code,
    )


def build_operational_issues_from_amortization_result(
    result: dict[str, Any],
) -> list[dict[str, Any]]:
    """Construye la lista sanitizada de problemas operativos desde un result de amortización."""
    if not isinstance(result, dict):
        return []

    web_urls = _collect_web_urls(result)
    issues: list[UiOperationalIssue] = []
    idx = 0

    merge_block = result.get("merge_incomplete_block")
    if isinstance(merge_block, dict):
        issues.extend(
            _issues_from_merge_block(merge_block, result, web_urls=web_urls, start_index=idx)
        )
        idx += len(issues)

    blocking_groups = [
        g for g in (result.get("blocking_abono_groups") or []) if isinstance(g, dict)
    ]
    if blocking_groups:
        for g_idx, group in enumerate(blocking_groups):
            issues.append(_issues_from_abono_group(group, g_idx, web_urls=web_urls))
    else:
        items = [
            it for it in (result.get("items") or []) if isinstance(it, dict) and _item_has_issue(it)
        ]
        preflight = result.get("preflight")
        if not items and isinstance(preflight, dict):
            items = [
                it
                for it in (preflight.get("items") or [])
                if isinstance(it, dict) and _item_has_issue(it)
            ]
        for item_idx, item in enumerate(items):
            issues.append(
                _issue_from_dry_run_item(item, item_idx, web_urls=web_urls)
            )

    outcome = _nz(result.get("outcome")).lower()
    status = _nz(result.get("status")).lower()
    needs_correction = (
        outcome == "requires_correction"
        or result.get("can_apply") is False
        or status in ("blocked", "preflight_failed")
    )
    if not issues and needs_correction:
        issues.append(_fallback_issue(result))

    return [_issue_dict(i) for i in issues]


def attach_operational_issues_to_amortization_result(
    result: dict[str, Any],
) -> dict[str, Any]:
    """Adjunta operational_issues y resume user_message/next_action cuando aplica."""
    if not isinstance(result, dict):
        return result
    out = dict(result)
    issues = build_operational_issues_from_amortization_result(out)
    if not issues:
        return out
    out["operational_issues"] = issues
    n = len(issues)
    out["user_message"] = (
        f"La amortización encontró {n} problema(s). No se modificó ninguna tabla."
    )
    format_family = any(
        _nz(i.get("technical_reference")).upper() in _FORMAT_FAMILY_CODES for i in issues
    )
    if format_family:
        out["next_action"] = (
            "Corrija los PDF en SharePoint, reconsolide el PDF (fase 3) "
            "y luego procese la amortización."
        )
    else:
        out["next_action"] = (
            "Revise cada punto en el detalle, corrija los documentos en SharePoint "
            "y vuelva a procesar la amortización."
        )
    return out


async def enrich_operational_issue_web_urls(
    graph: Any,
    site_id: str,
    drive_id: str,
    result: dict[str, Any],
) -> dict[str, Any]:
    """Completa ``web_url`` en links de operational_issues vía Graph (solo lectura).

    La UI solo muestra enlaces con ``web_url``; sin esto el botón
    «Abrir carpeta ASIENTOS» no aparece aunque haya ``path``.
    """
    if not isinstance(result, dict):
        return result
    out = attach_operational_issues_to_amortization_result(dict(result))
    issues = out.get("operational_issues")
    if not isinstance(issues, list) or not issues:
        return out

    from app.application.sharepoint_resolution import sharepoint_open_in_browser_url
    from app.application.use_cases.validate_payment_report import (
        _graph_get_item_metadata_by_path,
    )

    url_map = _collect_web_urls(out)
    paths_needed: list[str] = []
    seen_paths: set[str] = set()
    for issue in issues:
        if not isinstance(issue, dict):
            continue
        for link in issue.get("links") or []:
            if not isinstance(link, dict):
                continue
            path = _nz(link.get("path")).strip("/")
            if not path or _nz(link.get("web_url")):
                continue
            if path in url_map or path in seen_paths:
                continue
            seen_paths.add(path)
            paths_needed.append(path)

    for path in paths_needed:
        try:
            meta = await _graph_get_item_metadata_by_path(
                graph, site_id, drive_id, path
            )
        except Exception:
            meta = {}
        raw_url = _nz(meta.get("webUrl")) if isinstance(meta, dict) else ""
        if not raw_url:
            continue
        url = sharepoint_open_in_browser_url(raw_url) or raw_url
        if url:
            url_map[path] = url

    if url_map:
        folder_urls = out.get("folder_web_urls")
        if not isinstance(folder_urls, dict):
            folder_urls = {}
        folder_urls = {**folder_urls, **url_map}
        out["folder_web_urls"] = folder_urls

    patched: list[dict[str, Any]] = []
    for issue in issues:
        if not isinstance(issue, dict):
            patched.append(issue)  # type: ignore[arg-type]
            continue
        row = dict(issue)
        links_out: list[dict[str, Any]] = []
        for link in row.get("links") or []:
            if not isinstance(link, dict):
                continue
            link_row = dict(link)
            path = _nz(link_row.get("path")).strip("/")
            if path and not _nz(link_row.get("web_url")):
                url = url_map.get(path) or url_map.get(_nz(link_row.get("path")))
                if url:
                    link_row["web_url"] = url
            links_out.append(link_row)
        row["links"] = links_out
        patched.append(row)
    out["operational_issues"] = patched
    return out


__all__ = [
    "attach_operational_issues_to_amortization_result",
    "build_operational_issues_from_amortization_result",
    "enrich_operational_issue_web_urls",
]
