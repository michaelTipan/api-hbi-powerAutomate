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
    E16_ASIENTO_B_FILENAME,
    E16_CLIENT,
    E16_CREDIT_B,
    E16_CREDIT_B_FOLDER,
    E16_SPLIT_B,
    E16_TABLA_B_FILENAME,
    RC_MORA_CLIENT,
    RC_MORA_CREDIT,
    RC_MORA_FOLDER,
    RC_MORA_OBLIG,
    RC_MORA_VENCIDO,
    asientos_folder_rel,
    assert_sandbox_notify_recipients,
    blank_image_like_pdf,
    e15_asientos_folder_rel,
    minimal_amortization_xlsx,
    minimal_extract_pdf,
    parseable_asiento_pdf,
    rewrite_correos_recipients_bytes,
    spatial_extract_pdf,
)
from scripts.e2e_rc.graph_session import SandboxGraphSession
from scripts.e2e_rc.path_guard import AUTHORIZED_CLIENTS_BASE, assert_sandbox_mutable_path


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


def provision_e16_second_active_credit(session: SandboxGraphSession) -> dict[str, Any]:
    """Crea CREDITO # 299 activo bajo GEOEXCON (254 es TERMINADO y Generate lo omite).

    Sube tabla mínima + asiento parseable para que Generate descubra el crédito
    y Merge/Amort tengan evidencia contable reconciliable.
    """
    credit_root = assert_sandbox_mutable_path(
        f"{AUTHORIZED_CLIENTS_BASE}/{E16_CLIENT}/{E16_CREDIT_B_FOLDER}"
    )
    tabla_path = f"{credit_root}/{E16_TABLA_B_FILENAME}"
    asientos_folder = asientos_folder_rel(
        E16_CLIENT, E16_CREDIT_B_FOLDER, E16_CREDIT_B
    )
    asiento_path = f"{asientos_folder}/{E16_ASIENTO_B_FILENAME}"

    tabla = minimal_amortization_xlsx(credit=E16_CREDIT_B, saldo=E16_SPLIT_B)
    session.upload_by_path(tabla_path, tabla)

    extract = minimal_extract_pdf(credit=E16_CREDIT_B, valor_obligacion=E16_SPLIT_B)
    extract_name = f"Extracto RC-E16 Obligacion # {E16_CREDIT_B}.pdf"
    extract_root = f"{credit_root}/{extract_name}"
    extract_folder = f"{credit_root}/EXTRACTOS/{extract_name}"
    session.upload_by_path(extract_root, extract)
    session.upload_by_path(extract_folder, extract)

    asiento = parseable_asiento_pdf(
        credit=E16_CREDIT_B,
        valor_pagado=E16_SPLIT_B,
        capital=2_000_000.0,
        intereses=2_500_000.0,
        mora=1_397_837.0,
        title="RC-E16 asiento parseable CRED 299",
        comprobante="9916",
    )
    session.upload_by_path(asiento_path, asiento)

    return {
        "credit_folder": credit_root,
        "tabla": tabla_path,
        "extract_root": extract_root,
        "extract_folder": extract_folder,
        "asiento": asiento_path,
        "split_b": E16_SPLIT_B,
        "note": "254 TERMINADO omitted by Generate; use 299",
    }


def provision_rc_mora_credit(
    session: SandboxGraphSession,
    *,
    credit: str = RC_MORA_CREDIT,
    folder: str = RC_MORA_FOLDER,
    right_role: str = "SALDO_VENCIDO",
    fecha_limite: str = "23/05/2026",
    valor_obligacion: float = RC_MORA_OBLIG,
    right_amount: float = RC_MORA_VENCIDO,
    asiento_valor: float | None = None,
    extra_extracts: list[dict[str, Any]] | None = None,
    asiento_mode: str = "parseable",
    asiento_credit_label: str | None = None,
) -> dict[str, Any]:
    """Crea/actualiza un crédito sandbox con extracto espacial + asiento + tabla."""
    client = RC_MORA_CLIENT
    credit_root = assert_sandbox_mutable_path(
        f"{AUTHORIZED_CLIENTS_BASE}/{client}/{folder}"
    )
    tabla_path = f"{credit_root}/Tabla de amortizacion {client} CRED {credit}.xlsx"
    asientos_folder = asientos_folder_rel(client, folder, credit)
    session.upload_by_path(
        tabla_path,
        minimal_amortization_xlsx(client=client, credit=credit, saldo=valor_obligacion),
    )
    extract = spatial_extract_pdf(
        credit=credit,
        fecha_limite=fecha_limite,
        valor_obligacion=valor_obligacion,
        client=client,
        right_role=right_role,
        right_amount=right_amount,
        left_intereses_mora=99_000.0 if right_role != "AMBIGUO" else None,
    )
    extract_name = f"Extracto RC {right_role} Obligacion # {credit}.pdf"
    extract_folder = f"{credit_root}/EXTRACTOS/{extract_name}"
    session.upload_by_path(extract_folder, extract)
    extra_paths: list[str] = []
    for spec in extra_extracts or []:
        extra_pdf = spatial_extract_pdf(
            credit=credit,
            fecha_limite=str(spec.get("fecha_limite") or fecha_limite),
            valor_obligacion=float(spec.get("valor_obligacion") or valor_obligacion),
            client=client,
            right_role=str(spec.get("right_role") or "VACIO"),
            right_amount=float(spec.get("right_amount") or 0),
        )
        extra_name = str(spec.get("name") or f"Extracto extra {credit}.pdf")
        extra_path = f"{credit_root}/EXTRACTOS/{extra_name}"
        session.upload_by_path(extra_path, extra_pdf)
        extra_paths.append(extra_path)

    valor = float(asiento_valor if asiento_valor is not None else valor_obligacion)
    asiento_name = f"Asiento RC {credit}.pdf"
    asiento_path = f"{asientos_folder}/{asiento_name}"
    if asiento_mode == "missing":
        # Borrar asientos parseables del nivel para E27.
        try:
            folder_id = session.walk(asientos_folder)
            for it in session.children(folder_id):
                name = str(it.get("name") or "")
                if name.lower().endswith(".pdf") and "folder" not in it:
                    session.delete_item(str(it["id"]), path_for_guard=f"{asientos_folder}/{name}")
        except FileNotFoundError:
            pass
        asiento_path = ""
    elif asiento_mode == "illegible":
        session.upload_by_path(asiento_path, blank_image_like_pdf())
    else:
        label = asiento_credit_label or credit
        session.upload_by_path(
            asiento_path,
            parseable_asiento_pdf(
                credit=label,
                valor_pagado=valor,
                capital=max(100_000.0, valor * 0.4),
                intereses=max(100_000.0, valor * 0.4),
                mora=max(0.0, valor * 0.2),
                title=f"RC asiento {label}",
                comprobante=f"9{credit}",
            ),
        )
    return {
        "credit_folder": credit_root,
        "tabla": tabla_path,
        "extract": extract_folder,
        "extra_extracts": extra_paths,
        "asiento": asiento_path,
        "right_role": right_role,
        "right_amount": right_amount,
        "asiento_mode": asiento_mode,
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

    from scripts.e2e_rc.fixtures_catalog import build_sandbox_correos_xlsx

    # Canonical values (not formulas). Notify loads with data_only=True.
    raw_out = build_sandbox_correos_xlsx(emisor=sandbox_to, receptores=[sandbox_to])
    # path-content creates a new item so cached/calculated blobs do not linger.
    session.delete_item(str(item["id"]), path_for_guard=path)
    session.upload_by_path(path, raw_out)
    return {
        "path": path,
        "created": False,
        "replaced": True,
        "bytes": len(raw_out),
        "sandbox_to": sandbox_to,
        "allowlist": sorted(assert_sandbox_notify_recipients([sandbox_to])),
    }
