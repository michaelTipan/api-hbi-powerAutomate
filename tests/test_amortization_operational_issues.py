"""Tests del builder de operational_issues para amortización requires_correction."""

from __future__ import annotations

from app.application.job_status_enrichment import enrich_job_for_http_response
from app.application.services.abono_dry_run import ABONO_ASIENTOS_NO_CUADRAN
from app.application.ui.amortization_operational_issues import (
    attach_operational_issues_to_amortization_result,
    build_operational_issues_from_amortization_result,
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


def test_bank_asientos_no_cuadran_is_visible_with_asientos_link() -> None:
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
    assert len(issues) == 1
    issue = issues[0]
    assert issue["technical_reference"] == "BANK_ASIENTOS_NO_CUADRAN"
    assert "cuadra" in issue["user_message"].lower()
    assert issue["links"][0]["rel"] == "asientos"
    assert issue["links"][0]["web_url"] == "https://contoso.sharepoint.com/asientos-248"


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
