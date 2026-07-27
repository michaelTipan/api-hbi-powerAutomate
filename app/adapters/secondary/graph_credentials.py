"""
Proveedor de credenciales de Microsoft Graph.

Dos fuentes seleccionables mediante ``GRAPH_CREDENTIAL_SOURCE``:

- ``env`` (defecto): lee ``GRAPH_TENANT_ID`` / ``GRAPH_CLIENT_ID`` / ``GRAPH_CLIENT_SECRET``.
  Pensado para desarrollo local y para el ambiente de pruebas actual.
- ``key_vault``: lee los tres secretos desde Azure Key Vault usando la identidad
  administrada del App Service. Pensado para producción, donde los valores en texto
  plano no se entregan al equipo de desarrollo.

La lectura es perezosa: nunca ocurre al importar el módulo ni al construir la app.
Esto garantiza que ``/health`` siga respondiendo aunque las credenciales estén mal
configuradas o Key Vault no esté disponible.
"""

from __future__ import annotations

import asyncio
import logging
import os
import threading
from dataclasses import dataclass

from app.domain.exceptions import GraphConfigError

logger = logging.getLogger(__name__)

CREDENTIAL_SOURCE_ENV = "env"
CREDENTIAL_SOURCE_KEY_VAULT = "key_vault"

ENV_CREDENTIAL_SOURCE = "GRAPH_CREDENTIAL_SOURCE"

ENV_TENANT_ID = "GRAPH_TENANT_ID"
ENV_CLIENT_ID = "GRAPH_CLIENT_ID"
ENV_CLIENT_SECRET = "GRAPH_CLIENT_SECRET"

ENV_KEY_VAULT_URI = "GRAPH_KEY_VAULT_URI"
ENV_KEY_VAULT_CLIENT_ID_SECRET_NAME = "GRAPH_KEY_VAULT_CLIENT_ID_SECRET_NAME"
ENV_KEY_VAULT_CLIENT_SECRET_SECRET_NAME = "GRAPH_KEY_VAULT_CLIENT_SECRET_SECRET_NAME"
ENV_KEY_VAULT_TENANT_ID_SECRET_NAME = "GRAPH_KEY_VAULT_TENANT_ID_SECRET_NAME"


@dataclass(frozen=True)
class GraphCredentials:
    """Credenciales de aplicación para el flujo client_credentials."""

    tenant_id: str
    client_id: str
    client_secret: str


_cache_lock = threading.Lock()
_key_vault_cache: GraphCredentials | None = None


def _env(key: str) -> str:
    return os.getenv(key, "").strip()


def resolve_credential_source() -> str:
    """Fuente configurada. Cualquier valor desconocido se trata como ``env``."""
    raw = _env(ENV_CREDENTIAL_SOURCE).lower()
    if raw == CREDENTIAL_SOURCE_KEY_VAULT:
        return CREDENTIAL_SOURCE_KEY_VAULT
    if raw and raw != CREDENTIAL_SOURCE_ENV:
        logger.warning(
            "%s=%r no reconocido; se usa %r.",
            ENV_CREDENTIAL_SOURCE,
            raw,
            CREDENTIAL_SOURCE_ENV,
        )
    return CREDENTIAL_SOURCE_ENV


def reset_credentials_cache() -> None:
    """Invalida la caché de Key Vault. Útil en pruebas y tras rotar secretos."""
    global _key_vault_cache
    with _cache_lock:
        _key_vault_cache = None


def _missing_env_credentials() -> list[str]:
    return [
        key
        for key in (ENV_TENANT_ID, ENV_CLIENT_ID, ENV_CLIENT_SECRET)
        if not _env(key)
    ]


def _missing_key_vault_settings() -> list[str]:
    return [
        key
        for key in (
            ENV_KEY_VAULT_URI,
            ENV_KEY_VAULT_CLIENT_ID_SECRET_NAME,
            ENV_KEY_VAULT_CLIENT_SECRET_SECRET_NAME,
            ENV_KEY_VAULT_TENANT_ID_SECRET_NAME,
        )
        if not _env(key)
    ]


def _load_from_env() -> GraphCredentials:
    missing = _missing_env_credentials()
    if missing:
        raise GraphConfigError(
            f"Missing environment variables for Graph: {', '.join(missing)}"
        )
    return GraphCredentials(
        tenant_id=_env(ENV_TENANT_ID),
        client_id=_env(ENV_CLIENT_ID),
        client_secret=_env(ENV_CLIENT_SECRET),
    )


def _read_key_vault_secrets() -> GraphCredentials:
    """Lee los tres secretos del Vault. Llamada bloqueante: ejecutar fuera del event loop."""
    try:
        from azure.core.exceptions import ClientAuthenticationError, HttpResponseError
        from azure.identity import DefaultAzureCredential
        from azure.keyvault.secrets import SecretClient
    except ImportError as exc:
        raise GraphConfigError(
            "GRAPH_CREDENTIAL_SOURCE=key_vault requiere los paquetes azure-identity y "
            f"azure-keyvault-secrets, que no están instalados: {exc}"
        ) from exc

    vault_uri = _env(ENV_KEY_VAULT_URI)
    name_client_id = _env(ENV_KEY_VAULT_CLIENT_ID_SECRET_NAME)
    name_client_secret = _env(ENV_KEY_VAULT_CLIENT_SECRET_SECRET_NAME)
    name_tenant_id = _env(ENV_KEY_VAULT_TENANT_ID_SECRET_NAME)

    try:
        credential = DefaultAzureCredential()
        secret_client = SecretClient(vault_url=vault_uri, credential=credential)
        tenant_id = (secret_client.get_secret(name_tenant_id).value or "").strip()
        client_id = (secret_client.get_secret(name_client_id).value or "").strip()
        client_secret = (secret_client.get_secret(name_client_secret).value or "").strip()
    except ClientAuthenticationError as exc:
        raise GraphConfigError(
            "No se pudo autenticar contra Key Vault. Verifique que el App Service tenga "
            "identidad administrada habilitada. "
            f"Vault: {vault_uri}. Detalle: {exc.__class__.__name__}"
        ) from exc
    except HttpResponseError as exc:
        status = getattr(exc, "status_code", None)
        if status == 403:
            raise GraphConfigError(
                "Key Vault respondió 403 Forbidden: la identidad administrada del App "
                "Service no tiene permiso de lectura sobre los secretos. Solicite el rol "
                f"'Key Vault Secrets User' sobre {vault_uri}."
            ) from exc
        if status == 404:
            raise GraphConfigError(
                "Key Vault respondió 404: alguno de los secretos no existe con el nombre "
                f"configurado ({name_tenant_id}, {name_client_id}, {name_client_secret}) "
                f"en {vault_uri}."
            ) from exc
        raise GraphConfigError(
            f"Error consultando Key Vault {vault_uri} (HTTP {status}): {exc.__class__.__name__}"
        ) from exc
    except Exception as exc:
        raise GraphConfigError(
            f"No se pudieron leer las credenciales desde Key Vault {vault_uri}: "
            f"{exc.__class__.__name__}"
        ) from exc

    missing = [
        name
        for name, value in (
            (name_tenant_id, tenant_id),
            (name_client_id, client_id),
            (name_client_secret, client_secret),
        )
        if not value
    ]
    if missing:
        raise GraphConfigError(
            f"Key Vault devolvió valores vacíos para: {', '.join(missing)}."
        )

    logger.info("Credenciales de Graph cargadas desde Key Vault %s.", vault_uri)
    return GraphCredentials(
        tenant_id=tenant_id,
        client_id=client_id,
        client_secret=client_secret,
    )


def _load_from_key_vault() -> GraphCredentials:
    global _key_vault_cache
    with _cache_lock:
        if _key_vault_cache is not None:
            return _key_vault_cache

    missing = _missing_key_vault_settings()
    if missing:
        raise GraphConfigError(
            f"Missing environment variables for Key Vault: {', '.join(missing)}"
        )

    credentials = _read_key_vault_secrets()
    with _cache_lock:
        _key_vault_cache = credentials
    return credentials


def get_graph_credentials() -> GraphCredentials:
    """Devuelve las credenciales según la fuente configurada. Puede bloquear en Key Vault."""
    if resolve_credential_source() == CREDENTIAL_SOURCE_KEY_VAULT:
        return _load_from_key_vault()
    return _load_from_env()


async def get_graph_credentials_async() -> GraphCredentials:
    """
    Versión no bloqueante. Solo delega a un hilo la primera lectura de Key Vault;
    el modo ``env`` y las lecturas cacheadas se resuelven en el mismo hilo.
    """
    if resolve_credential_source() != CREDENTIAL_SOURCE_KEY_VAULT:
        return _load_from_env()
    with _cache_lock:
        cached = _key_vault_cache
    if cached is not None:
        return cached
    return await asyncio.to_thread(_load_from_key_vault)


def describe_credential_config() -> dict[str, object]:
    """
    Resumen de configuración sin exponer secretos. Solo informa qué está definido
    y con qué nombres, nunca los valores.
    """
    source = resolve_credential_source()
    if source == CREDENTIAL_SOURCE_KEY_VAULT:
        missing = _missing_key_vault_settings()
        with _cache_lock:
            cached = _key_vault_cache is not None
        return {
            "source": source,
            "configured": not missing,
            "missing_settings": missing,
            "key_vault_uri": _env(ENV_KEY_VAULT_URI),
            "secret_names": {
                "tenant_id": _env(ENV_KEY_VAULT_TENANT_ID_SECRET_NAME),
                "client_id": _env(ENV_KEY_VAULT_CLIENT_ID_SECRET_NAME),
                "client_secret": _env(ENV_KEY_VAULT_CLIENT_SECRET_SECRET_NAME),
            },
            "cached": cached,
        }
    missing = _missing_env_credentials()
    return {
        "source": source,
        "configured": not missing,
        "missing_settings": missing,
        "key_vault_uri": "",
        "secret_names": {},
        "cached": False,
    }
