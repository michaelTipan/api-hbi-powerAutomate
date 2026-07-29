"""
Resolución de sitio / biblioteca / ruta de SharePoint desde configuración de entorno.

Soporta dos contextos independientes:

- **Operaciones**: donde vive todo el proceso (bancos, clientes, control, revisión,
  histórico, trazabilidad y correos enviados). Es el único contexto obligatorio.
- **Contabilidad**: destino exclusivo del PDF consolidado final. Es opcional: si no
  está configurado, el proceso sigue escribiendo en Operaciones como hasta ahora.

Para cada contexto el sitio puede resolverse de dos maneras:

1. Por ``hostname`` + ruta del sitio (``/sites/{host}:/sites/{nombre}``). Es la forma
   determinista y la recomendada en producción.
2. Por búsqueda de texto (``/sites?search=``), que es el mecanismo histórico y se
   conserva para no romper el ambiente de pruebas actual.
"""

from __future__ import annotations

import logging
import os
from urllib.parse import parse_qsl, quote, urlencode, urlsplit, urlunsplit

from app.domain.exceptions import GraphConfigError
from app.domain.ports.graph import GraphApiPort

logger = logging.getLogger(__name__)

ENV_SITE_SEARCH = "GRAPH_SHAREPOINT_SITE_SEARCH"
ENV_DRIVE_NAME = "GRAPH_SHAREPOINT_DRIVE_NAME"
ENV_FILE_PATH = "GRAPH_SHAREPOINT_FILE_PATH"

ENV_OPERATIONS_SITE_HOSTNAME = "GRAPH_OPERATIONS_SITE_HOSTNAME"
ENV_OPERATIONS_SITE_PATH = "GRAPH_OPERATIONS_SITE_PATH"
ENV_OPERATIONS_DRIVE_NAME = "GRAPH_OPERATIONS_DRIVE_NAME"

ENV_ACCOUNTING_SITE_HOSTNAME = "GRAPH_ACCOUNTING_SITE_HOSTNAME"
ENV_ACCOUNTING_SITE_PATH = "GRAPH_ACCOUNTING_SITE_PATH"
ENV_ACCOUNTING_DRIVE_NAME = "GRAPH_ACCOUNTING_DRIVE_NAME"


def _env(key: str) -> str:
    return os.getenv(key, "").strip()


def encode_graph_drive_path(relative_path: str) -> str:
    trimmed = relative_path.strip().strip("/")
    if not trimmed:
        raise GraphConfigError("Path must not be empty.")
    parts = [p for p in trimmed.split("/") if p]
    return "/".join(quote(part, safe="") for part in parts)


def _site_lookup_url(hostname: str, site_path: str) -> str:
    """Construye ``/sites/{hostname}:/sites/{nombre}`` tolerando barras sobrantes."""
    host = hostname.strip().strip("/")
    path = site_path.strip().strip("/")
    return f"/sites/{host}:/{path}"


async def _resolve_site_id_by_hostname(
    client: GraphApiPort, hostname: str, site_path: str
) -> str:
    url = _site_lookup_url(hostname, site_path)
    try:
        response = await client.get(url)
    except Exception as exc:
        raise GraphConfigError(
            f"No se pudo resolver el sitio de SharePoint en {url}: {exc}"
        ) from exc
    site_id = str((response or {}).get("id") or "")
    if not site_id:
        raise GraphConfigError(f"No SharePoint site found for {url}")
    return site_id


async def _resolve_site_id_by_search(client: GraphApiPort, site_search: str) -> str:
    sites = await client.get("/sites", params={"search": site_search})
    values = sites.get("value") or []
    if not values:
        raise GraphConfigError(f"No SharePoint site found for search: {site_search!r}")
    if len(values) > 1:
        wanted = site_search.strip().casefold()
        exact = next(
            (
                v
                for v in values
                if str(v.get("name") or "").strip().casefold() == wanted
                or str(v.get("displayName") or "").strip().casefold() == wanted
            ),
            None,
        )
        if exact is not None:
            return str(exact["id"])
        logger.warning(
            "La búsqueda de sitio %r devolvió %d resultados y ninguno coincide de forma "
            "exacta; se usa el primero (%r). Configure %s y %s para una resolución "
            "determinista.",
            site_search,
            len(values),
            values[0].get("name"),
            ENV_OPERATIONS_SITE_HOSTNAME,
            ENV_OPERATIONS_SITE_PATH,
        )
    return str(values[0]["id"])


async def _resolve_drive_id(client: GraphApiPort, site_id: str, drive_name: str) -> str:
    drives_resp = await client.get(f"/sites/{site_id}/drives")
    drives = drives_resp.get("value") or []
    if not drives:
        raise GraphConfigError(f"No drives found for site id {site_id!r}")
    if not drive_name:
        return str(drives[0]["id"])

    match = next((d for d in drives if d.get("name") == drive_name), None)
    if match is None:
        # Segunda pasada tolerante a mayúsculas y espacios sobrantes.
        wanted = drive_name.strip().casefold()
        match = next(
            (d for d in drives if str(d.get("name") or "").strip().casefold() == wanted),
            None,
        )
        if match is not None:
            logger.warning(
                "La biblioteca %r coincidió ignorando mayúsculas con %r.",
                drive_name,
                match.get("name"),
            )
    if match is None:
        raise GraphConfigError(
            f"No drive named {drive_name!r}; available: "
            f"{[d.get('name') for d in drives]}"
        )
    return str(match["id"])


def operations_site_is_configured() -> bool:
    """True si el sitio de Operaciones puede resolverse con la configuración actual."""
    if _env(ENV_OPERATIONS_SITE_HOSTNAME) and _env(ENV_OPERATIONS_SITE_PATH):
        return True
    return bool(_env(ENV_SITE_SEARCH))


def require_operations_site_config() -> None:
    """Valida que exista alguna forma de resolver el sitio de Operaciones."""
    if operations_site_is_configured():
        return
    raise GraphConfigError(
        "Missing environment variable: "
        f"{ENV_SITE_SEARCH} (o bien {ENV_OPERATIONS_SITE_HOSTNAME} y "
        f"{ENV_OPERATIONS_SITE_PATH})"
    )


async def resolve_sharepoint_path(
    client: GraphApiPort, site_search: str, drive_name: str, path: str
) -> dict[str, str]:
    """
    Resuelve una ruta dentro del sitio de Operaciones.

    Prioriza ``GRAPH_OPERATIONS_SITE_HOSTNAME`` / ``GRAPH_OPERATIONS_SITE_PATH`` cuando
    están definidos; si no, usa la búsqueda por texto recibida en ``site_search``.
    """
    if not path:
        raise GraphConfigError("Missing sharepoint path")

    path_encoded = encode_graph_drive_path(path)

    hostname = _env(ENV_OPERATIONS_SITE_HOSTNAME)
    site_path = _env(ENV_OPERATIONS_SITE_PATH)
    if hostname and site_path:
        site_id = await _resolve_site_id_by_hostname(client, hostname, site_path)
    else:
        if not site_search:
            raise GraphConfigError("Missing site_search")
        site_id = await _resolve_site_id_by_search(client, site_search)

    effective_drive_name = _env(ENV_OPERATIONS_DRIVE_NAME) or drive_name
    drive_id = await _resolve_drive_id(client, site_id, effective_drive_name)

    return {
        "site_id": site_id,
        "drive_id": drive_id,
        "path_encoded": path_encoded,
        "file_path": path,
    }


async def resolve_sharepoint_from_env(client: GraphApiPort) -> dict[str, str]:
    """Resuelve el contexto de Operaciones apoyándose en la ruta por defecto del entorno."""
    site_search = _env(ENV_SITE_SEARCH)
    file_path = _env(ENV_FILE_PATH)
    drive_name = _env(ENV_DRIVE_NAME)

    if not file_path:
        raise GraphConfigError(f"Missing environment variable: {ENV_FILE_PATH}")
    require_operations_site_config()

    return await resolve_sharepoint_path(client, site_search, drive_name, file_path)


def accounting_site_is_configured() -> bool:
    """
    True solo si se configuró explícitamente el sitio de Contabilidad.

    Mientras sea False, el PDF consolidado se sigue guardando en Operaciones, que es el
    comportamiento del ambiente de pruebas actual.
    """
    return bool(_env(ENV_ACCOUNTING_SITE_HOSTNAME) and _env(ENV_ACCOUNTING_SITE_PATH))


async def resolve_accounting_context(client: GraphApiPort) -> dict[str, str]:
    """Resuelve sitio y biblioteca de Contabilidad. Requiere configuración explícita."""
    hostname = _env(ENV_ACCOUNTING_SITE_HOSTNAME)
    site_path = _env(ENV_ACCOUNTING_SITE_PATH)
    if not hostname or not site_path:
        raise GraphConfigError(
            "Missing environment variables: "
            f"{ENV_ACCOUNTING_SITE_HOSTNAME}, {ENV_ACCOUNTING_SITE_PATH}"
        )

    site_id = await _resolve_site_id_by_hostname(client, hostname, site_path)
    drive_id = await _resolve_drive_id(client, site_id, _env(ENV_ACCOUNTING_DRIVE_NAME))
    return {"site_id": site_id, "drive_id": drive_id}


def sharepoint_open_in_browser_url(url: str | None) -> str:
    """
    Fuerza apertura en el navegador (Excel/Word Online) en lugar de descargar.

    Los ``webUrl`` directos a ``.xlsx`` suelen provocar descarga desde el correo;
    ``web=1`` es el parámetro documentado por Microsoft/SharePoint para abrir en web.
    """
    raw = str(url or "").strip()
    if not raw:
        return ""
    lower = raw.lower()
    if not (lower.startswith("http://") or lower.startswith("https://")):
        return raw

    parts = urlsplit(raw)
    query_pairs = [
        (k, v)
        for k, v in parse_qsl(parts.query, keep_blank_values=True)
        if k.lower() not in ("download", "web")
    ]
    query_pairs.append(("web", "1"))
    return urlunsplit(
        (parts.scheme, parts.netloc, parts.path, urlencode(query_pairs), parts.fragment)
    )


def describe_sharepoint_config() -> dict[str, object]:
    """Resumen de configuración de sitios para diagnóstico. No contiene secretos."""
    return {
        "operations": {
            "configured": operations_site_is_configured(),
            "resolution": (
                "hostname_path"
                if _env(ENV_OPERATIONS_SITE_HOSTNAME) and _env(ENV_OPERATIONS_SITE_PATH)
                else "site_search"
            ),
            "site_hostname": _env(ENV_OPERATIONS_SITE_HOSTNAME),
            "site_path": _env(ENV_OPERATIONS_SITE_PATH),
            "site_search": _env(ENV_SITE_SEARCH),
            "drive_name": _env(ENV_OPERATIONS_DRIVE_NAME) or _env(ENV_DRIVE_NAME),
        },
        "accounting": {
            "configured": accounting_site_is_configured(),
            "site_hostname": _env(ENV_ACCOUNTING_SITE_HOSTNAME),
            "site_path": _env(ENV_ACCOUNTING_SITE_PATH),
            "drive_name": _env(ENV_ACCOUNTING_DRIVE_NAME),
        },
    }
