"""Tests del builder de operational_issues para amortización requires_correction."""

from __future__ import annotations

import re

from app.application.job_status_enrichment import enrich_job_for_http_response
from app.application.services.abono_dry_run import ABONO_ASIENTOS_NO_CUADRAN
from app.application.ui.amortization_operational_issues import (
    _AMORTIZATION_ITEM_MESSAGES,
    _ENGLISH_HINT,
    _contract_es,
    _credits_with,
    attach_operational_issues_to_amortization_result,
    build_operational_issues_from_amortization_result,
    dry_run_skipped_correction_items,
)


def _completed(job_type: str, result: dict) -> dict:
    return {
        "job_id": "j-amort",
        "type": job_type,
        "status": "completed",
        "result": result,
    }


def test_abono_group_produces_one_issue_per_blocked_group() -> None:
    result = {
        "outcome": "requires_correction",
        "can_apply": False,
        "blocking_abono_groups": [
            {
                "id_pago": "AB1",
                "creditos_seleccionados": ["264"],
                "reconciliation_status": "FAILED",
                "blocking_errors": [
                    {
                        "error_code": ABONO_ASIENTOS_NO_CUADRAN,
                        "message": "La suma híbrida no cuadra con el monto bancario",
                        "credito": "264",
                        "paths": [
                            "clientes/X/CREDITO # 264/ASIENTOS CONTABLES CRED 264"
                        ],
                    }
                ],
            }
        ],
    }

    issues = build_operational_issues_from_amortization_result(result)

    assert len(issues) == 1
    issue = issues[0]
    assert issue["stage"] == "amortization"
    assert issue["category"] == "correction_required"
    assert issue["severity"] == "business"
    assert issue["recoverable"] is True
    assert issue["issue_id"].startswith("amort-")
    assert "264" in issue["title"]
    assert "cuadra" in issue["user_message"].lower()
    assert issue["technical_reference"] == ABONO_ASIENTOS_NO_CUADRAN
    assert issue["links"]
    assert issue["links"][0]["rel"] == "asientos"
    assert "ASIENTOS" in issue["links"][0]["label"]


def test_dry_run_table_error_links_to_tabla_not_asientos() -> None:
    result = {
        "outcome": "requires_correction",
        "can_apply": False,
        "items": [
            {
                "id_pago": "P1",
                "credito": "258",
                "application_status": "ERROR",
                "error_code": "TABLE_PATH_NOT_FOUND",
                "asiento_pdf_path": "clientes/E/CREDITO # 258/ASIENTOS/asiento.pdf",
                "tabla_amortizacion_path": (
                    "clientes/E/CREDITO # 258/Tabla_Amortizacion_258.xlsx"
                ),
                "tabla_web_url": "https://example.com/tabla.xlsx",
            }
        ],
        "web_urls": {
            "clientes/E/CREDITO # 258/Tabla_Amortizacion_258.xlsx": (
                "https://example.com/tabla.xlsx"
            ),
        },
    }
    issues = build_operational_issues_from_amortization_result(result)
    assert len(issues) == 1
    links = issues[0]["links"]
    assert links
    assert links[0]["rel"] == "amortization_table"
    assert "tabla" in links[0]["label"].lower()


def test_mora_column_missing_issue_links_to_tabla_with_copy() -> None:
    result = {
        "outcome": "requires_correction",
        "can_apply": False,
        "items": [
            {
                "id_pago": "P9",
                "cliente": "EL CONDOR",
                "credito": "248",
                "application_status": "ERROR",
                "error_code": "MORA_COLUMN_MISSING",
                "tabla_amortizacion_path": "clientes/CONDOR/CREDITO# 248/tabla.xlsx",
                "asiento_pdf_path": "clientes/CONDOR/ASIENTOS/asiento.pdf",
                "valor_mora": 881_857,
                "payment_application": {"mora": 881_857},
                "tabla_web_url": "https://example.com/tabla.xlsx",
            }
        ],
        "web_urls": {
            "clientes/CONDOR/CREDITO# 248/tabla.xlsx": "https://example.com/tabla.xlsx",
        },
    }
    issues = build_operational_issues_from_amortization_result(result)
    assert len(issues) == 1
    issue = issues[0]
    assert issue["technical_reference"] == "MORA_COLUMN_MISSING"
    assert "mora" in issue["user_message"].lower()
    assert "MORA_COLUMN_MISSING" not in issue["user_message"]
    assert issue["value_found"] == "$881.857"
    assert issue["expected_values"] == ["Intereses de mora"]
    links = issue["links"]
    assert links
    assert links[0]["rel"] == "amortization_table"
    assert "tabla" in links[0]["label"].lower()


def test_attach_format_family_sets_reconsolidate_next_action() -> None:
    result = {
        "outcome": "requires_correction",
        "can_apply": False,
        "items": [
            {
                "id_pago": "P9",
                "credito": "264",
                "application_status": "ERROR",
                "error_code": "ACCOUNTING_PARSE_FAILED",
                "asiento_pdf_path": "clientes/E/asiento.pdf",
            }
        ],
    }
    out = attach_operational_issues_to_amortization_result(result)
    assert "reconsolid" in (out.get("next_action") or "").lower()
    assert "amortiz" in (out.get("next_action") or "").lower()


def test_format_family_issue_includes_asientos_link_with_web_url() -> None:
    folder = "clientes/E/CREDITO # 264/ASIENTOS CONTABLES CRED 264"
    result = {
        "outcome": "requires_correction",
        "can_apply": False,
        "items": [
            {
                "id_pago": "P9",
                "credito": "264",
                "application_status": "ERROR",
                "error_code": "ACCOUNTING_PARSE_FAILED",
                "asiento_pdf_path": f"{folder}/asiento_264.pdf",
                "asiento_pdf_etag": '"etag-1"',
                "asiento_pdf_size": 4096,
                "asiento_pdf_last_modified": "2026-08-01T10:00:00Z",
            }
        ],
        "folder_web_urls": {
            folder: "https://contoso.sharepoint.com/asientos-264",
        },
    }
    issues = build_operational_issues_from_amortization_result(result)
    assert len(issues) == 1
    links = issues[0]["links"]
    assert len(links) == 1
    assert links[0]["rel"] == "asientos"
    assert "ASIENTOS" in links[0]["label"]
    assert links[0]["web_url"] == "https://contoso.sharepoint.com/asientos-264"
    assert links[0]["path"] == folder
    loc = issues[0]["location"]
    assert loc["file_name"] == "asiento_264.pdf"
    assert loc["file_etag"] == '"etag-1"'
    assert loc["file_size"] == 4096
    assert loc["file_last_modified"] == "2026-08-01T10:00:00Z"


def test_bank_asientos_no_cuadran_is_silent_in_modal() -> None:
    """Descuadre banco vs asientos: advisory interno; modal silencioso (Apply OK)."""
    folder = "clientes/M/CREDITO # 248/ASIENTOS CONTABLES CRED 248"
    result = {
        "outcome": "requires_correction",
        "can_apply": True,
        "items": [
            {
                "id_pago": "P248",
                "cliente": "MADERPOL SAS",
                "credito": "248",
                "application_status": "WOULD_APPLY",
                "advisory_code": "BANK_ASIENTOS_NO_CUADRAN",
                "warnings": ["Banco y asientos no cuadran exactamente"],
                "asiento_pdf_path": f"{folder}/248-2.pdf",
            }
        ],
        "folder_web_urls": {
            folder: "https://contoso.sharepoint.com/asientos-248",
        },
    }
    issues = build_operational_issues_from_amortization_result(result)
    assert issues == []
    attached = attach_operational_issues_to_amortization_result(result)
    assert "operational_issues" not in attached
    assert attached.get("can_apply") is True


def test_pdf_changed_does_not_leak_bank_asientos_warning() -> None:
    """Regresión: PDF_CHANGED no debe mostrar el warning silencioso de descuadre."""
    folder = (
        "INFORMACION CREDITOS-CLIENTES/VIAS Y CONSTRUCCIONES DEL CARIBE -VICONCA/"
        "ASIENTOS CONTABLES CRED 200"
    )
    result = {
        "outcome": "failed",
        "can_apply": False,
        "items": [
            {
                "id_pago": "c701246a",
                "cliente": "VICONCA",
                "credito": "200",
                "application_status": "WOULD_ADOPT_EXISTING",
                "apply_status": "ERROR",
                "apply_error_code": "PDF_CHANGED_SAME_PATH",
                "advisory_code": "BANK_ASIENTOS_NO_CUADRAN",
                "warnings": [
                    "Monto banco (45000000.0) no cuadra con Σ valor_pagado_cliente "
                    "de asientos (10215624.0)."
                ],
                "asiento_pdf_path": f"{folder}/200-1.pdf",
            }
        ],
    }
    issues = build_operational_issues_from_amortization_result(result)
    assert len(issues) == 1
    msg = issues[0]["user_message"]
    assert "no cuadra" not in msg.lower()
    assert "PDF" in msg or "asiento" in msg.lower()
    assert issues[0]["technical_reference"] == "PDF_CHANGED_SAME_PATH"


def test_payoff_not_achieved_is_silent_in_modal() -> None:
    """PAGO TOTAL / cancelación sin saldo 0: advisory interno; modal silencioso (Apply OK)."""
    folder = "clientes/E/CREDITO # 258/ASIENTOS CONTABLES CRED 258"
    result = {
        "outcome": "ok",
        "can_apply": True,
        "items": [
            {
                "id_pago": "P258",
                "cliente": "EQUINORTE",
                "credito": "258",
                "application_status": "WOULD_APPLY",
                "advisory_code": "PAYOFF_NOT_ACHIEVED",
                "payoff_expected": True,
                "warnings": ["Asiento no deja saldo en cero"],
                "asiento_pdf_path": f"{folder}/258-1.pdf",
            }
        ],
        "folder_web_urls": {
            folder: "https://contoso.sharepoint.com/asientos-258",
        },
    }
    issues = build_operational_issues_from_amortization_result(result)
    assert issues == []
    attached = attach_operational_issues_to_amortization_result(result)
    assert "operational_issues" not in attached
    assert attached.get("can_apply") is True
    assert attached["items"][0].get("advisory_code") == "PAYOFF_NOT_ACHIEVED"


def test_dry_run_items_with_errors_when_no_abono_block() -> None:
    result = {
        "outcome": "requires_correction",
        "can_apply": False,
        "items": [
            {
                "id_pago": "P1",
                "credito": "258",
                "cliente": "EQUINORTE",
                "application_status": "ERROR",
                "error_code": "TABLE_PATH_NOT_FOUND",
                "asiento_pdf_path": "clientes/E/asiento.pdf",
            }
        ],
    }

    issues = build_operational_issues_from_amortization_result(result)

    assert len(issues) == 1
    assert issues[0]["issue_id"].startswith("amort-TABLE_PATH_NOT_FOUND-258")
    assert "258" in issues[0]["title"]
    assert "tabla" in issues[0]["user_message"].lower() or "amortización" in issues[0][
        "user_message"
    ].lower()
    assert issues[0]["location"]["credit"] == "258"
    assert issues[0]["location"]["payment_id"] == "P1"


def test_merge_incomplete_block_expands_incomplete_groups() -> None:
    result = {
        "outcome": "requires_correction",
        "can_apply": False,
        "merge_incomplete_block": {
            "error_code": "MERGE_GROUP_PENDING_INPUTS",
            "user_message": "La unión quedó incompleta.",
            "next_action": "Revise Asientos_Pendientes.",
            "incomplete_groups": [
                {"id_pago": "G1", "missing_creditos": ["100", "200"]},
                {"id_pago": "G2", "missing_creditos": ["300"]},
            ],
        },
    }

    issues = build_operational_issues_from_amortization_result(result)

    assert len(issues) == 2
    assert all(i["category"] == "correction_required" for i in issues)
    assert "100" in issues[0]["user_message"]
    assert "300" in issues[1]["user_message"]


def test_attach_sets_summary_and_operational_issues() -> None:
    result = {
        "outcome": "requires_correction",
        "can_apply": False,
        "user_message": "Mensaje largo específico del gate.",
        "items": [
            {
                "id_pago": "P1",
                "credito": "1",
                "application_status": "ERROR",
                "error_code": "ASIENTO_PATH_MISSING",
            },
            {
                "id_pago": "P2",
                "credito": "2",
                "application_status": "ERROR",
                "error_code": "PDF_TEXT_NOT_EXTRACTABLE",
            },
        ],
    }

    enriched = attach_operational_issues_to_amortization_result(result)

    assert len(enriched["operational_issues"]) == 2
    assert enriched["user_message"] == (
        "La amortización encontró 2 problema(s). No se modificó ninguna tabla."
    )
    assert "SharePoint" in enriched["next_action"]


def test_enrichment_uses_issue_count_summary_for_amortization_process() -> None:
    raw = _completed(
        "amortization_process",
        {
            "outcome": "requires_correction",
            "can_apply": False,
            "operational_issues": [
                {
                    "issue_id": "amort-x-1-0",
                    "stage": "amortization",
                    "category": "correction_required",
                    "severity": "business",
                    "recoverable": True,
                    "title": "T",
                    "user_message": "Detalle",
                    "links": [],
                },
                {
                    "issue_id": "amort-x-2-1",
                    "stage": "amortization",
                    "category": "correction_required",
                    "severity": "business",
                    "recoverable": True,
                    "title": "T2",
                    "user_message": "Detalle 2",
                    "links": [],
                },
            ],
            "user_message": "La amortización encontró 2 problema(s). No se modificó ninguna tabla.",
        },
    )

    out = enrich_job_for_http_response(raw)

    assert out["severity"] == "warning"
    assert "2 problema" in out["user_message"].lower()
    assert "ninguna tabla" in out["user_message"].lower()


def test_fallback_issue_when_requires_correction_without_details() -> None:
    result = {
        "outcome": "requires_correction",
        "can_apply": False,
        "error_code": "preflight_errors",
    }

    issues = build_operational_issues_from_amortization_result(result)

    assert len(issues) == 1
    assert issues[0]["technical_reference"] == "preflight_errors"
    assert "validación previa" in issues[0]["user_message"].lower()


def test_warnings_not_allowed_shows_one_card_per_affected_credit() -> None:
    def _item(credito: str, warnings: list[str], advisory: str | None = None) -> dict:
        return {
            "credito": credito,
            "cliente": "CLIENTE",
            "application_status": "WOULD_APPLY",
            "warnings": warnings,
            "advisory_code": advisory,
        }

    result = {
        "outcome": "requires_correction",
        "can_apply": False,
        "preflight_error_code": "preflight_warnings_not_allowed",
        "items": [
            _item("322", ["Advertencia desconocida"]),
            _item("247", ["Advertencia desconocida"]),
            _item("247", ["Advertencia desconocida"]),
            _item("40", ["Monto banco no cuadra"], advisory="BANK_ASIENTOS_NO_CUADRAN"),
            _item("203", []),
        ],
    }

    issues = build_operational_issues_from_amortization_result(result)

    assert [i["location"]["credit"] for i in issues] == ["322", "247"]
    assert {i["technical_reference"] for i in issues} == {"ITEM_WARNING_NOT_ALLOWED"}
    assert all("Advertencia desconocida" in i["user_message"] for i in issues)
    # Sin modelo de lote no se conoce el grupo: no se ofrece excluir.
    assert all(i["decision"]["excludable"] is False for i in issues)


def test_warnings_not_allowed_fallback_without_items_keeps_generic_message() -> None:
    result = {
        "outcome": "requires_correction",
        "can_apply": False,
        "preflight_error_code": "preflight_warnings_not_allowed",
    }

    issues = build_operational_issues_from_amortization_result(result)

    assert len(issues) == 1
    assert "Afecta a" not in issues[0]["user_message"]


def test_parse_failed_messages_are_plain_spanish_with_file_name() -> None:
    """Fallos de parseo de asiento: copy claro + archivo; sin jerga ni códigos."""
    cases = [
        (
            "PDF_TEXT_NOT_EXTRACTABLE",
            "solo imagen",
            "texto seleccionable",
        ),
        (
            "ACCOUNTING_PARSE_FAILED",
            "mismo renglón",
            "sola línea",
        ),
        (
            "MISSING_BANK_VALUE_BUT_HAS_ACCOUNTING_LINES",
            "falta la línea del recaudo",
            "renglón del banco",
        ),
    ]
    for code, msg_needle, next_needle in cases:
        result = {
            "outcome": "requires_correction",
            "can_apply": False,
            "items": [
                {
                    "id_pago": "P9",
                    "credito": "264",
                    "cliente": "EQUINORTE",
                    "application_status": "ERROR",
                    "error_code": code,
                    "asiento_pdf_path": (
                        "clientes/E/CREDITO # 264/ASIENTOS/"
                        "asiento_banco_bogota_credito-264.pdf"
                    ),
                    "warnings": [
                        "parser_mode=split_code_pypdf",
                        "códigos detectados: 13050501",
                    ],
                }
            ],
        }
        issues = build_operational_issues_from_amortization_result(result)
        assert len(issues) == 1, code
        issue = issues[0]
        um = issue["user_message"]
        assert msg_needle in um.lower(), (code, um)
        assert "Archivo afectado: asiento_banco_bogota_credito-264.pdf" in um
        assert issue["location"]["file_name"] == (
            "asiento_banco_bogota_credito-264.pdf"
        )
        assert issue["location"]["credit"] == "264"
        assert next_needle in (issue["next_action"] or "").lower()
        assert issue["technical_reference"] == code
        assert "reconsolid" in (issue["next_action"] or "").lower()
        # El operador no debe ver códigos ni jerga en el mensaje visible.
        for banned in (
            "ACCOUNTING_PARSE",
            "PDF_TEXT",
            "MISSING_BANK",
            "parser_mode",
            "detected_codes",
            "códigos detectados",
            "ReportLab",
            "regex",
        ):
            assert banned.lower() not in um.lower(), (code, banned, um)
            assert banned.lower() not in (issue["next_action"] or "").lower()


def test_abono_parse_error_prefers_mapped_spanish_over_exception_text() -> None:
    result = {
        "outcome": "requires_correction",
        "can_apply": False,
        "blocking_abono_groups": [
            {
                "id_pago": "AB2",
                "creditos_seleccionados": ["264"],
                "blocking_errors": [
                    {
                        "error_code": "ACCOUNTING_PARSE_FAILED",
                        "message": (
                            "No se encontró recaudo bancario "
                            "(BANK_BOGOTA_SUFFIX / BANK_BANCOLOMBIA_SUFFIX) "
                            "en el asiento. parser_mode=token_per_line"
                        ),
                        "credito": "264",
                        "paths": [
                            "clientes/X/CREDITO # 264/ASIENTOS/"
                            "asiento_malo.pdf"
                        ],
                    }
                ],
            }
        ],
    }

    issues = build_operational_issues_from_amortization_result(result)

    assert len(issues) == 1
    um = issues[0]["user_message"]
    assert "formato de asiento" in um.lower()
    assert "Archivo afectado: asiento_malo.pdf" in um
    assert "BANK_" not in um
    assert "parser_mode" not in um
    assert issues[0]["technical_reference"] == "ACCOUNTING_PARSE_FAILED"


def test_blocking_abono_and_pago_items_both_appear_in_operational_issues() -> None:
    """Abono bloqueado no debe ocultar errores de ítems PAGO en el modal."""
    result = {
        "outcome": "requires_correction",
        "can_apply": False,
        "blocking_abono_groups": [
            {
                "id_pago": "AB1",
                "creditos_seleccionados": ["231"],
                "reconciliation_status": "FAILED",
                "blocking_errors": [
                    {
                        "error_code": "ACCOUNTING_PARSE_FAILED",
                        "message": "formato inválido",
                        "credito": "231",
                        "paths": [
                            "clientes/G/CREDITO # 231/ASIENTOS/asiento_231.pdf"
                        ],
                    }
                ],
            }
        ],
        "items": [
            {
                "id_pago": "AB1",
                "credito": "231",
                "tipo_aplicacion": "ABONO",
                "application_status": "ERROR",
                "error_code": "ACCOUNTING_PARSE_FAILED",
                "asiento_pdf_path": (
                    "clientes/G/CREDITO # 231/ASIENTOS/asiento_231.pdf"
                ),
            },
            {
                "id_pago": "P264",
                "credito": "264",
                "tipo_aplicacion": "PAGO",
                "application_status": "ERROR",
                "error_code": "PDF_TEXT_NOT_EXTRACTABLE",
                "asiento_pdf_path": (
                    "clientes/E/CREDITO # 264/ASIENTOS/asiento_264.pdf"
                ),
            },
        ],
    }

    issues = build_operational_issues_from_amortization_result(result)

    assert len(issues) == 2
    refs = {i["technical_reference"] for i in issues}
    assert "ACCOUNTING_PARSE_FAILED" in refs
    assert "PDF_TEXT_NOT_EXTRACTABLE" in refs
    titles = " ".join(i["title"] for i in issues)
    assert "231" in titles
    assert "264" in titles


def test_partial_apply_error_code_builds_table_issue() -> None:
    result = {
        "outcome": "partial",
        "status": "partial",
        "apply_wrote_changes": True,
        "tables_uploaded": ["clientes/I/Tabla.xlsx"],
        "items": [
            {
                "id_pago": "P53",
                "credito": "53",
                "cliente": "INGEOROZCOL",
                "apply_status": "ERROR",
                "apply_error_code": "EXCEL_LOCKED",
                "tabla_amortizacion_path": "clientes/I/CREDITO # 53/Tabla.xlsx",
                "tabla_web_url": "https://example.com/tabla53.xlsx",
            }
        ],
        "web_urls": {
            "clientes/I/CREDITO # 53/Tabla.xlsx": "https://example.com/tabla53.xlsx",
        },
    }
    issues = build_operational_issues_from_amortization_result(result)
    assert len(issues) == 1
    assert issues[0]["technical_reference"] == "EXCEL_LOCKED"
    assert issues[0]["links"]
    assert issues[0]["links"][0]["rel"] == "amortization_table"
    assert issues[0]["links"][0]["web_url"] == "https://example.com/tabla53.xlsx"

    attached = attach_operational_issues_to_amortization_result(result)
    assert attached["operational_issues"]
    assert "tabla" in (attached.get("next_action") or "").lower() or attached.get(
        "next_action"
    )


def test_partial_apply_errors_list_builds_issue_without_items() -> None:
    result = {
        "outcome": "partial",
        "status": "partial",
        "apply_errors": [
            {
                "tabla_amortizacion_path": "clientes/X/Tabla_Amort.xlsx",
                "error_code": "TABLE_APPLY_FAILED",
                "message": "upload failed",
                "credito": "99",
            }
        ],
        "web_urls": {
            "clientes/X/Tabla_Amort.xlsx": "https://example.com/t99.xlsx",
        },
    }
    issues = build_operational_issues_from_amortization_result(result)
    assert len(issues) == 1
    assert issues[0]["technical_reference"] == "TABLE_APPLY_FAILED"
    assert issues[0]["category"] == "partial_result"
    assert issues[0]["links"][0]["web_url"] == "https://example.com/t99.xlsx"


def test_fallback_issue_uses_secretary_file_link() -> None:
    result = {
        "outcome": "requires_correction",
        "can_apply": False,
        "error_code": "preflight_errors",
        "secretary_file_path": "logs/Asientos_Pendientes.xlsx",
        "folder_web_urls": {
            "logs/Asientos_Pendientes.xlsx": "https://example.com/pendientes.xlsx",
        },
    }
    issues = build_operational_issues_from_amortization_result(result)
    assert len(issues) == 1
    assert "validación previa" in issues[0]["user_message"].lower()
    assert issues[0]["links"]
    assert issues[0]["links"][0]["rel"] == "secretary_file"
    assert issues[0]["links"][0]["web_url"] == "https://example.com/pendientes.xlsx"


def test_table_path_missing_falls_back_to_credit_folder() -> None:
    result = {
        "outcome": "requires_correction",
        "can_apply": False,
        "items": [
            {
                "id_pago": "P1",
                "credito": "258",
                "application_status": "ERROR",
                "error_code": "TABLE_PATH_NOT_FOUND",
                "asiento_pdf_path": (
                    "clientes/E/CREDITO # 258/ASIENTOS/asiento.pdf"
                ),
            }
        ],
        "folder_web_urls": {
            "clientes/E/CREDITO # 258": "https://example.com/cred-258",
        },
    }
    issues = build_operational_issues_from_amortization_result(result)
    assert len(issues) == 1
    rels = {link["rel"] for link in issues[0]["links"]}
    assert "credit_folder" in rels
    assert any(link.get("web_url") for link in issues[0]["links"])


def test_merge_incomplete_uses_secretary_when_no_item_paths() -> None:
    result = {
        "outcome": "requires_correction",
        "can_apply": False,
        "secretary_file_path": "logs/Asientos_Pendientes.xlsx",
        "folder_web_urls": {
            "logs/Asientos_Pendientes.xlsx": "https://example.com/pendientes.xlsx",
        },
        "merge_incomplete_block": {
            "error_code": "MERGE_GROUP_PENDING_INPUTS",
            "user_message": "La unión quedó incompleta.",
            "next_action": "Revise Asientos_Pendientes.",
            "incomplete_groups": [
                {"id_pago": "G1", "missing_creditos": ["100"]},
            ],
        },
    }
    issues = build_operational_issues_from_amortization_result(result)
    assert len(issues) == 1
    assert issues[0]["links"]
    assert issues[0]["links"][0]["rel"] == "secretary_file"
    assert issues[0]["links"][0]["web_url"] == "https://example.com/pendientes.xlsx"


def test_sheet_not_found_names_missing_required_columns() -> None:
    result = {
        "outcome": "requires_correction",
        "can_apply": False,
        "items": [
            {
                "id_pago": "P259",
                "credito": "259",
                "cliente": "VICTOR SOTO",
                "application_status": "ERROR",
                "error_code": "AMORTIZATION_SHEET_NOT_FOUND",
                "tabla_amortizacion_path": "clientes/V/Tabla de amortizacion VICTOR SOTO.xlsx",
                "missing_required_headers": ["fecha_pago"],
                "found_headers": [
                    "dia",
                    "mes",
                    "anio",
                    "valor_intereses",
                    "abono_k",
                    "valor_pagado_cliente",
                ],
                "tabla_web_url": "https://contoso.sharepoint.com/victor-tabla",
            }
        ],
        "web_urls": {
            "clientes/V/Tabla de amortizacion VICTOR SOTO.xlsx": (
                "https://contoso.sharepoint.com/victor-tabla"
            ),
        },
    }
    issues = build_operational_issues_from_amortization_result(result)
    assert len(issues) == 1
    issue = issues[0]
    assert issue["technical_reference"] == "AMORTIZATION_SHEET_NOT_FOUND"
    assert "no tiene la columna «Fecha pago»" in issue["user_message"]
    assert "hoja o estructura esperada" not in issue["user_message"].lower()
    assert issue["expected_values"] == ["Fecha pago"]
    assert "Abra la tabla" not in (issue.get("next_action") or "")
    assert "plantilla" in (issue.get("next_action") or "").lower()
    assert issue["location"]["file_name"] == "Tabla de amortizacion VICTOR SOTO.xlsx"
    assert any(link.get("rel") == "amortization_table" for link in issue["links"])


def test_sheet_not_found_without_missing_list_keeps_safe_generic() -> None:
    result = {
        "outcome": "requires_correction",
        "can_apply": False,
        "items": [
            {
                "id_pago": "P1",
                "credito": "1",
                "application_status": "ERROR",
                "error_code": "AMORTIZATION_SHEET_NOT_FOUND",
                "tabla_amortizacion_path": "clientes/X/tabla.xlsx",
            }
        ],
    }
    issues = build_operational_issues_from_amortization_result(result)
    assert len(issues) == 1
    assert "columnas obligatorias" in issues[0]["user_message"].lower()
    assert issues[0]["expected_values"] == []


def test_abono_growth_blocked_shows_detected_value_and_table_link() -> None:
    """Abono bloqueado por celda interferente: mensaje genérico + valor real + CTA tabla."""
    tabla = (
        "INFORMACION CREDITOS-CLIENTES/03 COMWARE PRUEBAS- INFORMACION CREDITOS "
        "CLIENTES/ICOEQUIPOS SAS/Tabla de amortizacion ICOEQUIPOS.xlsx"
    )
    result = {
        "outcome": "requires_correction",
        "can_apply": False,
        "blocking_abono_groups": [
            {
                "id_pago": "2c91424b-5bfe-4d6e-a8cc-6409eda6d7ea",
                "creditos_seleccionados": ["256"],
                "reconciliation_status": "PASSED",
                "schedule_resolution_status": "NOT_REQUIRED",
                "blocking_errors": [
                    {
                        "error_code": "APPLICATION_GROWTH_BLOCKED",
                        "message": "celda que interfiere",
                        "credito": "256",
                        "paths": [tabla],
                        "tabla_amortizacion_path": tabla,
                        "growth_block_row": 14,
                        "growth_block_value": "FACTURACION",
                        "next_action": (
                            "Abra la tabla de amortización, quite o mueva ese contenido."
                        ),
                    }
                ],
            }
        ],
        "web_urls": {tabla: "https://example.com/tabla-icoequipos.xlsx"},
    }
    issues = build_operational_issues_from_amortization_result(result)
    assert len(issues) == 1
    issue = issues[0]
    assert issue["technical_reference"] == "APPLICATION_GROWTH_BLOCKED"
    assert "impiden llenar" in issue["user_message"].lower()
    assert "basura" not in issue["user_message"].lower()
    assert "por ejemplo facturacion" not in issue["user_message"].lower()
    # Evidencia estructurada (rango de filas, no el texto sucio de la celda).
    assert "FACTURACION" not in issue["user_message"]
    assert "Fila 14" not in issue["user_message"]
    assert issue["value_found"] == "Fila 14"
    assert issue["location"]["row"] == 14
    assert "documentales o de cuadre" not in issue["user_message"].lower()
    assert "Tabla de amortización" in issue["title"]
    assert "256" in issue["title"]
    assert issue["location"]["file_name"] == "Tabla de amortizacion ICOEQUIPOS.xlsx"
    assert issue["links"]
    assert issue["links"][0]["rel"] == "amortization_table"
    assert "tabla" in issue["links"][0]["label"].lower()
    assert issue["links"][0]["web_url"] == "https://example.com/tabla-icoequipos.xlsx"


def test_abono_growth_blocked_shows_row_range_not_cell_junk() -> None:
    """La evidencia es el rango de filas; no se nombra el texto sucio de la celda."""
    result = {
        "outcome": "requires_correction",
        "can_apply": False,
        "blocking_abono_groups": [
            {
                "id_pago": "AB1",
                "creditos_seleccionados": ["99"],
                "reconciliation_status": "PASSED",
                "blocking_errors": [
                    {
                        "error_code": "APPLICATION_GROWTH_BLOCKED",
                        "credito": "99",
                        "paths": ["clientes/X/Tabla.xlsx"],
                        "tabla_amortizacion_path": "clientes/X/Tabla.xlsx",
                        "growth_block_row": 20,
                        "growth_block_value": "NOTAS INTERNAS",
                    }
                ],
            }
        ],
    }
    issues = build_operational_issues_from_amortization_result(result)
    assert len(issues) == 1
    um = issues[0]["user_message"]
    assert "NOTAS INTERNAS" not in um
    assert issues[0]["value_found"] == "Fila 20"
    assert issues[0]["location"]["row"] == 20
    assert "impiden llenar" in um.lower()
    assert "basura" not in um.lower()
    assert "FACTURACION" not in um


def test_table_path_not_found_title_is_tabla_not_documento() -> None:
    result = {
        "outcome": "requires_correction",
        "can_apply": False,
        "items": [
            {
                "id_pago": "P1",
                "credito": "258",
                "application_status": "ERROR",
                "error_code": "TABLE_PATH_NOT_FOUND",
                "asiento_pdf_path": "clientes/E/CREDITO # 258/ASIENTOS/asiento.pdf",
            }
        ],
    }
    issues = build_operational_issues_from_amortization_result(result)
    assert len(issues) == 1
    title = issues[0]["title"]
    assert "Tabla de amortización" in title
    assert "Documento contable" not in title
    assert "258" in title
    assert "archivo afectado" not in issues[0]["user_message"].lower()


def test_two_table_download_failed_same_credit_merge_to_one_issue() -> None:
    folder = "clientes/M/CREDITO # 248/ASIENTOS CONTABLES CRED 248"
    credit_root = "clientes/M/CREDITO # 248"
    result = {
        "outcome": "requires_correction",
        "can_apply": False,
        "items": [
            {
                "id_pago": "P1",
                "credito": "248",
                "cliente": "MADERPOL SAS",
                "application_status": "ERROR",
                "error_code": "TABLE_DOWNLOAD_FAILED",
                "asiento_pdf_path": f"{folder}/248-1.pdf",
                "tabla_amortizacion_path": f"{credit_root}/Tabla de amortizacion MADERPOL.xlsx",
            },
            {
                "id_pago": "P2",
                "credito": "248",
                "cliente": "MADERPOL SAS",
                "application_status": "ERROR",
                "error_code": "TABLE_DOWNLOAD_FAILED",
                "asiento_pdf_path": f"{folder}/CRED 248-2.pdf",
                "tabla_amortizacion_path": f"{credit_root}/Tabla de amortizacion MADERPOL.xlsx",
            },
        ],
        "folder_web_urls": {
            credit_root: "https://contoso.sharepoint.com/maderpol-248",
        },
    }
    issues = build_operational_issues_from_amortization_result(result)
    assert len(issues) == 1
    issue = issues[0]
    assert issue["issue_id"] == "amort-TABLE_DOWNLOAD_FAILED-248-0"
    assert "248" in issue["title"]
    assert "Tabla de amortización" in issue["title"]
    assert "248-1.pdf" not in issue["user_message"]
    assert "CRED 248-2.pdf" not in issue["user_message"]
    assert issue["location"]["file_name"] == "Tabla de amortizacion MADERPOL.xlsx"
    assert issue["links"]
    assert issue["links"][0]["rel"] == "credit_folder"


def test_fail_closed_can_apply_false_still_projects_all_table_errors() -> None:
    """Fail-closed: can_apply=false; UI proyecta todos los errores de tabla."""
    folder_248 = "clientes/M/CREDITO # 248/ASIENTOS CONTABLES CRED 248"
    folder_99 = "clientes/O/CREDITO # 99/ASIENTOS CONTABLES CRED 99"
    dry_run = {
        "can_apply": False,
        "items": [
            {
                "id_pago": "P248a",
                "credito": "248",
                "application_status": "ERROR",
                "error_code": "TABLE_DOWNLOAD_FAILED",
                "asiento_pdf_path": f"{folder_248}/248-1.pdf",
            },
            {
                "id_pago": "P248b",
                "credito": "248",
                "application_status": "ERROR",
                "error_code": "TABLE_DOWNLOAD_FAILED",
                "asiento_pdf_path": f"{folder_248}/CRED 248-2.pdf",
            },
            {
                "id_pago": "P99",
                "credito": "99",
                "application_status": "WOULD_APPLY",
                "asiento_pdf_path": f"{folder_99}/99-1.pdf",
            },
        ],
    }
    skipped = dry_run_skipped_correction_items(dry_run)
    assert len(skipped) == 2
    reject_result = {
        "outcome": "requires_correction",
        "status": "blocked",
        "can_apply": False,
        "apply_wrote_changes": False,
        "items": list(dry_run["items"]),
        "preflight": dry_run,
    }
    enriched = attach_operational_issues_to_amortization_result(reject_result)
    issues = enriched.get("operational_issues") or []
    assert len(issues) == 1
    assert issues[0]["technical_reference"] == "TABLE_DOWNLOAD_FAILED"
    assert "248" in issues[0]["title"]
    assert "problema(s)" in str(enriched.get("user_message") or "").lower()
    assert "no se modificó ninguna tabla" in str(enriched.get("user_message") or "").lower()


def test_fail_closed_rejection_surfaces_all_distinct_credit_errors() -> None:
    """Varios créditos con error distinto → todos en operational_issues de una vez."""
    result = {
        "outcome": "requires_correction",
        "status": "blocked",
        "can_apply": False,
        "apply_wrote_changes": False,
        "items": [
            {
                "id_pago": "P86",
                "credito": "86",
                "application_status": "ERROR",
                "error_code": "AMBIGUOUS_AMORTIZATION_HEADERS",
                "tabla_amortizacion_path": "clientes/C/CREDITO # 86/Tabla.xlsx",
            },
            {
                "id_pago": "P97",
                "credito": "97",
                "application_status": "ERROR",
                "error_code": "AMBIGUOUS_AMORTIZATION_HEADERS",
                "tabla_amortizacion_path": "clientes/I/CREDITO # 97/Tabla.xlsx",
            },
            {
                "id_pago": "P93",
                "credito": "93",
                "application_status": "ERROR",
                "error_code": "AMORTIZATION_HEADERS_SPLIT_ACROSS_ROWS",
                "tabla_amortizacion_path": "clientes/I/CREDITO # 93/Tabla.xlsx",
            },
            {
                "id_pago": "P212",
                "credito": "212",
                "application_status": "WOULD_APPLY",
                "tabla_amortizacion_path": "clientes/V/CREDITO # 212/Tabla.xlsx",
            },
        ],
    }
    enriched = attach_operational_issues_to_amortization_result(result)
    issues = enriched.get("operational_issues") or []
    credits = {str((i.get("location") or {}).get("credit") or "") for i in issues}
    codes = {str(i.get("technical_reference") or "") for i in issues}
    assert credits == {"86", "97", "93"}
    assert "AMBIGUOUS_AMORTIZATION_HEADERS" in codes
    assert "AMORTIZATION_HEADERS_SPLIT_ACROSS_ROWS" in codes
    assert len(issues) == 3
    msg = str(enriched.get("user_message") or "").lower()
    assert "3 problema" in msg
    assert "no se modificó ninguna tabla" in msg


def test_two_table_path_missing_same_credit_merge_to_one_issue() -> None:
    result = {
        "outcome": "requires_correction",
        "can_apply": False,
        "items": [
            {
                "id_pago": "P1",
                "credito": "258",
                "application_status": "ERROR",
                "error_code": "TABLE_PATH_NOT_FOUND",
                "asiento_pdf_path": "clientes/E/CREDITO # 258/ASIENTOS/a1.pdf",
            },
            {
                "id_pago": "P2",
                "credito": "258",
                "application_status": "ERROR",
                "error_code": "TABLE_PATH_NOT_FOUND",
                "asiento_pdf_path": "clientes/E/CREDITO # 258/ASIENTOS/a2.pdf",
            },
        ],
    }
    issues = build_operational_issues_from_amortization_result(result)
    assert len(issues) == 1
    assert issues[0]["issue_id"] == "amort-TABLE_PATH_NOT_FOUND-258-0"
    assert issues[0]["technical_reference"] == "TABLE_PATH_NOT_FOUND"


def test_format_family_same_credit_two_pdfs_stay_separate() -> None:
    folder = "clientes/E/CREDITO # 264/ASIENTOS CONTABLES CRED 264"
    result = {
        "outcome": "requires_correction",
        "can_apply": False,
        "items": [
            {
                "id_pago": "P1",
                "credito": "264",
                "application_status": "ERROR",
                "error_code": "ACCOUNTING_PARSE_FAILED",
                "asiento_pdf_path": f"{folder}/asiento_1.pdf",
            },
            {
                "id_pago": "P2",
                "credito": "264",
                "application_status": "ERROR",
                "error_code": "ACCOUNTING_PARSE_FAILED",
                "asiento_pdf_path": f"{folder}/asiento_2.pdf",
            },
        ],
    }
    issues = build_operational_issues_from_amortization_result(result)
    assert len(issues) == 2
    files = {i["location"]["file_name"] for i in issues}
    assert files == {"asiento_1.pdf", "asiento_2.pdf"}


def test_abono_group_empty_blocking_enriched_from_item() -> None:
    """Si el grupo no trae blocking_errors, se recupera el detalle desde el ítem."""
    tabla = "clientes/I/Tabla de amortizacion ICOEQUIPOS.xlsx"
    result = {
        "outcome": "requires_correction",
        "can_apply": False,
        "blocking_abono_groups": [
            {
                "id_pago": "AB256",
                "creditos_seleccionados": ["256"],
                "reconciliation_status": "PASSED",
                "schedule_resolution_status": "NOT_REQUIRED",
                "blocking_errors": [],
            }
        ],
        "items": [
            {
                "id_pago": "AB256",
                "credito": "256",
                "tipo_aplicacion": "ABONO",
                "application_status": "ERROR",
                "error_code": "APPLICATION_GROWTH_BLOCKED",
                "tabla_amortizacion_path": tabla,
                "growth_block_row": 14,
                "growth_block_value": "FACTURACION",
                "user_message": "bloqueado por celda interferente",
                "asiento_pdf_path": "clientes/I/ASIENTOS/CRED 256-1.pdf",
            }
        ],
        "web_urls": {tabla: "https://example.com/tabla.xlsx"},
    }
    issues = build_operational_issues_from_amortization_result(result)
    assert len(issues) == 1
    assert issues[0]["technical_reference"] == "APPLICATION_GROWTH_BLOCKED"
    assert issues[0]["value_found"] == "Fila 14"
    assert "FACTURACION" not in issues[0]["user_message"]
    assert "impiden llenar" in issues[0]["user_message"].lower()
    assert "basura" not in issues[0]["user_message"].lower()
    assert issues[0]["links"][0]["rel"] == "amortization_table"


def test_error_without_code_with_tabla_uses_table_fallback() -> None:
    """Sin error_code pero con tabla → copy/título/link de tabla, no documento contable."""
    tabla = "clientes/N/NACHONAL/tabla de amortizacion NACHONAL.xlsx"
    result = {
        "outcome": "requires_correction",
        "can_apply": False,
        "items": [
            {
                "id_pago": "P93",
                "credito": "93",
                "application_status": "ERROR",
                "error_code": None,
                "tabla_amortizacion_path": tabla,
                "asiento_pdf_path": "clientes/N/NACHONAL/ASIENTOS/93.pdf",
            }
        ],
        "web_urls": {tabla: "https://example.com/tabla-93.xlsx"},
    }
    issues = build_operational_issues_from_amortization_result(result)
    assert len(issues) == 1
    issue = issues[0]
    assert "Tabla de amortización" in issue["title"]
    assert "Documento contable" not in issue["title"]
    assert "tabla de amortización" in issue["user_message"].lower()
    assert "inconveniente técnico" not in issue["user_message"].lower()
    assert str(issue.get("technical_reference") or "").upper() == "PREFLIGHT_TABLE_ITEM_ERROR"
    assert issue["links"][0]["rel"] == "amortization_table"
    assert issue["links"][0]["web_url"] == "https://example.com/tabla-93.xlsx"


def test_error_without_code_without_tabla_uses_secretary_not_asiento() -> None:
    folder = "clientes/E/CREDITO # 258/ASIENTOS"
    result = {
        "outcome": "requires_correction",
        "can_apply": False,
        "secretary_file_path": "logs/Asientos_Pendientes.xlsx",
        "items": [
            {
                "id_pago": "P1",
                "credito": "258",
                "application_status": "ERROR",
                "error_code": None,
                "asiento_pdf_path": f"{folder}/asiento.pdf",
            }
        ],
        "folder_web_urls": {
            folder: "https://example.com/asientos-258",
            "logs/Asientos_Pendientes.xlsx": "https://example.com/pendientes.xlsx",
        },
    }
    issues = build_operational_issues_from_amortization_result(result)
    assert len(issues) == 1
    issue = issues[0]
    assert "Documento contable" in issue["title"]
    assert "documento contable" in issue["user_message"].lower()
    assert str(issue.get("technical_reference") or "").upper() == "PREFLIGHT_ITEM_ERROR"
    assert issue["links"][0]["rel"] == "secretary_file"
    assert issue["links"][0]["web_url"] == "https://example.com/pendientes.xlsx"
    assert all(link["rel"] != "asientos" for link in issue["links"])
    assert "asiento.pdf" not in (issue.get("user_message") or "").lower()


def test_multi_asiento_pdf_unexpanded_has_specific_copy_and_asientos_link() -> None:
    folder = "clientes/E/CREDITO # 265/ASIENTOS"
    result = {
        "outcome": "requires_correction",
        "can_apply": False,
        "items": [
            {
                "id_pago": "P1",
                "credito": "265",
                "application_status": "ERROR",
                "error_code": "MULTI_ASIENTO_PDF_UNEXPANDED",
                "asiento_pdf_path": f"{folder}/multi.pdf",
            }
        ],
        "folder_web_urls": {folder: "https://example.com/asientos-265"},
    }
    issues = build_operational_issues_from_amortization_result(result)
    assert len(issues) == 1
    issue = issues[0]
    assert "varios asientos" in issue["user_message"].lower()
    assert "Documento contable" in issue["title"]
    assert issue["links"][0]["rel"] == "asientos"


def test_row_not_planned_has_specific_copy_and_table_link() -> None:
    tabla = "clientes/X/Tabla.xlsx"
    result = {
        "outcome": "requires_correction",
        "can_apply": False,
        "items": [
            {
                "id_pago": "P1",
                "credito": "99",
                "application_status": "ERROR",
                "apply_error_code": "ROW_NOT_PLANNED",
                "tabla_amortizacion_path": tabla,
                "asiento_pdf_path": "clientes/X/ASIENTOS/a.pdf",
            }
        ],
        "web_urls": {tabla: "https://example.com/tabla-99.xlsx"},
    }
    issues = build_operational_issues_from_amortization_result(result)
    assert len(issues) == 1
    issue = issues[0]
    assert "fila de aplicación planificada" in issue["user_message"].lower()
    assert "Tabla de amortización" in issue["title"]
    assert issue["links"][0]["rel"] == "amortization_table"


def test_growth_blocked_value_found_uses_row_range() -> None:
    tabla = "clientes/N/tabla.xlsx"
    result = {
        "outcome": "requires_correction",
        "can_apply": False,
        "items": [
            {
                "id_pago": "P295",
                "credito": "295",
                "application_status": "ERROR",
                "error_code": "APPLICATION_GROWTH_BLOCKED",
                "tabla_amortizacion_path": tabla,
                "growth_block_row": 5,
                "growth_block_end_row": 8,
                "growth_block_value": "Filas 5 a 8",
            }
        ],
        "web_urls": {tabla: "https://example.com/tabla-295.xlsx"},
    }
    issues = build_operational_issues_from_amortization_result(result)
    assert len(issues) == 1
    issue = issues[0]
    assert issue["value_found"] == "Filas 5 a 8"
    assert issue["location"]["row"] == 5
    assert "FACTURACION" not in issue["user_message"]
    assert "Tabla de amortización" in issue["title"]
    assert issue["links"][0]["rel"] == "amortization_table"


def test_post_upload_adopt_empty_remaps_to_clear_table_copy() -> None:
    """Verify genérico con «adoptada…APLICADO» no debe engañar al operador."""
    tabla = "clientes/N/BENAIA/tabla.xlsx"
    result = {
        "outcome": "partial",
        "can_apply": False,
        "items": [
            {
                "id_pago": "P295",
                "credito": "295",
                "cliente": "BENAIA",
                "application_status": "ALREADY_APPLIED",
                "apply_status": "ERROR",
                "apply_error_code": "POST_UPLOAD_VERIFICATION_FAILED",
                "apply_message": (
                    "id|295|path||: fila 7 adoptada esperada, estado=APLICADO"
                ),
                "tabla_amortizacion_path": tabla,
                "asiento_pdf_path": "clientes/N/ASIENTOS/295.pdf",
                "application_row": 7,
            }
        ],
        "web_urls": {tabla: "https://example.com/tabla-295.xlsx"},
    }
    issues = build_operational_issues_from_amortization_result(result)
    assert len(issues) == 1
    issue = issues[0]
    assert issue["technical_reference"] == "ADOPT_TARGET_EMPTY"
    assert "Tabla de amortización" in issue["title"]
    um = issue["user_message"].lower()
    assert "verificación posterior" not in um
    assert "vacía" in um or "impiden llenar" in um or "incompleta" in um
    assert issue["links"][0]["rel"] == "amortization_table"
    assert all(link["rel"] != "asientos" for link in issue["links"])


def test_post_upload_verification_failed_links_table_not_asiento() -> None:
    tabla = "clientes/N/tabla.xlsx"
    folder = "clientes/N/ASIENTOS"
    result = {
        "outcome": "partial",
        "can_apply": False,
        "items": [
            {
                "id_pago": "P295",
                "credito": "295",
                "apply_status": "ERROR",
                "apply_error_code": "POST_UPLOAD_VERIFICATION_FAILED",
                "tabla_amortizacion_path": tabla,
                "asiento_pdf_path": f"{folder}/295.pdf",
            }
        ],
        "web_urls": {tabla: "https://example.com/tabla-295.xlsx"},
        "folder_web_urls": {folder: "https://example.com/asientos-295"},
    }
    issues = build_operational_issues_from_amortization_result(result)
    assert len(issues) == 1
    issue = issues[0]
    assert issue["technical_reference"] == "POST_UPLOAD_VERIFICATION_FAILED"
    assert "Tabla de amortización" in issue["title"]
    assert "Documento contable" not in issue["title"]
    assert "verificación posterior" in issue["user_message"].lower()
    assert issue["links"][0]["rel"] == "amortization_table"
    assert issue["links"][0]["web_url"] == "https://example.com/tabla-295.xlsx"
    assert all(link["rel"] != "asientos" for link in issue["links"])


def test_unknown_error_code_links_secretary_not_asiento_pdf() -> None:
    result = {
        "outcome": "requires_correction",
        "can_apply": False,
        "secretary_file_path": "logs/Asientos_Pendientes.xlsx",
        "items": [
            {
                "id_pago": "P1",
                "credito": "295",
                "application_status": "ERROR",
                "error_code": "SOME_WEIRD_UNDOCUMENTED_CODE",
                "asiento_pdf_path": "clientes/N/ASIENTOS/295.pdf",
                "tabla_amortizacion_path": "clientes/N/tabla.xlsx",
            }
        ],
        "web_urls": {
            "clientes/N/tabla.xlsx": "https://example.com/tabla.xlsx",
            "clientes/N/ASIENTOS/295.pdf": "https://example.com/295.pdf",
        },
        "folder_web_urls": {
            "logs/Asientos_Pendientes.xlsx": "https://example.com/pendientes.xlsx",
        },
    }
    issues = build_operational_issues_from_amortization_result(result)
    assert len(issues) == 1
    issue = issues[0]
    assert issue["links"]
    assert issue["links"][0]["rel"] == "secretary_file"
    assert all(link["rel"] != "asientos" for link in issue["links"])
    assert all("295.pdf" not in (link.get("path") or "") for link in issue["links"])


# ─── Lenguaje de operador: sin códigos, sin inglés, contracciones ───────────

_UPPER_SNAKE = re.compile(r"\b[A-Z]{2,}(?:_[A-Z0-9]+)+\b")


def _assert_operator_text(text: str | None) -> None:
    body = text or ""
    assert not _UPPER_SNAKE.search(body), body
    assert not _ENGLISH_HINT.search(body), body
    assert not re.search(r"\b(de|a) el\b", body, re.IGNORECASE), body


def test_catalog_messages_have_no_codes_nor_english() -> None:
    for code, (user, nxt) in _AMORTIZATION_ITEM_MESSAGES.items():
        assert user, code
        _assert_operator_text(user)
        _assert_operator_text(nxt)


def _error_item(code: str, **extra) -> dict:
    return {
        "id_pago": "P1",
        "credito": "36",
        "cliente": "CLIENTE PRUEBA",
        "application_status": "ERROR",
        "error_code": code,
        "tabla_amortizacion_path": "clientes/C/CREDITO# 36/tabla.xlsx",
        **extra,
    }


def _issues_for(*items: dict) -> list:
    return build_operational_issues_from_amortization_result(
        {"outcome": "requires_correction", "can_apply": False, "items": list(items)}
    )


def test_due_date_row_not_found_names_the_date_and_action() -> None:
    issues = _issues_for(
        _error_item("DUE_DATE_ROW_NOT_FOUND", fecha_limite_pago="2026-09-30")
    )
    assert len(issues) == 1
    issue = issues[0]
    assert "La tabla no tiene una cuota con fecha 30/09/2026" in issue["user_message"]
    assert "cuota del 30/09/2026" in issue["next_action"]
    assert "excluya el crédito" in issue["next_action"]
    assert issue["expected_values"] == ["Cuota con fecha 30/09/2026"]
    _assert_operator_text(issue["user_message"])
    _assert_operator_text(issue["next_action"])


def test_due_date_row_two_credits_keep_their_own_dates() -> None:
    a = _error_item("DUE_DATE_ROW_NOT_FOUND", fecha_limite_pago="2026-09-30")
    b = {**_error_item("DUE_DATE_ROW_NOT_FOUND", fecha_limite_pago="2026-10-15"),
         "credito": "40", "id_pago": "P2"}
    issues = _issues_for(a, b)
    by_credit = {i["location"]["credit"]: i["user_message"] for i in issues}
    assert "30/09/2026" in by_credit["36"]
    assert "15/10/2026" in by_credit["40"]


def test_fecha_limite_not_found_points_to_historico_not_table() -> None:
    issues = _issues_for(_error_item("FECHA_LIMITE_NOT_FOUND"))
    assert len(issues) == 1
    issue = issues[0]
    assert issue["title"].startswith("Histórico")
    assert "histórico" in issue["user_message"].lower()
    assert "fecha límite de pago" in issue["user_message"]
    assert "histórico" in issue["next_action"].lower()
    _assert_operator_text(issue["user_message"])


def test_sheet_not_found_names_expected_and_found_column_credit_36() -> None:
    issues = _issues_for(
        _error_item(
            "AMORTIZATION_SHEET_NOT_FOUND",
            missing_required_headers=["valor_intereses"],
            header_labels=[
                "dia", "mes", "año", "Fecha pago", "Intereses ",
                "Intereses de mora", "Abono a K", "Valor pagado cliente",
            ],
        )
    )
    assert len(issues) == 1
    issue = issues[0]
    assert "«Valor intereses»" in issue["user_message"]
    assert "en su lugar aparece «Intereses»" in issue["user_message"]
    assert "Cambie el encabezado «Intereses» por «Valor intereses»" in issue["next_action"]
    assert issue["value_found"] == "Intereses"
    assert issue["expected_values"] == ["Valor intereses"]


def test_sheet_not_found_several_columns_lists_each_one() -> None:
    issues = _issues_for(
        _error_item(
            "AMORTIZATION_SHEET_NOT_FOUND",
            missing_required_headers=["valor_intereses", "abono_k"],
            header_labels=["dia", "mes", "año", "Fecha pago", "Intereses", "Abono capital"],
        )
    )
    msg = issues[0]["user_message"]
    assert "«Valor intereses» (aparece «Intereses»)" in msg
    assert "«Abono a K» (aparece «Abono capital»)" in msg


def test_new_catalog_codes_render_operator_copy() -> None:
    for code in (
        "TABLE_HEADERS_NOT_FOUND",
        "BANK_MONTO_BANCO_MISSING",
        "ABONO_ASIENTO_TOTAL_NOT_FOUND",
    ):
        issues = _issues_for(_error_item(code))
        assert len(issues) == 1, code
        issue = issues[0]
        assert issue["user_message"] != "Hay un problema que impide completar la amortización."
        _assert_operator_text(issue["user_message"])
        _assert_operator_text(issue["next_action"])


def test_abono_total_not_found_asks_to_reconsolidate() -> None:
    issue = _issues_for(_error_item("ABONO_ASIENTO_TOTAL_NOT_FOUND"))[0]
    assert issue.get("reconsolidate") is True
    assert "reconsolide" in issue["next_action"]


def test_dry_run_blocked_and_unexpected_error_fallbacks_are_spanish() -> None:
    for code in ("DRY_RUN_BLOCKED", "AMORTIZATION_UNEXPECTED_ERROR"):
        issues = build_operational_issues_from_amortization_result(
            {
                "outcome": "requires_correction",
                "can_apply": False,
                "error_code": code,
                "user_message": "Unexpected failure: object has no attribute 'x'",
            }
        )
        assert len(issues) == 1, code
        assert issues[0]["user_message"] == _AMORTIZATION_ITEM_MESSAGES[code][0]
        _assert_operator_text(issues[0]["user_message"])
        _assert_operator_text(issues[0]["next_action"])


def test_english_exception_text_is_never_shown() -> None:
    for outcome in ("requires_correction", "partial"):
        issues = build_operational_issues_from_amortization_result(
            {
                "outcome": outcome,
                "can_apply": False,
                "error_code": "SomethingWeird",
                "user_message": "The table could not be opened",
            }
        )
        assert len(issues) == 1, outcome
        assert "table" not in issues[0]["user_message"].lower()
        _assert_operator_text(issues[0]["user_message"])


def test_contractions_in_affected_credits() -> None:
    result = {
        "outcome": "requires_correction",
        "can_apply": False,
        "preflight_error_code": "preflight_warnings_not_allowed",
        "preflight": {
            "items": [
                {
                    "credito": "5",
                    "application_status": "WOULD_APPLY",
                    "warnings": ["Advertencia desconocida"],
                }
            ]
        },
    }
    issues = build_operational_issues_from_amortization_result(result)
    for issue in issues:
        _assert_operator_text(issue["user_message"])
        assert "a el" not in issue["user_message"]


def test_contraction_helper() -> None:
    assert _contract_es("Afecta a el crédito 5 de el cliente") == "Afecta al crédito 5 del cliente"
    assert _contract_es("Los asientos de EL CONDOR") == "Los asientos de EL CONDOR"
    assert _credits_with("de", ["5"]) == "del crédito 5"
    assert _credits_with("a", ["5"]) == "al crédito 5"
    assert _credits_with("de", ["5", "7"]).startswith("de los créditos")

