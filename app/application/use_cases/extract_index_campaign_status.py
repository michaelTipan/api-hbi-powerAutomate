"""Caso de uso: estado / pause / resume / cancel de campaña bootstrap."""

from __future__ import annotations

from app.application.services.extract_index.bootstrap_campaign import (
    BootstrapCampaignService,
)
from app.domain.models.extract_index import BootstrapControlRecord, ExtractIndexEnvironment


async def get_bootstrap_campaign_status(
    service: BootstrapCampaignService,
    *,
    environment: ExtractIndexEnvironment,
    campaign_id: str,
) -> BootstrapControlRecord | None:
    return await service.get_status(environment=environment, campaign_id=campaign_id)


async def pause_bootstrap_campaign(
    service: BootstrapCampaignService,
    *,
    environment: ExtractIndexEnvironment,
    campaign_id: str,
) -> BootstrapControlRecord:
    return await service.pause(environment=environment, campaign_id=campaign_id)


async def resume_bootstrap_campaign(
    service: BootstrapCampaignService,
    *,
    environment: ExtractIndexEnvironment,
    campaign_id: str,
) -> BootstrapControlRecord:
    return await service.resume(environment=environment, campaign_id=campaign_id)


async def request_bootstrap_cancellation(
    service: BootstrapCampaignService,
    *,
    environment: ExtractIndexEnvironment,
    campaign_id: str,
) -> BootstrapControlRecord:
    return await service.request_cancellation(
        environment=environment, campaign_id=campaign_id
    )
