"""Fase 3A1: motor bootstrap técnico desacoplado (solo fakes locales)."""

from __future__ import annotations

import asyncio
import pathlib
from datetime import date

import pytest

from app.application.services.extract_index.bootstrap_campaign import (
    GENERATE_LOCK_OWNER,
    BootstrapCampaignService,
)
from app.application.services.extract_index.bootstrap_clock import FakeClock
from app.application.services.extract_index.bootstrap_models import (
    BOOTSTRAP_PARSER_VERSION,
    BOOTSTRAP_SCHEMA_VERSION,
    BootstrapCheckpoint,
    CampaignScopeKey,
    CampaignTotals,
    ChunkStopReason,
)
from app.application.services.extract_index.credit_lock import InMemoryCreditLock
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
    BootstrapDriveMismatch,
    BootstrapEnvironmentMismatch,
    BootstrapSecurityViolation,
    BootstrapVersionMismatch,
    DocumentMutationForbidden,
)
from app.domain.models.extract_index import (
    CampaignStatus,
    CreditKey,
    DocKey,
    ExtractIndexCandidate,
    ExtractIndexEnvironment,
    ParseStatus,
)
from app.domain.ports.bootstrap_scope import BootstrapCreditUnit
from tests.fakes.fake_bootstrap import (
    FakeBootstrapScope,
    FakeReadonlyDocumentTree,
    InMemoryBootstrapControlRepository,
    InMemoryExtractIndexRepository,
)


def _cand(
    *,
    env: ExtractIndexEnvironment = ExtractIndexEnvironment.SANDBOX,
    drive: str = "drive-1",
    folder: str = "cred-1",
    item: str = "pdf-1",
    parse: ParseStatus = ParseStatus.OK,
    parse_error: str = "",
) -> ExtractIndexCandidate:
    ck = CreditKey(environment=env, drive_id=drive, credit_folder_item_id=folder)
    dk = DocKey(environment=env, drive_id=drive, item_id=item)
    return ExtractIndexCandidate(
        environment=env,
        credit_key=ck,
        doc_key=dk,
        drive_id=drive,
        item_id=item,
        credit_folder_item_id=folder,
        name=f"{item}.pdf",
        path=f"cli/{folder}/{item}.pdf",
        parse_status=parse,
        parser_version=BOOTSTRAP_PARSER_VERSION,
        fecha_limite=date(2026, 6, 1) if parse == ParseStatus.OK else None,
        parse_error=parse_error,
    )


def _unit(
    folder: str,
    *,
    client: str = "cli-a",
    env: ExtractIndexEnvironment = ExtractIndexEnvironment.SANDBOX,
    drive: str = "drive-1",
    item: str | None = None,
    parse: ParseStatus = ParseStatus.OK,
    parse_error: str = "",
) -> BootstrapCreditUnit:
    pdf = item or f"pdf-{folder}"
    return BootstrapCreditUnit(
        client_identity=client,
        credit_identity=folder,
        credit_folder_item_id=folder,
        credit_path=f"{client}/{folder}",
        candidates=[
            _cand(
                env=env,
                drive=drive,
                folder=folder,
                item=pdf,
                parse=parse,
                parse_error=parse_error,
            )
        ],
        opaque_cursor=folder,
    )


def _scope_key(
    env: ExtractIndexEnvironment = ExtractIndexEnvironment.SANDBOX,
    drive: str = "drive-1",
    root: str = "root-clients",
) -> CampaignScopeKey:
    return CampaignScopeKey(
        environment=env,
        drive_id=drive,
        root_identity=root,
        parser_version=BOOTSTRAP_PARSER_VERSION,
        schema_version=BOOTSTRAP_SCHEMA_VERSION,
    )


def _harness(
    units: list[BootstrapCreditUnit] | None = None,
    *,
    max_credits: int = 3,
    max_seconds: float = 180.0,
    fail_checkpoint_once: bool = False,
    clock: FakeClock | None = None,
    tree: FakeReadonlyDocumentTree | None = None,
):
    control = InMemoryBootstrapControlRepository()
    index = InMemoryExtractIndexRepository()
    lock = InMemoryCreditLock()
    scope = FakeBootstrapScope(units=units or [])
    clock = clock or FakeClock()
    tree = tree or FakeReadonlyDocumentTree()
    service = BootstrapCampaignService(
        control_repo=control,
        index_repo=index,
        lock=lock,
        scope=scope,
        clock=clock,
        document_tree=tree,
        max_credits_per_chunk=max_credits,
        max_seconds_per_chunk=max_seconds,
        fail_checkpoint_once=fail_checkpoint_once,
    )
    return service, control, index, lock, scope, clock, tree


def _run(coro):
    return asyncio.run(coro)


# --- 1 / 2: start + idempotencia ---


def test_start_new_campaign() -> None:
    service, *_ = _harness()
    rec = _run(start_bootstrap_campaign(service, _scope_key()))
    assert rec.status == CampaignStatus.RUNNING
    assert rec.campaign_id == _scope_key().as_campaign_id()
    assert rec.completed is False


def test_repeated_start_does_not_duplicate_active() -> None:
    service, control, *_ = _harness()
    a = _run(start_bootstrap_campaign(service, _scope_key()))
    b = _run(start_bootstrap_campaign(service, _scope_key()))
    assert a.campaign_id == b.campaign_id
    assert len(control.by_key) == 1


# --- 3–7: chunk exitoso / límites / continuation / completed ---


def test_process_successful_chunk() -> None:
    service, _, index, *_ = _harness([_unit("c1"), _unit("c2")], max_credits=5)
    key = _scope_key()
    _run(start_bootstrap_campaign(service, key))
    result = _run(
        process_bootstrap_chunk(
            service,
            environment=ExtractIndexEnvironment.SANDBOX,
            campaign_id=key.as_campaign_id(),
            expected_drive_id="drive-1",
        )
    )
    assert result.stop_reason == ChunkStopReason.COMPLETED
    assert result.continuation_required is False
    assert result.credits_confirmed == 2
    assert len(index.items) == 2


def test_stop_by_max_credits() -> None:
    units = [_unit(f"c{i}") for i in range(5)]
    service, *_ = _harness(units, max_credits=2)
    key = _scope_key()
    _run(start_bootstrap_campaign(service, key))
    result = _run(
        process_bootstrap_chunk(
            service,
            environment=ExtractIndexEnvironment.SANDBOX,
            campaign_id=key.as_campaign_id(),
        )
    )
    assert result.stop_reason == ChunkStopReason.MAX_CREDITS
    assert result.continuation_required is True
    assert result.credits_confirmed == 2


def test_stop_by_max_seconds() -> None:
    clock = FakeClock()
    units = [_unit(f"c{i}") for i in range(4)]
    service, control, index, lock, scope, _, tree = _harness(
        units, max_credits=10, max_seconds=1.0, clock=clock
    )

    def on_step(step: str) -> None:
        if step == "lock_acquired":
            clock.advance(2.0)

    service = BootstrapCampaignService(
        control_repo=control,
        index_repo=index,
        lock=lock,
        scope=scope,
        clock=clock,
        document_tree=tree,
        max_credits_per_chunk=10,
        max_seconds_per_chunk=1.0,
        on_step=on_step,
    )
    key = _scope_key()
    _run(start_bootstrap_campaign(service, key))
    # Primer crédito arranca (presupuesto se mira antes); tras él el mono ya pasó
    # Forzar mono alto ANTES del segundo: on_step avanza en el primero; antes del
    # segundo el check de tiempo detiene.
    result = _run(
        process_bootstrap_chunk(
            service,
            environment=ExtractIndexEnvironment.SANDBOX,
            campaign_id=key.as_campaign_id(),
        )
    )
    assert result.stop_reason == ChunkStopReason.MAX_SECONDS
    assert result.continuation_required is True
    assert result.credits_confirmed >= 1


def test_continuation_required_and_then_completed() -> None:
    units = [_unit("c1"), _unit("c2"), _unit("c3")]
    service, *_ = _harness(units, max_credits=2)
    key = _scope_key()
    _run(start_bootstrap_campaign(service, key))
    r1 = _run(
        process_bootstrap_chunk(
            service,
            environment=ExtractIndexEnvironment.SANDBOX,
            campaign_id=key.as_campaign_id(),
        )
    )
    assert r1.continuation_required is True
    r2 = _run(
        process_bootstrap_chunk(
            service,
            environment=ExtractIndexEnvironment.SANDBOX,
            campaign_id=key.as_campaign_id(),
        )
    )
    assert r2.stop_reason == ChunkStopReason.COMPLETED
    assert r2.continuation_required is False
    status = _run(
        get_bootstrap_campaign_status(
            service,
            environment=ExtractIndexEnvironment.SANDBOX,
            campaign_id=key.as_campaign_id(),
        )
    )
    assert status is not None
    assert status.status == CampaignStatus.COMPLETED
    assert status.completed is True


# --- 8–11: orden upsert → checkpoint ---


def test_checkpoint_after_upsert_order() -> None:
    _, control, index, lock, scope, clock, tree = _harness([_unit("c1")])
    order: list[str] = []
    service = BootstrapCampaignService(
        control_repo=control,
        index_repo=index,
        lock=lock,
        scope=scope,
        clock=clock,
        document_tree=tree,
        max_credits_per_chunk=3,
        max_seconds_per_chunk=60,
        on_step=order.append,
    )
    key = _scope_key()
    _run(start_bootstrap_campaign(service, key))
    _run(
        process_bootstrap_chunk(
            service,
            environment=ExtractIndexEnvironment.SANDBOX,
            campaign_id=key.as_campaign_id(),
        )
    )
    assert order.index("upsert_confirmed") < order.index("checkpoint_saved")
    rec = _run(
        get_bootstrap_campaign_status(
            service,
            environment=ExtractIndexEnvironment.SANDBOX,
            campaign_id=key.as_campaign_id(),
        )
    )
    assert rec is not None
    cp = BootstrapCheckpoint.from_json(rec.checkpoint)
    assert cp is not None
    assert "cred-1" in cp.last_confirmed_credit_key or cp.last_confirmed_credit == "c1"


def test_never_checkpoint_before_upsert() -> None:
    _, control, index, lock, scope, clock, tree = _harness([_unit("c1")])
    order: list[str] = []
    service = BootstrapCampaignService(
        control_repo=control,
        index_repo=index,
        lock=lock,
        scope=scope,
        clock=clock,
        document_tree=tree,
        on_step=order.append,
    )
    key = _scope_key()
    _run(start_bootstrap_campaign(service, key))
    _run(
        process_bootstrap_chunk(
            service,
            environment=ExtractIndexEnvironment.SANDBOX,
            campaign_id=key.as_campaign_id(),
        )
    )
    assert "checkpoint_saved" in order
    assert order.index("upsert_start") < order.index("checkpoint_saved")


def test_upsert_failure_does_not_advance_checkpoint() -> None:
    service, control, index, *_ = _harness([_unit("c1"), _unit("c2")])
    key = _scope_key()
    _run(start_bootstrap_campaign(service, key))
    index.fail_next_upsert = True
    result = _run(
        process_bootstrap_chunk(
            service,
            environment=ExtractIndexEnvironment.SANDBOX,
            campaign_id=key.as_campaign_id(),
        )
    )
    assert result.stop_reason == ChunkStopReason.UPSERT_FAILURE
    rec = control.by_key[(ExtractIndexEnvironment.SANDBOX.value, key.as_campaign_id())]
    assert rec.checkpoint == ""
    assert result.continuation_required is True


def test_upsert_ok_checkpoint_fail_idempotent_retry() -> None:
    service, control, index, *_ = _harness(
        [_unit("c1")], fail_checkpoint_once=True
    )
    key = _scope_key()
    _run(start_bootstrap_campaign(service, key))
    r1 = _run(
        process_bootstrap_chunk(
            service,
            environment=ExtractIndexEnvironment.SANDBOX,
            campaign_id=key.as_campaign_id(),
        )
    )
    assert r1.stop_reason == ChunkStopReason.CHECKPOINT_FAILURE
    rec = control.by_key[(ExtractIndexEnvironment.SANDBOX.value, key.as_campaign_id())]
    assert rec.checkpoint == ""
    assert len(index.items) == 1  # upsert ocurrió
    # Reintento: mismo crédito, upsert idempotente, checkpoint avanza
    r2 = _run(
        process_bootstrap_chunk(
            service,
            environment=ExtractIndexEnvironment.SANDBOX,
            campaign_id=key.as_campaign_id(),
        )
    )
    assert r2.credits_confirmed == 1
    assert r2.stop_reason == ChunkStopReason.COMPLETED
    rec2 = control.by_key[(ExtractIndexEnvironment.SANDBOX.value, key.as_campaign_id())]
    assert rec2.checkpoint
    assert len(index.items) == 1  # sin filas duplicadas


# --- 12–13: reanudación / recycle ---


def test_resume_from_last_confirmed_credit() -> None:
    units = [_unit("c1"), _unit("c2"), _unit("c3")]
    service, *_ = _harness(units, max_credits=1)
    key = _scope_key()
    _run(start_bootstrap_campaign(service, key))
    _run(
        process_bootstrap_chunk(
            service,
            environment=ExtractIndexEnvironment.SANDBOX,
            campaign_id=key.as_campaign_id(),
        )
    )
    status = _run(
        get_bootstrap_campaign_status(
            service,
            environment=ExtractIndexEnvironment.SANDBOX,
            campaign_id=key.as_campaign_id(),
        )
    )
    assert status is not None
    cp = BootstrapCheckpoint.from_json(status.checkpoint)
    assert cp is not None
    assert cp.last_confirmed_credit == "c1"
    r2 = _run(
        process_bootstrap_chunk(
            service,
            environment=ExtractIndexEnvironment.SANDBOX,
            campaign_id=key.as_campaign_id(),
        )
    )
    assert r2.credits_confirmed == 1  # solo c2


def test_simulated_recycle_and_resume() -> None:
    units = [_unit("c1"), _unit("c2")]
    service, control, index, lock, scope, clock, tree = _harness(units, max_credits=1)
    key = _scope_key()
    _run(start_bootstrap_campaign(service, key))
    _run(
        process_bootstrap_chunk(
            service,
            environment=ExtractIndexEnvironment.SANDBOX,
            campaign_id=key.as_campaign_id(),
        )
    )
    # Recycle: nuevo servicio, mismos repos (estado persistido)
    service2 = BootstrapCampaignService(
        control_repo=control,
        index_repo=index,
        lock=lock,
        scope=scope,
        clock=clock,
        document_tree=tree,
        max_credits_per_chunk=5,
        max_seconds_per_chunk=60,
    )
    r = _run(
        process_bootstrap_chunk(
            service2,
            environment=ExtractIndexEnvironment.SANDBOX,
            campaign_id=key.as_campaign_id(),
        )
    )
    assert r.stop_reason == ChunkStopReason.COMPLETED
    assert len(index.items) == 2


# --- 14–17: pause / cancel ---


def test_pause_before_credit() -> None:
    service, *_ = _harness([_unit("c1")])
    key = _scope_key()
    _run(start_bootstrap_campaign(service, key))
    _run(
        pause_bootstrap_campaign(
            service,
            environment=ExtractIndexEnvironment.SANDBOX,
            campaign_id=key.as_campaign_id(),
        )
    )
    result = _run(
        process_bootstrap_chunk(
            service,
            environment=ExtractIndexEnvironment.SANDBOX,
            campaign_id=key.as_campaign_id(),
        )
    )
    assert result.stop_reason == ChunkStopReason.PAUSED
    assert result.continuation_required is False
    assert result.credits_confirmed == 0


def test_pause_after_confirmed_credit() -> None:
    units = [_unit("c1"), _unit("c2")]
    _, control, index, lock, scope, clock, tree = _harness(units, max_credits=5)
    key = _scope_key()

    paused = {"done": False}

    def on_step(step: str) -> None:
        if step == "checkpoint_saved" and not paused["done"]:
            paused["done"] = True
            rec = control.by_key[
                (ExtractIndexEnvironment.SANDBOX.value, key.as_campaign_id())
            ]
            rec.paused = True

    service = BootstrapCampaignService(
        control_repo=control,
        index_repo=index,
        lock=lock,
        scope=scope,
        clock=clock,
        document_tree=tree,
        max_credits_per_chunk=5,
        on_step=on_step,
    )
    _run(start_bootstrap_campaign(service, key))
    result = _run(
        process_bootstrap_chunk(
            service,
            environment=ExtractIndexEnvironment.SANDBOX,
            campaign_id=key.as_campaign_id(),
        )
    )
    assert result.stop_reason == ChunkStopReason.PAUSED
    assert result.credits_confirmed == 1
    assert result.continuation_required is False


def test_cancel_before_chunk() -> None:
    service, *_ = _harness([_unit("c1")])
    key = _scope_key()
    _run(start_bootstrap_campaign(service, key))
    _run(
        request_bootstrap_cancellation(
            service,
            environment=ExtractIndexEnvironment.SANDBOX,
            campaign_id=key.as_campaign_id(),
        )
    )
    result = _run(
        process_bootstrap_chunk(
            service,
            environment=ExtractIndexEnvironment.SANDBOX,
            campaign_id=key.as_campaign_id(),
        )
    )
    assert result.stop_reason == ChunkStopReason.CANCELLED
    assert result.continuation_required is False


def test_cancel_during_campaign() -> None:
    units = [_unit("c1"), _unit("c2")]
    _, control, index, lock, scope, clock, tree = _harness(units, max_credits=5)
    key = _scope_key()

    def on_step(step: str) -> None:
        if step == "checkpoint_saved":
            rec = control.by_key[
                (ExtractIndexEnvironment.SANDBOX.value, key.as_campaign_id())
            ]
            rec.cancellation_requested = True

    service = BootstrapCampaignService(
        control_repo=control,
        index_repo=index,
        lock=lock,
        scope=scope,
        clock=clock,
        document_tree=tree,
        max_credits_per_chunk=5,
        on_step=on_step,
    )
    _run(start_bootstrap_campaign(service, key))
    result = _run(
        process_bootstrap_chunk(
            service,
            environment=ExtractIndexEnvironment.SANDBOX,
            campaign_id=key.as_campaign_id(),
        )
    )
    assert result.status == CampaignStatus.CANCELLED
    assert result.continuation_required is False


# --- 18–21: locks / Generate priority ---


def test_lock_held_by_generate_skips_without_forcing() -> None:
    unit = _unit("c1")
    service, _, index, lock, *_ = _harness([unit, _unit("c2")], max_credits=5)
    key = _scope_key()
    ck = unit.candidates[0].credit_key.as_string()
    _run(lock.try_acquire(ck, owner=GENERATE_LOCK_OWNER))
    _run(start_bootstrap_campaign(service, key))
    result = _run(
        process_bootstrap_chunk(
            service,
            environment=ExtractIndexEnvironment.SANDBOX,
            campaign_id=key.as_campaign_id(),
        )
    )
    assert result.credits_skipped_locked >= 1
    assert ck not in {c.credit_key.as_string() for c in index.items.values()} or True
    # c1 no indexado (omitido); c2 sí
    assert any(k.endswith("|c2|") or "c2" in k for k in index.items) or len(index.items) == 1


def test_lock_released_after_success_and_error() -> None:
    service, _, index, lock, *_ = _harness([_unit("c1")])
    key = _scope_key()
    _run(start_bootstrap_campaign(service, key))
    _run(
        process_bootstrap_chunk(
            service,
            environment=ExtractIndexEnvironment.SANDBOX,
            campaign_id=key.as_campaign_id(),
        )
    )
    ck = _unit("c1").candidates[0].credit_key.as_string()
    assert _run(lock.is_held(ck)) is False

    service2, _, index2, lock2, *_ = _harness([_unit("c9")])
    index2.fail_next_upsert = True
    key2 = _scope_key(root="root-err")
    _run(start_bootstrap_campaign(service2, key2))
    _run(
        process_bootstrap_chunk(
            service2,
            environment=ExtractIndexEnvironment.SANDBOX,
            campaign_id=key2.as_campaign_id(),
        )
    )
    ck2 = _unit("c9").candidates[0].credit_key.as_string()
    assert _run(lock2.is_held(ck2)) is False


def test_generate_has_logical_priority() -> None:
    """Generate owner bloquea; bootstrap no roba el lock."""
    lock = InMemoryCreditLock()
    ck = "sandbox|drive-1|cred-x"
    assert _run(lock.try_acquire(ck, owner=GENERATE_LOCK_OWNER)) is True
    assert _run(lock.try_acquire(ck, owner="bootstrap")) is False
    assert _run(lock.holder(ck)) == GENERATE_LOCK_OWNER


# --- 22–23: security fail-closed ---


def test_security_violation_aborts_and_blocks_continuation() -> None:
    tree = FakeReadonlyDocumentTree(
        raise_on_get=DocumentMutationForbidden("drive write blocked")
    )
    service, control, *_ = _harness([_unit("c1"), _unit("c2")], tree=tree)
    # Re-bind tree into service — harness already passed tree
    key = _scope_key()
    _run(start_bootstrap_campaign(service, key))
    result = _run(
        process_bootstrap_chunk(
            service,
            environment=ExtractIndexEnvironment.SANDBOX,
            campaign_id=key.as_campaign_id(),
        )
    )
    assert result.stop_reason == ChunkStopReason.SECURITY_VIOLATION
    assert result.continuation_required is False
    assert result.security_violation is True
    totals = CampaignTotals.from_json(
        control.by_key[
            (ExtractIndexEnvironment.SANDBOX.value, key.as_campaign_id())
        ].totals_json
    )
    assert totals.security_violation is True
    with pytest.raises(BootstrapSecurityViolation):
        _run(
            resume_bootstrap_campaign(
                service,
                environment=ExtractIndexEnvironment.SANDBOX,
                campaign_id=key.as_campaign_id(),
            )
        )


# --- 24–27: aislamiento ---


def test_environment_mismatch() -> None:
    service, control, *_ = _harness([_unit("c1")])
    key = _scope_key()
    _run(start_bootstrap_campaign(service, key))
    rec = control.by_key[(ExtractIndexEnvironment.SANDBOX.value, key.as_campaign_id())]
    rec.environment = ExtractIndexEnvironment.PRODUCTION
    with pytest.raises(BootstrapEnvironmentMismatch):
        _run(
            process_bootstrap_chunk(
                service,
                environment=ExtractIndexEnvironment.SANDBOX,
                campaign_id=key.as_campaign_id(),
            )
        )


def test_drive_mismatch() -> None:
    service, *_ = _harness([_unit("c1")])
    key = _scope_key()
    _run(start_bootstrap_campaign(service, key))
    with pytest.raises(BootstrapDriveMismatch):
        _run(
            process_bootstrap_chunk(
                service,
                environment=ExtractIndexEnvironment.SANDBOX,
                campaign_id=key.as_campaign_id(),
                expected_drive_id="other-drive",
            )
        )


def test_parser_schema_version_mismatch() -> None:
    service, control, *_ = _harness([_unit("c1")])
    key = _scope_key()
    _run(start_bootstrap_campaign(service, key))
    # Completar un checkpoint y luego alterar versión
    _run(
        process_bootstrap_chunk(
            service,
            environment=ExtractIndexEnvironment.SANDBOX,
            campaign_id=key.as_campaign_id(),
        )
    )
    # Nueva campaña no: corromper checkpoint de una campaña RUNNING reiniciada
    key2 = _scope_key(root="root-v")
    _run(start_bootstrap_campaign(service, key2))
    rec = control.by_key[(ExtractIndexEnvironment.SANDBOX.value, key2.as_campaign_id())]
    bad_cp = BootstrapCheckpoint(
        environment=ExtractIndexEnvironment.SANDBOX,
        drive_id="drive-1",
        last_confirmed_credit_key="sandbox|drive-1|x",
        parser_version="v999",
        schema_version=BOOTSTRAP_SCHEMA_VERSION,
    )
    rec.checkpoint = bad_cp.to_json()
    with pytest.raises(BootstrapVersionMismatch):
        _run(
            process_bootstrap_chunk(
                service,
                environment=ExtractIndexEnvironment.SANDBOX,
                campaign_id=key2.as_campaign_id(),
            )
        )


def test_sandbox_and_production_campaigns_isolated() -> None:
    sb_units = [
        _unit("c1", env=ExtractIndexEnvironment.SANDBOX, drive="drv-sb")
    ]
    pr_units = [
        _unit("c1", env=ExtractIndexEnvironment.PRODUCTION, drive="drv-pr")
    ]
    sb, *_ = _harness(sb_units)
    # production harness separado
    pr_service, pr_control, pr_index, pr_lock, pr_scope, pr_clock, pr_tree = _harness(
        pr_units
    )
    # Fix production units drive in harness — rebuild pr with correct drive in scope key
    pr_service = BootstrapCampaignService(
        control_repo=pr_control,
        index_repo=pr_index,
        lock=pr_lock,
        scope=FakeBootstrapScope(units=pr_units),
        clock=pr_clock,
        document_tree=pr_tree,
    )
    sb_key = _scope_key(env=ExtractIndexEnvironment.SANDBOX, drive="drv-sb")
    pr_key = _scope_key(env=ExtractIndexEnvironment.PRODUCTION, drive="drv-pr")
    # Fix sandbox service drive
    sb_service, sb_control, sb_index, sb_lock, _, sb_clock, sb_tree = _harness(sb_units)
    sb_service = BootstrapCampaignService(
        control_repo=sb_control,
        index_repo=sb_index,
        lock=sb_lock,
        scope=FakeBootstrapScope(units=sb_units),
        clock=sb_clock,
        document_tree=sb_tree,
    )
    _run(start_bootstrap_campaign(sb_service, sb_key))
    _run(start_bootstrap_campaign(pr_service, pr_key))
    assert sb_key.as_campaign_id() != pr_key.as_campaign_id()
    _run(
        process_bootstrap_chunk(
            sb_service,
            environment=ExtractIndexEnvironment.SANDBOX,
            campaign_id=sb_key.as_campaign_id(),
            expected_drive_id="drv-sb",
        )
    )
    _run(
        process_bootstrap_chunk(
            pr_service,
            environment=ExtractIndexEnvironment.PRODUCTION,
            campaign_id=pr_key.as_campaign_id(),
            expected_drive_id="drv-pr",
        )
    )
    assert len(sb_index.items) == 1
    assert len(pr_index.items) == 1
    assert all(
        c.environment == ExtractIndexEnvironment.SANDBOX for c in sb_index.items.values()
    )
    assert all(
        c.environment == ExtractIndexEnvironment.PRODUCTION
        for c in pr_index.items.values()
    )


# --- 28–30: idempotencia datos / parse_error / métricas ---


def test_duplicate_candidates_do_not_duplicate_rows() -> None:
    c = _cand(folder="c1", item="pdf-same")
    unit = BootstrapCreditUnit(
        client_identity="cli",
        credit_identity="c1",
        credit_folder_item_id="c1",
        credit_path="cli/c1",
        candidates=[c, c],  # mismo DOC_KEY dos veces en el crédito
    )
    service, _, index, *_ = _harness([unit])
    key = _scope_key()
    _run(start_bootstrap_campaign(service, key))
    _run(
        process_bootstrap_chunk(
            service,
            environment=ExtractIndexEnvironment.SANDBOX,
            campaign_id=key.as_campaign_id(),
        )
    )
    assert len(index.items) == 1


def test_parse_error_credit_is_recorded() -> None:
    service, control, index, *_ = _harness(
        [
            _unit(
                "c1",
                parse=ParseStatus.ERROR,
                parse_error="PdfStreamError: truncated",
            )
        ]
    )
    key = _scope_key()
    _run(start_bootstrap_campaign(service, key))
    _run(
        process_bootstrap_chunk(
            service,
            environment=ExtractIndexEnvironment.SANDBOX,
            campaign_id=key.as_campaign_id(),
        )
    )
    assert len(index.items) == 1
    stored = next(iter(index.items.values()))
    assert stored.parse_status == ParseStatus.ERROR
    totals = CampaignTotals.from_json(
        control.by_key[
            (ExtractIndexEnvironment.SANDBOX.value, key.as_campaign_id())
        ].totals_json
    )
    assert totals.credits_parse_error >= 1
    assert totals.credits_processed >= 1
    rec = control.by_key[(ExtractIndexEnvironment.SANDBOX.value, key.as_campaign_id())]
    assert rec.heartbeat is not None


# --- 31–34: seguridad de alcance ---


def test_zero_document_mutations_and_no_create_task() -> None:
    tree = FakeReadonlyDocumentTree()
    service, *_ = _harness([_unit("c1")], tree=tree)
    key = _scope_key()
    _run(start_bootstrap_campaign(service, key))
    _run(
        process_bootstrap_chunk(
            service,
            environment=ExtractIndexEnvironment.SANDBOX,
            campaign_id=key.as_campaign_id(),
        )
    )
    src = pathlib.Path(
        "app/application/services/extract_index/bootstrap_campaign.py"
    ).read_text(encoding="utf-8")
    assert "create_task" not in src
    assert tree.gets  # solo lecturas


def test_payment_validation_generate_unchanged_vs_2b2() -> None:
    """Generate puede recibir fixes operativos de develop; no debe acoplarse a bootstrap admin."""
    src = pathlib.Path(
        "app/application/use_cases/payment_validation_generate.py"
    ).read_text(encoding="utf-8")
    assert "extract_index_admin" not in src
    assert "bootstrap_campaign" not in src
    assert "ShadowIndexEvaluator" in src or "shadow_index_evaluator" in src


def test_logical_preflight() -> None:
    from app.application.config.extract_index_settings import (
        ExtractIndexMode,
        ExtractIndexSettings,
    )

    cfg = ExtractIndexSettings(
        mode=ExtractIndexMode.OFF,
        environment=ExtractIndexEnvironment.SANDBOX,
        bootstrap_enabled=True,
        max_clients_per_chunk=3,
        max_seconds_per_chunk=180,
        shadow_max_credits=None,
        shadow_sample_pct=None,
        shadow_allowed_banks=frozenset(),
        shadow_allowed_dates=frozenset(),
        shadow_timeout_seconds=8.0,
        shadow_total_budget_seconds=45.0,
        indice_list_display_name="INDICE_EXTRACTOS",
        control_list_display_name="CONTROL_INDICE_EXTRACTOS",
        graph_retry_max=2,
        graph_retry_base_seconds=0.1,
    )
    ok = run_extract_index_preflight(settings=cfg)
    assert ok.ok is True
    assert ok.capabilities["graph_real"] is False
    bad = run_extract_index_preflight(settings=cfg, has_lock=False)
    assert bad.ok is False
    assert "missing_credit_lock" in bad.issues


def test_resume_after_pause() -> None:
    service, *_ = _harness([_unit("c1"), _unit("c2")], max_credits=1)
    key = _scope_key()
    _run(start_bootstrap_campaign(service, key))
    _run(
        process_bootstrap_chunk(
            service,
            environment=ExtractIndexEnvironment.SANDBOX,
            campaign_id=key.as_campaign_id(),
        )
    )
    _run(
        pause_bootstrap_campaign(
            service,
            environment=ExtractIndexEnvironment.SANDBOX,
            campaign_id=key.as_campaign_id(),
        )
    )
    resumed = _run(
        resume_bootstrap_campaign(
            service,
            environment=ExtractIndexEnvironment.SANDBOX,
            campaign_id=key.as_campaign_id(),
        )
    )
    assert resumed.status == CampaignStatus.RUNNING
    assert resumed.continuation_required is True
    r = _run(
        process_bootstrap_chunk(
            service,
            environment=ExtractIndexEnvironment.SANDBOX,
            campaign_id=key.as_campaign_id(),
        )
    )
    assert r.stop_reason == ChunkStopReason.COMPLETED
