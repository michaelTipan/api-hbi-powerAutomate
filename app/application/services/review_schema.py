"""
Fuente única de verdad del Excel de revisión — schema v3 únicamente.

Generate escribe con estas constantes. Finalize lee con las mismas.
No hay compatibilidad con schemas v1/v2 ni hojas Distribucion_*.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from enum import Enum
from typing import Any


# ---------------------------------------------------------------------------
# Version
# ---------------------------------------------------------------------------

REVIEW_SCHEMA_VERSION = 3


# ---------------------------------------------------------------------------
# Hojas
# ---------------------------------------------------------------------------

class ReviewSheets:
    APLICACION_PAGOS = "Aplicacion_Pagos"
    ERRORES = "Errores"
    LISTAS = "_Listas"
    META = "_Meta"


def _norm_sheet_name(title: str) -> str:
    return _accent_fold_upper(str(title or "").strip().replace("_", " "))


def find_aplicacion_pagos_sheet(wb: Any) -> Any:
    """Localiza la hoja Aplicacion_Pagos. Fail-closed: sin fallback legacy."""
    target = _norm_sheet_name(ReviewSheets.APLICACION_PAGOS)
    for ws in wb.worksheets:
        if _norm_sheet_name(ws.title) == target:
            return ws
    raise ValueError("missing_aplicacion_pagos_sheet")


def workbook_has_aplicacion_pagos_sheet(wb: Any) -> bool:
    try:
        find_aplicacion_pagos_sheet(wb)
        return True
    except ValueError:
        return False


def read_meta_review_schema_version(ws_meta: Any) -> int | None:
    """Lee ReviewSchemaVersion desde hoja _Meta (filas Campo/Valor)."""
    if ws_meta is None:
        return None
    for row in ws_meta.iter_rows(min_row=1, max_row=ws_meta.max_row or 1, values_only=True):
        if not row or len(row) < 2:
            continue
        campo = str(row[0] or "").strip()
        if campo == MetaCols.ROW_REVIEW_SCHEMA_VERSION:
            try:
                return int(str(row[1] or "").strip())
            except ValueError:
                return None
    return None


def require_review_schema_v3(wb: Any) -> int:
    """
    Exige schema 3. Sin migración silenciosa.
    Preferencia: _Meta.ReviewSchemaVersion; si falta, headers de Aplicacion_Pagos.
    """
    version: int | None = None
    if ReviewSheets.META in getattr(wb, "sheetnames", []):
        version = read_meta_review_schema_version(wb[ReviewSheets.META])
    if version is None:
        try:
            ws = find_aplicacion_pagos_sheet(wb)
            header_row = 1
            for r_idx, row in enumerate(ws.iter_rows(values_only=True), start=1):
                texts = [str(v or "").strip() for v in (row or ())]
                if AplicacionPagosCols.ID_PAGO in texts and AplicacionPagosCols.VALIDAR_PAGO in texts:
                    header_row = r_idx
                    headers = texts
                    if detect_aplicacion_pagos_schema_version(headers) == REVIEW_SCHEMA_VERSION:
                        version = REVIEW_SCHEMA_VERSION
                    break
            _ = header_row
        except ValueError:
            version = None
    if version != REVIEW_SCHEMA_VERSION:
        raise ValueError("unsupported_review_schema_version")
    return version


def detect_aplicacion_pagos_schema_version(headers: list[Any]) -> int:
    """v3 si están las 21 columnas canónicas (orden no exigido aquí)."""
    names = {str(h or "").strip() for h in headers if h is not None and str(h).strip()}
    required = set(AplicacionPagosCols.HEADERS)
    if required.issubset(names):
        return REVIEW_SCHEMA_VERSION
    return 0


# ---------------------------------------------------------------------------
# Meta
# ---------------------------------------------------------------------------

class MetaCols:
    CAMPO = "Campo"
    VALOR = "Valor"
    ROW_REVIEW_SCHEMA_VERSION = "ReviewSchemaVersion"
    ROW_PROCESS_ID = "ProcessId"
    ROW_PROCESS_DATE = "ProcessDate"
    ROW_BANK_CODE = "BankCode"


# ---------------------------------------------------------------------------
# Validar Pago
# ---------------------------------------------------------------------------

class ValidarPago:
    POR_DEFINIR = "POR DEFINIR"
    SI = "SI"
    NO = "NO"

    OPTIONS_ORDERED = [POR_DEFINIR, SI, NO]
    ALLOWED = frozenset(OPTIONS_ORDERED)


def _normalize_validar_pago_raw(raw: Any) -> str:
    s = str(raw or "").strip().upper()
    s = s.replace("Í", "I").replace("í", "I")
    if s in ("POR DEFINIR", "POR_DEFINIR", "PENDING", "PENDIENTE"):
        return ValidarPago.POR_DEFINIR
    if s in ("SI", "SÍ", "YES", "TRUE", "1", "Y"):
        return ValidarPago.SI
    if s in ("NO", "N", "FALSE", "0"):
        return ValidarPago.NO
    return ""


def normalize_validar_pago_value(raw: Any) -> str:
    """Devuelve POR DEFINIR | SI | NO | '' si no se reconoce."""
    return _normalize_validar_pago_raw(raw)


def is_validar_pago_si(row: dict[str, Any]) -> bool:
    return normalize_validar_pago_value(row.get(AplicacionPagosCols.VALIDAR_PAGO)) == ValidarPago.SI


def is_validar_pago_por_definir(row: dict[str, Any]) -> bool:
    return (
        normalize_validar_pago_value(row.get(AplicacionPagosCols.VALIDAR_PAGO))
        == ValidarPago.POR_DEFINIR
    )


# ---------------------------------------------------------------------------
# Tipo de aplicación confirmado (decisión humana)
# ---------------------------------------------------------------------------

class TipoAplicacionConfirmado:
    PAGO_OBLIGACION_ACTUAL = "PAGO DE OBLIGACIÓN ACTUAL"
    PAGO_PARCIAL_OBLIGACION_ACTUAL = "PAGO PARCIAL A OBLIGACIÓN ACTUAL"
    APLICACION_SALDO_VENCIDO = "APLICACIÓN A SALDO VENCIDO"
    PAGO_COMBINADO = "PAGO COMBINADO (SALDO VENCIDO + OBLIGACIÓN ACTUAL)"
    PAGO_Y_ABONO_CAPITAL = "PAGO Y ABONO A CAPITAL"
    SALDO_VENCIDO_Y_ABONO_CAPITAL = "APLICACIÓN A SALDO VENCIDO + ABONO A CAPITAL"
    PAGO_COMBINADO_Y_ABONO_CAPITAL = "PAGO COMBINADO + ABONO A CAPITAL"
    ABONO_A_CAPITAL = "ABONO A CAPITAL"
    CANCELACION_PAGO_TOTAL = "CANCELACIÓN / PAGO TOTAL"

    OPTIONS_ORDERED = [
        PAGO_OBLIGACION_ACTUAL,
        PAGO_PARCIAL_OBLIGACION_ACTUAL,
        APLICACION_SALDO_VENCIDO,
        PAGO_COMBINADO,
        PAGO_Y_ABONO_CAPITAL,
        SALDO_VENCIDO_Y_ABONO_CAPITAL,
        PAGO_COMBINADO_Y_ABONO_CAPITAL,
        ABONO_A_CAPITAL,
        CANCELACION_PAGO_TOTAL,
    ]
    ALLOWED = frozenset(OPTIONS_ORDERED)


# Alias interno canónico (manifest / amort)
TIPO_CONFIRMADO_CANONICAL: dict[str, str] = {
    TipoAplicacionConfirmado.PAGO_OBLIGACION_ACTUAL: "PAGO_OBLIGACION_ACTUAL",
    TipoAplicacionConfirmado.PAGO_PARCIAL_OBLIGACION_ACTUAL: "PAGO_PARCIAL_OBLIGACION_ACTUAL",
    TipoAplicacionConfirmado.APLICACION_SALDO_VENCIDO: "APLICACION_SALDO_VENCIDO",
    TipoAplicacionConfirmado.PAGO_COMBINADO: "PAGO_COMBINADO",
    TipoAplicacionConfirmado.PAGO_Y_ABONO_CAPITAL: "PAGO_Y_ABONO_CAPITAL",
    TipoAplicacionConfirmado.SALDO_VENCIDO_Y_ABONO_CAPITAL: "SALDO_VENCIDO_Y_ABONO_CAPITAL",
    TipoAplicacionConfirmado.PAGO_COMBINADO_Y_ABONO_CAPITAL: "PAGO_COMBINADO_Y_ABONO_CAPITAL",
    TipoAplicacionConfirmado.ABONO_A_CAPITAL: "ABONO_A_CAPITAL",
    TipoAplicacionConfirmado.CANCELACION_PAGO_TOTAL: "CANCELACION_PAGO_TOTAL",
}


def _accent_fold_upper(text: str) -> str:
    folded = unicodedata.normalize("NFD", text)
    stripped = "".join(c for c in folded if unicodedata.category(c) != "Mn")
    return stripped.upper()


def _normalize_tipo_text(value: Any) -> str:
    raw = str(value or "").strip()
    if not raw:
        return ""
    collapsed = re.sub(r"\s+", " ", raw)
    return _accent_fold_upper(collapsed)


def normalize_tipo_aplicacion_confirmado(value: Any) -> str:
    """Devuelve el literal canónico de TipoAplicacionConfirmado o ''."""
    text = _normalize_tipo_text(value)
    if not text:
        return ""
    for opt in TipoAplicacionConfirmado.OPTIONS_ORDERED:
        if _normalize_tipo_text(opt) == text:
            return opt
    return ""


def require_tipo_aplicacion_confirmado(value: Any) -> str:
    norm = normalize_tipo_aplicacion_confirmado(value)
    if not norm:
        raise ValueError("tipo_aplicacion_required")
    return norm


# ---------------------------------------------------------------------------
# Aplicación sugerida (calculadora; nunca bloquea Finalize)
# ---------------------------------------------------------------------------

class AplicacionSugerida:
    POR_DEFINIR = "POR DEFINIR"
    NO_APLICA = "NO APLICA"
    POR_DISTRIBUIR = "POR DISTRIBUIR"
    PAGO_OBLIGACION_ACTUAL = TipoAplicacionConfirmado.PAGO_OBLIGACION_ACTUAL
    PAGO_PARCIAL_OBLIGACION_ACTUAL = TipoAplicacionConfirmado.PAGO_PARCIAL_OBLIGACION_ACTUAL
    APLICACION_SALDO_VENCIDO = TipoAplicacionConfirmado.APLICACION_SALDO_VENCIDO
    PAGO_COMBINADO = TipoAplicacionConfirmado.PAGO_COMBINADO
    PAGO_Y_ABONO_CAPITAL = TipoAplicacionConfirmado.PAGO_Y_ABONO_CAPITAL
    SALDO_VENCIDO_Y_ABONO_CAPITAL = TipoAplicacionConfirmado.SALDO_VENCIDO_Y_ABONO_CAPITAL
    PAGO_COMBINADO_Y_ABONO_CAPITAL = TipoAplicacionConfirmado.PAGO_COMBINADO_Y_ABONO_CAPITAL
    ABONO_A_CAPITAL = TipoAplicacionConfirmado.ABONO_A_CAPITAL


MONEY_EQ_TOLERANCE = 0.01


def money_eq(left: float | None, right: float | None, *, tol: float = MONEY_EQ_TOLERANCE) -> bool:
    if left is None or right is None:
        return False
    return abs(float(left) - float(right)) <= tol


def _safe_money(value: Any) -> float:
    if value is None or str(value).strip() == "":
        return 0.0
    if isinstance(value, (int, float)):
        return float(value)
    s = str(value).strip().replace("$", "").replace(" ", "")
    if "," in s and "." in s:
        s = s.replace(".", "").replace(",", ".")
    elif "," in s:
        s = s.replace(",", ".")
    try:
        return float(s)
    except ValueError:
        return 0.0


def compute_aplicacion_sugerida(
    *,
    validar_pago: Any,
    aplicar_obligacion: Any = 0,
    aplicar_saldo_vencido: Any = 0,
    abono_capital: Any = 0,
    valor_obligacion_actual: Any = None,
) -> str:
    """Matriz de aplicación sugerida (ayuda operativa; no es fuente de verdad)."""
    vp = normalize_validar_pago_value(validar_pago)
    if vp == ValidarPago.POR_DEFINIR or vp == "":
        return AplicacionSugerida.POR_DEFINIR
    if vp == ValidarPago.NO:
        return AplicacionSugerida.NO_APLICA

    a = _safe_money(aplicar_obligacion)
    v = _safe_money(aplicar_saldo_vencido)
    k = _safe_money(abono_capital)
    a_pos, v_pos, k_pos = a > MONEY_EQ_TOLERANCE, v > MONEY_EQ_TOLERANCE, k > MONEY_EQ_TOLERANCE

    if not a_pos and not v_pos and not k_pos:
        return AplicacionSugerida.POR_DISTRIBUIR

    if a_pos and not v_pos and not k_pos:
        oblig = valor_obligacion_actual
        if oblig is not None and str(oblig).strip() != "":
            oblig_f = _safe_money(oblig)
            if oblig_f > MONEY_EQ_TOLERANCE and a + MONEY_EQ_TOLERANCE < oblig_f:
                return AplicacionSugerida.PAGO_PARCIAL_OBLIGACION_ACTUAL
        return AplicacionSugerida.PAGO_OBLIGACION_ACTUAL

    if not a_pos and v_pos and not k_pos:
        return AplicacionSugerida.APLICACION_SALDO_VENCIDO
    if not a_pos and not v_pos and k_pos:
        return AplicacionSugerida.ABONO_A_CAPITAL
    if a_pos and v_pos and not k_pos:
        return AplicacionSugerida.PAGO_COMBINADO
    if a_pos and not v_pos and k_pos:
        return AplicacionSugerida.PAGO_Y_ABONO_CAPITAL
    if not a_pos and v_pos and k_pos:
        return AplicacionSugerida.SALDO_VENCIDO_Y_ABONO_CAPITAL
    if a_pos and v_pos and k_pos:
        return AplicacionSugerida.PAGO_COMBINADO_Y_ABONO_CAPITAL

    return AplicacionSugerida.POR_DISTRIBUIR


# ---------------------------------------------------------------------------
# Columnas Aplicacion_Pagos (21 visibles exactas)
# ---------------------------------------------------------------------------

class AplicacionPagosCols:
    ID_PAGO = "ID Pago"
    CLIENTE = "Cliente"
    CREDITO = "Crédito"
    MONTO_BANCO = "Monto banco"
    FECHA_BANCO = "Fecha banco"
    FECHA_LIMITE = "Fecha límite"
    DIAS_RESPECTO_VENCIMIENTO = "Días respecto vencimiento"
    VALOR_OBLIGACION_ACTUAL = "Valor obligación actual"
    SALDO_VENCIDO = "Saldo vencido"
    VALIDAR_PAGO = "Validar Pago"
    APLICAR_OBLIGACION_ACTUAL = "Aplicar a obligación actual"
    APLICAR_SALDO_VENCIDO = "Aplicar a saldo vencido"
    ABONO_ADICIONAL_CAPITAL = "Abono adicional a capital"
    TOTAL_ASIGNADO = "Total asignado al crédito"
    SALDO_POR_ASIGNAR = "Saldo por asignar"
    APLICACION_SUGERIDA = "Aplicación sugerida"
    TIPO_APLICACION = "Tipo de aplicación"
    LINK_EXTRACTO = "Link extracto"
    LINK_TABLA = "Link tabla amortización"
    LINK_CARPETA_CREDITO = "Link carpeta crédito"
    OBSERVACION = "Observación"

    HEADERS = [
        ID_PAGO,
        CLIENTE,
        CREDITO,
        MONTO_BANCO,
        FECHA_BANCO,
        FECHA_LIMITE,
        DIAS_RESPECTO_VENCIMIENTO,
        VALOR_OBLIGACION_ACTUAL,
        SALDO_VENCIDO,
        VALIDAR_PAGO,
        APLICAR_OBLIGACION_ACTUAL,
        APLICAR_SALDO_VENCIDO,
        ABONO_ADICIONAL_CAPITAL,
        TOTAL_ASIGNADO,
        SALDO_POR_ASIGNAR,
        APLICACION_SUGERIDA,
        TIPO_APLICACION,
        LINK_EXTRACTO,
        LINK_TABLA,
        LINK_CARPETA_CREDITO,
        OBSERVACION,
    ]

    SYSTEM_LOCKED = frozenset(
        {
            ID_PAGO,
            CLIENTE,
            CREDITO,
            MONTO_BANCO,
            FECHA_BANCO,
            FECHA_LIMITE,
            DIAS_RESPECTO_VENCIMIENTO,
            VALOR_OBLIGACION_ACTUAL,
            SALDO_VENCIDO,
            TOTAL_ASIGNADO,
            SALDO_POR_ASIGNAR,
            APLICACION_SUGERIDA,
            LINK_EXTRACTO,
            LINK_TABLA,
            LINK_CARPETA_CREDITO,
        }
    )

    SECRETARY_EDITABLE = frozenset(
        {
            VALIDAR_PAGO,
            APLICAR_OBLIGACION_ACTUAL,
            APLICAR_SALDO_VENCIDO,
            ABONO_ADICIONAL_CAPITAL,
            TIPO_APLICACION,
            OBSERVACION,
        }
    )


# ---------------------------------------------------------------------------
# Errores
# ---------------------------------------------------------------------------

class ErroresCols:
    ID_PAGO = "ID Pago"
    CLIENTE = "Cliente"
    CREDITO = "Crédito"
    TIPO_CASO = "Tipo de caso"
    DESCRIPCION = "Descripción para revisión"
    QUE_DEBE_HACER = "Qué debe hacer"
    REQUIERE_SOPORTE = "Requiere soporte"
    LINK_EXTRACTO = "Link extracto"
    LINK_CARPETA_CREDITO = "Link carpeta crédito"
    CODIGO_TECNICO = "Código técnico"

    HEADERS = [
        ID_PAGO,
        CLIENTE,
        CREDITO,
        TIPO_CASO,
        DESCRIPCION,
        QUE_DEBE_HACER,
        REQUIERE_SOPORTE,
        LINK_EXTRACTO,
        LINK_CARPETA_CREDITO,
        CODIGO_TECNICO,
    ]


# ---------------------------------------------------------------------------
# Asientos pendientes (soporte secretaría post-Finalize)
# ---------------------------------------------------------------------------

class AsientosPendientesCols:
    TIPO_APLICACION = "Tipo de aplicación"
    ID_PAGO = "ID Pago"
    BANCO = "Banco"
    CLIENTE = "Cliente"
    CREDITO = "Crédito"
    MONTO_BANCO = "Monto banco"
    FECHA_BANCO = "Fecha banco"
    FECHA_LIMITE = "Fecha límite"
    TOTAL_VALIDADO = "Total validado"
    LINK_CARPETA_ASIENTOS = "Link carpeta asientos contables"
    LINK_EXTRACTO = "Link extracto"
    LINK_TABLA = "Link tabla amortización"
    OBSERVACION = "Observación"

    HEADERS = [
        TIPO_APLICACION,
        ID_PAGO,
        BANCO,
        CLIENTE,
        CREDITO,
        MONTO_BANCO,
        FECHA_BANCO,
        FECHA_LIMITE,
        TOTAL_VALIDADO,
        LINK_CARPETA_ASIENTOS,
        LINK_EXTRACTO,
        LINK_TABLA,
        OBSERVACION,
    ]


SUPPORT_NOT_APPLICABLE = "NO APLICA"


# ---------------------------------------------------------------------------
# Políticas documentales derivadas DESPUÉS de la revisión
# (sin genera_siguiente_extracto — la automatización NO genera extractos)
# ---------------------------------------------------------------------------

class TipoAplicacion(str, Enum):
    """Tipo canónico documental (PAGO / ABONO) para Merge/Notify/Amort."""

    PAGO = "PAGO"
    ABONO = "ABONO"


class CanonicalApplicationType:
    PAGO = "PAGO"
    ABONO = "ABONO"


class ApplicationSubtype:
    CUOTA = "CUOTA"
    CUOTA_PARCIAL = "CUOTA_PARCIAL"
    CUOTA_MAS_CAPITAL = "CUOTA_MAS_CAPITAL"
    CAPITAL = "CAPITAL"
    MORA = "MORA"
    COMBINADO = "COMBINADO"
    COMBINADO_MAS_CAPITAL = "COMBINADO_MAS_CAPITAL"
    SALDO_VENCIDO = "SALDO_VENCIDO"
    SALDO_VENCIDO_MAS_CAPITAL = "SALDO_VENCIDO_MAS_CAPITAL"
    CANCELACION = "CANCELACION"
    GENERAL = "GENERAL"


class ExtractRole:
    CIERRE_CUOTA = "CIERRE_CUOTA"
    REFERENCIA_MORA = "REFERENCIA_MORA"
    REFERENCIA_SALDO = "REFERENCIA_SALDO"
    NO_APLICA = "NO_APLICA"


@dataclass(frozen=True)
class ApplicationPolicy:
    tipo_aplicacion_original: str
    tipo_aplicacion_canonica: str
    subtipo_aplicacion: str
    requiere_extracto: bool
    rol_extracto: str
    cierra_cuota: bool
    actualiza_ibr: bool | None  # None = decidir en preflight amort; no congelar en Generate
    payoff_expected: bool = False

    @property
    def canonical_enum(self) -> TipoAplicacion:
        if self.tipo_aplicacion_canonica == TipoAplicacion.ABONO.value:
            return TipoAplicacion.ABONO
        return TipoAplicacion.PAGO

    def policy_dict(self) -> dict[str, Any]:
        return {
            "tipo_aplicacion_original": self.tipo_aplicacion_original,
            "tipo_aplicacion_canonica": self.tipo_aplicacion_canonica,
            "subtipo_aplicacion": self.subtipo_aplicacion,
            "requiere_extracto": self.requiere_extracto,
            "rol_extracto": self.rol_extracto,
            "cierra_cuota": self.cierra_cuota,
            "actualiza_ibr": self.actualiza_ibr,
            "payoff_expected": self.payoff_expected,
        }


def resolve_policy_from_tipo_confirmado(value: Any) -> ApplicationPolicy:
    """Deriva política documental desde Tipo de aplicación confirmado (post-revisión)."""
    tipo = require_tipo_aplicacion_confirmado(value)

    if tipo == TipoAplicacionConfirmado.PAGO_OBLIGACION_ACTUAL:
        return ApplicationPolicy(
            tipo_aplicacion_original=tipo,
            tipo_aplicacion_canonica=CanonicalApplicationType.PAGO,
            subtipo_aplicacion=ApplicationSubtype.CUOTA,
            requiere_extracto=True,
            rol_extracto=ExtractRole.CIERRE_CUOTA,
            cierra_cuota=True,
            actualiza_ibr=None,
        )
    if tipo == TipoAplicacionConfirmado.PAGO_PARCIAL_OBLIGACION_ACTUAL:
        return ApplicationPolicy(
            tipo_aplicacion_original=tipo,
            tipo_aplicacion_canonica=CanonicalApplicationType.PAGO,
            subtipo_aplicacion=ApplicationSubtype.CUOTA_PARCIAL,
            requiere_extracto=True,
            rol_extracto=ExtractRole.CIERRE_CUOTA,
            cierra_cuota=False,
            actualiza_ibr=None,
        )
    if tipo == TipoAplicacionConfirmado.APLICACION_SALDO_VENCIDO:
        return ApplicationPolicy(
            tipo_aplicacion_original=tipo,
            tipo_aplicacion_canonica=CanonicalApplicationType.PAGO,
            subtipo_aplicacion=ApplicationSubtype.SALDO_VENCIDO,
            requiere_extracto=True,
            rol_extracto=ExtractRole.REFERENCIA_SALDO,
            cierra_cuota=False,
            actualiza_ibr=None,
        )
    if tipo == TipoAplicacionConfirmado.PAGO_COMBINADO:
        return ApplicationPolicy(
            tipo_aplicacion_original=tipo,
            tipo_aplicacion_canonica=CanonicalApplicationType.PAGO,
            subtipo_aplicacion=ApplicationSubtype.COMBINADO,
            requiere_extracto=True,
            rol_extracto=ExtractRole.CIERRE_CUOTA,
            cierra_cuota=True,
            actualiza_ibr=None,
        )
    if tipo == TipoAplicacionConfirmado.PAGO_Y_ABONO_CAPITAL:
        return ApplicationPolicy(
            tipo_aplicacion_original=tipo,
            tipo_aplicacion_canonica=CanonicalApplicationType.PAGO,
            subtipo_aplicacion=ApplicationSubtype.CUOTA_MAS_CAPITAL,
            requiere_extracto=True,
            rol_extracto=ExtractRole.CIERRE_CUOTA,
            cierra_cuota=True,
            actualiza_ibr=None,
        )
    if tipo == TipoAplicacionConfirmado.SALDO_VENCIDO_Y_ABONO_CAPITAL:
        return ApplicationPolicy(
            tipo_aplicacion_original=tipo,
            tipo_aplicacion_canonica=CanonicalApplicationType.PAGO,
            subtipo_aplicacion=ApplicationSubtype.SALDO_VENCIDO_MAS_CAPITAL,
            requiere_extracto=True,
            rol_extracto=ExtractRole.REFERENCIA_SALDO,
            cierra_cuota=False,
            actualiza_ibr=None,
        )
    if tipo == TipoAplicacionConfirmado.PAGO_COMBINADO_Y_ABONO_CAPITAL:
        return ApplicationPolicy(
            tipo_aplicacion_original=tipo,
            tipo_aplicacion_canonica=CanonicalApplicationType.PAGO,
            subtipo_aplicacion=ApplicationSubtype.COMBINADO_MAS_CAPITAL,
            requiere_extracto=True,
            rol_extracto=ExtractRole.CIERRE_CUOTA,
            cierra_cuota=True,
            actualiza_ibr=None,
        )
    if tipo == TipoAplicacionConfirmado.ABONO_A_CAPITAL:
        return ApplicationPolicy(
            tipo_aplicacion_original=tipo,
            tipo_aplicacion_canonica=CanonicalApplicationType.ABONO,
            subtipo_aplicacion=ApplicationSubtype.CAPITAL,
            requiere_extracto=False,
            rol_extracto=ExtractRole.NO_APLICA,
            cierra_cuota=False,
            actualiza_ibr=False,
        )
    if tipo == TipoAplicacionConfirmado.CANCELACION_PAGO_TOTAL:
        return ApplicationPolicy(
            tipo_aplicacion_original=tipo,
            tipo_aplicacion_canonica=CanonicalApplicationType.PAGO,
            subtipo_aplicacion=ApplicationSubtype.CANCELACION,
            requiere_extracto=True,
            rol_extracto=ExtractRole.CIERRE_CUOTA,
            cierra_cuota=True,
            actualiza_ibr=None,
            payoff_expected=True,
        )
    raise ValueError("tipo_aplicacion_invalid")


def resolve_application_policy(value: Any, *, from_bank: bool = False) -> ApplicationPolicy:
    """
    Resuelve política desde Tipo confirmado v3.
    from_bank=True siempre falla: el Excel bancario ya no trae Tipo Aplicación.
    """
    if from_bank:
        raise ValueError("tipo_aplicacion_from_bank_removed")
    return resolve_policy_from_tipo_confirmado(value)


def normalize_tipo_aplicacion(value: Any) -> TipoAplicacion:
    return resolve_policy_from_tipo_confirmado(value).canonical_enum


def requiere_extracto(tipo: TipoAplicacion | ApplicationPolicy | str | Any) -> bool:
    if isinstance(tipo, ApplicationPolicy):
        return tipo.requiere_extracto
    if isinstance(tipo, TipoAplicacion):
        return tipo == TipoAplicacion.PAGO
    try:
        return resolve_policy_from_tipo_confirmado(tipo).requiere_extracto
    except ValueError:
        return str(tipo or "").strip().upper() == TipoAplicacion.PAGO.value


def policy_requires_closing_extract(policy: ApplicationPolicy) -> bool:
    return policy.rol_extracto == ExtractRole.CIERRE_CUOTA and policy.requiere_extracto


def policy_requires_reference_extract(policy: ApplicationPolicy) -> bool:
    return (
        policy.rol_extracto in (ExtractRole.REFERENCIA_MORA, ExtractRole.REFERENCIA_SALDO)
        and policy.requiere_extracto
    )


def resolve_manifest_policy(
    source: dict[str, Any],
    *,
    default_canonical: str | None = None,
) -> ApplicationPolicy:
    """Resuelve política desde manifest/output/credit_item (post-Finalize)."""
    original = (
        source.get("tipo_aplicacion_original")
        or source.get(AplicacionPagosCols.TIPO_APLICACION)
        or source.get("tipo_aplicacion")
        or source.get(AsientosPendientesCols.TIPO_APLICACION)
    )
    if original:
        try:
            return resolve_policy_from_tipo_confirmado(original)
        except ValueError:
            pass

    canon = str(source.get("tipo_aplicacion_canonica") or "").strip().upper()
    subtipo = str(source.get("subtipo_aplicacion") or "").strip().upper()
    if canon and subtipo:
        return ApplicationPolicy(
            tipo_aplicacion_original=str(source.get("tipo_aplicacion_original") or original or canon),
            tipo_aplicacion_canonica=canon,
            subtipo_aplicacion=subtipo,
            requiere_extracto=bool(source.get("requiere_extracto")),
            rol_extracto=str(source.get("rol_extracto") or ""),
            cierra_cuota=bool(source.get("cierra_cuota")),
            actualiza_ibr=source.get("actualiza_ibr"),
            payoff_expected=bool(source.get("payoff_expected")),
        )

    if canon == CanonicalApplicationType.ABONO or default_canonical == TipoAplicacion.ABONO.value:
        return resolve_policy_from_tipo_confirmado(TipoAplicacionConfirmado.ABONO_A_CAPITAL)
    return resolve_policy_from_tipo_confirmado(TipoAplicacionConfirmado.PAGO_OBLIGACION_ACTUAL)


def policy_observability_dict(policy: ApplicationPolicy) -> dict[str, Any]:
    pd = policy.policy_dict()
    return {
        "tipo_aplicacion": policy.tipo_aplicacion_canonica,
        "tipo_aplicacion_original": pd["tipo_aplicacion_original"],
        "tipo_aplicacion_canonica": pd["tipo_aplicacion_canonica"],
        "subtipo_aplicacion": pd["subtipo_aplicacion"],
        "requiere_extracto": pd["requiere_extracto"],
        "requires_extract": pd["requiere_extracto"],
        "rol_extracto": pd["rol_extracto"],
        "cierra_cuota": pd["cierra_cuota"],
        "actualiza_ibr": pd["actualiza_ibr"],
        "updates_ibr": pd["actualiza_ibr"],
        "payoff_expected": pd["payoff_expected"],
    }


def policy_fields_for_manifest(policy: ApplicationPolicy) -> dict[str, Any]:
    return dict(policy.policy_dict())


def policy_from_row(row: dict[str, Any]) -> ApplicationPolicy:
    original = row.get(AplicacionPagosCols.TIPO_APLICACION) or row.get(
        AsientosPendientesCols.TIPO_APLICACION
    )
    if original:
        return resolve_policy_from_tipo_confirmado(original)
    raise ValueError("tipo_aplicacion_required")


def normalize_credito_digits(raw: Any) -> str:
    """Número de crédito limpio (ej. 258) desde etiqueta visible o celda."""
    s = str(raw or "").strip()
    if not s:
        return ""
    m = re.search(r"(?i)credito\s*#?\s*(\d+)", s)
    if m:
        return m.group(1)
    m2 = re.search(r"\d{1,12}", s)
    return m2.group(0) if m2 else ""


def dias_respecto_vencimiento(fecha_banco: Any, fecha_limite: Any) -> int | None:
    """Fecha banco - Fecha límite. None si falta alguna fecha."""
    from datetime import date, datetime

    def _as_date(v: Any) -> date | None:
        if v is None or str(v).strip() == "":
            return None
        if isinstance(v, datetime):
            return v.date()
        if isinstance(v, date):
            return v
        s = str(v).strip()[:10]
        try:
            return date.fromisoformat(s)
        except ValueError:
            return None

    fb = _as_date(fecha_banco)
    fl = _as_date(fecha_limite)
    if fb is None or fl is None:
        return None
    return (fb - fl).days


# ---------------------------------------------------------------------------
# Bridge temporal para callers Notify/Merge/Amort / helpers Finalize aún no
# migrados en este bloque. NO son parte del Excel v3 visible.
# TODO(next): eliminar tras cablear Notify/Merge/Amort a Aplicacion_Pagos.
# ---------------------------------------------------------------------------

class DistribucionCols(AplicacionPagosCols):
    ESTADO_PAGO = "Estado Pago"
    OTROS_VALORES = "Otros valores"
    VALOR_EXTRACTO = AplicacionPagosCols.VALOR_OBLIGACION_ACTUAL
    APLICAR_A_EXTRACTO = AplicacionPagosCols.APLICAR_OBLIGACION_ACTUAL
    MORA_A_APLICAR = AplicacionPagosCols.APLICAR_SALDO_VENCIDO
    ABONO_A_CAPITAL = AplicacionPagosCols.ABONO_ADICIONAL_CAPITAL
    TOTAL_APLICADO = AplicacionPagosCols.TOTAL_ASIGNADO
    DIAS_MORA = AplicacionPagosCols.DIAS_RESPECTO_VENCIMIENTO
    RUTA = "_ruta_extracto"
    RUTA_UNIDAD_CREDITO = "_ruta_unidad_credito"
    RUTA_TABLA_AMORTIZACION = "_ruta_tabla_amortizacion"
    RUTA_ASIENTOS_CONTABLES = "_ruta_asientos_contables"
    CREDITO_NORMALIZADO = "_credito_normalizado"
    TIPO_APLICACION_ORIGINAL = "_tipo_aplicacion_original"
    TIPO_APLICACION_CANONICA = "_tipo_aplicacion_canonica"
    SUBTIPO_APLICACION = "_subtipo_aplicacion"
    REQUIERE_EXTRACTO = "_requiere_extracto"
    ROL_EXTRACTO = "_rol_extracto"
    CIERRA_CUOTA = "_cierra_cuota"
    ACTUALIZA_IBR = "_actualiza_ibr"
    ESTADO_LINEA = ESTADO_PAGO
    VALOR_INTERESES = APLICAR_A_EXTRACTO
    ABONO_K = ABONO_A_CAPITAL
    INTERESES_MORA = OTROS_VALORES


class DistribucionAbonosCols(DistribucionCols):
    VALIDAR_ABONO = AplicacionPagosCols.VALIDAR_PAGO
    ORIGEN_CREDITO = "Origen crédito"
    TIPO_APLICACION = AplicacionPagosCols.TIPO_APLICACION
    RUTA_EXTRACTO = "_ruta_extracto"
    LINK_EXTRACTO = AplicacionPagosCols.LINK_EXTRACTO


class EstadoPago:
    ADELANTADO = "ADELANTADO"
    ATRASADO = "ATRASADO"
    NORMAL = "NORMAL"
    REVISION_MANUAL = "REVISION_MANUAL"
    ALLOWED = frozenset({ADELANTADO, ATRASADO, NORMAL, REVISION_MANUAL})
    OPTIONS_ORDERED = [ADELANTADO, ATRASADO, NORMAL, REVISION_MANUAL]
    FINALIZE_FORBIDDEN = frozenset({REVISION_MANUAL})
    COUNTERS_POSITIVE_TOTAL = frozenset({NORMAL, ATRASADO, ADELANTADO})
    SECRETARY_AND_RUTA = frozenset({NORMAL, ATRASADO, ADELANTADO})
    CLEARS_PENDING = COUNTERS_POSITIVE_TOTAL


class ValidarAbono:
    SI = ValidarPago.SI
    NO = ValidarPago.NO


class ControlCols:
    CAMPO = "Campo"
    VALOR = "Valor"
    ROW_PROCESAR = "Procesar"
    ROW_ESTADO_PROCESO = "Estado proceso"
    ROW_FECHA_PROCESAMIENTO = "Fecha procesamiento"
    ROW_RESULTADO = "Resultado"
    ROW_ID_PROCESO = "ID Proceso"
    ROW_REVIEW_SCHEMA_VERSION = "ReviewSchemaVersion"
    ROW_ESTADO = "Estado"
    ROW_FECHA = "Fecha"
    VAL_PROCESAR_SI = "SI"
    VAL_PROCESAR_NO = "NO"
    VAL_PROCESADO = "PROCESADO"
    VAL_FINALIZADO = "FINALIZADO"
    ESTADO_OPTIONS = ["EN_REVISION", "PROCESANDO", "PROCESADO", "ERROR", "CANCELADO"]
    PROCESAR_OPTIONS = [VAL_PROCESAR_NO, VAL_PROCESAR_SI]


class CasosPagoCols:
    ID_PAGO = "ID Pago"
    FECHA_BANCO = "Fecha banco"
    CLIENTE = "Cliente"
    CONCEPTO_BANCO = "Concepto banco"
    MONTO_BANCO = "Monto banco"
    OBSERVACION = "Observación"
    HEADERS = [ID_PAGO, FECHA_BANCO, CLIENTE, CONCEPTO_BANCO, MONTO_BANCO, OBSERVACION]


class TipoAplicacionVisible:
    PAGO = TipoAplicacionConfirmado.PAGO_OBLIGACION_ACTUAL
    PAGO_Y_ABONO_CAPITAL = TipoAplicacionConfirmado.PAGO_Y_ABONO_CAPITAL
    ABONO_CAPITAL = TipoAplicacionConfirmado.ABONO_A_CAPITAL
    ABONO_MORA = TipoAplicacionConfirmado.APLICACION_SALDO_VENCIDO
    ABONO_LEGACY = TipoAplicacionConfirmado.ABONO_A_CAPITAL


APPLICATION_TYPES_SUPPORTED: tuple[str, ...] = tuple(TipoAplicacionConfirmado.OPTIONS_ORDERED)

ReviewSheets.DISTRIBUCION_PAGOS = ReviewSheets.APLICACION_PAGOS  # type: ignore[attr-defined]
ReviewSheets.DISTRIBUCION_ABONOS = "Distribucion_Abonos"  # type: ignore[attr-defined]
ReviewSheets.CONTROL = "Control"  # type: ignore[attr-defined]
ReviewSheets.CASOS_PAGO = "Casos_Pago"  # type: ignore[attr-defined]
ReviewSheets.RESUMEN = "Resumen"  # type: ignore[attr-defined]
ReviewSheets.DISTRIBUCION = "Distribucion"  # type: ignore[attr-defined]
ReviewSheets.DISTRIBUCION_LEGACY = "Distribucion"  # type: ignore[attr-defined]
ReviewSheets.LISTAS = "_Listas"  # already set
ReviewSheets.DISTRIBUCION_PAGOS_FUTURE = ReviewSheets.APLICACION_PAGOS  # type: ignore[attr-defined]

DISTRIBUCION_TECHNICAL_HIDDEN_COLUMNS: frozenset[str] = frozenset()
DISTRIBUCION_ABONOS_TECHNICAL_HIDDEN_COLUMNS: frozenset[str] = frozenset()


def find_distribucion_pagos_sheet(wb: Any) -> Any:
    return find_aplicacion_pagos_sheet(wb)


def workbook_has_distribucion_pagos_sheet(wb: Any) -> bool:
    return workbook_has_aplicacion_pagos_sheet(wb)


def parse_bank_tipo_aplicacion(value: Any) -> ApplicationPolicy:
    raise ValueError("tipo_aplicacion_from_bank_removed")


def require_validar_abono_value(raw: Any) -> str:
    if raw is None or str(raw).strip() == "":
        return ValidarPago.NO
    norm = normalize_validar_pago_value(raw)
    if not norm:
        raise ValueError("invalid_validar_abono")
    return norm


def is_validar_abono_si(row: dict[str, Any]) -> bool:
    return is_validar_pago_si(row)


def apply_policy_to_pagos_row(row: dict[str, Any], policy: ApplicationPolicy) -> None:
    pd = policy.policy_dict()
    row[DistribucionCols.TIPO_APLICACION_ORIGINAL] = pd["tipo_aplicacion_original"]
    row[DistribucionCols.TIPO_APLICACION_CANONICA] = pd["tipo_aplicacion_canonica"]
    row[DistribucionCols.SUBTIPO_APLICACION] = pd["subtipo_aplicacion"]
    row[DistribucionCols.REQUIERE_EXTRACTO] = pd["requiere_extracto"]
    row[DistribucionCols.ROL_EXTRACTO] = pd["rol_extracto"]
    row[DistribucionCols.CIERRA_CUOTA] = pd["cierra_cuota"]
    row[DistribucionCols.ACTUALIZA_IBR] = pd["actualiza_ibr"]


def apply_policy_to_abonos_row(row: dict[str, Any], policy: ApplicationPolicy) -> None:
    apply_policy_to_pagos_row(row, policy)
    row[DistribucionAbonosCols.TIPO_APLICACION] = policy.tipo_aplicacion_canonica


def apply_legacy_estado_migration(row: dict[str, Any]) -> None:
    """No-op: schema v3 no migra Estado Pago legacy."""
    _ = row


def detect_distrib_schema_version_from_headers(headers: list[Any]) -> int:
    return detect_aplicacion_pagos_schema_version(headers)


def normalize_distrib_row_keys(
    row: dict[str, Any],
    *,
    schema_version: int | None = None,
) -> dict[str, Any]:
    _ = schema_version
    return dict(row)


def read_control_review_schema_version(ws_control: Any) -> int | None:
    """Bridge: lee version desde Control si existe; preferir _Meta via require_review_schema_v3."""
    if ws_control is None:
        return None
    for row in ws_control.iter_rows(min_row=1, max_row=ws_control.max_row or 1, values_only=True):
        if not row or len(row) < 2:
            continue
        if str(row[0] or "").strip() == ControlCols.ROW_REVIEW_SCHEMA_VERSION:
            try:
                return int(str(row[1] or "").strip())
            except ValueError:
                return None
    return None


REVIEW_SCHEMA_VERSION_V1 = 0  # retirado; cualquier referencia debe fallar en Finalize

DISTRIB_LEGACY_HEADER_ALIASES: dict[str, str] = {}


class EstadoLinea:
    """Retirado en v3; stub para tests legacy hasta limpieza del siguiente frente."""

    VALIDAR = "VALIDAR"
    REPROGRAMAR = "REPROGRAMAR"
    NO_VALIDAR = "NO_VALIDAR"
    PENDIENTE_MORA = "PENDIENTE_MORA"
    REVISION_MANUAL = "REVISION_MANUAL"
    OPTIONS = [VALIDAR, PENDIENTE_MORA, REPROGRAMAR, NO_VALIDAR, REVISION_MANUAL]
