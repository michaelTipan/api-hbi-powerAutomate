"""
Fuente única de verdad del Excel de revisión.

- v4: contrato operativo actual (Generate/Finalize).
- v3: esquema histórico de 21 columnas; Finalize exige regenerar.

No hay compatibilidad con schemas v1/v2 ni hojas Distribucion_*.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from datetime import date
from enum import Enum
from typing import Any


# ---------------------------------------------------------------------------
# Version
# ---------------------------------------------------------------------------

REVIEW_SCHEMA_VERSION = 4
REVIEW_SCHEMA_VERSION_V3 = 3
REVIEW_SCHEMA_REQUIRES_REGENERATION = "review_schema_requires_regeneration"
REVIEW_SCHEMA_INCONSISTENT = "review_schema_inconsistent"


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


def _header_schema_version_from_wb(wb: Any) -> int:
    try:
        ws = find_aplicacion_pagos_sheet(wb)
        for row in ws.iter_rows(values_only=True):
            texts = [str(v or "").strip() for v in (row or ())]
            if AplicacionPagosCols.ID_PAGO in texts and AplicacionPagosCols.VALIDAR_PAGO in texts:
                return detect_aplicacion_pagos_schema_version(texts)
    except ValueError:
        return 0
    return 0


def require_review_schema_v4(wb: Any) -> int:
    """
    Exige schema 4 coherente: meta y headers reales.
    v3 (meta o headers) → review_schema_requires_regeneration.
    Meta 4 con headers que no son v4 → review_schema_inconsistent.
    Otro/ausente → unsupported_review_schema_version.
    """
    meta: int | None = None
    if ReviewSheets.META in getattr(wb, "sheetnames", []):
        meta = read_meta_review_schema_version(wb[ReviewSheets.META])
    header_ver = _header_schema_version_from_wb(wb)

    if meta == REVIEW_SCHEMA_VERSION_V3 or header_ver == REVIEW_SCHEMA_VERSION_V3:
        if meta == REVIEW_SCHEMA_VERSION and header_ver == REVIEW_SCHEMA_VERSION_V3:
            raise ValueError(REVIEW_SCHEMA_INCONSISTENT)
        raise ValueError(REVIEW_SCHEMA_REQUIRES_REGENERATION)

    if meta is not None and meta != REVIEW_SCHEMA_VERSION:
        raise ValueError("unsupported_review_schema_version")

    if header_ver != REVIEW_SCHEMA_VERSION:
        if meta == REVIEW_SCHEMA_VERSION:
            raise ValueError(REVIEW_SCHEMA_INCONSISTENT)
        raise ValueError("unsupported_review_schema_version")

    return REVIEW_SCHEMA_VERSION


def detect_aplicacion_pagos_schema_version(headers: list[Any]) -> int:
    """Detecta v4 vs v3 por headers. Nunca trata v3 como v4."""
    names = {str(h or "").strip() for h in headers if h is not None and str(h).strip()}
    removed = MANUAL_DISTRIBUTION_HEADERS_V3
    v4_required = set(AplicacionPagosCols.HEADERS)
    v3_required = set(AplicacionPagosColsV3.HEADERS)
    if removed & names:
        if v3_required.issubset(names):
            return REVIEW_SCHEMA_VERSION_V3
        return 0
    if v4_required.issubset(names):
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
    REVISAR_TIPO = "REVISAR TIPO DE APLICACIÓN"
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
    valor_obligacion_actual: Any = None,
    saldo_vencido: Any = None,
    monto_banco: Any = None,
) -> str:
    """Sugerencia informativa v4: extracto + Validar Pago + monto banco canónico."""
    vp = normalize_validar_pago_value(validar_pago)
    if vp == ValidarPago.POR_DEFINIR or vp == "":
        return AplicacionSugerida.POR_DEFINIR
    if vp == ValidarPago.NO:
        return AplicacionSugerida.NO_APLICA

    oblig = _safe_money(valor_obligacion_actual) if valor_obligacion_actual not in (None, "") else None
    venc = _safe_money(saldo_vencido) if saldo_vencido not in (None, "") else None
    banco = _safe_money(monto_banco) if monto_banco not in (None, "") else None
    if banco is None or banco <= MONEY_EQ_TOLERANCE:
        return AplicacionSugerida.REVISAR_TIPO

    oblig_pos = oblig is not None and oblig > MONEY_EQ_TOLERANCE
    venc_pos = venc is not None and venc > MONEY_EQ_TOLERANCE
    if oblig_pos and venc_pos and money_eq(banco, (oblig or 0) + (venc or 0)):
        return AplicacionSugerida.PAGO_COMBINADO
    if oblig_pos and money_eq(banco, oblig):
        return AplicacionSugerida.PAGO_OBLIGACION_ACTUAL
    if venc_pos and money_eq(banco, venc):
        return AplicacionSugerida.APLICACION_SALDO_VENCIDO
    if oblig_pos and banco + MONEY_EQ_TOLERANCE < (oblig or 0):
        return AplicacionSugerida.PAGO_PARCIAL_OBLIGACION_ACTUAL
    return AplicacionSugerida.REVISAR_TIPO


# ---------------------------------------------------------------------------
# Columnas históricas v3 (21 visibles). Solo detección / fixtures legacy.
# ---------------------------------------------------------------------------

class AplicacionPagosColsV3:
    """Contrato histórico de 21 columnas. Generate ya no emite este esquema."""

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


MANUAL_DISTRIBUTION_HEADERS_V3 = frozenset(
    {
        AplicacionPagosColsV3.APLICAR_OBLIGACION_ACTUAL,
        AplicacionPagosColsV3.APLICAR_SALDO_VENCIDO,
        AplicacionPagosColsV3.ABONO_ADICIONAL_CAPITAL,
        AplicacionPagosColsV3.TOTAL_ASIGNADO,
        AplicacionPagosColsV3.SALDO_POR_ASIGNAR,
    }
)


# ---------------------------------------------------------------------------
# Columnas Aplicacion_Pagos v4 (16 visibles exactas)
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
            APLICACION_SUGERIDA,
            LINK_EXTRACTO,
            LINK_TABLA,
            LINK_CARPETA_CREDITO,
        }
    )

    PRIMARY_EDITABLE = frozenset({VALIDAR_PAGO, TIPO_APLICACION})
    SECRETARY_EDITABLE = frozenset({VALIDAR_PAGO, TIPO_APLICACION, OBSERVACION})


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
# Políticas documentales derivadas DESPUÉS de la revisión humana.
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
class ClassificationPolicy:
    """A. Tipo/clasificación confirmada (post-revisión humana)."""

    tipo_aplicacion_original: str
    tipo_aplicacion_canonica: str
    subtipo_aplicacion: str


@dataclass(frozen=True)
class DocumentaryPolicy:
    """B. Política documental del extracto / consolidado."""

    requiere_extracto: bool
    rol_extracto: str
    include_extract_in_composite: bool


@dataclass(frozen=True)
class AmortizationStrategyHints:
    """
    C. Pistas de estrategia de amortización.
    Los importes escritos en tabla vienen del asiento, no de A/V/K.
    """

    cierra_cuota: bool
    payoff_expected: bool = False


@dataclass(frozen=True)
class IbrDecisionHint:
    """
    D. Seguimiento IBR.
    None = decidir en preflight amort (tabla+asiento+estado); no congelar True en Generate.
    False = no actualizar IBR automáticamente (p.ej. pago parcial).
    """

    actualiza_ibr: bool | None


@dataclass(frozen=True)
class ApplicationPolicy:
    """
    Fachada estable: composición de clasificación / documental / amort / IBR.
    Campos planos conservados para callers existentes (Merge/Notify/Amort/Finalize).
    """

    tipo_aplicacion_original: str
    tipo_aplicacion_canonica: str
    subtipo_aplicacion: str
    requiere_extracto: bool
    rol_extracto: str
    cierra_cuota: bool
    actualiza_ibr: bool | None  # None = decidir en preflight amort; no congelar en Generate
    payoff_expected: bool = False
    # Política documental explícita (no usar solo requiere_extracto en Merge).
    include_extract_in_composite: bool = True

    @property
    def classification(self) -> ClassificationPolicy:
        return ClassificationPolicy(
            tipo_aplicacion_original=self.tipo_aplicacion_original,
            tipo_aplicacion_canonica=self.tipo_aplicacion_canonica,
            subtipo_aplicacion=self.subtipo_aplicacion,
        )

    @property
    def documentary(self) -> DocumentaryPolicy:
        return DocumentaryPolicy(
            requiere_extracto=self.requiere_extracto,
            rol_extracto=self.rol_extracto,
            include_extract_in_composite=self.include_extract_in_composite,
        )

    @property
    def amortization(self) -> AmortizationStrategyHints:
        return AmortizationStrategyHints(
            cierra_cuota=self.cierra_cuota,
            payoff_expected=self.payoff_expected,
        )

    @property
    def ibr(self) -> IbrDecisionHint:
        return IbrDecisionHint(actualiza_ibr=self.actualiza_ibr)

    @classmethod
    def compose(
        cls,
        classification: ClassificationPolicy,
        documentary: DocumentaryPolicy,
        amortization: AmortizationStrategyHints,
        ibr: IbrDecisionHint,
    ) -> ApplicationPolicy:
        return cls(
            tipo_aplicacion_original=classification.tipo_aplicacion_original,
            tipo_aplicacion_canonica=classification.tipo_aplicacion_canonica,
            subtipo_aplicacion=classification.subtipo_aplicacion,
            requiere_extracto=documentary.requiere_extracto,
            rol_extracto=documentary.rol_extracto,
            include_extract_in_composite=documentary.include_extract_in_composite,
            cierra_cuota=amortization.cierra_cuota,
            payoff_expected=amortization.payoff_expected,
            actualiza_ibr=ibr.actualiza_ibr,
        )

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
            "include_extract_in_composite": self.include_extract_in_composite,
        }


def resolve_actualiza_ibr(
    policy: ApplicationPolicy | None,
    *,
    payment_date: date | None,
    fecha_limite: date | None,
) -> bool:
    """
    Decisión canónica IBR (dry-run y Apply).

    Fecha banco < Fecha límite → no buscar / no exigir / no escribir IBR.
    En caso contrario: False explícito apaga; True enciende; None → cierra_cuota.
    """
    if payment_date is not None and fecha_limite is not None and payment_date < fecha_limite:
        return False
    if policy is None:
        return False
    if policy.actualiza_ibr is False:
        return False
    if policy.actualiza_ibr is True:
        return True
    return bool(policy.cierra_cuota)


# Tokens de nombre del PDF consolidado (Merge). No son tipos Excel.
MERGE_NAME_TOKEN_BY_TIPO: dict[str, str] = {
    TipoAplicacionConfirmado.PAGO_OBLIGACION_ACTUAL: "PAGO",
    TipoAplicacionConfirmado.PAGO_PARCIAL_OBLIGACION_ACTUAL: "PAGO",
    TipoAplicacionConfirmado.APLICACION_SALDO_VENCIDO: "PAGO SALDO VENCIDO",
    TipoAplicacionConfirmado.PAGO_COMBINADO: "PAGO COMBINADO",
    TipoAplicacionConfirmado.PAGO_Y_ABONO_CAPITAL: "PAGO Y ABONO CAPITAL",
    TipoAplicacionConfirmado.SALDO_VENCIDO_Y_ABONO_CAPITAL: "SALDO VENCIDO Y ABONO CAPITAL",
    TipoAplicacionConfirmado.PAGO_COMBINADO_Y_ABONO_CAPITAL: "PAGO COMBINADO Y ABONO CAPITAL",
    TipoAplicacionConfirmado.ABONO_A_CAPITAL: "ABONO CAPITAL",
    TipoAplicacionConfirmado.CANCELACION_PAGO_TOTAL: "PAGO TOTAL",
}

MERGE_NAME_TOKEN_MULTIPLE = "APLICACION MULTIPLE"


def merge_name_token_for_tipos(tipos: list[Any] | tuple[Any, ...]) -> str:
    """
    Token documental del consolidado por ID Pago.
    Tipos distintos → APLICACION MULTIPLE (solo naming; no es tipo Excel).
    """
    normalized: list[str] = []
    for raw in tipos:
        try:
            normalized.append(require_tipo_aplicacion_confirmado(raw))
        except ValueError:
            continue
    unique = list(dict.fromkeys(normalized))
    if not unique:
        return "PAGO"
    if len(unique) > 1:
        return MERGE_NAME_TOKEN_MULTIPLE
    return MERGE_NAME_TOKEN_BY_TIPO.get(unique[0], "PAGO")


def _compose_policy(
    *,
    tipo: str,
    canonica: str,
    subtipo: str,
    requiere_extracto: bool,
    rol_extracto: str,
    include_extract_in_composite: bool,
    cierra_cuota: bool,
    actualiza_ibr: bool | None,
    payoff_expected: bool = False,
) -> ApplicationPolicy:
    """Construye ApplicationPolicy separando clasificación / documental / amort / IBR."""
    return ApplicationPolicy.compose(
        ClassificationPolicy(
            tipo_aplicacion_original=tipo,
            tipo_aplicacion_canonica=canonica,
            subtipo_aplicacion=subtipo,
        ),
        DocumentaryPolicy(
            requiere_extracto=requiere_extracto,
            rol_extracto=rol_extracto,
            include_extract_in_composite=include_extract_in_composite,
        ),
        AmortizationStrategyHints(
            cierra_cuota=cierra_cuota,
            payoff_expected=payoff_expected,
        ),
        IbrDecisionHint(actualiza_ibr=actualiza_ibr),
    )


def resolve_policy_from_tipo_confirmado(value: Any) -> ApplicationPolicy:
    """Deriva políticas separadas desde Tipo de aplicación confirmado (post-revisión)."""
    tipo = require_tipo_aplicacion_confirmado(value)

    if tipo == TipoAplicacionConfirmado.PAGO_OBLIGACION_ACTUAL:
        return _compose_policy(
            tipo=tipo,
            canonica=CanonicalApplicationType.PAGO,
            subtipo=ApplicationSubtype.CUOTA,
            requiere_extracto=True,
            rol_extracto=ExtractRole.CIERRE_CUOTA,
            include_extract_in_composite=True,
            cierra_cuota=True,
            actualiza_ibr=None,
        )
    if tipo == TipoAplicacionConfirmado.PAGO_PARCIAL_OBLIGACION_ACTUAL:
        return _compose_policy(
            tipo=tipo,
            canonica=CanonicalApplicationType.PAGO,
            subtipo=ApplicationSubtype.CUOTA_PARCIAL,
            requiere_extracto=True,
            rol_extracto=ExtractRole.CIERRE_CUOTA,
            include_extract_in_composite=True,
            cierra_cuota=False,
            # Pago parcial no implica IBR automáticamente.
            actualiza_ibr=False,
        )
    if tipo == TipoAplicacionConfirmado.APLICACION_SALDO_VENCIDO:
        return _compose_policy(
            tipo=tipo,
            canonica=CanonicalApplicationType.PAGO,
            subtipo=ApplicationSubtype.SALDO_VENCIDO,
            requiere_extracto=True,
            rol_extracto=ExtractRole.REFERENCIA_SALDO,
            include_extract_in_composite=True,
            cierra_cuota=False,
            actualiza_ibr=None,
        )
    if tipo == TipoAplicacionConfirmado.PAGO_COMBINADO:
        return _compose_policy(
            tipo=tipo,
            canonica=CanonicalApplicationType.PAGO,
            subtipo=ApplicationSubtype.COMBINADO,
            requiere_extracto=True,
            rol_extracto=ExtractRole.CIERRE_CUOTA,
            include_extract_in_composite=True,
            cierra_cuota=True,
            actualiza_ibr=None,
        )
    if tipo == TipoAplicacionConfirmado.PAGO_Y_ABONO_CAPITAL:
        return _compose_policy(
            tipo=tipo,
            canonica=CanonicalApplicationType.PAGO,
            subtipo=ApplicationSubtype.CUOTA_MAS_CAPITAL,
            requiere_extracto=True,
            rol_extracto=ExtractRole.CIERRE_CUOTA,
            include_extract_in_composite=True,
            cierra_cuota=True,
            actualiza_ibr=None,
        )
    if tipo == TipoAplicacionConfirmado.SALDO_VENCIDO_Y_ABONO_CAPITAL:
        return _compose_policy(
            tipo=tipo,
            canonica=CanonicalApplicationType.PAGO,
            subtipo=ApplicationSubtype.SALDO_VENCIDO_MAS_CAPITAL,
            requiere_extracto=True,
            rol_extracto=ExtractRole.REFERENCIA_SALDO,
            include_extract_in_composite=True,
            cierra_cuota=False,
            actualiza_ibr=None,
        )
    if tipo == TipoAplicacionConfirmado.PAGO_COMBINADO_Y_ABONO_CAPITAL:
        return _compose_policy(
            tipo=tipo,
            canonica=CanonicalApplicationType.PAGO,
            subtipo=ApplicationSubtype.COMBINADO_MAS_CAPITAL,
            requiere_extracto=True,
            rol_extracto=ExtractRole.CIERRE_CUOTA,
            include_extract_in_composite=True,
            cierra_cuota=True,
            actualiza_ibr=None,
        )
    if tipo == TipoAplicacionConfirmado.ABONO_A_CAPITAL:
        return _compose_policy(
            tipo=tipo,
            canonica=CanonicalApplicationType.ABONO,
            subtipo=ApplicationSubtype.CAPITAL,
            requiere_extracto=False,
            rol_extracto=ExtractRole.NO_APLICA,
            include_extract_in_composite=False,
            cierra_cuota=False,
            actualiza_ibr=False,
        )
    if tipo == TipoAplicacionConfirmado.CANCELACION_PAGO_TOTAL:
        return _compose_policy(
            tipo=tipo,
            canonica=CanonicalApplicationType.PAGO,
            subtipo=ApplicationSubtype.CANCELACION,
            requiere_extracto=True,
            rol_extracto=ExtractRole.CIERRE_CUOTA,
            # Puede mostrarse en revisión/notify; no va como extracto regular del consolidado.
            include_extract_in_composite=False,
            cierra_cuota=True,
            actualiza_ibr=None,
            payoff_expected=True,
        )
    raise ValueError("tipo_aplicacion_invalid")


def resolve_application_policy(value: Any, *, from_bank: bool = False) -> ApplicationPolicy:
    """Resuelve política desde Tipo confirmado v4. from_bank=True siempre falla."""
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
            up = str(original).strip().upper()
            if up == CanonicalApplicationType.ABONO:
                return resolve_policy_from_tipo_confirmado(TipoAplicacionConfirmado.ABONO_A_CAPITAL)
            if up == CanonicalApplicationType.PAGO:
                return resolve_policy_from_tipo_confirmado(
                    TipoAplicacionConfirmado.PAGO_OBLIGACION_ACTUAL
                )
            raise

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
            include_extract_in_composite=bool(
                source["include_extract_in_composite"]
                if "include_extract_in_composite" in source
                else source.get("requiere_extracto", True)
            ),
        )

    if canon == CanonicalApplicationType.ABONO or default_canonical == TipoAplicacion.ABONO.value:
        return resolve_policy_from_tipo_confirmado(TipoAplicacionConfirmado.ABONO_A_CAPITAL)
    if canon == CanonicalApplicationType.PAGO or default_canonical == TipoAplicacion.PAGO.value:
        return resolve_policy_from_tipo_confirmado(TipoAplicacionConfirmado.PAGO_OBLIGACION_ACTUAL)
    # Manifest legacy sin tipo: contrato histórico Merge/Apply (no es el Excel de revisión).
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
        "include_extract_in_composite": pd["include_extract_in_composite"],
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
# Rutas internas (no visibles; columnas técnicas / keys de fila)
# ---------------------------------------------------------------------------

class InternalPathCols:
    """Keys técnicas en filas/histórico. No forman parte de las 16 visibles v4."""

    RUTA_EXTRACTO = "_ruta_extracto"
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


INTERNAL_PATH_COLUMNS: frozenset[str] = frozenset(
    {
        InternalPathCols.RUTA_EXTRACTO,
        InternalPathCols.RUTA_UNIDAD_CREDITO,
        InternalPathCols.RUTA_TABLA_AMORTIZACION,
        InternalPathCols.RUTA_ASIENTOS_CONTABLES,
        InternalPathCols.CREDITO_NORMALIZADO,
        InternalPathCols.TIPO_APLICACION_ORIGINAL,
        InternalPathCols.TIPO_APLICACION_CANONICA,
        InternalPathCols.SUBTIPO_APLICACION,
        InternalPathCols.REQUIERE_EXTRACTO,
        InternalPathCols.ROL_EXTRACTO,
        InternalPathCols.CIERRA_CUOTA,
        InternalPathCols.ACTUALIZA_IBR,
    }
)


def apply_policy_to_row(row: dict[str, Any], policy: ApplicationPolicy) -> None:
    pd = policy.policy_dict()
    row[InternalPathCols.TIPO_APLICACION_ORIGINAL] = pd["tipo_aplicacion_original"]
    row[InternalPathCols.TIPO_APLICACION_CANONICA] = pd["tipo_aplicacion_canonica"]
    row[InternalPathCols.SUBTIPO_APLICACION] = pd["subtipo_aplicacion"]
    row[InternalPathCols.REQUIERE_EXTRACTO] = pd["requiere_extracto"]
    row[InternalPathCols.ROL_EXTRACTO] = pd["rol_extracto"]
    row[InternalPathCols.CIERRA_CUOTA] = pd["cierra_cuota"]
    # No congelar True desde Finalize/Generate: None → vacío (preflight amort decide).
    ibr = pd["actualiza_ibr"]
    row[InternalPathCols.ACTUALIZA_IBR] = "" if ibr is None else bool(ibr)


APPLICATION_TYPES_SUPPORTED: tuple[str, ...] = tuple(TipoAplicacionConfirmado.OPTIONS_ORDERED)
