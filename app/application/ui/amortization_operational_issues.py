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

_AMORTIZATION_ITEM_MESSAGES: dict[str, tuple[str, str]] = {
    "ASIENTO_PATH_MISSING": (
        "Falta la ruta del PDF del asiento contable para este movimiento.",
        "Suba el PDF en la carpeta ASIENTOS del crédito y vuelva a procesar la amortización.",
    ),
    "TABLE_PATH_NOT_FOUND": (
        "No se encontró la tabla de amortización del crédito en SharePoint.",
        "Verifique que el Excel de amortización exista en la carpeta del crédito y vuelva a procesar.",
    ),
    "PDF_TEXT_NOT_EXTRACTABLE": (
        "El PDF del asiento no contiene texto legible para la automatización.",
        "Cargue un PDF con texto seleccionable en la carpeta ASIENTOS y vuelva a procesar.",
    ),
    "ASIENTO_DOWNLOAD_FAILED": (
        "No fue posible descargar el PDF del asiento contable.",
        "Verifique que el archivo exista en SharePoint y no esté bloqueado; luego reintente.",
    ),
    "ACCOUNTING_PARSE_FAILED": (
        "No fue posible interpretar el contenido del asiento contable.",
        "Revise el PDF en ASIENTOS, corrija el formato y vuelva a procesar.",
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
    if msg and not _SNAKE_CODE.fullmatch(msg):
        return msg, ""
    return (
        "Se encontró un problema que impide continuar con la amortización.",
        "Revise los documentos del crédito en SharePoint y vuelva a procesar la amortización.",
    )


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
        if raw_msg and not _SNAKE_CODE.fullmatch(raw_msg):
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

    user_message = " ".join(dict.fromkeys(messages))
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
        user, nxt = _humanize_code(code)
        user = user or "Este movimiento requiere revisión manual antes de aplicar la amortización."
    else:
        user, nxt = _humanize_code(code)

    asiento = _nz(item.get("asiento_pdf_path"))
    tabla = _nz(item.get("tabla_amortizacion_path"))
    file_name = None
    if asiento:
        file_name = asiento.rsplit("/", 1)[-1]

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
        user_message=user,
        location=UiIssueLocation(
            file_name=file_name or None,
            credit=credito or None,
            payment_id=id_pago or None,
            client_name=cliente or None,
        ),
        next_action=nxt
        or "Revise el asiento, la tabla de amortización o el extracto en SharePoint y vuelva a procesar.",
        links=_build_asientos_links(asiento, tabla, web_urls=web_urls),
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
    out["next_action"] = (
        "Revise cada punto en el detalle, corrija los documentos en SharePoint "
        "y vuelva a procesar la amortización."
    )
    return out


__all__ = [
    "attach_operational_issues_to_amortization_result",
    "build_operational_issues_from_amortization_result",
]
