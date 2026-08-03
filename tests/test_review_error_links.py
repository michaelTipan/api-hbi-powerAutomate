"""Tests del mapa código técnico → links de corrección (hoja Errores)."""
from __future__ import annotations

from app.application.ui.review_error_links import (
    ReviewErrorLinkContext,
    build_review_error_issue_links,
    normalize_review_error_code,
)
from app.application.ui.review_errores_read import (
    ReviewErrorRow,
    build_operational_issues_from_review_errores,
)
from app.application.ui.schemas import UiLink


def _row(**overrides: object) -> ReviewErrorRow:
    base = dict(
        row_number=2,
        id_pago="PAY-1",
        cliente="CLIENTE DEMO",
        credito="215",
        tipo_caso="Caso",
        descripcion="Desc",
        que_debe_hacer="Corregir",
        requiere_soporte="",
        codigo_tecnico="unknown_code",
        extract_label="",
        folder_label="",
        extract_url=None,
        folder_url=None,
    )
    base.update(overrides)
    return ReviewErrorRow(**base)  # type: ignore[arg-type]


def _ctx(**urls: str) -> ReviewErrorLinkContext:
    def link(rel: str, label: str, url: str | None) -> UiLink | None:
        if not url:
            return None
        return UiLink(rel=rel, label=label, path=None, web_url=url, open_mode="sharepoint")

    return ReviewErrorLinkContext(
        bank_input_link=link("bank_input", "Abrir Excel del banco", urls.get("bank")),
        bank_folder_link=link("bank_folder", "Abrir carpeta del banco", urls.get("bank_folder")),
        clients_base_link=link(
            "clients_base", "Abrir carpetas de clientes", urls.get("clients")
        ),
    )


def test_normalize_alias_cliente_no_encontrado() -> None:
    assert normalize_review_error_code("CLIENTE_NO_ENCONTRADO") == "customer_not_found"
    assert normalize_review_error_code("cliente_no_encontrado") == "customer_not_found"
    assert normalize_review_error_code("customer_not_found") == "customer_not_found"


def test_extract_damaged_prioritizes_file_then_folder() -> None:
    row = _row(
        codigo_tecnico="fecha_limite_extracto_not_readable",
        extract_label="extracto_malo.pdf",
        extract_url="https://sp.example/extracto.pdf",
        folder_label="CREDITO 215",
        folder_url="https://sp.example/folder",
    )
    links = build_review_error_issue_links(row, context=_ctx())
    assert [l.rel for l in links] == ["error_extract", "error_folder"]
    assert links[0].label == "extracto_malo.pdf"


def test_extract_not_found_folder_only_no_fake_extract() -> None:
    row = _row(
        codigo_tecnico="extract_not_found",
        folder_url="https://sp.example/folder",
        folder_label="CREDITO 215",
        extract_url=None,
    )
    links = build_review_error_issue_links(row, context=_ctx())
    assert [l.rel for l in links] == ["error_folder"]


def test_customer_not_found_bank_then_clients_base() -> None:
    row = _row(codigo_tecnico="customer_not_found", extract_url=None, folder_url=None)
    links = build_review_error_issue_links(
        row,
        context=_ctx(
            bank="https://sp.example/banco.xlsx",
            clients="https://sp.example/clientes",
        ),
    )
    assert [l.rel for l in links] == ["bank_input", "clients_base"]
    assert links[0].label == "Abrir Excel del banco"
    assert links[1].label == "Abrir carpetas de clientes"


def test_cliente_no_encontrado_alias_uses_same_map() -> None:
    row = _row(codigo_tecnico="CLIENTE_NO_ENCONTRADO")
    links = build_review_error_issue_links(
        row,
        context=_ctx(bank="https://sp.example/banco.xlsx", clients="https://sp.example/c"),
    )
    assert links[0].rel == "bank_input"
    assert links[1].rel == "clients_base"


def test_generic_abono_bank_input_and_bank_folder() -> None:
    row = _row(codigo_tecnico="generic_abono_not_supported")
    links = build_review_error_issue_links(
        row,
        context=_ctx(
            bank="https://sp.example/banco.xlsx",
            bank_folder="https://sp.example/banco-folder",
        ),
    )
    assert [l.rel for l in links] == ["bank_input", "bank_folder"]


def test_omits_links_without_web_url() -> None:
    row = _row(codigo_tecnico="customer_not_found")
    # Contexto sin URLs: no inventar destinos.
    links = build_review_error_issue_links(row, context=ReviewErrorLinkContext())
    assert links == []


def test_default_unknown_code_uses_row_links_without_review_excel() -> None:
    row = _row(
        codigo_tecnico="codigo_nuevo_desconocido",
        extract_url="https://sp.example/a.pdf",
        folder_url="https://sp.example/f",
    )
    links = build_review_error_issue_links(row, context=_ctx())
    assert [l.rel for l in links] == ["error_extract", "error_folder"]
    assert "review_excel" not in [l.rel for l in links]


def test_credit_folder_not_found_falls_back_to_clients_base() -> None:
    row = _row(codigo_tecnico="credit_folder_not_found", folder_url=None)
    links = build_review_error_issue_links(
        row,
        context=_ctx(clients="https://sp.example/clientes"),
    )
    assert [l.rel for l in links] == ["clients_base"]


def test_build_operational_issues_orders_links_by_code() -> None:
    row = _row(
        codigo_tecnico="fecha_limite_extracto_not_readable",
        tipo_caso="Extracto",
        extract_url="https://sp.example/e.pdf",
        extract_label="e.pdf",
        folder_url="https://sp.example/f",
        folder_label="CREDITO 215",
    )
    issues = build_operational_issues_from_review_errores([row], file_name="rev.xlsx")
    assert [l.rel for l in issues[0].links] == [
        "error_extract",
        "error_folder",
    ]
    assert "review_excel" not in [l.rel for l in issues[0].links]
