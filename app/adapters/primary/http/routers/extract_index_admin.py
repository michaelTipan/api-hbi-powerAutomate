"""
Router admin del índice de extractos (Fase 3A2).

Contratos HTTP listos; **no** se monta en ``app_factory`` en esta rama.
Los tests montan el router en una app de prueba con fakes.
"""

from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field

from app.adapters.primary.http.extract_index_admin_deps import (
    ExtractIndexAdminState,
    assert_bootstrap_admin_gates,
    assert_environment_matches_runtime,
    get_extract_index_admin_state,
    parse_environment,
    sanitize_error_text,
)
from app.application.services.extract_index.bootstrap_models import (
    BOOTSTRAP_PARSER_VERSION,
    BOOTSTRAP_SCHEMA_VERSION,
    CampaignScopeKey,
    CampaignTotals,
    LogicalPreflightResult,
)
from app.application.use_cases.bootstrap_extract_index_chunk import (
    process_bootstrap_chunk,
    start_bootstrap_campaign,
)
from app.application.use_cases.extract_index_campaign_status import (
    get_bootstrap_campaign_status,
    pause_bootstrap_campaign,
    request_bootstrap_cancellation,
    resume_bootstrap_campaign,
)
from app.application.use_cases.extract_index_preflight import run_extract_index_preflight
from app.domain.exceptions import (
    BootstrapCampaignError,
    BootstrapDriveMismatch,
    BootstrapEnvironmentMismatch,
    BootstrapSecurityViolation,
    BootstrapVersionMismatch,
    DocumentMutationForbidden,
    ExtractIndexError,
)
from app.domain.models.extract_index import BootstrapControlRecord, CampaignStatus
from fastapi import HTTPException

router = APIRouter(prefix="/extract-index/admin", tags=["extract-index-admin"])


class StartCampaignBody(BaseModel):
    environment: Literal["sandbox", "production"]
    drive_id: str = Field(min_length=1, max_length=200)
    root_identity: str = Field(min_length=1, max_length=500)
    parser_version: str = Field(default=BOOTSTRAP_PARSER_VERSION, max_length=32)
    schema_version: str = Field(default=BOOTSTRAP_SCHEMA_VERSION, max_length=32)


class ProcessChunkBody(BaseModel):
    environment: Literal["sandbox", "production"]
    expected_drive_id: str | None = Field(default=None, max_length=200)


class CampaignActionBody(BaseModel):
    environment: Literal["sandbox", "production"]


class CampaignEnvelope(BaseModel):
    campaign_id: str
    chunk_id: str = ""
    status: str
    checkpoint: str = ""
    continuation_required: bool = False
    paused: bool = False
    completed: bool = False
    cancellation_requested: bool = False
    security_violation: bool = False
    error_summary: str = ""
    current_client: str = ""
    current_credit: str = ""
    environment: str
    drive_id: str = ""
    heartbeat: str | None = None
    totals: dict[str, Any] = Field(default_factory=dict)


class ChunkEnvelope(CampaignEnvelope):
    stop_reason: str = ""
    credits_confirmed: int = 0
    credits_attempted: int = 0
    credits_skipped_locked: int = 0
    elapsed_seconds: float = 0.0


class PreflightEnvelope(BaseModel):
    ok: bool
    issues: list[str]
    capabilities: dict[str, Any]


def _admin(request: Request) -> ExtractIndexAdminState:
    state = get_extract_index_admin_state(request)
    assert_bootstrap_admin_gates(state.settings)
    return state


def _record_to_envelope(record: BootstrapControlRecord) -> CampaignEnvelope:
    totals = CampaignTotals.from_json(record.totals_json)
    return CampaignEnvelope(
        campaign_id=record.campaign_id,
        chunk_id=record.chunk_id,
        status=record.status.value,
        checkpoint=record.checkpoint,
        continuation_required=record.continuation_required,
        paused=record.paused,
        completed=record.completed,
        cancellation_requested=record.cancellation_requested,
        security_violation=totals.security_violation,
        error_summary=sanitize_error_text(record.error_summary),
        current_client=record.current_client,
        current_credit=record.current_credit,
        environment=record.environment.value,
        drive_id=totals.drive_id,
        heartbeat=record.heartbeat.isoformat() if record.heartbeat else None,
        totals={
            "credits_processed": totals.credits_processed,
            "credits_skipped_locked": totals.credits_skipped_locked,
            "credits_failed": totals.credits_failed,
            "credits_parse_error": totals.credits_parse_error,
            "upserts_ok": totals.upserts_ok,
            "chunks_run": totals.chunks_run,
            "security_violation": totals.security_violation,
            "parser_version": totals.parser_version,
            "schema_version": totals.schema_version,
            # sin call_order_trace ni last_error crudo completo
        },
    )


def _map_domain_error(exc: Exception) -> HTTPException:
    if isinstance(exc, DocumentMutationForbidden | BootstrapSecurityViolation):
        return HTTPException(
            status_code=409,
            detail={
                "code": "security_violation",
                "message": sanitize_error_text(str(exc)),
            },
        )
    if isinstance(exc, BootstrapEnvironmentMismatch):
        return HTTPException(
            status_code=409,
            detail={"code": "environment_mismatch", "message": sanitize_error_text(str(exc))},
        )
    if isinstance(exc, BootstrapDriveMismatch):
        return HTTPException(
            status_code=409,
            detail={"code": "drive_mismatch", "message": sanitize_error_text(str(exc))},
        )
    if isinstance(exc, BootstrapVersionMismatch):
        return HTTPException(
            status_code=409,
            detail={"code": "version_mismatch", "message": sanitize_error_text(str(exc))},
        )
    if isinstance(exc, BootstrapCampaignError):
        return HTTPException(
            status_code=404,
            detail={"code": "campaign_error", "message": sanitize_error_text(str(exc))},
        )
    if isinstance(exc, ExtractIndexError):
        return HTTPException(
            status_code=400,
            detail={"code": "extract_index_error", "message": sanitize_error_text(str(exc))},
        )
    return HTTPException(
        status_code=500,
        detail={"code": "internal_error", "message": "error_sanitized"},
    )


@router.post("/preflight", response_model=PreflightEnvelope)
async def preflight_admin(
    state: ExtractIndexAdminState = Depends(_admin),
) -> PreflightEnvelope:
    """Preflight lógico (3A2); sin Graph remoto aún."""
    wiring = state.wiring
    result: LogicalPreflightResult = run_extract_index_preflight(
        settings=state.settings,
        has_control_repo=True,
        has_index_repo=True,
        has_lock=wiring.lock is not None,
        has_scope=wiring.scope is not None,
        has_readonly_tree=wiring.document_tree is not None,
        control_schema_ok=True,
        index_schema_ok=True,
    )
    return PreflightEnvelope(
        ok=result.ok, issues=list(result.issues), capabilities=dict(result.capabilities)
    )


@router.post("/campaigns/start", response_model=CampaignEnvelope)
async def start_campaign_admin(
    body: StartCampaignBody,
    state: ExtractIndexAdminState = Depends(_admin),
) -> CampaignEnvelope:
    env = parse_environment(body.environment)
    assert_environment_matches_runtime(env, state.settings)
    scope_key = CampaignScopeKey(
        environment=env,
        drive_id=body.drive_id.strip(),
        root_identity=body.root_identity.strip(),
        parser_version=body.parser_version.strip() or BOOTSTRAP_PARSER_VERSION,
        schema_version=body.schema_version.strip() or BOOTSTRAP_SCHEMA_VERSION,
    )
    try:
        record = await start_bootstrap_campaign(state.service, scope_key)
    except Exception as exc:  # noqa: BLE001 — mapeo HTTP
        raise _map_domain_error(exc) from exc
    return _record_to_envelope(record)


@router.post("/campaigns/{campaign_id}/chunks", response_model=ChunkEnvelope)
async def process_one_chunk_admin(
    campaign_id: str,
    body: ProcessChunkBody,
    state: ExtractIndexAdminState = Depends(_admin),
) -> ChunkEnvelope:
    """Procesa exactamente un chunk; no autoencadena."""
    env = parse_environment(body.environment)
    assert_environment_matches_runtime(env, state.settings)
    try:
        chunk = await process_bootstrap_chunk(
            state.service,
            environment=env,
            campaign_id=campaign_id,
            expected_drive_id=body.expected_drive_id,
        )
        record = await get_bootstrap_campaign_status(
            state.service, environment=env, campaign_id=campaign_id
        )
    except Exception as exc:  # noqa: BLE001
        raise _map_domain_error(exc) from exc
    if record is None:
        raise HTTPException(
            status_code=404,
            detail={"code": "campaign_not_found", "message": campaign_id},
        )
    base = _record_to_envelope(record)
    payload = base.model_dump()
    payload.update(
        {
            "stop_reason": chunk.stop_reason.value,
            "credits_confirmed": chunk.credits_confirmed,
            "credits_attempted": chunk.credits_attempted,
            "credits_skipped_locked": chunk.credits_skipped_locked,
            "elapsed_seconds": round(chunk.elapsed_seconds, 3),
            "continuation_required": chunk.continuation_required,
            "status": chunk.status.value,
            "chunk_id": chunk.chunk_id,
            "security_violation": chunk.security_violation,
            "error_summary": sanitize_error_text(
                chunk.error_summary or record.error_summary
            ),
        }
    )
    return ChunkEnvelope(**payload)


@router.get("/campaigns/{campaign_id}", response_model=CampaignEnvelope)
async def get_campaign_status_admin(
    campaign_id: str,
    environment: Literal["sandbox", "production"],
    state: ExtractIndexAdminState = Depends(_admin),
) -> CampaignEnvelope:
    env = parse_environment(environment)
    assert_environment_matches_runtime(env, state.settings)
    try:
        record = await get_bootstrap_campaign_status(
            state.service, environment=env, campaign_id=campaign_id
        )
    except Exception as exc:  # noqa: BLE001
        raise _map_domain_error(exc) from exc
    if record is None:
        raise HTTPException(
            status_code=404,
            detail={"code": "campaign_not_found", "message": campaign_id},
        )
    # Defensa: el environment de la campaña debe coincidir
    if record.environment != env:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "environment_mismatch",
                "message": "campaign environment distinto al solicitado",
            },
        )
    return _record_to_envelope(record)


@router.post("/campaigns/{campaign_id}/pause", response_model=CampaignEnvelope)
async def pause_campaign_admin(
    campaign_id: str,
    body: CampaignActionBody,
    state: ExtractIndexAdminState = Depends(_admin),
) -> CampaignEnvelope:
    env = parse_environment(body.environment)
    assert_environment_matches_runtime(env, state.settings)
    try:
        record = await pause_bootstrap_campaign(
            state.service, environment=env, campaign_id=campaign_id
        )
    except Exception as exc:  # noqa: BLE001
        raise _map_domain_error(exc) from exc
    return _record_to_envelope(record)


@router.post("/campaigns/{campaign_id}/resume", response_model=CampaignEnvelope)
async def resume_campaign_admin(
    campaign_id: str,
    body: CampaignActionBody,
    state: ExtractIndexAdminState = Depends(_admin),
) -> CampaignEnvelope:
    env = parse_environment(body.environment)
    assert_environment_matches_runtime(env, state.settings)
    try:
        record = await resume_bootstrap_campaign(
            state.service, environment=env, campaign_id=campaign_id
        )
    except Exception as exc:  # noqa: BLE001
        raise _map_domain_error(exc) from exc
    return _record_to_envelope(record)


@router.post("/campaigns/{campaign_id}/cancel", response_model=CampaignEnvelope)
async def cancel_campaign_admin(
    campaign_id: str,
    body: CampaignActionBody,
    state: ExtractIndexAdminState = Depends(_admin),
) -> CampaignEnvelope:
    env = parse_environment(body.environment)
    assert_environment_matches_runtime(env, state.settings)
    try:
        record = await request_bootstrap_cancellation(
            state.service, environment=env, campaign_id=campaign_id
        )
        # Cancelación limpia: un chunk vacío aplica el estado CANCELLED si ya marcado
        if record.status != CampaignStatus.CANCELLED:
            chunk = await process_bootstrap_chunk(
                state.service, environment=env, campaign_id=campaign_id
            )
            record = await get_bootstrap_campaign_status(
                state.service, environment=env, campaign_id=campaign_id
            )
            if record is None:
                raise HTTPException(
                    status_code=404,
                    detail={"code": "campaign_not_found", "message": campaign_id},
                )
            # Si el process devolvió cancelled, usamos ese estado
            _ = chunk
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001
        raise _map_domain_error(exc) from exc
    return _record_to_envelope(record)
