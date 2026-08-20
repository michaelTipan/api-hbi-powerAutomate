"""Guía operativa de la hoja Errores (textos quirúrgicos + enriquecimiento).

Misma semántica que ui-stable: Tipo de caso / Descripción / Qué debe hacer /
Requiere soporte a partir del código técnico. Adaptado a v4 (sin columnas
A/V/K ni hoja Control).
"""
from __future__ import annotations

from typing import Any

from app.application.services.review_schema import ErroresCols

ERRORES_GUIDE_FALLBACK: tuple[str, str, str, str] = (
    "Revisión",
    "El caso requiere revisión manual.",
    "Revise la información del cliente y, si no puede corregirlo, comuníquelo al equipo encargado.",
    "SI, si persiste",
)

ERRORES_GUIDE_BY_CODE: dict[str, tuple[str, str, str, str]] = {
    "fecha_limite_extracto_not_readable": (
        "Extracto",
        "Hay extractos en la carpeta del crédito que el sistema no puede usar.",
        "Retire o corrija los archivos listados y vuelva a generar.",
        "SI, si persiste",
    ),
    "extract_not_found": (
        "Extracto",
        "No se encontró un PDF de extracto para este crédito.",
        "Cargue el extracto correspondiente en la carpeta EXTRACTOS del crédito indicado, "
        "o en la carpeta del crédito si todavía no existe EXTRACTOS. "
        "Luego vuelva a ejecutar la generación.",
        "NO",
    ),
    "extract_as_of_not_found": (
        "Extracto",
        "No se encontró un extracto usable para esta unidad de crédito.",
        "Cargue o deje un único extracto válido en EXTRACTOS (o en la raíz del crédito) "
        "y vuelva a generar.",
        "NO",
    ),
    "extract_tie_as_of_bank_date": (
        "Extracto",
        "Hay más de un extracto con la misma fecha límite máxima y el sistema no puede escoger uno automáticamente.",
        "Revise los extractos listados en la descripción y deje únicamente el extracto correcto, "
        "o mueva los duplicados a una carpeta de respaldo. Luego vuelva a ejecutar la generación.",
        "NO",
    ),
    "extract_tie_max_fecha_limite": (
        "Extracto",
        "Hay más de un extracto con la misma fecha límite máxima y el sistema no puede escoger uno automáticamente.",
        "Revise los extractos listados en la descripción y deje únicamente el extracto correcto, "
        "o mueva los duplicados a una carpeta de respaldo. Luego vuelva a ejecutar la generación.",
        "NO",
    ),
    "credit_folder_not_found": (
        "Crédito",
        "No se pudo identificar una unidad de crédito válida para este cliente.",
        "Verifique que el cliente tenga una carpeta de crédito, una carpeta EXTRACTOS o extractos válidos "
        "en la raíz del cliente. Si la estructura no corresponde al estándar, comuníquelo al equipo encargado.",
        "SI, si estructura no estándar",
    ),
    "only_terminal_credit_folders": (
        "Crédito",
        "Este cliente solo tiene carpetas de crédito cerradas "
        "(TERMINADO/FINALIZADO/CANCELADO/PAGADO/LIQUIDADO); no hay una unidad activa para validar.",
        "Si el pago corresponde a un crédito vigente, renombre o cree la carpeta del crédito activo "
        "(sin esas marcas) y vuelva a generar. Las carpetas cerradas se ignoran a propósito.",
        "NO",
    ),
    "customer_not_found": (
        "Cliente",
        "No se encontró en SharePoint una carpeta de cliente que coincida con el concepto del banco.",
        "Revise el nombre del cliente en el Excel del banco y que exista la carpeta correspondiente "
        "bajo INFORMACION CREDITOS-CLIENTES. Corrija el nombre o cree/renombre la carpeta y vuelva a generar.",
        "NO",
    ),
    "customer_ambiguous": (
        "Cliente",
        "El concepto del banco coincide con más de una carpeta de cliente en SharePoint.",
        "Ajuste el nombre en el Excel del banco o renombre carpetas para que quede una sola coincidencia clara. "
        "Luego vuelva a generar.",
        "NO",
    ),
    "amortization_table_not_found": (
        "Tabla de amortización",
        "No se encontró una tabla de amortización Excel para este crédito.",
        "Verifique que exista un archivo Excel de tabla de amortización en la carpeta del crédito o del cliente.",
        "SI, si persiste",
    ),
    "amortization_table_ambiguous": (
        "Tabla de amortización",
        "Se encontraron varias tablas de amortización posibles y no se pudo elegir una de forma segura.",
        "Revise la carpeta y deje identificada claramente la tabla de amortización vigente.",
        "SI, si persiste",
    ),
    "extract_amount_not_found": (
        "Extracto",
        "No se pudo leer el monto «Total a pagar» en el PDF del extracto.",
        "Revise el PDF (texto seleccionable, sin cortes); cargue un extracto válido si es necesario "
        "y vuelva a ejecutar la generación.",
        "SI, si persiste",
    ),
    "abono_no_credit_candidates": (
        "Abono",
        "No se encontró ningún crédito válido con tabla de amortización para aplicar el abono.",
        "Verifique la carpeta del cliente y que cada crédito tenga tabla de amortización. Vuelva a generar.",
        "SI, si persiste",
    ),
    "abono_credit_without_amortization_table": (
        "Abono",
        "El crédito no tiene una tabla de amortización válida para ofrecerlo como candidato de abono.",
        "Cargue o corrija la tabla de amortización en la carpeta del crédito y vuelva a generar.",
        "SI, si persiste",
    ),
    "generic_abono_not_supported": (
        "Tipo Aplicación",
        "El valor «ABONO» genérico ya no se acepta en el Excel del banco.",
        "Use «ABONO CAPITAL» o «ABONO MORA» según corresponda y vuelva a ejecutar la generación.",
        "NO",
    ),
    "abono_mora_extract_missing": (
        "Abono mora",
        "No se encontró un extracto de referencia para aplicar el abono a mora en este crédito.",
        "Cargue el extracto correspondiente en la carpeta EXTRACTOS del crédito "
        "y vuelva a ejecutar la generación.",
        "NO",
    ),
    "abono_mora_extract_ambiguous": (
        "Abono mora",
        "Hay más de un extracto candidato con la misma fecha límite máxima y no se puede elegir uno.",
        "Revise los extractos listados en la descripción y deje únicamente el extracto de referencia correcto. "
        "Luego vuelva a ejecutar la generación.",
        "NO",
    ),
}


def errores_row_meta(code: str) -> tuple[str, str, str, str]:
    return ERRORES_GUIDE_BY_CODE.get(str(code or "").strip(), ERRORES_GUIDE_FALLBACK)


def format_archivos_problema_list(archivos: list[dict[str, str]]) -> str:
    names: list[str] = []
    seen: set[str] = set()
    for item in archivos:
        name = str(item.get("name") or "").strip()
        if not name or name in seen:
            continue
        seen.add(name)
        reason = str(item.get("reason") or "")
        if reason == "download_failed":
            detail = str(item.get("detail") or "").strip()
            suffix = f": {detail}" if detail else ""
            names.append(f"«{name}» (no se pudo descargar{suffix})")
        elif reason == "pdf_no_text":
            names.append(f"«{name}» (PDF escaneado sin texto)")
        elif reason == "fecha_limite_not_readable":
            names.append(f"«{name}» (fecha límite no reconocida)")
        elif reason in {"tie_max_fecha_limite", "tie_as_of_bank_date"}:
            fe = str(item.get("fecha_limite") or "").strip()
            suffix = f" (fecha límite {fe})" if fe else ""
            names.append(f"«{name}»{suffix}")
        else:
            names.append(f"«{name}»")
    if not names:
        return ""
    if len(names) == 1:
        return names[0]
    if len(names) == 2:
        return f"{names[0]} y {names[1]}"
    return ", ".join(names[:-1]) + f" y {names[-1]}"


def _contexto_cliente_credito(rec: dict[str, Any]) -> str:
    cliente = str(rec.get("cliente") or "").strip()
    credito = str(rec.get("credito") or "").strip()
    parts: list[str] = []
    if cliente:
        parts.append(f"cliente «{cliente}»")
    if credito:
        parts.append(f"crédito «{credito}»")
    if not parts:
        return ""
    return " / ".join(parts)


def enrich_errores_guide_texts(
    code: str,
    descr: str,
    hacer: str,
    rec: dict[str, Any],
) -> tuple[str, str]:
    """Añade cliente/crédito y nombres de archivo problemáticos a la guía operativa."""
    ctx = _contexto_cliente_credito(rec)
    archivos = rec.get("archivos_problema")
    archivos_list = archivos if isinstance(archivos, list) else []
    archivos_txt = format_archivos_problema_list(
        [a for a in archivos_list if isinstance(a, dict)]
    )

    if code == "fecha_limite_extracto_not_readable":
        if archivos_txt:
            descr = f"No se pudo usar: {archivos_txt}."
        return descr, hacer

    if code in {
        "extract_tie_max_fecha_limite",
        "extract_tie_as_of_bank_date",
        "abono_mora_extract_ambiguous",
    }:
        base = descr
        if ctx:
            base = f"{descr} ({ctx})."
        if archivos_txt:
            descr = f"{base} Archivos en empate: {archivos_txt}."
            hacer = (
                "Deje únicamente el extracto correcto (mueva los demás a respaldo) "
                "y vuelva a generar."
            )
        else:
            descr = base
        return descr, hacer

    if code in {"extract_not_found", "extract_as_of_not_found", "abono_mora_extract_missing"}:
        if ctx:
            descr = (
                f"No se encontró un PDF de extracto para {ctx}. "
                "Se esperaba un archivo .pdf con «extracto» en el nombre "
                "en la carpeta EXTRACTOS o en la raíz de esa unidad de crédito."
            )
            hacer = (
                f"Cargue el extracto correspondiente para {ctx} "
                "(preferible en EXTRACTOS) y vuelva a generar."
            )
        return descr, hacer

    if code == "extract_amount_not_found":
        base = f"En {ctx}: " if ctx else ""
        if archivos_txt:
            descr = f"{base}no se pudo leer el monto «Total a pagar» en {archivos_txt}."
            hacer = (
                f"Revise {archivos_txt} (texto seleccionable, sin cortes); "
                "cargue un extracto válido si es necesario y vuelva a generar."
            )
        elif ctx:
            descr = f"{base}{descr[0].lower() + descr[1:] if descr else descr}"
        return descr, hacer

    if code == "customer_not_found":
        concepto = str(rec.get("cliente") or "").strip()
        if concepto:
            descr = (
                f"No se encontró en SharePoint una carpeta de cliente que coincida con "
                f"el concepto del banco «{concepto}»."
            )
            hacer = (
                f"Revise el Excel del banco: el concepto «{concepto}» debe coincidir con el nombre "
                "de la carpeta del cliente bajo INFORMACION CREDITOS-CLIENTES. "
                "Corrija el nombre o cree/renombre la carpeta y vuelva a generar."
            )
        return descr, hacer

    if code == "customer_ambiguous":
        concepto = str(rec.get("cliente") or "").strip()
        if concepto:
            descr = (
                f"El concepto del banco «{concepto}» coincide con más de una carpeta de cliente."
            )
        return descr, hacer

    if code in {
        "credit_folder_not_found",
        "amortization_table_not_found",
        "amortization_table_ambiguous",
        "abono_no_credit_candidates",
        "abono_credit_without_amortization_table",
    }:
        if ctx:
            descr = f"En {ctx}: {descr[0].lower() + descr[1:] if descr else descr}"
        return descr, hacer

    if ctx and code not in {"generic_abono_not_supported"}:
        descr = f"En {ctx}: {descr[0].lower() + descr[1:] if descr else descr}"
    return descr, hacer


def error_record_to_sheet_row(rec: dict[str, Any]) -> list[Any]:
    """Fila Errores con guía operativa (no deja Descripción/Acción vacías)."""
    code = str(rec.get("code") or rec.get("codigo") or rec.get("codigo_tecnico") or "").strip()
    tipo, descr, hacer, soporte = errores_row_meta(code)
    descr, hacer = enrich_errores_guide_texts(code, descr, hacer, rec)
    values_by_col = {
        ErroresCols.ID_PAGO: rec.get("id_pago"),
        ErroresCols.CLIENTE: rec.get("cliente"),
        ErroresCols.CREDITO: rec.get("credito"),
        ErroresCols.TIPO_CASO: rec.get("tipo_caso") or tipo,
        ErroresCols.DESCRIPCION: rec.get("descripcion") or rec.get("message") or descr,
        ErroresCols.QUE_DEBE_HACER: rec.get("que_debe_hacer") or hacer,
        ErroresCols.REQUIERE_SOPORTE: rec.get("requiere_soporte") or soporte,
        ErroresCols.LINK_EXTRACTO: "",
        ErroresCols.LINK_CARPETA_CREDITO: "",
        ErroresCols.CODIGO_TECNICO: code,
    }
    return [values_by_col[c] for c in ErroresCols.HEADERS]


def guide_texts_for_ui(codigo_tecnico: str, rec: dict[str, Any] | None = None) -> tuple[str, str, str]:
    """Fallback UI cuando la hoja Errores llegó sin descripción (Excel ya generado)."""
    code = str(codigo_tecnico or "").strip()
    tipo, descr, hacer, _soporte = errores_row_meta(code)
    if rec:
        descr, hacer = enrich_errores_guide_texts(code, descr, hacer, rec)
    return tipo, descr, hacer
