"""Provisiona fixtures mutables solo bajo PRUEBAS (asientos E15, CORREOS E31)."""
from __future__ import annotations

from typing import Any

from app.application.services.accounting_pdf_parser import (
    AccountingParseError,
    PdfTextNotExtractableError,
    extract_text_from_pdf,
    parse_accounting_text,
)

from scripts.e2e_rc.fixtures_catalog import (
    ASIENTO_QUARANTINE_SUBFOLDER,
    CORREOS_XLSX_REL,
    E15_ASIENTO_FILENAME,
    E15_CREDIT,
    assert_sandbox_notify_recipients,
    e15_asientos_folder_rel,
    parseable_asiento_pdf,
    rewrite_correos_recipients_bytes,
)
from scripts.e2e_rc.graph_session import SandboxGraphSession
from scripts.e2e_rc.path_guard import assert_sandbox_mutable_path


def _asiento_is_parseable(raw: bytes, *, credit: str = E15_CREDIT) -> bool:
    try:
        text = extract_text_from_pdf(raw)
        parse_accounting_text(
            text,
            {
                "id_pago": "rc-e15",
                "cliente": "GEOEXCON",
                "credito": f"CREDITO # {credit}",
                "asiento_pdf_path": "fixture",
            },
        )
        return True
    except (PdfTextNotExtractableError, AccountingParseError, ValueError):
        return False


def provision_e15_parseable_asiento(session: SandboxGraphSession) -> dict[str, Any]:
    """Sube asiento parseable GEOEXCON/231 y cuarentena PDFs ilegibles en el nivel.

    Merge lista solo PDF en el nivel ASIENTOS (subcarpetas ignoradas). Mover
    ilegibles a ``_RC_CUARENTENA`` evita ``ACCOUNTING_PARSE_FAILED`` que enmascara
    ``PAYOFF_NOT_ACHIEVED``.
    """
    folder = assert_sandbox_mutable_path(e15_asientos_folder_rel())
    folder_id = session.walk(folder)
    kids = session.children(folder_id)
    quarantined: list[str] = []
    kept_parseable: list[str] = []

    for it in kids:
        if "folder" in it:
            continue
        if "file" not in it:
            continue
        name = str(it.get("name") or "")
        if not name.lower().endswith(".pdf"):
            continue
        item_id = str(it["id"])
        full = f"{folder}/{name}"
        raw = session.download_item(item_id)
        if name == E15_ASIENTO_FILENAME or _asiento_is_parseable(raw):
            kept_parseable.append(name)
            continue
        # Copia a cuarentena + borra del nivel (patrón E2E; merge ignora subcarpetas).
        q_path = f"{folder}/{ASIENTO_QUARANTINE_SUBFOLDER}/{name}"
        session.upload_by_path(q_path, raw)
        session.delete_item(item_id, path_for_guard=full)
        quarantined.append(name)

    pdf = parseable_asiento_pdf()
    target = f"{folder}/{E15_ASIENTO_FILENAME}"
    session.upload_by_path(target, pdf)
    return {
        "folder": folder,
        "uploaded": target,
        "bytes": len(pdf),
        "quarantined": quarantined,
        "kept_parseable": kept_parseable,
        "quarantine_subfolder": ASIENTO_QUARANTINE_SUBFOLDER,
    }


def rewrite_sandbox_correos_xlsx(
    session: SandboxGraphSession,
    *,
    sandbox_to: str = "herramientas.jsakedev@gmail.com",
) -> dict[str, Any]:
    """Reescribe CORREOS.xlsx bajo PRUEBAS: recipients solo allowlist (sin @hbi.com.co)."""
    path = assert_sandbox_mutable_path(CORREOS_XLSX_REL)
    assert_sandbox_notify_recipients([sandbox_to])
    parent = "/".join(path.split("/")[:-1])
    name = path.split("/")[-1]
    folder_id = session.walk(parent)
    item = next((i for i in session.children(folder_id) if i.get("name") == name), None)
    if not item:
        # Crear workbook mínimo si falta.
        from scripts.e2e_rc.fixtures_catalog import build_sandbox_correos_xlsx

        raw_out = build_sandbox_correos_xlsx(emisor=sandbox_to, receptores=[sandbox_to])
        session.upload_by_path(path, raw_out)
        return {"path": path, "created": True, "bytes": len(raw_out), "sandbox_to": sandbox_to}

    raw_in = session.download_item(str(item["id"]))
    raw_out = rewrite_correos_recipients_bytes(raw_in, sandbox_to=sandbox_to)
    session.upload_item(str(item["id"]), raw_out, path_for_guard=path)
    return {
        "path": path,
        "created": False,
        "bytes": len(raw_out),
        "sandbox_to": sandbox_to,
        "allowlist": sorted(assert_sandbox_notify_recipients([sandbox_to])),
    }
