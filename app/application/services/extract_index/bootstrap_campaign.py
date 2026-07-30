"""
Motor de bootstrap técnico desacoplado (Fase 3A1).

Sin HTTP, Azure, Graph real ni Generate. Solo puertos + fakes.
"""

from __future__ import annotations

import logging
import uuid
from typing import Callable

from app.application.services.extract_index.bootstrap_models import (
    BOOTSTRAP_PARSER_VERSION,
    BOOTSTRAP_SCHEMA_VERSION,
    BootstrapCheckpoint,
    CampaignScopeKey,
    CampaignTotals,
    ChunkResult,
    ChunkStopReason,
    LogicalPreflightResult,
)
from app.domain.exceptions import (
    BootstrapCampaignError,
    BootstrapCheckpointError,
    BootstrapDriveMismatch,
    BootstrapEnvironmentMismatch,
    BootstrapSecurityViolation,
    BootstrapVersionMismatch,
    DocumentMutationForbidden,
    ExtractIndexError,
)
from app.domain.models.extract_index import (
    BootstrapControlRecord,
    CampaignStatus,
    ExtractIndexCandidate,
    ExtractIndexEnvironment,
    ParseStatus,
)
from app.domain.ports.bootstrap_scope import BootstrapCreditUnit, BootstrapScopePort
from app.domain.ports.clock import ClockPort
from app.domain.ports.credit_lock import CreditLockPort
from app.domain.ports.document_tree_readonly import DocumentTreeReadOnlyPort
from app.domain.ports.extract_index import (
    BootstrapControlRepository,
    ExtractIndexRepository,
)

logger = logging.getLogger(__name__)

BOOTSTRAP_LOCK_OWNER = "bootstrap"
GENERATE_LOCK_OWNER = "generate"

_ACTIVE_STATUSES = frozenset({CampaignStatus.RUNNING, CampaignStatus.PAUSED})


class BootstrapCampaignService:
    """
    Casos de uso técnicos: start / process_chunk / status / pause / resume / cancel.
    """

    def __init__(
        self,
        *,
        control_repo: BootstrapControlRepository,
        index_repo: ExtractIndexRepository,
        lock: CreditLockPort,
        scope: BootstrapScopePort,
        clock: ClockPort,
        document_tree: DocumentTreeReadOnlyPort | None = None,
        max_credits_per_chunk: int = 3,
        max_seconds_per_chunk: float = 180.0,
        fail_checkpoint_once: bool = False,
        on_step: Callable[[str], None] | None = None,
    ) -> None:
        self._control = control_repo
        self._index = index_repo
        self._lock = lock
        self._scope = scope
        self._clock = clock
        self._document_tree = document_tree
        self._max_credits = max(1, int(max_credits_per_chunk))
        self._max_seconds = max(0.05, float(max_seconds_per_chunk))
        self._fail_checkpoint_once = fail_checkpoint_once
        self._checkpoint_fail_armed = fail_checkpoint_once
        self._on_step = on_step

    def _trace(self, step: str, totals: CampaignTotals) -> None:
        totals.call_order_trace.append(step)
        if self._on_step is not None:
            self._on_step(step)

    async def start_campaign(self, scope_key: CampaignScopeKey) -> BootstrapControlRecord:
        campaign_id = scope_key.as_campaign_id()
        existing = await self._control.get_by_campaign_id(
            environment=scope_key.environment, campaign_id=campaign_id
        )
        if existing is not None and existing.status in _ACTIVE_STATUSES:
            return existing

        totals = CampaignTotals(
            drive_id=scope_key.drive_id,
            root_identity=scope_key.root_identity,
            parser_version=scope_key.parser_version,
            schema_version=scope_key.schema_version,
        )
        record = BootstrapControlRecord(
            environment=scope_key.environment,
            campaign_id=campaign_id,
            status=CampaignStatus.RUNNING,
            chunk_id="",
            checkpoint="",
            current_client="",
            current_credit="",
            heartbeat=self._clock.now(),
            continuation_required=False,
            paused=False,
            cancellation_requested=False,
            completed=False,
            error_summary="",
            totals_json=totals.to_json(),
            list_item_id=existing.list_item_id if existing else None,
        )
        return await self._control.upsert_by_campaign_id(record)

    async def get_status(
        self, *, environment: ExtractIndexEnvironment, campaign_id: str
    ) -> BootstrapControlRecord | None:
        return await self._control.get_by_campaign_id(
            environment=environment, campaign_id=campaign_id
        )

    async def request_cancellation(
        self, *, environment: ExtractIndexEnvironment, campaign_id: str
    ) -> BootstrapControlRecord:
        record = await self._require_campaign(environment, campaign_id)
        record.cancellation_requested = True
        record.heartbeat = self._clock.now()
        return await self._control.upsert_by_campaign_id(record)

    async def pause(
        self, *, environment: ExtractIndexEnvironment, campaign_id: str
    ) -> BootstrapControlRecord:
        record = await self._require_campaign(environment, campaign_id)
        record.paused = True
        record.status = CampaignStatus.PAUSED
        record.continuation_required = False
        record.heartbeat = self._clock.now()
        return await self._control.upsert_by_campaign_id(record)

    async def resume(
        self, *, environment: ExtractIndexEnvironment, campaign_id: str
    ) -> BootstrapControlRecord:
        record = await self._require_campaign(environment, campaign_id)
        self._assert_scope_consistency(record, expected_env=environment)
        if record.extra_fields.get("security_violation") or CampaignTotals.from_json(
            record.totals_json
        ).security_violation:
            raise BootstrapSecurityViolation(
                "No se puede reanudar una campaña con security_violation"
            )
        record.paused = False
        record.cancellation_requested = False
        record.status = CampaignStatus.RUNNING
        record.completed = False
        record.continuation_required = True
        record.heartbeat = self._clock.now()
        return await self._control.upsert_by_campaign_id(record)

    async def process_one_chunk(
        self,
        *,
        environment: ExtractIndexEnvironment,
        campaign_id: str,
        expected_drive_id: str | None = None,
    ) -> ChunkResult:
        record = await self._require_campaign(environment, campaign_id)
        totals = CampaignTotals.from_json(record.totals_json)
        self._assert_scope_consistency(
            record,
            expected_env=environment,
            expected_drive_id=expected_drive_id or totals.drive_id,
            totals=totals,
        )

        chunk_id = f"chunk-{uuid.uuid4().hex[:12]}"
        record.chunk_id = chunk_id
        record.heartbeat = self._clock.now()
        call_order: list[str] = []

        def _local_trace(step: str) -> None:
            call_order.append(step)
            self._trace(step, totals)

        # Al iniciar el chunk
        if record.cancellation_requested:
            return await self._finalize_cancelled(record, totals, chunk_id, call_order)
        if record.paused or record.status == CampaignStatus.PAUSED:
            record.status = CampaignStatus.PAUSED
            record.continuation_required = False
            record.totals_json = totals.to_json()
            await self._control.upsert_by_campaign_id(record)
            return ChunkResult(
                campaign_id=campaign_id,
                chunk_id=chunk_id,
                status=CampaignStatus.PAUSED,
                stop_reason=ChunkStopReason.PAUSED,
                continuation_required=False,
                call_order=call_order,
                heartbeat=record.heartbeat,
            )
        if totals.security_violation:
            raise BootstrapSecurityViolation(
                "Campaña bloqueada por security_violation previa"
            )

        record.status = CampaignStatus.RUNNING
        record.paused = False
        record.completed = False
        await self._control.upsert_by_campaign_id(record)

        started = self._clock.monotonic()
        checkpoint = BootstrapCheckpoint.from_json(record.checkpoint)
        after_key = checkpoint.last_confirmed_credit_key if checkpoint else None

        credits_confirmed = 0
        credits_skipped = 0
        credits_attempted = 0
        stop_reason = ChunkStopReason.EMPTY
        error_summary = ""
        security = False

        # Pedir más de max para detectar continuation; procesamos hasta el límite.
        pending = await self._scope.list_credits(
            after_credit_key=after_key, limit=self._max_credits + 1
        )

        for unit in pending:
            # Presupuesto cooperativo: comprobar ANTES de cada crédito
            elapsed = self._clock.monotonic() - started
            if elapsed >= self._max_seconds:
                stop_reason = ChunkStopReason.MAX_SECONDS
                break
            if credits_confirmed + credits_skipped >= self._max_credits:
                stop_reason = ChunkStopReason.MAX_CREDITS
                break

            # Pause / cancel antes del crédito
            refreshed = await self._require_campaign(environment, campaign_id)
            if refreshed.cancellation_requested:
                record = refreshed
                return await self._finalize_cancelled(
                    record, totals, chunk_id, call_order, started=started
                )
            if refreshed.paused:
                record = refreshed
                record.status = CampaignStatus.PAUSED
                record.continuation_required = False
                record.totals_json = totals.to_json()
                record.heartbeat = self._clock.now()
                await self._control.upsert_by_campaign_id(record)
                return ChunkResult(
                    campaign_id=campaign_id,
                    chunk_id=chunk_id,
                    status=CampaignStatus.PAUSED,
                    stop_reason=ChunkStopReason.PAUSED,
                    continuation_required=False,
                    credits_attempted=credits_attempted,
                    credits_confirmed=credits_confirmed,
                    credits_skipped_locked=credits_skipped,
                    elapsed_seconds=self._clock.monotonic() - started,
                    call_order=call_order,
                    heartbeat=record.heartbeat,
                )

            credit_key = unit.candidates[0].credit_key.as_string() if unit.candidates else (
                f"{environment.value}|{totals.drive_id}|{unit.credit_folder_item_id}"
            )
            record.current_client = unit.client_identity
            record.current_credit = unit.credit_identity
            record.heartbeat = self._clock.now()
            await self._control.upsert_by_campaign_id(record)

            credits_attempted += 1
            try:
                outcome = await self._process_credit(
                    unit=unit,
                    credit_key=credit_key,
                    environment=environment,
                    drive_id=totals.drive_id,
                    campaign_id=campaign_id,
                    totals=totals,
                    trace=_local_trace,
                )
            except DocumentMutationForbidden as exc:
                security = True
                error_summary = f"security_violation:{type(exc).__name__}"
                stop_reason = ChunkStopReason.SECURITY_VIOLATION
                await self._abort_security(record, totals, error_summary, call_order)
                return ChunkResult(
                    campaign_id=campaign_id,
                    chunk_id=chunk_id,
                    status=CampaignStatus.FAILED,
                    stop_reason=stop_reason,
                    continuation_required=False,
                    credits_attempted=credits_attempted,
                    credits_confirmed=credits_confirmed,
                    credits_skipped_locked=credits_skipped,
                    elapsed_seconds=self._clock.monotonic() - started,
                    security_violation=True,
                    error_summary=error_summary,
                    call_order=call_order,
                    heartbeat=self._clock.now(),
                )
            except BootstrapSecurityViolation as exc:
                security = True
                error_summary = str(exc)[:300]
                stop_reason = ChunkStopReason.SECURITY_VIOLATION
                await self._abort_security(record, totals, error_summary, call_order)
                return ChunkResult(
                    campaign_id=campaign_id,
                    chunk_id=chunk_id,
                    status=CampaignStatus.FAILED,
                    stop_reason=stop_reason,
                    continuation_required=False,
                    credits_attempted=credits_attempted,
                    credits_confirmed=credits_confirmed,
                    credits_skipped_locked=credits_skipped,
                    elapsed_seconds=self._clock.monotonic() - started,
                    security_violation=True,
                    error_summary=error_summary,
                    call_order=call_order,
                    heartbeat=self._clock.now(),
                )
            except BootstrapCheckpointError as exc:
                # Upserts OK pero checkpoint falló: no asumir confirmado
                error_summary = str(exc)[:300]
                stop_reason = ChunkStopReason.CHECKPOINT_FAILURE
                totals.last_error = error_summary
                record.error_summary = error_summary
                record.continuation_required = True
                record.status = CampaignStatus.RUNNING
                record.totals_json = totals.to_json()
                record.heartbeat = self._clock.now()
                await self._control.upsert_by_campaign_id(record)
                return ChunkResult(
                    campaign_id=campaign_id,
                    chunk_id=chunk_id,
                    status=CampaignStatus.RUNNING,
                    stop_reason=stop_reason,
                    continuation_required=True,
                    credits_attempted=credits_attempted,
                    credits_confirmed=credits_confirmed,
                    credits_skipped_locked=credits_skipped,
                    elapsed_seconds=self._clock.monotonic() - started,
                    error_summary=error_summary,
                    call_order=call_order,
                    heartbeat=record.heartbeat,
                )
            except ExtractIndexError as exc:
                totals.credits_failed += 1
                totals.last_error = str(exc)[:300]
                error_summary = totals.last_error
                stop_reason = ChunkStopReason.UPSERT_FAILURE
                record.error_summary = error_summary
                record.continuation_required = True
                record.status = CampaignStatus.RUNNING
                record.totals_json = totals.to_json()
                record.heartbeat = self._clock.now()
                await self._control.upsert_by_campaign_id(record)
                return ChunkResult(
                    campaign_id=campaign_id,
                    chunk_id=chunk_id,
                    status=CampaignStatus.RUNNING,
                    stop_reason=stop_reason,
                    continuation_required=True,
                    credits_attempted=credits_attempted,
                    credits_confirmed=credits_confirmed,
                    credits_skipped_locked=credits_skipped,
                    elapsed_seconds=self._clock.monotonic() - started,
                    error_summary=error_summary,
                    call_order=call_order,
                    heartbeat=record.heartbeat,
                )

            if outcome == "skipped_locked":
                credits_skipped += 1
                totals.credits_skipped_locked += 1
                stop_reason = ChunkStopReason.LOCK_CONTENTION
                # Continúa con el siguiente (omitir, no forzar)
                continue

            # outcome == confirmed → checkpoint ya guardado dentro de _process_credit
            credits_confirmed += 1
            totals.credits_processed += 1
            stop_reason = ChunkStopReason.MAX_CREDITS  # provisional

            # Pause / cancel después de confirmar
            refreshed = await self._require_campaign(environment, campaign_id)
            record = refreshed
            if refreshed.cancellation_requested:
                return await self._finalize_cancelled(
                    record, totals, chunk_id, call_order, started=started
                )
            if refreshed.paused:
                record.status = CampaignStatus.PAUSED
                record.continuation_required = False
                record.totals_json = totals.to_json()
                record.heartbeat = self._clock.now()
                await self._control.upsert_by_campaign_id(record)
                return ChunkResult(
                    campaign_id=campaign_id,
                    chunk_id=chunk_id,
                    status=CampaignStatus.PAUSED,
                    stop_reason=ChunkStopReason.PAUSED,
                    continuation_required=False,
                    credits_attempted=credits_attempted,
                    credits_confirmed=credits_confirmed,
                    credits_skipped_locked=credits_skipped,
                    elapsed_seconds=self._clock.monotonic() - started,
                    call_order=call_order,
                    heartbeat=record.heartbeat,
                )

        # ¿Quedan más créditos?
        last_cp = BootstrapCheckpoint.from_json(record.checkpoint)
        after = last_cp.last_confirmed_credit_key if last_cp else after_key
        remaining = await self._scope.list_credits(after_credit_key=after, limit=1)
        has_more = len(remaining) > 0

        if not pending and stop_reason == ChunkStopReason.EMPTY:
            has_more = False

        if stop_reason == ChunkStopReason.MAX_SECONDS:
            continuation = True
        elif stop_reason == ChunkStopReason.MAX_CREDITS and has_more:
            continuation = True
        elif stop_reason == ChunkStopReason.LOCK_CONTENTION and has_more:
            continuation = True
        elif has_more and credits_confirmed + credits_skipped > 0:
            continuation = True
            stop_reason = ChunkStopReason.MAX_CREDITS
        elif not has_more:
            continuation = False
            stop_reason = ChunkStopReason.COMPLETED
        else:
            continuation = False

        totals.chunks_run += 1
        record.totals_json = totals.to_json()
        record.continuation_required = continuation
        record.heartbeat = self._clock.now()
        record.current_client = ""
        record.current_credit = ""
        if not continuation and stop_reason == ChunkStopReason.COMPLETED:
            record.status = CampaignStatus.COMPLETED
            record.completed = True
        else:
            record.status = CampaignStatus.RUNNING
            record.completed = False
        await self._control.upsert_by_campaign_id(record)

        return ChunkResult(
            campaign_id=campaign_id,
            chunk_id=chunk_id,
            status=record.status,
            stop_reason=stop_reason,
            continuation_required=continuation,
            credits_attempted=credits_attempted,
            credits_confirmed=credits_confirmed,
            credits_skipped_locked=credits_skipped,
            elapsed_seconds=self._clock.monotonic() - started,
            security_violation=security,
            error_summary=error_summary,
            call_order=call_order,
            heartbeat=record.heartbeat,
        )

    async def _process_credit(
        self,
        *,
        unit: BootstrapCreditUnit,
        credit_key: str,
        environment: ExtractIndexEnvironment,
        drive_id: str,
        campaign_id: str,
        totals: CampaignTotals,
        trace: Callable[[str], None],
    ) -> str:
        """
        Orden obligatorio:
        lock → read → reconcile → parse → upserts → confirm → checkpoint → metrics → unlock
        """
        acquired = await self._lock.try_acquire(credit_key, owner=BOOTSTRAP_LOCK_OWNER)
        if not acquired:
            holder = await self._lock.holder(credit_key)
            if holder == GENERATE_LOCK_OWNER:
                trace("skip_locked_generate_priority")
            else:
                trace("skip_locked")
            return "skipped_locked"

        try:
            trace("lock_acquired")
            # 2. Leer candidatos (unidad ya trae candidatos locales; tree solo lectura)
            candidates = list(unit.candidates)
            trace("read_candidates")
            if self._document_tree is not None:
                # Touch read-only path (sin mutar); fallos de mutación vienen del guard
                await self._document_tree.get_json(
                    f"/drives/{drive_id}/items/{unit.credit_folder_item_id}"
                )

            # 3–4. Reconciliar / parsear (en 3A1: candidatos ya preparados; marcar parse)
            for cand in candidates:
                if cand.environment != environment:
                    raise BootstrapEnvironmentMismatch(
                        "Candidato con ENVIRONMENT distinto al de la campaña"
                    )
                if cand.drive_id != drive_id:
                    raise BootstrapDriveMismatch(
                        "Candidato con drive_id distinto al de la campaña"
                    )
                if cand.parse_status == ParseStatus.ERROR:
                    totals.credits_parse_error += 1
                trace("reconcile_parse")

            # 5–6. Upserts idempotentes + confirmación
            for cand in candidates:
                trace("upsert_start")
                await self._index.upsert_by_doc_key(cand)
                trace("upsert_confirmed")
                totals.upserts_ok += 1

            # 7. Checkpoint SOLO después de confirmar upserts
            new_cp = BootstrapCheckpoint(
                environment=environment,
                drive_id=drive_id,
                last_confirmed_client=unit.client_identity,
                last_confirmed_credit=unit.credit_identity,
                last_confirmed_credit_key=credit_key,
                opaque_cursor=unit.opaque_cursor or unit.credit_folder_item_id,
                parser_version=totals.parser_version,
                schema_version=totals.schema_version,
            )
            if self._checkpoint_fail_armed:
                self._checkpoint_fail_armed = False
                trace("checkpoint_failed")
                raise BootstrapCheckpointError(
                    "checkpoint_persist_failed_after_upserts"
                )

            record = await self._control.get_by_campaign_id(
                environment=environment,
                campaign_id=campaign_id,
            )
            if record is None:
                raise BootstrapCampaignError("Campaña desapareció durante el crédito")
            record.checkpoint = new_cp.to_json()
            record.current_client = unit.client_identity
            record.current_credit = unit.credit_identity
            record.heartbeat = self._clock.now()
            record.totals_json = totals.to_json()
            await self._control.upsert_by_campaign_id(record)
            trace("checkpoint_saved")

            # 8. métricas ya en totals
            trace("metrics_updated")
            return "confirmed"
        finally:
            await self._lock.release(credit_key, owner=BOOTSTRAP_LOCK_OWNER)
            trace("lock_released")

    async def _finalize_cancelled(
        self,
        record: BootstrapControlRecord,
        totals: CampaignTotals,
        chunk_id: str,
        call_order: list[str],
        *,
        started: float | None = None,
    ) -> ChunkResult:
        record.status = CampaignStatus.CANCELLED
        record.cancellation_requested = True
        record.continuation_required = False
        record.completed = False
        record.paused = False
        record.chunk_id = chunk_id
        record.totals_json = totals.to_json()
        record.heartbeat = self._clock.now()
        record.current_client = ""
        record.current_credit = ""
        await self._control.upsert_by_campaign_id(record)
        elapsed = (
            self._clock.monotonic() - started if started is not None else 0.0
        )
        return ChunkResult(
            campaign_id=record.campaign_id,
            chunk_id=chunk_id,
            status=CampaignStatus.CANCELLED,
            stop_reason=ChunkStopReason.CANCELLED,
            continuation_required=False,
            elapsed_seconds=elapsed,
            call_order=call_order,
            heartbeat=record.heartbeat,
        )

    async def _abort_security(
        self,
        record: BootstrapControlRecord,
        totals: CampaignTotals,
        error_summary: str,
        call_order: list[str],
    ) -> None:
        totals.security_violation = True
        totals.last_error = error_summary
        record.status = CampaignStatus.FAILED
        record.paused = True
        record.continuation_required = False
        record.completed = False
        record.error_summary = error_summary
        record.totals_json = totals.to_json()
        record.heartbeat = self._clock.now()
        await self._control.upsert_by_campaign_id(record)
        logger.info(
            "bootstrap_security_violation campaign_id=%s error=%s",
            record.campaign_id,
            error_summary[:200],
        )

    async def _require_campaign(
        self, environment: ExtractIndexEnvironment, campaign_id: str
    ) -> BootstrapControlRecord:
        record = await self._control.get_by_campaign_id(
            environment=environment, campaign_id=campaign_id
        )
        if record is None:
            raise BootstrapCampaignError(f"Campaña no encontrada: {campaign_id}")
        if record.environment != environment:
            raise BootstrapEnvironmentMismatch(
                f"ENVIRONMENT mismatch: campaign={record.environment.value} "
                f"requested={environment.value}"
            )
        return record

    def _assert_scope_consistency(
        self,
        record: BootstrapControlRecord,
        *,
        expected_env: ExtractIndexEnvironment,
        expected_drive_id: str | None = None,
        totals: CampaignTotals | None = None,
    ) -> None:
        if record.environment != expected_env:
            raise BootstrapEnvironmentMismatch(
                f"ENVIRONMENT mismatch: {record.environment.value} vs {expected_env.value}"
            )
        totals = totals or CampaignTotals.from_json(record.totals_json)
        if expected_drive_id and totals.drive_id and totals.drive_id != expected_drive_id:
            raise BootstrapDriveMismatch(
                f"drive_id mismatch: {totals.drive_id} vs {expected_drive_id}"
            )
        cp = BootstrapCheckpoint.from_json(record.checkpoint)
        if cp is not None:
            if cp.environment != expected_env:
                raise BootstrapEnvironmentMismatch(
                    "Checkpoint ENVIRONMENT distinto al de la campaña"
                )
            if expected_drive_id and cp.drive_id and cp.drive_id != expected_drive_id:
                raise BootstrapDriveMismatch(
                    "Checkpoint drive_id distinto al de la campaña"
                )
            if cp.parser_version != totals.parser_version:
                raise BootstrapVersionMismatch(
                    f"parser_version mismatch: {cp.parser_version} vs {totals.parser_version}"
                )
            if cp.schema_version != totals.schema_version:
                raise BootstrapVersionMismatch(
                    f"schema_version mismatch: {cp.schema_version} vs {totals.schema_version}"
                )


def logical_preflight(
    *,
    bootstrap_enabled: bool,
    mode: str,
    has_control_repo: bool,
    has_index_repo: bool,
    has_lock: bool,
    has_scope: bool,
    has_readonly_tree: bool,
    control_schema_ok: bool = True,
    index_schema_ok: bool = True,
) -> LogicalPreflightResult:
    """
    Preflight puramente lógico (sin Graph real).
    """
    issues: list[str] = []
    if not bootstrap_enabled:
        issues.append("bootstrap_disabled")
    if mode.strip().lower() == "active":
        issues.append("active_mode_forbidden_in_3a1")
    if not has_control_repo:
        issues.append("missing_control_repo")
    if not has_index_repo:
        issues.append("missing_index_repo")
    if not has_lock:
        issues.append("missing_credit_lock")
    if not has_scope:
        issues.append("missing_bootstrap_scope")
    if not has_readonly_tree:
        issues.append("missing_readonly_document_tree")
    if not control_schema_ok:
        issues.append("control_schema_incompatible")
    if not index_schema_ok:
        issues.append("index_schema_incompatible")
    return LogicalPreflightResult(
        ok=not issues,
        issues=issues,
        capabilities={
            "parser_version": BOOTSTRAP_PARSER_VERSION,
            "schema_version": BOOTSTRAP_SCHEMA_VERSION,
            "graph_real": False,
            "router": False,
            "active_mode": False,
        },
    )
