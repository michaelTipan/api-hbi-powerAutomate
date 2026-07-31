import logging
import os
from base64 import b64decode, b64encode
from typing import Any

import httpx
from fastapi import APIRouter, BackgroundTasks, Body, HTTPException

from app.adapters.primary.http.deps import GraphClientDep
from app.application.job_manager import get_job_manager
from app.application.job_status_enrichment import enrich_job_for_http_response
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
from app.application.use_cases.sharepoint_from_env import (
    download_configured_file_base64,
    resolve_configured_item,
    upload_configured_file,
)
from app.domain.exceptions import GraphConfigError
from app.models import GraphUploadRequest, MergeCompositeValidadoRequest, NotifyValidarExtractosRequest

router = APIRouter(prefix="/graph/sharepoint", tags=["sharepoint"])
logger = logging.getLogger(__name__)


@router.get("/site")
async def graph_sharepoint_site(graph: GraphClientDep, hostname: str, site_path: str) -> dict:
    try:
        endpoint = f"/sites/{hostname}:{site_path}"
        return await graph.get(endpoint)
    except GraphConfigError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Graph request failed: {exc}") from exc


@router.get("/sites/{site_id}/drives")
async def graph_sharepoint_drives(graph: GraphClientDep, site_id: str) -> dict:
    try:
        return await graph.get(f"/sites/{site_id}/drives")
    except GraphConfigError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Graph request failed: {exc}") from exc


@router.get("/drives/{drive_id}/children")
async def graph_drive_children(
    graph: GraphClientDep,
    drive_id: str,
    folder_item_id: str = "root",
) -> dict:
    try:
        endpoint = f"/drives/{drive_id}/items/{folder_item_id}/children"
        return await graph.get(endpoint)
    except GraphConfigError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Graph request failed: {exc}") from exc


@router.get("/drives/{drive_id}/item-content")
async def graph_download_item_content(graph: GraphClientDep, drive_id: str, item_id: str) -> dict:
    try:
        content = await graph.get_bytes(f"/drives/{drive_id}/items/{item_id}/content")
        return {"content_base64": b64encode(content).decode("utf-8")}
    except GraphConfigError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Graph request failed: {exc}") from exc


@router.put("/drives/{drive_id}/item-content")
async def graph_update_item_content(
    graph: GraphClientDep,
    drive_id: str,
    item_id: str,
    payload: GraphUploadRequest,
) -> dict:
    try:
        file_bytes = b64decode(payload.content_base64)
        endpoint = f"/drives/{drive_id}/items/{item_id}/content"
        return await graph.put_bytes(endpoint, file_bytes)
    except GraphConfigError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Graph request failed: {exc}") from exc


@router.put("/drives/{drive_id}/path-content")
async def graph_upload_path_content(
    graph: GraphClientDep,
    drive_id: str,
    item_path: str,
    payload: GraphUploadRequest,
) -> dict:
    try:
        from app.application.sharepoint_resolution import encode_graph_drive_path

        file_bytes = b64decode(payload.content_base64)
        encoded = encode_graph_drive_path(item_path.strip().strip("/"))
        endpoint = f"/drives/{drive_id}/root:/{encoded}:/content"
        return await graph.put_bytes(endpoint, file_bytes)
    except GraphConfigError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Graph request failed: {exc}") from exc


@router.delete("/drives/{drive_id}/items/{item_id}")
async def graph_delete_drive_item(
    graph: GraphClientDep,
    drive_id: str,
    item_id: str,
) -> dict[str, str]:
    """Elimina un ítem del drive (p. ej. limpiar la carpeta de revisión en sandbox)."""
    try:
        await graph.delete(f"/drives/{drive_id}/items/{item_id}")
        return {"status": "ok", "drive_id": drive_id, "item_id": item_id}
    except GraphConfigError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Graph request failed: {exc}") from exc


@router.get("/sites-search")
async def graph_sharepoint_sites_search(graph: GraphClientDep, search: str | None = None) -> dict:
    term = (search or "").strip()
    if not term:
        term = os.getenv("GRAPH_SHAREPOINT_SITE_SEARCH", "").strip()
    if not term:
        raise HTTPException(
            status_code=400,
            detail="Pass ?search=... or set GRAPH_SHAREPOINT_SITE_SEARCH",
        )
    try:
        return await graph.get("/sites", params={"search": term})
    except GraphConfigError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Graph request failed: {exc}") from exc


@router.get("/resolve-env")
async def graph_sharepoint_resolve_env(graph: GraphClientDep) -> dict:
    try:
        return await resolve_configured_item(graph)
    except GraphConfigError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Graph request failed: {exc}") from exc


@router.get("/excel-from-env")
async def graph_sharepoint_excel_from_env(graph: GraphClientDep) -> dict:
    try:
        return await download_configured_file_base64(graph)
    except GraphConfigError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Graph request failed: {exc}") from exc


@router.put("/file-from-env")
async def graph_sharepoint_upload_from_env(
    graph: GraphClientDep,
    payload: GraphUploadRequest,
) -> dict:
    try:
        return await upload_configured_file(graph, payload.content_base64)
    except GraphConfigError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Graph request failed: {exc}") from exc


@router.get("/notify-validar-extractos-email/jobs/{job_id}")
async def notify_validar_extractos_job_status(job_id: str) -> dict:
    """Polling PA: lee JobManager (persistido); shape HTTP compatible."""
    job = get_job_manager().get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return enrich_job_for_http_response(job)


@router.get("/merge-composite-validado-pdfs/jobs/{job_id}")
async def merge_composite_validado_pdfs_job_status(job_id: str) -> dict:
    """Polling PA: lee JobManager (persistido); shape HTTP compatible."""
    job = get_job_manager().get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return enrich_job_for_http_response(job)


@router.post("/merge-composite-validado-pdfs", status_code=202)
async def post_merge_composite_validado_pdfs(
    graph: GraphClientDep,
    background_tasks: BackgroundTasks,
    body: MergeCompositeValidadoRequest | None = Body(default=None),
) -> dict[str, Any]:
    """
    Une PDFs por cada ID Pago (Estado línea según GRAPH_VALIDAR_EXTRACTO_ESTADO_CONTAINS):
    PDF del correo (carpeta de correos enviados, una vez), luego por crédito todos los asientos
    y un extracto único.
    Mismo ID Pago = un solo PDF. ``force_rebuild=true`` regenera el consolidado aunque ya exista.
    Consulta ``GET …/merge-composite-validado-pdfs/jobs/{job_id}``.

    Orquestación: MergeQueueService (compartido con la UI; JobManager + mutex Generate/Finalize/Notify).
    """
    payload = body or MergeCompositeValidadoRequest()
    svc = get_merge_queue_service()
    try:
        accepted = await svc.enqueue(
            graph=graph,
            background_tasks=background_tasks,
            bank_code=payload.bank_code,
            historical_file_path=payload.historical_file_path,
            email_pdf_path=payload.email_pdf_path,
            force_rebuild=payload.force_rebuild,
            trigger_source="power_automate",
            ui_mode=False,
        )
    except MergeQueueBusyError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except MergeAlreadyMergedError as exc:
        # Con ui_mode=False el service reutiliza prior; si llega aquí, 202 con prior.
        job_id = exc.prior_job_id or ""
        logger.info(
            "job %s: merge ya consolidado (reuso PA) process_key=%s",
            job_id,
            exc.process_key,
        )
        return {
            "status": "queued",
            "job_id": job_id,
            "estimated_processing_seconds": 300,
            "message": (
                "Trabajo en cola. Consulta "
                f"/graph/sharepoint/merge-composite-validado-pdfs/jobs/{job_id}"
            ),
        }

    logger.info(
        "job %s: encolado merge_composite_validado_pdfs reused_prior=%s",
        accepted.job_id,
        accepted.reused_prior,
    )
    return {
        "status": "queued",
        "job_id": accepted.job_id,
        "estimated_processing_seconds": 300,
        "message": (
            "Trabajo en cola. Consulta "
            f"/graph/sharepoint/merge-composite-validado-pdfs/jobs/{accepted.job_id}"
        ),
    }


@router.post("/notify-validar-extractos-email", status_code=202)
async def notify_validar_extractos_email(
    graph: GraphClientDep,
    background_tasks: BackgroundTasks,
    body: NotifyValidarExtractosRequest | None = Body(default=None),
) -> dict:
    """
    Si el body NO incluye ``historical_file_path``, el job resuelve el histórico desde el control
    oficial por banco (cuando exactamente un banco esté listo: EstadoProceso=FINALIZADO, IsActive=true,
    HistoricalFilePath no vacío). Opcionalmente, puede enviar ``bank_code`` como override.

    Lee el Excel del reporte (GRAPH_SHAREPOINT_FILE_PATH) para la tabla del correo y la fecha mínima
    en la columna Fecha. El histórico de validación **solo** se obtiene por ``historical_file_path``
    (no hay resolución automática por carpetas).

    Hoja Distribución del histórico; filas con Estado línea según GRAPH_VALIDAR_EXTRACTO_ESTADO_CONTAINS.
    Remitente y destinatarios: CORREOS.xlsx salvo overrides ``to`` / ``cc`` en el body.

    Orquestación: NotifyQueueService (compartido con la UI; JobManager + mutex Generate/Finalize).
    """
    payload = body or NotifyValidarExtractosRequest()
    svc = get_notify_queue_service()
    try:
        accepted = await svc.enqueue(
            graph=graph,
            background_tasks=background_tasks,
            historical_file_path=payload.historical_file_path,
            bank_code=payload.bank_code,
            to_override=payload.to,
            cc_override=payload.cc,
            trigger_source="power_automate",
        )
    except NotifyAlreadyNotifiedError as exc:
        raise HTTPException(
            status_code=409,
            detail={
                "error_code": "already_notified",
                "message": "El correo de este proceso ya fue enviado.",
                "process_key": exc.process_key,
                "prior_job_id": exc.prior_job_id,
            },
        ) from exc
    except NotifyQueueBusyError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    logger.info("job %s: encolado notify_validar_extractos", accepted.job_id)
    return {
        "status": "queued",
        "job_id": accepted.job_id,
        "estimated_processing_seconds": 180,
        "message": (
            "Trabajo en cola. Consulta "
            f"/graph/sharepoint/notify-validar-extractos-email/jobs/{accepted.job_id}"
        ),
    }
