"""Issues operativos de Merge a partir del último job (skips / grupos incompletos)."""
from __future__ import annotations

from typing import Any

from app.application.job_status_enrichment import merge_skip_operator_copy
from app.application.services.merge_group_validation import (
    _assignment_code_from_skip,
    _credits_from_seleccionados,
    _parse_skip_reason_for_credit,
)
from app.application.ui.job_read import JobReadResult
from app.application.ui.schemas import (
    UiIssueLocation,
    UiLink,
    UiOperationalIssue,
)

_FALLBACK_USER = "Falta un documento requerido para consolidar este crédito."
_FALLBACK_NEXT = (
    "Revise ASIENTOS y el extracto del crédito, corrija y vuelva a unir PDFs."
)


def _nz(value: object) -> str | None:
    text = str(value or "").strip()
    return text or None


def _folder_link_for_credit(
    folder_links: list[dict[str, Any]],
    credito: str,
) -> UiLink | None:
    want = credito.strip()
    if not want:
        return None
    for folder in folder_links:
        if str(folder.get("credito") or "").strip() != want:
            continue
        web = _nz(folder.get("web_url"))
        path = _nz(folder.get("path"))
        if not web and not path:
            continue
        return UiLink(
            rel="asientos",
            label="Abrir carpeta ASIENTOS",
            path=path,
            web_url=web,
            open_mode="sharepoint",
        )
    return None


def _copy_for_code(code: str, credito: str | None) -> tuple[str, str]:
    mapped = merge_skip_operator_copy(code)
    if mapped:
        user, nxt = mapped
        if credito and "crédito" not in user.lower() and "credito" not in user.lower():
            user = f"{user} Crédito {credito}."
        return user, nxt
    if code == "asiento_contable_not_found":
        if credito:
            return (
                f"Falta el PDF del asiento contable en la carpeta ASIENTOS del crédito {credito}.",
                "Cargue el asiento en ASIENTOS y vuelva a unir PDFs.",
            )
        return (
            "Falta el PDF del asiento contable en la carpeta ASIENTOS.",
            "Cargue el asiento en ASIENTOS y vuelva a unir PDFs.",
        )
    if code == "extract_routes_missing":
        if credito:
            return (
                f"Falta el extracto PDF del crédito {credito} (ruta vacía o archivo ausente).",
                "Verifique el extracto en la carpeta del crédito y vuelva a finalizar si hace falta; "
                "luego reintente la consolidación.",
            )
        return (
            "Falta la ruta del extracto bancario o el PDF no está en SharePoint.",
            "Verifique el extracto en la carpeta del crédito y vuelva a finalizar si hace falta.",
        )
    if code == "asiento_contable_credit_mismatch":
        if credito:
            return (
                f"Hay un PDF en ASIENTOS del crédito {credito} cuyo nombre no coincide con ese crédito.",
                "Deje en esa carpeta solo el asiento de ese crédito y vuelva a unir PDFs.",
            )
        return (
            "Hay un PDF en ASIENTOS cuyo nombre no coincide con el crédito.",
            "Corrija el archivo en ASIENTOS y vuelva a unir PDFs.",
        )
    if credito:
        return (
            f"{_FALLBACK_USER} Crédito {credito}.",
            _FALLBACK_NEXT,
        )
    return _FALLBACK_USER, _FALLBACK_NEXT


def _issue_from_missing_input(
    *,
    job_id: str,
    idx: int,
    item: dict[str, Any],
    id_pago: str | None,
    folder_links: list[dict[str, Any]],
) -> UiOperationalIssue | None:
    code = _nz(item.get("error_code")) or "document_missing"
    credito = _nz(item.get("credito"))
    user, nxt = _copy_for_code(code, credito)
    title = (
        f"Documento contable · Crédito {credito}" if credito else "Documento contable"
    )
    link = _folder_link_for_credit(folder_links, credito or "")
    return UiOperationalIssue(
        issue_id=f"HBI-MERGE-{code}-{job_id[:8]}-{idx}",
        stage="merge",
        category="correction_required",
        severity="business",
        recoverable=True,
        title=title,
        user_message=user,
        location=UiIssueLocation(
            file_name=None,
            sheet=None,
            row=None,
            column=None,
            credit=credito,
            payment_id=id_pago,
            client_name=None,
        ),
        value_found=_nz(item.get("found_pdf_name")),
        expected_values=[],
        next_action=nxt,
        retry=None,
        links=[link] if link else [],
        technical_reference=f"job:{job_id}|code:{code}",
    )


def build_operational_issues_from_merge_job(
    job: JobReadResult,
    *,
    folder_links: list[dict[str, Any]] | None = None,
) -> list[UiOperationalIssue]:
    """Expande skips / incomplete_groups del job Merge a un issue por crédito."""
    payload = job.payload
    status = str(payload.get("status") or "").lower()
    result = payload.get("result") if isinstance(payload.get("result"), dict) else {}
    if status not in {"completed", "failed"}:
        return []
    groups = result.get("incomplete_groups") or []
    skipped = result.get("skipped") or []
    if not groups and not skipped:
        return []

    folders = [dict(x) for x in (folder_links or []) if isinstance(x, dict)]
    out: list[UiOperationalIssue] = []
    seen: set[tuple[str, str]] = set()
    idx = 0

    for group in groups:
        if not isinstance(group, dict):
            continue
        id_pago = _nz(group.get("id_pago"))
        items = group.get("missing_inputs") or []
        if not isinstance(items, list):
            continue
        for item in items:
            if not isinstance(item, dict):
                continue
            code = _nz(item.get("error_code")) or "document_missing"
            credito = _nz(item.get("credito")) or ""
            key = (code, credito)
            if key in seen:
                continue
            seen.add(key)
            issue = _issue_from_missing_input(
                job_id=job.job_id,
                idx=idx,
                item=item,
                id_pago=id_pago,
                folder_links=folders,
            )
            if issue:
                out.append(issue)
                idx += 1

    for line in skipped:
        text = str(line or "").strip()
        if not text:
            continue
        creditos = _credits_from_seleccionados(text)
        if not creditos:
            assignment = _assignment_code_from_skip(text)
            if assignment:
                creditos = {""}
        for credito in sorted(creditos):
            parsed = _parse_skip_reason_for_credit(text, credito) if credito else None
            code = (
                (parsed or {}).get("error_code")
                or _assignment_code_from_skip(text)
                or "document_missing"
            )
            key = (code, credito)
            if key in seen:
                continue
            seen.add(key)
            item = parsed or {"error_code": code, "credito": credito or None}
            issue = _issue_from_missing_input(
                job_id=job.job_id,
                idx=idx,
                item=item,
                id_pago=None,
                folder_links=folders,
            )
            if issue:
                out.append(issue)
                idx += 1

    return out


__all__ = ["build_operational_issues_from_merge_job"]
