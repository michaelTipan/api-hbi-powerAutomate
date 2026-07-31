"""Readiness de Merge (solo lectura): histórico + listado de ASIENTOS.

No adquiere mutex, no escribe control, no une PDFs ni sube manifiestos.
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from io import BytesIO
from typing import Any, Protocol

from openpyxl import load_workbook

from app.application.job_manager import get_job_manager
from app.application.services.colombia_time import now_colombia_iso
from app.application.services.historical_application_rows import (
    group_rows_by_id_pago,
    read_validated_abono_rows,
    read_validated_payment_rows,
)
from app.application.services.merge_group_validation import (
    validate_merge_group_completeness,
)
from app.application.ui.merge_capabilities import control_indicates_already_merged
from app.application.use_cases.merge_composite_validado_pdfs import (
    _classify_asiento_pdf_names,
    _pdf_names_in_children,
    _ruta_asientos_from_cell,
)
from app.application.use_cases.payment_validation_process_control import (
    ProcessControlSnapshot,
)
from app.application.use_cases.send_validar_extractos_notification import (
    _list_drive_folder_children,
)
from app.application.use_cases.validate_payment_report import _graph_download_by_path
from app.application.sharepoint_resolution import resolve_sharepoint_from_env

logger = logging.getLogger(__name__)

_MSG_ALREADY = "Los soportes de este proceso ya fueron consolidados."
_MSG_INCOMPLETE = "Faltan soportes contables."
_MSG_UNKNOWN = (
    "No se pudo verificar si los soportes están completos. "
    "Actualice e intente nuevamente."
)
_MSG_READY = "Los soportes están listos para consolidar."
_NEXT_LOAD = "Cargue los archivos pendientes antes de consolidar."
_NEXT_RETRY = "Actualice el detalle del proceso e intente nuevamente."
_NEXT_MERGE = "Puede consolidar los soportes desde la UI."
_NEXT_DONE = "Consulte los PDFs consolidados y continúe con amortización cuando corresponda."


class GraphLike(Protocol):
    async def get(self, *a: Any, **k: Any) -> Any: ...
    async def get_bytes(self, *a: Any, **k: Any) -> Any: ...


@dataclass
class MergeReadiness:
    status: str  # ready|incomplete|unknown|already_merged
    expected_groups: int = 0
    ready_groups: int = 0
    missing_groups: int = 0
    missing_items: list[dict[str, Any]] = field(default_factory=list)
    folder_links: list[dict[str, Any]] = field(default_factory=list)
    checked_at: str = ""
    user_message: str = ""
    next_action: str = ""


def _now() -> str:
    return now_colombia_iso()


def _result(
    status: str,
    *,
    expected: int = 0,
    ready: int = 0,
    missing_items: list[dict[str, Any]] | None = None,
    folder_links: list[dict[str, Any]] | None = None,
    user_message: str,
    next_action: str,
) -> MergeReadiness:
    missing_groups = max(0, expected - ready)
    return MergeReadiness(
        status=status,
        expected_groups=expected,
        ready_groups=ready,
        missing_groups=missing_groups,
        missing_items=list(missing_items or []),
        folder_links=list(folder_links or []),
        checked_at=_now(),
        user_message=user_message,
        next_action=next_action,
    )


async def assess_merge_readiness(
    graph: GraphLike,
    snap: ProcessControlSnapshot,
    bank_code: str,
) -> MergeReadiness:
    """Evalúa si hay soportes suficientes para consolidar (solo lectura)."""
    pk = (snap.process_key or "").strip()
    if control_indicates_already_merged(snap) or (
        pk and get_job_manager().has_completed_merge(pk)
    ):
        return _result(
            "already_merged",
            user_message=_MSG_ALREADY,
            next_action=_NEXT_DONE,
        )

    historico = (snap.historical_file_path or "").strip().strip("/")
    email_pdf = (snap.email_pdf_path or "").strip().strip("/")
    if not historico or not email_pdf:
        return _result(
            "incomplete",
            user_message=_MSG_INCOMPLETE,
            next_action=_NEXT_LOAD,
        )

    try:
        ctx = await resolve_sharepoint_from_env(graph)
        site_id = str(ctx["site_id"])
        drive_id = str(ctx["drive_id"])
        hist_bytes = await _graph_download_by_path(graph, site_id, drive_id, historico)
        estado = (
            os.getenv("GRAPH_VALIDAR_EXTRACTO_ESTADO_CONTAINS") or "VALIDAR"
        ).strip() or "VALIDAR"
        wb = load_workbook(filename=BytesIO(hist_bytes), data_only=True)
        try:
            payment_rows = read_validated_payment_rows(wb, legacy_estado_token=estado)
            abono_rows = read_validated_abono_rows(wb)
            payment_groups = group_rows_by_id_pago(payment_rows)
            abono_groups = group_rows_by_id_pago(abono_rows)
        finally:
            wb.close()

        all_groups: list[tuple[str, str, list[dict[str, Any]]]] = []
        for id_pago, rows in payment_groups.items():
            all_groups.append((str(id_pago), "PAGO", list(rows)))
        for id_pago, rows in abono_groups.items():
            all_groups.append((str(id_pago), "ABONO", list(rows)))

        if not all_groups:
            return _result(
                "incomplete",
                user_message=_MSG_INCOMPLETE,
                next_action=_NEXT_LOAD,
            )

        ready = 0
        missing_items: list[dict[str, Any]] = []
        folder_links: list[dict[str, Any]] = []
        seen_folders: set[str] = set()

        for id_pago, tipo, rows in all_groups:
            credit_items: list[dict[str, Any]] = []
            pre_skips: list[str] = []
            for row in rows:
                credit_digits = str(row.get("credito_digits") or "").strip()
                asientos_dir = _ruta_asientos_from_cell(row.get("ruta_asientos_cell"))
                if not asientos_dir:
                    pre_skips.append(
                        f"missing_ruta_asientos_contables credito={credit_digits}"
                    )
                    continue
                if asientos_dir not in seen_folders:
                    seen_folders.add(asientos_dir)
                    folder_links.append(
                        {
                            "rel": "asientos",
                            "path": asientos_dir,
                            "credito": credit_digits,
                            "label": "Carpeta ASIENTOS",
                        }
                    )
                try:
                    children = await _list_drive_folder_children(
                        graph, site_id, drive_id, asientos_dir
                    )
                except Exception:
                    logger.info(
                        "merge_readiness: list asientos falló path=%s",
                        asientos_dir,
                        exc_info=True,
                    )
                    return _result(
                        "unknown",
                        expected=len(all_groups),
                        ready=ready,
                        missing_items=missing_items,
                        folder_links=folder_links,
                        user_message=_MSG_UNKNOWN,
                        next_action=_NEXT_RETRY,
                    )
                names = _pdf_names_in_children(children)
                valid_names, _rejected = _classify_asiento_pdf_names(
                    names, credit_digits
                )
                if not valid_names:
                    pre_skips.append(
                        f"asiento_contable_not_found credito={credit_digits}"
                    )
                    continue
                credit_items.append(
                    {
                        "credito": credit_digits,
                        "asiento_pdf_paths": [
                            f"{asientos_dir}/{n}".replace("//", "/")
                            for n in valid_names
                        ],
                    }
                )

            validation = validate_merge_group_completeness(
                id_pago=id_pago,
                tipo_aplicacion=tipo,
                group_rows=rows,
                credit_items=credit_items,
                pre_skips=pre_skips,
            )
            if validation.is_complete:
                ready += 1
            else:
                for item in validation.missing_inputs:
                    missing_items.append(
                        {
                            "id_pago": id_pago,
                            "tipo_aplicacion": tipo,
                            **dict(item),
                        }
                    )

        expected = len(all_groups)
        if ready >= expected and expected > 0 and not missing_items:
            return _result(
                "ready",
                expected=expected,
                ready=ready,
                missing_items=[],
                folder_links=folder_links,
                user_message=_MSG_READY,
                next_action=_NEXT_MERGE,
            )
        return _result(
            "incomplete",
            expected=expected,
            ready=ready,
            missing_items=missing_items,
            folder_links=folder_links,
            user_message=_MSG_INCOMPLETE,
            next_action=_NEXT_LOAD,
        )
    except Exception:
        logger.info(
            "merge_readiness: fallo Graph/histórico bank=%s",
            bank_code,
            exc_info=True,
        )
        return _result(
            "unknown",
            user_message=_MSG_UNKNOWN,
            next_action=_NEXT_RETRY,
        )
