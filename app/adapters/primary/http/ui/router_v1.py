"""Router UI v1 — solo GET. Montado desde create_app cuando UI_ENABLED."""
from __future__ import annotations

from typing import Any, Callable
from urllib.parse import unquote

from fastapi import APIRouter, HTTPException, Query, Request, Response

from app.adapters.primary.http.ui.deps import require_ui_enabled
from app.application.ui.entra_config import resolve_entra_spa_config
from app.application.ui.environment import resolve_active_environment
from app.application.ui.feature_flags import get_ui_feature_flags
from app.application.ui.job_read import read_any_job
from app.application.ui.download_limits import UiDownloadTooLargeError
from app.application.ui.local_auth import (
    GENERIC_LOGIN_FAILURE,
    authenticate_local_credentials,
    clear_session_cookie,
    is_login_rate_limited,
    logout_request,
    me_payload,
    resolve_session_from_request,
    set_session_cookie,
    validate_same_origin,
)
from app.application.ui.local_session_config import resolve_local_session_config
from app.application.ui.path_guard import UiPathEscapeError
from app.application.ui.ports import UiSharePointReadPort
from app.application.ui.process_key import UiInvalidProcessKeyError, assert_ui_process_key
from app.application.ui.process_projection import PaymentProcessProjectionService
from app.application.ui.process_query import UiProcessQueryService
from app.application.ui.schemas import (
    UiBootstrapResponse,
    UiEnvironmentResponse,
    UiErrorBody,
    UiJobView,
    UiLoginRequest,
    UiLoginResponse,
    UiLogoutResponse,
    UiMeResponse,
    UiProcessDetail,
    UiProcessListResponse,
    UiProcessSummary,
)
from app.application.use_cases.payment_validation_process_control import (
    ProcessControlSnapshot,
)

router = APIRouter(prefix="/api/ui/v1", tags=["ui-v1"])

KNOWN_BANKS: tuple[str, ...] = ("banco_bogota", "banco_bancolombia")

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
    if flags.ui_auth_mode == "local_session":
        return UiBootstrapResponse(
            ui_enabled=flags.ui_enabled,
            writes_allowed=flags.writes_allowed,
            active_environment=env.environment,
            display_label=env.display_label,
            auth_mode="local_session",
            login_required=True,
        )
    spa = resolve_entra_spa_config()
    return UiBootstrapResponse(
        ui_enabled=flags.ui_enabled,
        writes_allowed=flags.writes_allowed,
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
    logout_request(request)
    clear_session_cookie(response)
    return UiLogoutResponse(ok=True)


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
async def get_process(process_key: str, request: Request) -> UiProcessDetail:
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
    payload = found.payload
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
                "already_merged",
                "already_applied",
                "user_message",
                "status",
            )
            if k in result
        }
    err = payload.get("error")
    safe_error = None
    if isinstance(err, dict):
        safe_error = {
            k: err.get(k)
            for k in ("type", "message", "error_code", "user_message", "next_action")
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
        raw_available=True,
    )
