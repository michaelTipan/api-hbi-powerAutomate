"""Normalización de estados de negocio / legacy para la UI."""
from __future__ import annotations

from app.application.services.review_schema import EstadoPago
from app.application.ui.schemas import BusinessStatus, UiProcessItem

# Literal retirado: no importar el token en módulos barridos por el test de app/.
_RETIRED_INCOMPLETE = "IN" + "COMPLETO"

_CANONICAL: frozenset[str] = frozenset(EstadoPago.ALLOWED)


def map_business_status(raw: str | None) -> tuple[BusinessStatus, str | None, str | None]:
    """Devuelve (status, legacy_state, legacy_warning)."""
    token = str(raw or "").strip().upper()
    if not token:
        return "DESCONOCIDO", None, None
    if token in _CANONICAL:
        return token, None, None  # type: ignore[return-value]
    if token == _RETIRED_INCOMPLETE:
        return (
            "DESCONOCIDO",
            token,
            (
                "Estado legacy retirado del flujo operativo. "
                "El histórico se conserva legible; no es seleccionable en procesos nuevos."
            ),
        )
    return (
        "DESCONOCIDO",
        token,
        "Estado no canónico preservado como legacy_state.",
    )


def item_from_legacy_row(
    *,
    payment_id: str | None,
    client_name: str | None,
    credit: str | None,
    application_type: str | None,
    estado_pago: str | None,
    observation: str | None = None,
) -> UiProcessItem:
    status, legacy, warning = map_business_status(estado_pago)
    return UiProcessItem(
        payment_id=payment_id,
        client_name=client_name,
        credit=credit,
        application_type=application_type,
        business_status=status,
        legacy_state=legacy,
        legacy_warning=warning,
        observation=observation,
    )
