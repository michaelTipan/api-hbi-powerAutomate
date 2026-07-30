"""Caso de uso: iniciar campaña + procesar exactamente un chunk."""

from __future__ import annotations

from app.application.services.extract_index.bootstrap_campaign import (
    BootstrapCampaignService,
)
from app.application.services.extract_index.bootstrap_models import (
    CampaignScopeKey,
    ChunkResult,
)
from app.domain.models.extract_index import BootstrapControlRecord, ExtractIndexEnvironment


async def start_bootstrap_campaign(
    service: BootstrapCampaignService,
    scope_key: CampaignScopeKey,
) -> BootstrapControlRecord:
    """Inicia (o reutiliza) una campaña técnica idempotente por ámbito."""
    return await service.start_campaign(scope_key)


async def process_bootstrap_chunk(
    service: BootstrapCampaignService,
    *,
    environment: ExtractIndexEnvironment,
    campaign_id: str,
    expected_drive_id: str | None = None,
) -> ChunkResult:
    """Procesa exactamente un chunk; no autoencadena el siguiente."""
    return await service.process_one_chunk(
        environment=environment,
        campaign_id=campaign_id,
        expected_drive_id=expected_drive_id,
    )
