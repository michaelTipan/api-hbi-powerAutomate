"""Preparación canónica de amortización (una sola validación financiera por intento).

Separada de la ejecución de escrituras para:
- UI: validar una vez; si can_apply=false → requires_correction sin writes;
  si true → execute con el mismo plan (sin re-dry-run completo).
- PA Apply: prepare + execute vía run_amortization_fill_apply (contrato intacto).
"""
from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass, field
from typing import Any

from app.application.services.merge_manifest_gate import (
    MERGE_INCOMPLETE_NOT_APPLICABLE,
    evaluate_merge_incomplete_block,
)
from app.application.use_cases.amortization_fill_dry_run import (
    AMORTIZATION_RUNNABLE_STATES,
    _drive_context,
    _resolve_amortization_inputs,
    run_amortization_fill_dry_run,
)
from app.application.use_cases.payment_validation_process_control import (
    ProcessControlSnapshot,
)
from app.application.use_cases.validate_payment_report import _graph_download_by_path
from app.domain.ports.graph import GraphApiPort

logger = logging.getLogger(__name__)


def _finalize_rejection(rejection: dict[str, Any]) -> dict[str, Any]:
    """Adjunta operational_issues y resume user_message para requires_correction."""
    from app.application.ui.amortization_operational_issues import (
        attach_operational_issues_to_amortization_result,
    )

    return attach_operational_issues_to_amortization_result(rejection)


async def _read_control_snapshot(graph, site_id, drive_id, *, bank_code):
    """Lee control vía apply para respetar monkeypatches de tests existentes."""
    from app.application.use_cases import amortization_fill_apply as apply_mod

    return await apply_mod.read_process_control_snapshot(
        graph, site_id, drive_id, bank_code=bank_code
    )


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


@dataclass
class AmortizationPreparedPlan:
    """Plan validado listo para Apply o para rechazo sin escritura."""

    can_apply: bool
    already_applied: bool = False
    rejection_kind: str | None = None
    # blocked_merge | blocked_abono | preflight | dry_run_blocked | already_applied
    dry_run: dict[str, Any] | None = None
    fingerprints: dict[str, Any] = field(default_factory=dict)
    site_id: str = ""
    drive_id: str = ""
    resolved_bank_code: str = ""
    resolved_bank_name: str = ""
    bank_code_param: str | None = None
    resolved_process_key: str = ""
    resolved_control_path: str = ""
    ready_banks_detected: list[str] = field(default_factory=list)
    merge_manifest_source: str = ""
    historical_file_source: str = ""
    manifest_rel: str = ""
    hist_path: str | None = None
    resolved_date: str | None = None
    pre_apply_estado: str = "CONSOLIDADO"
    review_validation_path: str = ""
    apply_idempotency_key: str = ""
    already_applied_result: dict[str, Any] | None = None
    rejection_result: dict[str, Any] | None = None
    preflight_error: Exception | None = None
    abono_block: dict[str, Any] | None = None
    merge_block: dict[str, Any] | None = None
    table_bytes: dict[str, bytes] = field(default_factory=dict)
    table_etags: dict[str, str] = field(default_factory=dict)


def _collect_fingerprints(
    *,
    snap: ProcessControlSnapshot | None,
    process_key: str,
    estado: str,
    manifest_rel: str,
    manifest_sha256: str | None,
    hist_path: str | None,
    hist_sha256: str | None,
    dry_run: dict[str, Any] | None,
) -> dict[str, Any]:
    items = [
        it for it in ((dry_run or {}).get("items") or []) if isinstance(it, dict)
    ]
    event_keys: list[str] = []
    pdf_hashes: list[dict[str, str]] = []
    table_paths: list[str] = []
    for it in items:
        key = str(it.get("idempotency_key") or "").strip()
        if key:
            event_keys.append(key)
        pdf_path = str(
            it.get("asiento_pdf_path") or it.get("accounting_pdf_path") or ""
        ).strip()
        pdf_hash = str(it.get("asiento_pdf_hash") or "").strip()
        if pdf_path or pdf_hash:
            pdf_hashes.append({"path": pdf_path, "sha256": pdf_hash})
        tabla = str(it.get("tabla_amortizacion_path") or "").strip()
        if tabla and tabla not in table_paths:
            table_paths.append(tabla)

    table_fingerprints: list[dict[str, str]] = []
    seen_fp: set[str] = set()
    for it in items:
        tabla = str(it.get("tabla_amortizacion_path") or "").strip()
        if not tabla or tabla in seen_fp:
            continue
        seen_fp.add(tabla)
        table_fingerprints.append(
            {
                "path": tabla,
                "sha256": str(it.get("tabla_sha256") or "").strip(),
            }
        )

    ibr_path = str(
        (dry_run or {}).get("ibr_workbook_path")
        or (dry_run or {}).get("ibr_path")
        or ""
    ).strip()

    return {
        "process_key": process_key,
        "estado_proceso": estado,
        "merge_manifest_path": manifest_rel,
        "manifest_sha256": manifest_sha256 or "",
        "historical_file_path": (hist_path or "").strip(),
        "historical_sha256": hist_sha256 or "",
        "ibr_path": ibr_path,
        "event_keys": sorted(event_keys),
        "pdf_hashes": pdf_hashes,
        "table_paths": sorted(table_paths),
        "table_fingerprints": table_fingerprints,
        "apply_idempotency_key": (
            (snap.apply_idempotency_key if snap is not None else "") or ""
        ).strip(),
        "control_is_active": bool(snap.is_active) if snap is not None else False,
    }


async def prepare_amortization_application(
    graph: GraphApiPort,
    *,
    report_date_iso: str | None = None,
    merge_manifest_path: str | None = None,
    historical_file_path: str | None = None,
    bank_code: str | None = None,
    job_id: str | None = None,
    update_process_control: bool = False,
) -> AmortizationPreparedPlan:
    """Ejecuta la preparación financiera canónica (dry-run interno una vez).

    ``update_process_control`` solo afecta al dry-run (LastStepStatus). Para UI
    debe ser False. No escribe EstadoProceso ni tablas.
    """
    # Imports diferidos para evitar ciclos con amortization_fill_apply.
    from app.application.use_cases.amortization_fill_apply import (
        AmortizationPreflightError,
        _apply_observability_base,
        _apply_summarize,
        _build_already_applied_result,
        _try_coarse_apply_early_return,
        empty_accounting_pdf_move_summary_safe,
        validate_amortization_preflight,
    )
    from app.application.use_cases import amortization_fill_apply as apply_mod

    # Usar bindings de apply para respetar monkeypatches históricos de tests.
    site_id, drive_id = await apply_mod._drive_context(graph)

    early = await _try_coarse_apply_early_return(
        graph,
        site_id,
        drive_id,
        bank_code_param=bank_code,
        merge_manifest_path=merge_manifest_path,
        historical_file_path=historical_file_path,
    )
    if early is not None:
        pk = str(early.get("process_key") or "").strip()
        return AmortizationPreparedPlan(
            can_apply=False,
            already_applied=True,
            rejection_kind="already_applied",
            site_id=site_id,
            drive_id=drive_id,
            resolved_bank_code=str(early.get("bank_code") or ""),
            resolved_process_key=pk,
            apply_idempotency_key=str(early.get("apply_idempotency_key") or pk),
            already_applied_result=early,
            fingerprints={"process_key": pk, "already_applied": True},
        )

    (
        resolved_manifest,
        resolved_date,
        resolved_hist,
        resolved_bank_code,
        resolved_bank_name,
        resolved_process_key,
        resolved_control_path,
        ready_banks_detected,
        merge_manifest_source,
        historical_file_source,
    ) = await apply_mod._resolve_amortization_inputs(
        graph,
        site_id,
        drive_id,
        bank_code=bank_code,
        report_date_iso=report_date_iso,
        merge_manifest_path=merge_manifest_path,
        historical_file_path=historical_file_path,
    )

    manifest_rel = (resolved_manifest or merge_manifest_path or "").strip().strip("/")
    hist_path = (resolved_hist or historical_file_path or "").strip().strip("/") or None
    apply_idempotency_key = (resolved_process_key or "").strip()

    pre_apply_estado = "CONSOLIDADO"
    snap: ProcessControlSnapshot | None = None
    review_validation_path = ""
    try:
        snap = await _read_control_snapshot(
            graph, site_id, drive_id, bank_code=resolved_bank_code
        )
        review_validation_path = (
            getattr(snap, "validation_file_path", None) or ""
        ).strip().strip("/")
        pre_apply_estado = (snap.estado_proceso or "CONSOLIDADO").strip() or "CONSOLIDADO"
        if not apply_idempotency_key:
            apply_idempotency_key = (snap.process_key or "").strip()
        from app.application.use_cases.amortization_fill_apply import (
            _is_coarse_apply_already_done,
        )

        if _is_coarse_apply_already_done(snap) and (
            not apply_idempotency_key
            or (snap.apply_idempotency_key or "").strip() == apply_idempotency_key
        ):
            early_done = _build_already_applied_result(
                snap=snap,
                bank_code=resolved_bank_code,
                bank_code_param=bank_code,
            )
            return AmortizationPreparedPlan(
                can_apply=False,
                already_applied=True,
                rejection_kind="already_applied",
                site_id=site_id,
                drive_id=drive_id,
                resolved_bank_code=resolved_bank_code,
                resolved_bank_name=resolved_bank_name,
                bank_code_param=bank_code,
                resolved_process_key=apply_idempotency_key,
                resolved_control_path=resolved_control_path,
                manifest_rel=manifest_rel,
                hist_path=hist_path,
                pre_apply_estado=pre_apply_estado,
                review_validation_path=review_validation_path,
                apply_idempotency_key=apply_idempotency_key,
                already_applied_result=early_done,
                fingerprints=_collect_fingerprints(
                    snap=snap,
                    process_key=apply_idempotency_key,
                    estado=pre_apply_estado,
                    manifest_rel=manifest_rel,
                    manifest_sha256=None,
                    hist_path=hist_path,
                    hist_sha256=None,
                    dry_run=None,
                ),
            )
    except Exception as exc:
        logger.warning("prepare: no se pudo revalidar control: %s", exc)

    manifest_sha256: str | None = None
    hist_sha256: str | None = None
    manifest_doc: dict[str, Any] | None = None

    if manifest_rel:
        try:
            manifest_raw = await _graph_download_by_path(
                graph, site_id, drive_id, manifest_rel
            )
            manifest_sha256 = _sha256_bytes(manifest_raw)
            manifest_doc = json.loads(manifest_raw.decode("utf-8"))
            merge_skipped = None
            if snap is not None:
                raw_skip = getattr(snap, "merge_skipped_count", None)
                if raw_skip is not None:
                    merge_skipped = int(raw_skip)
            merge_block = evaluate_merge_incomplete_block(
                manifest_doc,
                estado_proceso=pre_apply_estado,
                merge_skipped_count=merge_skipped,
            )
            if merge_block is not None:
                rejection = {
                    "status": "blocked",
                    "mode": "prepare",
                    "can_apply": False,
                    "apply_wrote_changes": False,
                    "already_applied": False,
                    "outcome": "requires_correction",
                    "error_code": merge_block.get(
                        "error_code", MERGE_INCOMPLETE_NOT_APPLICABLE
                    ),
                    "merge_incomplete_block": merge_block,
                    "user_message": merge_block.get("user_message"),
                    "next_action": merge_block.get("next_action"),
                    "bank_code": resolved_bank_code,
                    "bank_name": resolved_bank_name,
                    "process_key": apply_idempotency_key,
                    "manifest_path": manifest_rel,
                    "items": [],
                    "tables_uploaded": [],
                    "tables_summary": [],
                    "summary": _apply_summarize([]),
                    **empty_accounting_pdf_move_summary_safe(),
                }
                return AmortizationPreparedPlan(
                    can_apply=False,
                    rejection_kind="blocked_merge",
                    site_id=site_id,
                    drive_id=drive_id,
                    resolved_bank_code=resolved_bank_code,
                    resolved_bank_name=resolved_bank_name,
                    bank_code_param=bank_code,
                    resolved_process_key=apply_idempotency_key,
                    resolved_control_path=resolved_control_path,
                    ready_banks_detected=list(ready_banks_detected),
                    merge_manifest_source=merge_manifest_source,
                    historical_file_source=historical_file_source,
                    manifest_rel=manifest_rel,
                    hist_path=hist_path,
                    resolved_date=resolved_date,
                    pre_apply_estado=pre_apply_estado,
                    review_validation_path=review_validation_path,
                    apply_idempotency_key=apply_idempotency_key,
                    merge_block=merge_block,
                    rejection_result=_finalize_rejection(rejection),
                    fingerprints=_collect_fingerprints(
                        snap=snap,
                        process_key=apply_idempotency_key,
                        estado=pre_apply_estado,
                        manifest_rel=manifest_rel,
                        manifest_sha256=manifest_sha256,
                        hist_path=hist_path,
                        hist_sha256=None,
                        dry_run=None,
                    ),
                )
        except json.JSONDecodeError:
            pass
        except Exception as exc:
            logger.warning("prepare: no se pudo validar manifest: %s", exc)

    if hist_path:
        try:
            hist_raw = await _graph_download_by_path(
                graph, site_id, drive_id, hist_path
            )
            hist_sha256 = _sha256_bytes(hist_raw)
        except Exception as exc:
            logger.warning("prepare: no se pudo hashear histórico: %s", hist_path)

    dry_run_fn = run_amortization_fill_dry_run
    try:
        from app.application.use_cases import amortization_fill_apply as _apply_mod

        dry_run_fn = getattr(
            _apply_mod, "run_amortization_fill_dry_run", run_amortization_fill_dry_run
        )
    except Exception:
        dry_run_fn = run_amortization_fill_dry_run

    dry_run = await dry_run_fn(
        graph,
        report_date_iso=resolved_date or report_date_iso,
        merge_manifest_path=resolved_manifest or merge_manifest_path,
        historical_file_path=resolved_hist or historical_file_path,
        bank_code=resolved_bank_code,
        job_id=job_id,
        update_process_control=update_process_control,
    )

    from app.application.services.abono_apply_gate import evaluate_abono_apply_block

    block = evaluate_abono_apply_block(dry_run)

    base_obs = _apply_observability_base(
        resolved_bank_code=resolved_bank_code,
        resolved_bank_name=resolved_bank_name,
        bank_code_param=bank_code,
        resolved_process_key=apply_idempotency_key,
        resolved_control_path=resolved_control_path,
        ready_banks_detected=ready_banks_detected,
        merge_manifest_source=merge_manifest_source,
        historical_file_source=historical_file_source,
        manifest_rel=manifest_rel,
        hist_path=hist_path,
        process_control_updated=False,
        process_control_estado=pre_apply_estado,
    )

    if block is not None:
        rejection = {
            **base_obs,
            "status": "blocked",
            "mode": "prepare",
            "error_code": block["error_code"],
            "user_message": block["user_message"],
            "next_action": block["next_action"],
            "can_apply": False,
            "outcome": "requires_correction",
            "abono_groups_total": block["abono_groups_total"],
            "abono_groups_blocked": block["abono_groups_blocked"],
            "requires_business_rule": block["requires_business_rule"],
            "blocking_abono_groups": block["blocking_abono_groups"],
            "preflight": dry_run,
            "already_applied": False,
            "apply_idempotency_key": apply_idempotency_key,
            "apply_wrote_changes": False,
            "tables_uploaded_count": 0,
            "tables_skipped_count": 0,
            "idempotent_skips_count": 0,
            "items": list(dry_run.get("items") or []),
            "tables_uploaded": [],
            "tables_summary": [],
            "summary": dry_run.get("summary") or _apply_summarize([]),
            **empty_accounting_pdf_move_summary_safe(),
        }
        return AmortizationPreparedPlan(
            can_apply=False,
            rejection_kind="blocked_abono",
            dry_run=dry_run,
            site_id=site_id,
            drive_id=drive_id,
            resolved_bank_code=resolved_bank_code,
            resolved_bank_name=resolved_bank_name,
            bank_code_param=bank_code,
            resolved_process_key=apply_idempotency_key,
            resolved_control_path=resolved_control_path,
            ready_banks_detected=list(ready_banks_detected),
            merge_manifest_source=merge_manifest_source,
            historical_file_source=historical_file_source,
            manifest_rel=manifest_rel,
            hist_path=hist_path,
            resolved_date=resolved_date,
            pre_apply_estado=pre_apply_estado,
            review_validation_path=review_validation_path,
            apply_idempotency_key=apply_idempotency_key,
            abono_block=block,
            rejection_result=_finalize_rejection(rejection),
            fingerprints=_collect_fingerprints(
                snap=snap,
                process_key=apply_idempotency_key,
                estado=pre_apply_estado,
                manifest_rel=manifest_rel,
                manifest_sha256=manifest_sha256,
                hist_path=hist_path,
                hist_sha256=hist_sha256,
                dry_run=dry_run,
            ),
        )

    try:
        validate_amortization_preflight(dry_run)
    except AmortizationPreflightError as exc:
        rejection = {
            **base_obs,
            "status": "preflight_failed",
            "mode": "prepare",
            "preflight_error_code": exc.error_code,
            "message": str(exc),
            "user_message": (
                "Se encontraron datos que requieren corrección. "
                "No se realizaron escrituras en las tablas."
            ),
            "next_action": (
                "Corrija los documentos indicados y vuelva a procesar la amortización."
            ),
            "can_apply": False,
            "outcome": "requires_correction",
            "preflight": dry_run,
            "already_applied": False,
            "apply_idempotency_key": apply_idempotency_key,
            "apply_wrote_changes": False,
            "tables_uploaded_count": 0,
            "tables_skipped_count": 0,
            "idempotent_skips_count": 0,
            "items": list(dry_run.get("items") or []),
            "tables_uploaded": [],
            "tables_summary": [],
            "summary": dry_run.get("summary") or _apply_summarize([]),
            **empty_accounting_pdf_move_summary_safe(),
        }
        return AmortizationPreparedPlan(
            can_apply=False,
            rejection_kind="preflight",
            dry_run=dry_run,
            site_id=site_id,
            drive_id=drive_id,
            resolved_bank_code=resolved_bank_code,
            resolved_bank_name=resolved_bank_name,
            bank_code_param=bank_code,
            resolved_process_key=apply_idempotency_key,
            resolved_control_path=resolved_control_path,
            ready_banks_detected=list(ready_banks_detected),
            merge_manifest_source=merge_manifest_source,
            historical_file_source=historical_file_source,
            manifest_rel=manifest_rel,
            hist_path=hist_path,
            resolved_date=resolved_date,
            pre_apply_estado=pre_apply_estado,
            review_validation_path=review_validation_path,
            apply_idempotency_key=apply_idempotency_key,
            preflight_error=exc,
            rejection_result=_finalize_rejection(rejection),
            fingerprints=_collect_fingerprints(
                snap=snap,
                process_key=apply_idempotency_key,
                estado=pre_apply_estado,
                manifest_rel=manifest_rel,
                manifest_sha256=manifest_sha256,
                hist_path=hist_path,
                hist_sha256=hist_sha256,
                dry_run=dry_run,
            ),
        )

    if str(dry_run.get("status") or "").strip().lower() == "blocked":
        block_code = str(dry_run.get("error_code") or "DRY_RUN_BLOCKED").strip()
        rejection = {
            **base_obs,
            "status": "blocked",
            "mode": "prepare",
            "error_code": block_code,
            "user_message": dry_run.get("user_message"),
            "next_action": dry_run.get("next_action"),
            "can_apply": False,
            "outcome": "requires_correction",
            "preflight": dry_run,
            "already_applied": False,
            "apply_idempotency_key": apply_idempotency_key,
            "apply_wrote_changes": False,
            "tables_uploaded_count": 0,
            "tables_skipped_count": 0,
            "idempotent_skips_count": 0,
            "items": list(dry_run.get("items") or []),
            "tables_uploaded": [],
            "tables_summary": [],
            "summary": dry_run.get("summary") or _apply_summarize([]),
            **empty_accounting_pdf_move_summary_safe(),
        }
        return AmortizationPreparedPlan(
            can_apply=False,
            rejection_kind="dry_run_blocked",
            dry_run=dry_run,
            site_id=site_id,
            drive_id=drive_id,
            resolved_bank_code=resolved_bank_code,
            resolved_bank_name=resolved_bank_name,
            bank_code_param=bank_code,
            resolved_process_key=apply_idempotency_key,
            resolved_control_path=resolved_control_path,
            ready_banks_detected=list(ready_banks_detected),
            merge_manifest_source=merge_manifest_source,
            historical_file_source=historical_file_source,
            manifest_rel=manifest_rel,
            hist_path=hist_path,
            resolved_date=resolved_date,
            pre_apply_estado=pre_apply_estado,
            review_validation_path=review_validation_path,
            apply_idempotency_key=apply_idempotency_key,
            rejection_result=_finalize_rejection(rejection),
            fingerprints=_collect_fingerprints(
                snap=snap,
                process_key=apply_idempotency_key,
                estado=pre_apply_estado,
                manifest_rel=manifest_rel,
                manifest_sha256=manifest_sha256,
                hist_path=hist_path,
                hist_sha256=hist_sha256,
                dry_run=dry_run,
            ),
        )

    can_apply = bool(dry_run.get("can_apply"))
    fingerprints = _collect_fingerprints(
        snap=snap,
        process_key=apply_idempotency_key,
        estado=pre_apply_estado,
        manifest_rel=manifest_rel,
        manifest_sha256=manifest_sha256,
        hist_path=hist_path,
        hist_sha256=hist_sha256,
        dry_run=dry_run,
    )

    if not can_apply:
        rejection = {
            **base_obs,
            "status": "blocked",
            "mode": "prepare",
            "can_apply": False,
            "outcome": "requires_correction",
            "user_message": (
                "Se encontraron datos que requieren corrección. "
                "No se realizaron escrituras en las tablas."
            ),
            "next_action": (
                "Corrija los documentos indicados y vuelva a procesar la amortización."
            ),
            "preflight": dry_run,
            "already_applied": False,
            "apply_idempotency_key": apply_idempotency_key,
            "apply_wrote_changes": False,
            "items": list(dry_run.get("items") or []),
            "tables_uploaded": [],
            "tables_summary": [],
            "summary": dry_run.get("summary") or _apply_summarize([]),
            **empty_accounting_pdf_move_summary_safe(),
        }
        return AmortizationPreparedPlan(
            can_apply=False,
            rejection_kind="preflight",
            dry_run=dry_run,
            fingerprints=fingerprints,
            site_id=site_id,
            drive_id=drive_id,
            resolved_bank_code=resolved_bank_code,
            resolved_bank_name=resolved_bank_name,
            bank_code_param=bank_code,
            resolved_process_key=apply_idempotency_key,
            resolved_control_path=resolved_control_path,
            ready_banks_detected=list(ready_banks_detected),
            merge_manifest_source=merge_manifest_source,
            historical_file_source=historical_file_source,
            manifest_rel=manifest_rel,
            hist_path=hist_path,
            resolved_date=resolved_date,
            pre_apply_estado=pre_apply_estado,
            review_validation_path=review_validation_path,
            apply_idempotency_key=apply_idempotency_key,
            rejection_result=_finalize_rejection(rejection),
        )

    return AmortizationPreparedPlan(
        can_apply=True,
        dry_run=dry_run,
        fingerprints=fingerprints,
        site_id=site_id,
        drive_id=drive_id,
        resolved_bank_code=resolved_bank_code,
        resolved_bank_name=resolved_bank_name,
        bank_code_param=bank_code,
        resolved_process_key=apply_idempotency_key,
        resolved_control_path=resolved_control_path,
        ready_banks_detected=list(ready_banks_detected),
        merge_manifest_source=merge_manifest_source,
        historical_file_source=historical_file_source,
        manifest_rel=manifest_rel,
        hist_path=hist_path,
        resolved_date=resolved_date,
        pre_apply_estado=pre_apply_estado,
        review_validation_path=review_validation_path,
        apply_idempotency_key=apply_idempotency_key,
    )


async def verify_amortization_plan_freshness(
    graph: GraphApiPort,
    plan: AmortizationPreparedPlan,
) -> dict[str, Any] | None:
    """Relee insumos críticos. Retorna payload de rechazo si hay cambio; None si OK."""
    from app.application.use_cases.amortization_fill_apply import (
        _is_coarse_apply_already_done,
        empty_accounting_pdf_move_summary_safe,
    )

    fp = plan.fingerprints or {}
    want_pk = str(fp.get("process_key") or plan.apply_idempotency_key or "").strip()

    try:
        snap = await _read_control_snapshot(
            graph, plan.site_id, plan.drive_id, bank_code=plan.resolved_bank_code
        )
    except Exception as exc:
        logger.warning("freshness: no se pudo leer control: %s", exc)
        snap = None

    if snap is not None:
        got_pk = (snap.process_key or "").strip()
        if want_pk and got_pk and got_pk != want_pk:
            return _stale_result(want_pk, plan, "PROCESS_KEY_CHANGED")

        if _is_coarse_apply_already_done(snap):
            from app.application.use_cases.amortization_fill_apply import (
                _build_already_applied_result,
            )

            return _build_already_applied_result(
                snap=snap,
                bank_code=plan.resolved_bank_code,
                bank_code_param=plan.bank_code_param,
            )

        estado = (snap.estado_proceso or "").strip().upper()
        if (
            estado not in AMORTIZATION_RUNNABLE_STATES
            and estado != "APLICANDO_AMORTIZACION"
        ):
            return _stale_result(want_pk, plan, "ESTADO_NOT_RUNNABLE")

        if not snap.is_active:
            return _stale_result(want_pk, plan, "PROCESS_INACTIVE")
    else:
        # Sin control legible no asumimos already_applied; los hashes de
        # manifiesto/histórico siguen protegiendo insumos críticos.
        logger.warning(
            "freshness: control ilegible; se continúan checks de hash de archivos"
        )

    manifest_rel = str(fp.get("merge_manifest_path") or plan.manifest_rel or "").strip()
    want_manifest_hash = str(fp.get("manifest_sha256") or "").strip()
    if manifest_rel and want_manifest_hash:
        try:
            raw = await _graph_download_by_path(
                graph, plan.site_id, plan.drive_id, manifest_rel
            )
            if _sha256_bytes(raw) != want_manifest_hash:
                return _stale_result(want_pk, plan, "MANIFEST_CHANGED")
        except Exception as exc:
            logger.warning("freshness: manifest: %s", exc)
            return _stale_result(want_pk, plan, "MANIFEST_UNREADABLE")

    hist_path = str(fp.get("historical_file_path") or plan.hist_path or "").strip()
    want_hist_hash = str(fp.get("historical_sha256") or "").strip()
    if hist_path and want_hist_hash:
        try:
            raw = await _graph_download_by_path(
                graph, plan.site_id, plan.drive_id, hist_path
            )
            if _sha256_bytes(raw) != want_hist_hash:
                return _stale_result(want_pk, plan, "HISTORICAL_CHANGED")
        except Exception as exc:
            logger.warning("freshness: histórico: %s", exc)
            return _stale_result(want_pk, plan, "HISTORICAL_UNREADABLE")

    table_fps = list(fp.get("table_fingerprints") or [])
    if not table_fps:
        for p in fp.get("table_paths") or []:
            table_fps.append({"path": str(p), "sha256": ""})

    from app.application.services.amortization_workbook import detect_amortization_sheet
    from app.application.use_cases.amortization_fill_dry_run import (
        RETENCIONES_COLUMN_MISSING,
        _PAYOFF_TOLERANCE,
    )
    from app.application.use_cases.validate_payment_report import (
        _graph_get_item_metadata_by_path,
    )
    import openpyxl
    import io as _io

    items = [it for it in (plan.dry_run or {}).get("items") or [] if isinstance(it, dict)]
    table_bytes: dict[str, bytes] = {}
    table_etags: dict[str, str] = {}
    for spec in table_fps:
        path = str(spec.get("path") or "").strip()
        if not path:
            continue
        want_hash = str(spec.get("sha256") or "").strip()
        meta_before = await _graph_get_item_metadata_by_path(
            graph, plan.site_id, plan.drive_id, path
        )
        etag_before = str(meta_before.get("eTag") or meta_before.get("etag") or "")
        if not meta_before or not etag_before:
            logger.warning("freshness: metadata BEFORE faltante path=%s", path)
            return _stale_result(
                want_pk, plan, "AMORTIZATION_TABLE_CHANGED_REQUIRES_REVALIDATION"
            )
        try:
            raw = await _graph_download_by_path(
                graph, plan.site_id, plan.drive_id, path
            )
        except Exception as exc:
            logger.warning("freshness: tabla %s: %s", path, exc)
            return _stale_result(want_pk, plan, "AMORTIZATION_TABLE_CHANGED_REQUIRES_REVALIDATION")
        meta_after = await _graph_get_item_metadata_by_path(
            graph, plan.site_id, plan.drive_id, path
        )
        etag_after = str(meta_after.get("eTag") or meta_after.get("etag") or "")
        if not meta_after or not etag_after:
            logger.warning("freshness: metadata AFTER faltante path=%s", path)
            return _stale_result(
                want_pk, plan, "AMORTIZATION_TABLE_CHANGED_REQUIRES_REVALIDATION"
            )
        if etag_before and etag_after and etag_before != etag_after:
            return _stale_result(
                want_pk, plan, "AMORTIZATION_TABLE_CHANGED_REQUIRES_REVALIDATION"
            )
        got_hash = _sha256_bytes(raw)
        if want_hash and got_hash != want_hash:
            return _stale_result(
                want_pk, plan, "AMORTIZATION_TABLE_CHANGED_REQUIRES_REVALIDATION"
            )
        try:
            wb = openpyxl.load_workbook(_io.BytesIO(raw), data_only=True)
            try:
                match = detect_amortization_sheet(wb, tabla_amortizacion_path=path)
            finally:
                closer = getattr(wb, "close", None)
                if callable(closer):
                    closer()
        except Exception:
            return _stale_result(
                want_pk, plan, "AMORTIZATION_TABLE_CHANGED_REQUIRES_REVALIDATION"
            )
        headers = match.headers
        for it in items:
            if str(it.get("tabla_amortizacion_path") or "").strip() != path:
                continue
            pay = it.get("payment_application") or {}
            ret = float(pay.get("retenciones") or it.get("valor_retenciones") or 0)
            if ret > _PAYOFF_TOLERANCE and not headers.get("retenciones"):
                return {
                    "status": "blocked",
                    "mode": "apply",
                    "outcome": "requires_correction",
                    "can_apply": False,
                    "apply_wrote_changes": False,
                    "already_applied": False,
                    "error_code": RETENCIONES_COLUMN_MISSING,
                    "user_message": (
                        "La tabla de amortización del crédito no tiene la columna RETENCIONES, "
                        "pero el asiento contiene retenciones. No se realizó ninguna modificación."
                    ),
                    "next_action": (
                        "Abra la tabla de amortización y corrija la plantilla para incluir "
                        "la columna RETENCIONES. Luego vuelva a procesar la amortización."
                    ),
                    "process_key": want_pk,
                    "bank_code": plan.resolved_bank_code,
                    "preflight": plan.dry_run,
                }
        table_bytes[path] = raw
        table_etags[path] = etag_after or etag_before

    if table_etags:
        plan.table_bytes = table_bytes
        plan.table_etags = table_etags

    return None


def _stale_result(
    process_key: str,
    plan: AmortizationPreparedPlan,
    error_code: str,
) -> dict[str, Any]:
    from app.application.use_cases.amortization_fill_apply import (
        empty_accounting_pdf_move_summary_safe,
    )

    return {
        "status": "blocked",
        "mode": "apply",
        "outcome": "input_changed_requires_retry",
        "can_apply": False,
        "apply_wrote_changes": False,
        "already_applied": False,
        "error_code": error_code,
        "user_message": (
            "La tabla de amortización cambió después de la validación. "
            "No se realizó ninguna modificación sobre esa versión."
            if error_code == "AMORTIZATION_TABLE_CHANGED_REQUIRES_REVALIDATION"
            else (
                "La información cambió durante la validación. "
                "Actualice e intente nuevamente."
            )
        ),
        "next_action": (
            "Vuelva a procesar la amortización para validar la tabla actual."
            if error_code == "AMORTIZATION_TABLE_CHANGED_REQUIRES_REVALIDATION"
            else "Actualice el detalle del proceso e intente nuevamente."
        ),
        "process_key": process_key,
        "bank_code": plan.resolved_bank_code,
        "preflight": plan.dry_run,
        **empty_accounting_pdf_move_summary_safe(),
    }
