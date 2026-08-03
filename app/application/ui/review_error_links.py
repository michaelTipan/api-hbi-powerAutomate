"""Resolución de links de corrección por código técnico de la hoja Errores.

Prioridad: archivo concreto → carpeta contenedora → Excel de revisión.
No inventa URLs: solo incluye destinos con ``web_url`` real (o path conocido
cuando el caller ya resolvió la URL).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.application.ui.review_errores_read import ReviewErrorRow

# Alias operador / legado → código canónico de Generate.
_CODE_ALIASES: dict[str, str] = {
    "cliente_no_encontrado": "customer_not_found",
    "CLIENTE_NO_ENCONTRADO": "customer_not_found",
    "cliente_ambiguo": "customer_ambiguous",
    "CLIENTE_AMBIGUO": "customer_ambiguous",
}

# Extracto: PDF concreto + carpeta del crédito.
_EXTRACT_FILE_PRIMARY: frozenset[str] = frozenset(
    {
        "fecha_limite_extracto_not_readable",
        "extract_amount_not_found",
    }
)

# Carpeta (dónde subir / elegir entre varios) como destino principal.
_FOLDER_PRIMARY: frozenset[str] = frozenset(
    {
        "extract_not_found",
        "extract_tie_max_fecha_limite",
        "abono_mora_extract_missing",
        "abono_mora_extract_ambiguous",
        "amortization_table_not_found",
        "amortization_table_ambiguous",
        "abono_credit_without_amortization_table",
        "credit_folder_not_found",
        "abono_no_credit_candidates",
    }
)

# Excel de carga del banco (+ base clientes cuando aporta).
_BANK_INPUT_PRIMARY: frozenset[str] = frozenset(
    {
        "customer_not_found",
        "customer_ambiguous",
        "generic_abono_not_supported",
        "tipo_aplicacion_invalid",
        "tipo_aplicacion_required",
    }
)

# Códigos donde la carpeta base de clientes es útil como 2.º destino.
_CLIENTS_BASE_SECONDARY: frozenset[str] = frozenset(
    {
        "customer_not_found",
        "customer_ambiguous",
        "credit_folder_not_found",
        "abono_no_credit_candidates",
    }
)


@dataclass(frozen=True)
class ReviewErrorLinkContext:
    """Links de proceso ya resueltos (best-effort; pueden ser None)."""

    review_link: Any | None = None
    bank_input_link: Any | None = None
    bank_folder_link: Any | None = None
    clients_base_link: Any | None = None


def normalize_review_error_code(codigo_tecnico: str | None) -> str:
    """Normaliza código técnico / alias a forma canónica snake_case."""
    raw = str(codigo_tecnico or "").strip()
    if not raw:
        return ""
    if raw in _CODE_ALIASES:
        return _CODE_ALIASES[raw]
    lower = raw.lower()
    if lower in _CODE_ALIASES:
        return _CODE_ALIASES[lower]
    return lower


def _has_openable_url(link: Any | None) -> bool:
    if link is None:
        return False
    url = getattr(link, "web_url", None)
    if url is None and isinstance(link, dict):
        url = link.get("web_url")
    return bool(str(url or "").strip())


def _clone_link(
    *,
    rel: str,
    label: str,
    source: Any | None = None,
    web_url: str | None = None,
    path: str | None = None,
) -> Any:
    """Construye UiLink (import diferido) solo si hay web_url real."""
    from app.application.ui.schemas import UiLink

    url = web_url
    p = path
    if source is not None:
        if url is None:
            url = getattr(source, "web_url", None)
            if url is None and isinstance(source, dict):
                url = source.get("web_url")
        if p is None:
            p = getattr(source, "path", None)
            if p is None and isinstance(source, dict):
                p = source.get("path")
    url_txt = str(url or "").strip() or None
    if not url_txt:
        return None
    return UiLink(
        rel=rel,
        label=label,
        path=(str(p).strip() or None) if p else None,
        web_url=url_txt,
        open_mode="sharepoint",
    )


def _append_unique(out: list[Any], link: Any | None) -> None:
    if link is None:
        return
    url = str(getattr(link, "web_url", None) or "").strip()
    if not url:
        return
    if any(str(getattr(x, "web_url", None) or "").strip() == url for x in out):
        return
    out.append(link)


def build_review_error_issue_links(
    row: ReviewErrorRow,
    *,
    context: ReviewErrorLinkContext | None = None,
) -> list[Any]:
    """Arma links priorizados de corrección para una fila de Errores.

    Omite destinos sin ``web_url``. El Excel de revisión se añade al final
    como ancla de fila cuando aporta y no duplica URL.
    """
    ctx = context or ReviewErrorLinkContext()
    code = normalize_review_error_code(row.codigo_tecnico)
    out: list[Any] = []

    extract = None
    if row.extract_url:
        extract = _clone_link(
            rel="error_extract",
            label=row.extract_label or "Abrir extracto",
            web_url=row.extract_url,
        )
    folder = None
    if row.folder_url:
        folder = _clone_link(
            rel="error_folder",
            label=row.folder_label or "Abrir carpeta del crédito",
            web_url=row.folder_url,
        )

    bank_input = None
    if _has_openable_url(ctx.bank_input_link):
        bank_input = _clone_link(
            rel="bank_input",
            label="Abrir Excel del banco",
            source=ctx.bank_input_link,
        )
    bank_folder = None
    if _has_openable_url(ctx.bank_folder_link):
        bank_folder = _clone_link(
            rel="bank_folder",
            label="Abrir carpeta del banco",
            source=ctx.bank_folder_link,
        )
    clients_base = None
    if _has_openable_url(ctx.clients_base_link):
        clients_base = _clone_link(
            rel="clients_base",
            label="Abrir carpetas de clientes",
            source=ctx.clients_base_link,
        )
    review = None
    if _has_openable_url(ctx.review_link):
        review = _clone_link(
            rel="review_excel",
            label="Abrir Excel de revisión",
            source=ctx.review_link,
        )

    if code in _EXTRACT_FILE_PRIMARY:
        _append_unique(out, extract)
        _append_unique(out, folder)
    elif code in _BANK_INPUT_PRIMARY:
        _append_unique(out, bank_input)
        if code in _CLIENTS_BASE_SECONDARY:
            _append_unique(out, clients_base)
        else:
            _append_unique(out, bank_folder)
        # Si no hubo banco, la fila a veces trae carpeta (poco frecuente).
        _append_unique(out, folder)
        _append_unique(out, extract)
    elif code in _FOLDER_PRIMARY:
        _append_unique(out, folder)
        _append_unique(out, extract)
        if code in _CLIENTS_BASE_SECONDARY and not folder:
            _append_unique(out, clients_base)
    else:
        # Default: lo que traiga la fila; Excel de revisión como ancla.
        _append_unique(out, extract)
        _append_unique(out, folder)

    _append_unique(out, review)

    # Sin ningún destino de fila/banco: al menos revisión si existe.
    if not out and review is not None:
        out.append(review)
    return out
