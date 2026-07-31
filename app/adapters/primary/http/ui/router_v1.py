"""Router UI v1. Montado desde create_app cuando UI_ENABLED."""
from __future__ import annotations

import uuid
from typing import Any, Callable
from urllib.parse import unquote

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Request, Response

from app.adapters.primary.http.deps import GraphClientDep
from app.adapters.primary.http.ui.deps import require_ui_enabled
from app.adapters.primary.http.ui.write_deps import (
    require_finalize_access,
    require_merge_access,
    require_notify_access,
    require_write_access,
)
from app.application.job_manager import get_job_manager
from app.application.job_status_enrichment import enrich_job_for_http_response
from app.application.services.finalize_queue_service import (
    FinalizeQueueBusyError,
    FinalizeQueueValidationError,
    get_finalize_queue_service,
)
from app.application.services.generate_queue_service import (
    GenerateQueueBusyError,
    GenerateQueueValidationError,
    get_generate_queue_service,
)
from app.application.services.merge_queue_service import (
    MergeAlreadyMergedError,
    MergeQueueBusyError,
    get_merge_queue_service,
)
from app.application.services.notify_queue_service import (
    NotifyAlreadyNotifiedError,
    NotifyQueueBusyError,
    get_notify_queue_service,
)
from app.application.ui.entra_config import resolve_entra_spa_config
from app.application.ui.environment import resolve_active_environment
from app.application.ui.feature_flags import get_ui_feature_flags
from app.application.ui.finalize_resolve import (
    FinalizeProcessIdentityError,
    resolve_finalize_target_from_control,
)
from app.application.ui.generate_capabilities import compute_generate_availability
from app.application.ui.job_read import read_any_job
from app.application.ui.download_limits import UiDownloadTooLargeError
from app.application.ui.local_auth import (
    GENERIC_LOGIN_FAILURE,
    AuthenticatedLocalUser,
    authenticate_local_credentials,
    clear_session_cookie,
    csrf_token_for_user,
    is_login_rate_limited,
    logout_request,
    me_payload,
    resolve_session_from_request,
    set_session_cookie,
    validate_csrf_header,
    validate_same_origin,
)
from app.application.ui.local_session_config import resolve_local_session_config
from app.application.ui.merge_readiness import assess_merge_readiness
from app.application.ui.merge_resolve import (
    MergeProcessIdentityError,
    resolve_merge_target_from_control,
)
from app.application.ui.notify_resolve import (
    NotifyProcessIdentityError,
    resolve_notify_target_from_control,
)
from app.application.ui.notify_sandbox_recipients import get_ui_notify_sandbox_recipients
from app.application.ui.path_guard import UiPathEscapeError
from app.application.ui.ports import UiSharePointReadPort
from app.application.ui.process_key import UiInvalidProcessKeyError, assert_ui_process_key
from app.application.ui.process_projection import PaymentProcessProjectionService
from app.application.ui.process_query import UiProcessQueryService
from app.application.ui.schemas import (
    UiActionAvailability,
    UiBankCapabilities,
    UiBootstrapResponse,
    UiCsrfResponse,
    UiEnvironmentResponse,
    UiErrorBody,
    UiGenerateAccepted,
    UiGenerateRequest,
    UiFinalizeAccepted,
    UiFinalizeRequest,
    UiJobView,
    UiLoginRequest,
    UiLoginResponse,
    UiLogoutResponse,
    UiMeResponse,
    UiMergeAccepted,
    UiMergeRequest,
    UiNotifyAccepted,
    UiNotifyRequest,
    UiProcessDetail,
    UiProcessListResponse,
    UiProcessSummary,
)
from app.application.use_cases.payment_validation_process_control import (
    ProcessControlSnapshot,
)

router = APIRouter(prefix="/api/ui/v1", tags=["ui-v1"])

KNOWN_BANKS: tuple[str, ...] = ("banco_bogota", "banco_bancolombia")
BANK_DISPLAY_NAMES: dict[str, str] = {
    "banco_bogota": "Banco de Bogotá",
    "banco_bancolombia": "Bancolombia",
}

_control_loader: Callable[[str], ProcessControlSnapshot] | None = None
_memory_job_lookup: Callable[[str], dict[str, Any] | None] | None = None
_sharepoint_reader: UiSharePointReadPort | None = None


def configure_ui_router(
    *,
    control_loader: Callable[[str], ProcessControlSnapshot] | None = None,
    memory_job_lookup: Callable[[str], dict[str, Any] | None] | None = None,
    sharepoint_reader: UiSharePointReadPort | None = None,
) -> None:
    """Inyecta puertos de lectura (producción / tests). Sin Graph mutante."""
    global _control_loader, _memory_job_lookup, _sharepoint_reader
    _control_loader = control_loader
    _memory_job_lookup = memory_job_lookup
    _sharepoint_reader = sharepoint_reader


# Alias histórico de tests U1.
configure_ui_router_for_tests = configure_ui_router


def reset_ui_router_test_hooks() -> None:
    configure_ui_router(
        control_loader=None,
        memory_job_lookup=None,
        sharepoint_reader=None,
    )


def _legacy_loader_detail(bank_code: str) -> UiProcessDetail:
    """Compat U1: control_loader síncrono sin puerto SharePoint."""
    if _control_loader is None:
        raise HTTPException(
            status_code=503,
            detail=UiErrorBody(
                error_code="ui_control_loader_unavailable",
                user_message=(
                    "La lectura de Control aún no está cableada. "
                    "Inyecte UiSharePointReadPort en tests o en integración."
                ),
                next_action="Usar FakeUiSharePointRead o el adaptador read-only.",
                severity="fatal",
            ).model_dump(),
        )
    snap = _control_loader(bank_code)
    if not (snap.process_key or "").strip() and not (snap.estado_proceso or "").strip():
        raise HTTPException(
            status_code=404,
            detail=UiErrorBody(
                error_code="process_not_found",
                user_message="No hay proceso activo para ese banco.",
                next_action="Verifique el banco o inicie Generate desde Power Automate.",
            ).model_dump(),
        )
    from app.application.ui.process_projection import ProjectionSources

    return PaymentProcessProjectionService().project(ProjectionSources(snapshot=snap))


async def _detail_for_bank(bank_code: str) -> UiProcessDetail:
    if _sharepoint_reader is not None:
        svc = UiProcessQueryService(
            _sharepoint_reader,
            memory_job_lookup=_memory_job_lookup,
        )
        try:
            return await svc.project_bank(bank_code)
        except UiPathEscapeError as exc:
            raise HTTPException(
                status_code=400,
                detail=UiErrorBody(
                    error_code="path_outside_environment_roots",
                    user_message="Ruta SharePoint fuera del ambiente activo.",
                    next_action="Verifique el overlay sandbox y los paths del control.",
                    severity="fatal",
                ).model_dump(),
            ) from exc
        except UiDownloadTooLargeError as exc:
            raise HTTPException(
                status_code=413,
                detail=UiErrorBody(
                    error_code="download_too_large",
                    user_message="El archivo de control o evidencia supera el límite de lectura UI.",
                    next_action="Contacte a soporte; no intente pasar rutas Graph desde el navegador.",
                    severity="fatal",
                ).model_dump(),
            ) from exc
        except KeyError:
            raise HTTPException(
                status_code=404,
                detail=UiErrorBody(
                    error_code="process_not_found",
                    user_message="No hay proceso activo para ese banco.",
                    next_action="Verifique el banco.",
                ).model_dump(),
            )
    return _legacy_loader_detail(bank_code)


@router.get("/bootstrap", response_model=UiBootstrapResponse)
async def get_bootstrap() -> UiBootstrapResponse:
    """Config pública sanitizada para la SPA (sin sesión / Bearer)."""
    require_ui_enabled()
    env = resolve_active_environment()
    flags = get_ui_feature_flags()
    finalize_allowed = (
        flags.finalize_allowed and env.environment == "sandbox"
    )
    recipients_configured = get_ui_notify_sandbox_recipients().configured
    notify_allowed = (
        flags.notify_allowed
        and env.environment == "sandbox"
        and recipients_configured
    )
    merge_allowed = flags.merge_allowed and env.environment == "sandbox"
    if flags.ui_auth_mode == "local_session":
        return UiBootstrapResponse(
            ui_enabled=flags.ui_enabled,
            writes_allowed=flags.writes_allowed,
            finalize_allowed=finalize_allowed,
            notify_allowed=notify_allowed,
            notify_test_recipients_configured=recipients_configured,
            merge_allowed=merge_allowed,
            active_environment=env.environment,
            display_label=env.display_label,
            auth_mode="local_session",
            login_required=True,
        )
    spa = resolve_entra_spa_config()
    return UiBootstrapResponse(
        ui_enabled=flags.ui_enabled,
        writes_allowed=flags.writes_allowed,
        finalize_allowed=finalize_allowed,
        notify_allowed=notify_allowed,
        notify_test_recipients_configured=recipients_configured,
        merge_allowed=merge_allowed,
        active_environment=env.environment,
        display_label=env.display_label,
        auth_mode=flags.ui_auth_mode,
        login_required=flags.ui_auth_mode == "entra",
        entra_authority=spa.authority,
        entra_spa_client_id=spa.spa_client_id,
        entra_api_scope=spa.api_scope,
    )


@router.post("/auth/login", response_model=UiLoginResponse)
async def post_login(
    body: UiLoginRequest,
    request: Request,
    response: Response,
) -> UiLoginResponse:
    require_ui_enabled()
    flags = get_ui_feature_flags()
    if flags.ui_auth_mode != "local_session":
        raise HTTPException(
            status_code=404,
            detail=UiErrorBody(
                error_code="login_not_available",
                user_message="El login local no está activo en este modo.",
                next_action="Use el modo de autenticación configurado.",
                severity="fatal",
            ).model_dump(),
        )
    if not validate_same_origin(request):
        raise HTTPException(
            status_code=403,
            detail=UiErrorBody(
                error_code="invalid_origin",
                user_message="Origen de la petición no permitido.",
                next_action="Acceda a la UI desde el mismo host de la aplicación.",
                severity="fatal",
            ).model_dump(),
        )
    if is_login_rate_limited(username=body.username, request=request):
        raise HTTPException(
            status_code=429,
            detail={
                "error_code": "login_rate_limited",
                "user_message": "Demasiados intentos. Intente más tarde.",
                "next_action": "Espere unos minutos e intente de nuevo.",
                "severity": "fatal",
            },
        )
    result = authenticate_local_credentials(
        username=body.username,
        password=body.password,
        request=request,
    )
    if result is None:
        raise HTTPException(status_code=401, detail=GENERIC_LOGIN_FAILURE)
    token, record = result
    cfg = resolve_local_session_config()
    set_session_cookie(response, token, cfg)
    return UiLoginResponse(
        authenticated=True,
        username=record.username,
        role=record.role,
        auth_mode="local_session",
    )


@router.post("/auth/logout", response_model=UiLogoutResponse)
async def post_logout(request: Request, response: Response) -> UiLogoutResponse:
    require_ui_enabled()
    if not validate_same_origin(request):
        raise HTTPException(
            status_code=403,
            detail=UiErrorBody(
                error_code="invalid_origin",
                user_message="Origen de la petición no permitido.",
                next_action="Acceda a la UI desde el mismo host de la aplicación.",
                severity="fatal",
            ).model_dump(),
        )
    # Logout es idempotente: sin sesión no hay CSRF que validar (nada que invalidar).
    # Con sesión activa, sí se exige X-CSRF-Token (todo POST autenticado lo requiere).
    user = getattr(request.state, "ui_local_user", None)
    if user is None:
        user = resolve_session_from_request(request)
    if user is not None and not validate_csrf_header(request, user):
        raise HTTPException(
            status_code=403,
            detail=UiErrorBody(
                error_code="invalid_csrf_token",
                user_message="Token CSRF inválido o ausente.",
                next_action="Solicite un token vigente en GET /api/ui/v1/auth/csrf y reintente.",
                severity="fatal",
            ).model_dump(),
        )
    logout_request(request)
    clear_session_cookie(response)
    return UiLogoutResponse(ok=True)


@router.get("/auth/csrf", response_model=UiCsrfResponse)
async def get_csrf(request: Request) -> UiCsrfResponse:
    """Token CSRF vigente de la sesión. Sin rotación en GET (idempotente)."""
    require_ui_enabled()
    user = getattr(request.state, "ui_local_user", None)
    if user is None:
        user = resolve_session_from_request(request)
    if user is None:
        raise HTTPException(
            status_code=401,
            detail={
                "error_code": "missing_or_invalid_session",
                "user_message": "Sesión no válida o expirada.",
                "next_action": "Inicie sesión de nuevo en la UI.",
                "severity": "fatal",
            },
        )
    token = csrf_token_for_user(user)
    if not token:
        raise HTTPException(
            status_code=401,
            detail={
                "error_code": "missing_or_invalid_session",
                "user_message": "Sesión no válida o expirada.",
                "next_action": "Inicie sesión de nuevo en la UI.",
                "severity": "fatal",
            },
        )
    return UiCsrfResponse(csrf_token=token)


@router.get("/auth/me", response_model=UiMeResponse)
async def get_me(request: Request) -> UiMeResponse:
    require_ui_enabled()
    user = getattr(request.state, "ui_local_user", None)
    if user is None:
        user = resolve_session_from_request(request)
    if user is None:
        raise HTTPException(
            status_code=401,
            detail={
                "error_code": "missing_or_invalid_session",
                "user_message": "Sesión no válida o expirada.",
                "next_action": "Inicie sesión de nuevo en la UI.",
                "severity": "fatal",
            },
        )
    payload = me_payload(user)
    return UiMeResponse(**payload)


@router.get("/environment", response_model=UiEnvironmentResponse)
async def get_environment(request: Request) -> UiEnvironmentResponse:
    require_ui_enabled()
    env = resolve_active_environment()
    flags = get_ui_feature_flags()
    return UiEnvironmentResponse(
        environment=env.environment,
        display_label=env.display_label,
        ui_enabled=flags.ui_enabled,
        ui_write_enabled=flags.ui_write_enabled,
        ui_auth_mode=flags.ui_auth_mode,
    )


@router.get("/processes", response_model=UiProcessListResponse)
async def list_processes(
    request: Request,
    bank_code: str | None = Query(default=None),
) -> UiProcessListResponse:
    require_ui_enabled()
    if request.query_params.get("path") or request.query_params.get("web_url"):
        raise HTTPException(
            status_code=400,
            detail=UiErrorBody(
                error_code="client_path_forbidden",
                user_message="No se aceptan paths ni URLs SharePoint desde el cliente.",
                next_action="Filtre solo por bank_code; el backend deriva rutas del Control.",
                severity="fatal",
            ).model_dump(),
        )
    env = resolve_active_environment()
    banks = (bank_code.strip(),) if bank_code and bank_code.strip() else KNOWN_BANKS
    if bank_code and bank_code.strip() not in KNOWN_BANKS:
        raise HTTPException(
            status_code=422,
            detail=UiErrorBody(
                error_code="invalid_bank_code",
                user_message="Banco no válido.",
                next_action="Use banco_bogota o banco_bancolombia.",
            ).model_dump(),
        )

    svc = PaymentProcessProjectionService()
    items: list[UiProcessSummary] = []
    for bc in banks:
        try:
            detail = await _detail_for_bank(bc)
        except HTTPException as exc:
            if exc.status_code in {404, 503}:
                continue
            raise
        except Exception:
            continue
        if not detail.process_key and detail.control_estado_proceso in (None, "VACIO"):
            continue
        items.append(svc.summarize(detail))

    return UiProcessListResponse(environment=env.environment, items=items)


@router.get("/processes/{process_key:path}", response_model=UiProcessDetail)
async def get_process(
    process_key: str,
    request: Request,
    graph: GraphClientDep,
) -> UiProcessDetail:
    require_ui_enabled()
    # El navegador solo envía process_key / bank_code / job_id — nunca paths Graph.
    if request.query_params.get("path") or request.query_params.get("web_url"):
        raise HTTPException(
            status_code=400,
            detail=UiErrorBody(
                error_code="client_path_forbidden",
                user_message="No se aceptan paths ni URLs SharePoint desde el cliente.",
                next_action="Consulte el proceso por process_key; el backend resuelve webUrl.",
                severity="fatal",
            ).model_dump(),
        )
    try:
        key = assert_ui_process_key(unquote(process_key).strip())
    except UiInvalidProcessKeyError as exc:
        raise HTTPException(
            status_code=422,
            detail=UiErrorBody(
                error_code="invalid_process_key",
                user_message="process_key inválido o con forma de URL/path.",
                next_action="Use el process_key de Control (payment-validation|banco|fecha|uuid).",
            ).model_dump(),
        ) from exc

    if _sharepoint_reader is not None:
        svc = UiProcessQueryService(
            _sharepoint_reader,
            memory_job_lookup=_memory_job_lookup,
            graph=graph,
            assess_merge=True,
        )
        try:
            return await svc.project_process_key(key, KNOWN_BANKS)
        except KeyError:
            pass
        except UiPathEscapeError as exc:
            raise HTTPException(
                status_code=400,
                detail=UiErrorBody(
                    error_code="path_outside_environment_roots",
                    user_message="Ruta SharePoint fuera del ambiente activo.",
                    next_action="Verifique el overlay del ambiente activo.",
                    severity="fatal",
                ).model_dump(),
            ) from exc
        except UiDownloadTooLargeError as exc:
            raise HTTPException(
                status_code=413,
                detail=UiErrorBody(
                    error_code="download_too_large",
                    user_message="El archivo supera el límite de lectura UI.",
                    next_action="Contacte a soporte.",
                    severity="fatal",
                ).model_dump(),
            ) from exc

    for bc in KNOWN_BANKS:
        try:
            detail = await _detail_for_bank(bc)
        except HTTPException:
            continue
        if (detail.process_key or "").strip() == key:
            return detail

    raise HTTPException(
        status_code=404,
        detail=UiErrorBody(
            error_code="process_not_found",
            user_message="No se encontró el proceso solicitado.",
            next_action="Verifique el process_key o el banco.",
        ).model_dump(),
    )


@router.get("/banks", response_model=list[UiBankCapabilities])
async def list_bank_capabilities() -> list[UiBankCapabilities]:
    """available_actions.generate por banco. Pura: no adquiere locks."""
    require_ui_enabled()
    flags = get_ui_feature_flags()
    env = resolve_active_environment()
    write_allowed = flags.writes_allowed and env.environment == "sandbox"
    # Lectura pura del lock (sin adquirirlo): informativa para el botón de la SPA.
    lock_active = get_job_manager().is_generate_or_finalize_active()
    availability = compute_generate_availability(
        write_allowed=write_allowed,
        generate_or_finalize_active=lock_active,
    )
    action = UiActionAvailability(allowed=availability.allowed, reason=availability.reason)
    return [
        UiBankCapabilities(
            bank_code=bc,
            bank_name=BANK_DISPLAY_NAMES.get(bc),
            available_actions={"generate": action},
        )
        for bc in KNOWN_BANKS
    ]


@router.post(
    "/processes/generate",
    response_model=UiGenerateAccepted,
    status_code=202,
)
async def post_generate(
    body: UiGenerateRequest,
    background_tasks: BackgroundTasks,
    graph: GraphClientDep,
    user: AuthenticatedLocalUser = Depends(require_write_access),
) -> UiGenerateAccepted:
    """Encola Generate reutilizando GenerateQueueService (misma cola que PA)."""
    require_ui_enabled()
    svc = get_generate_queue_service()
    try:
        accepted = await svc.enqueue(
            graph=graph,
            background_tasks=background_tasks,
            bank_code=body.bank_code,
            trigger_source="web_ui",
            requested_by=user.username,
            ui_request_id=str(uuid.uuid4()),
        )
    except GenerateQueueBusyError as exc:
        raise HTTPException(
            status_code=409,
            detail=UiErrorBody(
                error_code="generate_busy",
                user_message="Ya existe un proceso Generate o Finalize activo.",
                next_action="Espere a que termine el proceso actual y consulte /jobs/{job_id}.",
                severity="business",
            ).model_dump(),
        ) from exc
    except GenerateQueueValidationError as exc:
        raise HTTPException(
            status_code=422,
            detail=UiErrorBody(
                error_code="invalid_bank_code",
                user_message=exc.message,
                next_action="Use banco_bogota o banco_bancolombia.",
                severity="business",
            ).model_dump(),
        ) from exc

    # 202 sin process_key: aún no se conoce al momento de encolar (lo resuelve
    # el control Excel durante la ejecución en background).
    return UiGenerateAccepted(
        accepted=True,
        action="generate",
        bank_code=accepted.bank_code,
        job_id=accepted.job_id,
        status=accepted.status,
        poll_url=f"/api/ui/v1/jobs/{accepted.job_id}",
    )


async def _snapshot_for_bank(bank_code: str) -> ProcessControlSnapshot:
    """Lee control por banco (reader o loader de tests). Sin Excel de revisión."""
    if _sharepoint_reader is not None:
        control = await _sharepoint_reader.read_process_control(bank_code)
        return control.snapshot
    if _control_loader is not None:
        return _control_loader(bank_code)
    raise HTTPException(
        status_code=503,
        detail=UiErrorBody(
            error_code="ui_control_loader_unavailable",
            user_message="La lectura de Control aún no está cableada.",
            next_action="Verifique el adaptador SharePoint read-only.",
            severity="fatal",
        ).model_dump(),
    )


@router.post(
    "/processes/finalize",
    response_model=UiFinalizeAccepted,
    status_code=202,
)
async def post_finalize(
    body: UiFinalizeRequest,
    background_tasks: BackgroundTasks,
    graph: GraphClientDep,
    user: AuthenticatedLocalUser = Depends(require_finalize_access),
) -> UiFinalizeAccepted:
    """Encola Finalize vía FinalizeQueueService (misma cola que PA)."""
    require_ui_enabled()
    # Rechazar paths / force si el cliente los cuela en el body JSON extra.
    # Pydantic ya limita el modelo; revalidamos identidad contra control.
    if get_job_manager().is_generate_or_finalize_active():
        raise HTTPException(
            status_code=409,
            detail=UiErrorBody(
                error_code="finalize_busy",
                user_message="Ya existe un proceso Generate o Finalize activo.",
                next_action="Espere a que termine el proceso actual.",
                severity="business",
            ).model_dump(),
        )

    try:
        snap = await _snapshot_for_bank(body.bank_code)
        target = resolve_finalize_target_from_control(
            snap,
            bank_code=body.bank_code,
            process_key=body.process_key.strip(),
        )
    except FinalizeProcessIdentityError as exc:
        raise HTTPException(
            status_code=409,
            detail=UiErrorBody(
                error_code=exc.error_code,
                user_message=exc.message,
                next_action="Actualice el detalle del proceso y verifique el Excel de control.",
                severity="business",
            ).model_dump(),
        ) from exc

    svc = get_finalize_queue_service()
    try:
        accepted = await svc.enqueue(
            graph=graph,
            background_tasks=background_tasks,
            bank_code=target.bank_code,
            validation_file_path=target.validation_file_path,
            process_key=target.process_key,
            trigger_source="web_ui",
            requested_by=user.username,
            ui_request_id=str(uuid.uuid4()),
        )
    except FinalizeQueueBusyError as exc:
        raise HTTPException(
            status_code=409,
            detail=UiErrorBody(
                error_code="finalize_busy",
                user_message="Ya existe un proceso Generate o Finalize activo.",
                next_action="Espere a que termine el proceso actual y consulte /jobs/{job_id}.",
                severity="business",
            ).model_dump(),
        ) from exc
    except FinalizeQueueValidationError as exc:
        raise HTTPException(
            status_code=422,
            detail=UiErrorBody(
                error_code="invalid_finalize_request",
                user_message=exc.message,
                next_action="Use banco_bogota o banco_bancolombia y process_key válido.",
                severity="business",
            ).model_dump(),
        ) from exc

    return UiFinalizeAccepted(
        accepted=True,
        action="finalize",
        bank_code=target.bank_code,
        process_key=target.process_key,
        job_id=accepted.job_id,
        status=accepted.status,
        poll_url=f"/api/ui/v1/jobs/{accepted.job_id}",
    )


@router.post(
    "/processes/notify",
    response_model=UiNotifyAccepted,
    status_code=202,
)
async def post_notify(
    body: UiNotifyRequest,
    background_tasks: BackgroundTasks,
    graph: GraphClientDep,
    user: AuthenticatedLocalUser = Depends(require_notify_access),
) -> UiNotifyAccepted:
    """Encola Notify vía NotifyQueueService (misma cola que PA). Sin to/cc del cliente."""
    require_ui_enabled()
    if get_job_manager().is_generate_or_finalize_active():
        raise HTTPException(
            status_code=409,
            detail=UiErrorBody(
                error_code="notify_busy",
                user_message="Ya existe un proceso Generate, Finalize o Notify activo.",
                next_action="Espere a que termine el proceso actual.",
                severity="business",
            ).model_dump(),
        )

    try:
        snap = await _snapshot_for_bank(body.bank_code)
        target = resolve_notify_target_from_control(
            snap,
            bank_code=body.bank_code,
            process_key=body.process_key.strip(),
        )
    except NotifyProcessIdentityError as exc:
        raise HTTPException(
            status_code=409,
            detail=UiErrorBody(
                error_code=exc.error_code,
                user_message=exc.message,
                next_action="Actualice el detalle del proceso y verifique el Excel de control.",
                severity="business",
            ).model_dump(),
        ) from exc

    recipients = get_ui_notify_sandbox_recipients()
    svc = get_notify_queue_service()
    try:
        accepted = await svc.enqueue(
            graph=graph,
            background_tasks=background_tasks,
            bank_code=target.bank_code,
            historical_file_path=target.historical_file_path,
            to_override=recipients.to_override_csv(),
            cc_override=recipients.cc_override_csv(),
            process_key=target.process_key,
            trigger_source="web_ui",
            requested_by=user.username,
            ui_request_id=str(uuid.uuid4()),
        )
    except NotifyAlreadyNotifiedError as exc:
        raise HTTPException(
            status_code=409,
            detail=UiErrorBody(
                error_code="already_notified",
                user_message="El correo de este proceso ya fue enviado.",
                next_action="Consulte el PDF del correo y continúe con Asientos / Merge cuando corresponda.",
                severity="business",
            ).model_dump(),
        ) from exc
    except NotifyQueueBusyError as exc:
        raise HTTPException(
            status_code=409,
            detail=UiErrorBody(
                error_code="notify_busy",
                user_message="Ya existe un proceso Generate, Finalize o Notify activo.",
                next_action="Espere a que termine el proceso actual y consulte /jobs/{job_id}.",
                severity="business",
            ).model_dump(),
        ) from exc

    return UiNotifyAccepted(
        accepted=True,
        action="notify",
        bank_code=target.bank_code,
        process_key=target.process_key,
        job_id=accepted.job_id,
        status=accepted.status,
        poll_url=f"/api/ui/v1/jobs/{accepted.job_id}",
    )


@router.post(
    "/processes/merge",
    response_model=UiMergeAccepted,
    status_code=202,
)
async def post_merge(
    body: UiMergeRequest,
    background_tasks: BackgroundTasks,
    graph: GraphClientDep,
    user: AuthenticatedLocalUser = Depends(require_merge_access),
) -> UiMergeAccepted:
    """Encola Merge vía MergeQueueService. Paths solo desde control; sin force_rebuild."""
    require_ui_enabled()
    if get_job_manager().is_generate_or_finalize_active():
        raise HTTPException(
            status_code=409,
            detail=UiErrorBody(
                error_code="merge_busy",
                user_message="Ya existe un proceso Generate, Finalize, Notify o Merge activo.",
                next_action="Espere a que termine el proceso actual.",
                severity="business",
            ).model_dump(),
        )

    try:
        snap = await _snapshot_for_bank(body.bank_code)
        target = resolve_merge_target_from_control(
            snap,
            bank_code=body.bank_code,
            process_key=body.process_key.strip(),
        )
    except MergeProcessIdentityError as exc:
        raise HTTPException(
            status_code=409,
            detail=UiErrorBody(
                error_code=exc.error_code,
                user_message=exc.message,
                next_action="Actualice el detalle del proceso y verifique el Excel de control.",
                severity="business",
            ).model_dump(),
        ) from exc

    readiness = await assess_merge_readiness(graph, target.snapshot, target.bank_code)
    if readiness.status in {"incomplete", "unknown"}:
        raise HTTPException(
            status_code=409,
            detail=UiErrorBody(
                error_code=f"merge_readiness_{readiness.status}",
                user_message=readiness.user_message
                or (
                    "Faltan soportes contables."
                    if readiness.status == "incomplete"
                    else "No se pudo verificar si los soportes están completos."
                ),
                next_action=readiness.next_action
                or "Cargue los archivos pendientes o actualice e intente nuevamente.",
                severity="business",
            ).model_dump(),
        )
    if readiness.status == "already_merged":
        raise HTTPException(
            status_code=409,
            detail=UiErrorBody(
                error_code="already_merged",
                user_message="Los soportes de este proceso ya fueron consolidados.",
                next_action="Consulte los PDFs consolidados y continúe con amortización cuando corresponda.",
                severity="business",
            ).model_dump(),
        )

    svc = get_merge_queue_service()
    try:
        accepted = await svc.enqueue(
            graph=graph,
            background_tasks=background_tasks,
            bank_code=target.bank_code,
            historical_file_path=target.historical_file_path,
            email_pdf_path=target.email_pdf_path,
            force_rebuild=False,
            process_key=target.process_key,
            trigger_source="web_ui",
            requested_by=user.username,
            ui_request_id=str(uuid.uuid4()),
            ui_mode=True,
        )
    except MergeAlreadyMergedError as exc:
        raise HTTPException(
            status_code=409,
            detail=UiErrorBody(
                error_code="already_merged",
                user_message="Los soportes de este proceso ya fueron consolidados.",
                next_action="Consulte los PDFs consolidados y continúe con amortización cuando corresponda.",
                severity="business",
            ).model_dump(),
        ) from exc
    except MergeQueueBusyError as exc:
        raise HTTPException(
            status_code=409,
            detail=UiErrorBody(
                error_code="merge_busy",
                user_message="Ya existe un proceso Generate, Finalize, Notify o Merge activo.",
                next_action="Espere a que termine el proceso actual y consulte /jobs/{job_id}.",
                severity="business",
            ).model_dump(),
        ) from exc

    return UiMergeAccepted(
        accepted=True,
        action="merge",
        bank_code=target.bank_code,
        process_key=target.process_key,
        job_id=accepted.job_id,
        status=accepted.status,
        poll_url=f"/api/ui/v1/jobs/{accepted.job_id}",
    )


@router.get("/jobs/{job_id}", response_model=UiJobView)
async def get_job(job_id: str, request: Request) -> UiJobView:
    require_ui_enabled()
    env = resolve_active_environment()
    found = read_any_job(job_id, memory_lookup=_memory_job_lookup)
    if not found:
        raise HTTPException(
            status_code=404,
            detail=UiErrorBody(
                error_code="job_not_found",
                user_message="No se encontró el trabajo solicitado.",
                next_action=(
                    "Si el App Service se recicló, el job en memoria pudo perderse. "
                    "Consulte el proceso por process_key en Control."
                ),
            ).model_dump(),
        )
    # Reusa el mismo enriquecimiento que PA (user_message/next_action/severity
    # homogéneos) antes de sanear campos técnicos.
    payload = enrich_job_for_http_response(found.payload)
    result = payload.get("result")
    result_summary = None
    if isinstance(result, dict):
        # Sanitizado: sin bytes, tokens ni tracebacks.
        result_summary = {
            k: result.get(k)
            for k in (
                "process_key",
                "bank_code",
                "already_generated",
                "already_finalized",
                "already_merged",
                "already_applied",
                "already_notified",
                "merge_control_error_code",
                "merge_control_warning",
                "merge_control_status",
                "historical_file_path",
                "historical_file_url",
                "secretary_file_path",
                "secretary_file_url",
                "email_pdf_path",
                "user_message",
                "status",
                "file_action",
            )
            if k in result
        }
        # Ya notificado: alias seguro para la SPA (sin mail_to / direcciones).
        if result.get("merge_control_error_code") == "already_notified":
            result_summary["already_notified"] = True
        # Nunca filtrar mail_to/mail_sender hacia la SPA aunque vengan en result.
    err = payload.get("error")
    safe_error = None
    if isinstance(err, dict):
        safe_error = {
            k: err.get(k)
            for k in (
                "type",
                "message",
                "error_code",
                "user_message",
                "next_action",
                "severity",
            )
            if k in err
        }
    return UiJobView(
        job_id=job_id,
        type=str(payload.get("type") or "") or None,
        status=str(payload.get("status") or "unknown"),
        store=found.store,
        process_key=(
            str((result or {}).get("process_key") or payload.get("process_key") or "")
            or None
            if isinstance(result, dict) or payload.get("process_key")
            else None
        ),
        bank_code=(
            str((result or {}).get("bank_code") or payload.get("bank_code") or "") or None
            if isinstance(result, dict) or payload.get("bank_code")
            else None
        ),
        environment=env.environment,
        created_at=str(payload.get("created_at") or payload.get("queued_at") or "") or None,
        started_at=str(payload.get("started_at") or "") or None,
        finished_at=str(payload.get("finished_at") or "") or None,
        result_summary=result_summary,
        error=safe_error,
        user_message=str(payload.get("user_message") or "") or None,
        next_action=str(payload.get("next_action") or "") or None,
        severity=str(payload.get("severity") or "") or None,
        raw_available=True,
    )
