"""
Destino del PDF consolidado en el sitio de Contabilidad.

La ruta se deriva de la fecha bancaria del pago y del banco:

    {año}/TESORERIA {año}/{mes_numero} {MES}/{carpeta del banco}

Las tres primeras carpetas siguen una convención determinista y se crean si faltan.
La carpeta del banco **no** se crea: su nombre no es derivable (por ejemplo
``INGRESOS PA BANCOLOMBIA``), así que si no existe se informa un error accionable en
lugar de inventar una carpeta que nadie revisaría.

La resolución se cachea por combinación de año, mes y banco, de modo que una corrida
completa de merge cuesta a lo sumo unas pocas consultas adicionales a Graph.
"""

from __future__ import annotations

import logging
import os
import unicodedata
from datetime import date
from typing import Any
from urllib.parse import parse_qs, urlparse

from app.application.config.payment_validation_settings import (
    BANK_CODE_BANCOLOMBIA,
    BANK_CODE_BOGOTA,
)
from app.application.sharepoint_resolution import encode_graph_drive_path
from app.domain.ports.graph import GraphApiPort

logger = logging.getLogger(__name__)

MESES_ES: tuple[str, ...] = (
    "ENERO",
    "FEBRERO",
    "MARZO",
    "ABRIL",
    "MAYO",
    "JUNIO",
    "JULIO",
    "AGOSTO",
    "SEPTIEMBRE",
    "OCTUBRE",
    "NOVIEMBRE",
    "DICIEMBRE",
)

TESORERIA_FOLDER_TEMPLATE = "TESORERIA {year}"

DEFAULT_ACCOUNTING_BANK_FOLDER: dict[str, str] = {
    BANK_CODE_BOGOTA: "INGRESOS BANCO BOGOTA",
    BANK_CODE_BANCOLOMBIA: "INGRESOS PA BANCOLOMBIA",
}

_ACCOUNTING_BANK_FOLDER_ENV: dict[str, str] = {
    BANK_CODE_BOGOTA: "GRAPH_ACCOUNTING_BOGOTA_FOLDER_NAME",
    BANK_CODE_BANCOLOMBIA: "GRAPH_ACCOUNTING_BANCOLOMBIA_FOLDER_NAME",
}

ERROR_BANK_FOLDER_NOT_FOUND = "accounting_bank_folder_not_found"
ERROR_BANK_FOLDER_AMBIGUOUS = "accounting_bank_folder_ambiguous"


class AccountingDestinationError(RuntimeError):
    """Error accionable al resolver la carpeta destino en Contabilidad."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(f"{code}|{message}")
        self.code = code
        self.message = message


def resolve_accounting_bank_folder_name(bank_code: str) -> str:
    """Nombre de la carpeta de ingresos del banco dentro del mes contable."""
    env_key = _ACCOUNTING_BANK_FOLDER_ENV.get(bank_code, "")
    configured = os.getenv(env_key, "").strip() if env_key else ""
    if configured:
        return configured
    default = DEFAULT_ACCOUNTING_BANK_FOLDER.get(bank_code, "")
    if not default:
        raise AccountingDestinationError(
            ERROR_BANK_FOLDER_NOT_FOUND,
            f"No hay carpeta contable configurada para el banco {bank_code!r}.",
        )
    return default


def build_accounting_month_segments(report_date: date) -> tuple[str, str, str]:
    """Devuelve (año, ``TESORERIA {año}``, ``{MM} {MES}``) para la fecha indicada."""
    year = f"{report_date.year:04d}"
    tesoreria = TESORERIA_FOLDER_TEMPLATE.format(year=year)
    month = f"{report_date.month:02d} {MESES_ES[report_date.month - 1]}"
    return year, tesoreria, month


def _normalize_folder_name(name: str) -> str:
    """Compara nombres ignorando tildes, mayúsculas y espacios repetidos."""
    decomposed = unicodedata.normalize("NFKD", name)
    without_accents = "".join(ch for ch in decomposed if not unicodedata.combining(ch))
    return " ".join(without_accents.split()).casefold()


def _endpoint_and_params_from_next_link(next_link: str) -> tuple[str, dict[str, str] | None]:
    parsed = urlparse(next_link)
    path = parsed.path or ""
    endpoint = path.split("/v1.0/", 1)[1].lstrip("/") if "/v1.0/" in path else path.lstrip("/")
    if not parsed.query:
        return endpoint, None
    flat = {k: v[0] for k, v in parse_qs(parsed.query).items() if v}
    return endpoint, flat or None


class AccountingDestinationResolver:
    """Resuelve y cachea la carpeta destino dentro del sitio de Contabilidad."""

    def __init__(self, graph: GraphApiPort, site_id: str, drive_id: str) -> None:
        self._graph = graph
        self._site_id = site_id
        self._drive_id = drive_id
        self._folder_cache: dict[tuple[str, str], str] = {}

    async def _list_folder_names(self, folder_path: str) -> list[str]:
        if folder_path:
            encoded = encode_graph_drive_path(folder_path)
            endpoint = f"sites/{self._site_id}/drives/{self._drive_id}/root:/{encoded}:/children"
        else:
            endpoint = f"sites/{self._site_id}/drives/{self._drive_id}/root/children"

        names: list[str] = []
        params: dict[str, str] | None = {"$top": "200"}
        while True:
            response = await self._graph.get(endpoint, params=params)
            for item in response.get("value") or []:
                if isinstance(item, dict) and "folder" in item and item.get("name"):
                    names.append(str(item["name"]))
            next_link = response.get("@odata.nextLink")
            if not next_link:
                break
            endpoint, params = _endpoint_and_params_from_next_link(next_link)
        return names

    async def _create_folder(self, parent_path: str, folder_name: str) -> None:
        if parent_path:
            encoded = encode_graph_drive_path(parent_path)
            endpoint = f"/sites/{self._site_id}/drives/{self._drive_id}/root:/{encoded}:/children"
        else:
            endpoint = f"/sites/{self._site_id}/drives/{self._drive_id}/root/children"
        body: dict[str, Any] = {
            "name": folder_name,
            "folder": {},
            "@microsoft.graph.conflictBehavior": "fail",
        }
        await self._graph.post_json(endpoint, body)

    @staticmethod
    def _match_existing(names: list[str], wanted: str) -> list[str]:
        exact = [n for n in names if n == wanted]
        if exact:
            return exact[:1]
        target = _normalize_folder_name(wanted)
        return [n for n in names if _normalize_folder_name(n) == target]

    async def _ensure_folder(self, parent_path: str, wanted: str) -> str:
        """Devuelve el nombre real de la carpeta, creándola si no existe."""
        cache_key = (parent_path, wanted)
        cached = self._folder_cache.get(cache_key)
        if cached is not None:
            return cached

        names = await self._list_folder_names(parent_path)
        matches = self._match_existing(names, wanted)
        if matches:
            actual = matches[0]
            if actual != wanted:
                logger.info(
                    "contabilidad: se reutiliza la carpeta existente %r en lugar de crear %r.",
                    actual,
                    wanted,
                )
        else:
            await self._create_folder(parent_path, wanted)
            actual = wanted
            logger.info("contabilidad: carpeta creada %s/%s", parent_path or "(raíz)", wanted)

        self._folder_cache[cache_key] = actual
        return actual

    async def _require_folder(self, parent_path: str, wanted: str, bank_code: str) -> str:
        """Exige que la carpeta exista; nunca la crea."""
        cache_key = (parent_path, wanted)
        cached = self._folder_cache.get(cache_key)
        if cached is not None:
            return cached

        names = await self._list_folder_names(parent_path)
        matches = self._match_existing(names, wanted)
        if not matches:
            raise AccountingDestinationError(
                ERROR_BANK_FOLDER_NOT_FOUND,
                (
                    f"No existe la carpeta {wanted!r} dentro de {parent_path!r} en el sitio "
                    f"de Contabilidad (banco {bank_code}). Créela con ese nombre exacto o "
                    "corrija la variable de entorno correspondiente. Carpetas presentes: "
                    f"{sorted(names)}"
                ),
            )
        if len(matches) > 1:
            raise AccountingDestinationError(
                ERROR_BANK_FOLDER_AMBIGUOUS,
                (
                    f"Hay {len(matches)} carpetas equivalentes a {wanted!r} dentro de "
                    f"{parent_path!r} en el sitio de Contabilidad: {sorted(matches)}. "
                    "Deje una sola y vuelva a ejecutar."
                ),
            )

        actual = matches[0]
        self._folder_cache[cache_key] = actual
        return actual

    async def resolve_folder(self, report_date: date, bank_code: str) -> str:
        """
        Ruta relativa de la carpeta destino para la fecha bancaria y el banco indicados.

        Crea año, ``TESORERIA {año}`` y el mes si faltan; exige que la carpeta del banco
        ya exista.
        """
        year, tesoreria, month = build_accounting_month_segments(report_date)
        bank_folder = resolve_accounting_bank_folder_name(bank_code)

        actual_year = await self._ensure_folder("", year)
        actual_tesoreria = await self._ensure_folder(actual_year, tesoreria)
        tesoreria_path = f"{actual_year}/{actual_tesoreria}"
        actual_month = await self._ensure_folder(tesoreria_path, month)
        month_path = f"{tesoreria_path}/{actual_month}"
        actual_bank = await self._require_folder(month_path, bank_folder, bank_code)
        return f"{month_path}/{actual_bank}"
