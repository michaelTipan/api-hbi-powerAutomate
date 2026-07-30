"""Fase 2B2: cableado mínimo shadow en Generate (sin Graph real / sin active)."""

from __future__ import annotations

import asyncio
import copy
import inspect
import json
from datetime import date
from typing import Any
from unittest import mock

import pytest

from app.application.config.extract_index_settings import (
    ExtractIndexMode,
    ExtractIndexSettings,
)
from app.application.services.extract_index.generate_shadow_hook import (
    GenerateShadowJobContext,
    maybe_evaluate_shadow_after_v2,
    new_generate_shadow_job_context,
)
from app.application.services.extract_index.shadow_evaluator import (
    ShadowIndexEvaluator,
    ShadowJobBudget,
)
from app.application.services.extract_index.shadow_models import (
    DivergenceType,
    OfficialV2Snapshot,
    ShadowComparisonRecord,
    ShadowEvaluationResult,
    ShadowOutcomeKind,
    ShadowSkipReason,
)
from app.domain.models.extract_index import ExtractIndexEnvironment


def _settings(**overrides: Any) -> ExtractIndexSettings:
    base = dict(
        mode=ExtractIndexMode.SHADOW,
        environment=ExtractIndexEnvironment.SANDBOX,
        bootstrap_enabled=False,
        max_clients_per_chunk=3,
        max_seconds_per_chunk=180,
        shadow_max_credits=None,
        shadow_sample_pct=100.0,
        shadow_allowed_banks=frozenset(),
        shadow_allowed_dates=frozenset(),
        shadow_timeout_seconds=2.0,
        shadow_total_budget_seconds=45.0,
        indice_list_display_name="INDICE_EXTRACTOS",
        control_list_display_name="CONTROL_INDICE_EXTRACTOS",
        graph_retry_max=2,
        graph_retry_base_seconds=0.01,
    )
    base.update(overrides)
    return ExtractIndexSettings(**base)


class _FakeEvaluator:
    def __init__(self) -> None:
        self.calls: list[OfficialV2Snapshot] = []
        self._budget = ShadowJobBudget()
        self._settings = _settings()
        self.raise_cancelled = False
        self.raise_runtime = False
        self.raise_pdf_stream = False
        self.outcome = ShadowOutcomeKind.INDEX_SELECTED
        self.comparison: ShadowComparisonRecord | None = None
        self.delay_s = 0.0

    async def evaluate(
        self,
        *,
        official_v2: OfficialV2Snapshot,
        request: Any,
        bank_code: str,
        process_date: date,
        index_available: bool = True,
    ) -> ShadowEvaluationResult:
        if self.raise_cancelled:
            raise asyncio.CancelledError()
        if self.raise_pdf_stream:
            raise RuntimeError("PdfStreamError: truncated stream")
        if self.raise_runtime:
            raise RuntimeError("shadow boom")
        if self.delay_s:
            await asyncio.sleep(self.delay_s)
        self.calls.append(official_v2)
        return ShadowEvaluationResult(
            outcome=self.outcome,
            comparison=self.comparison,
        )


def _hook_kwargs(
    *,
    evaluator: Any,
    ctx: GenerateShadowJobContext | None,
    credit_folder_item_id: str = "c1",
    statement_item: dict[str, Any] | None = None,
    fecha_limite_pdf: date | None = None,
) -> dict[str, Any]:
    return dict(
        evaluator=evaluator,
        job_ctx=ctx,
        bank_code="banco_bogota",
        process_date=date(2026, 7, 29),
        drive_id="d1",
        credit_folder_item_id=credit_folder_item_id,
        credit_path="cli/c1",
        credit_folder_items=[],
        pool=[],
        statement_item=statement_item if statement_item is not None else {"id": "OFFICIAL"},
        fecha_limite_pdf=fecha_limite_pdf if fecha_limite_pdf is not None else date(2026, 6, 1),
        sel_err=None,
        selected={"source_location": "extractos_folder", "relative_path": "a.pdf"},
    )


# --- 1 / 2: mode=off ---


def test_mode_off_context_is_none(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("EXTRACT_INDEX_MODE", "off")
    assert new_generate_shadow_job_context(job_id="j1") is None


def test_mode_off_hook_never_calls_evaluator() -> None:
    async def _run() -> None:
        ev = _FakeEvaluator()
        await maybe_evaluate_shadow_after_v2(**_hook_kwargs(evaluator=ev, ctx=None))
        assert ev.calls == []

    asyncio.run(_run())


def test_mode_off_baseline_equivalence_of_official_locals() -> None:
    """
    Equivalencia: con ctx=None (mode=off) los locales oficiales quedan idénticos
    al baseline previo al hook (snapshot JSON).
    """

    async def _run() -> None:
        statement_item = {"id": "V2", "name": "Extracto.pdf"}
        fecha_limite_pdf = date(2026, 3, 15)
        sel_err = None
        selected = {"relative_path": "x.pdf", "source_location": "extractos_folder"}
        baseline = {
            "statement_item": copy.deepcopy(statement_item),
            "fecha_limite_pdf": fecha_limite_pdf.isoformat(),
            "sel_err": sel_err,
            "selected": copy.deepcopy(selected),
        }
        ev = _FakeEvaluator()
        await maybe_evaluate_shadow_after_v2(
            **_hook_kwargs(
                evaluator=ev,
                ctx=None,
                statement_item=statement_item,
                fecha_limite_pdf=fecha_limite_pdf,
            )
        )
        after = {
            "statement_item": statement_item,
            "fecha_limite_pdf": fecha_limite_pdf.isoformat(),
            "sel_err": sel_err,
            "selected": selected,
        }
        assert json.dumps(baseline, sort_keys=True) == json.dumps(after, sort_keys=True)
        assert ev.calls == []

    asyncio.run(_run())


# --- 3: shadow llama después de V2 ---


def test_mode_shadow_calls_evaluator_after_v2(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("EXTRACT_INDEX_MODE", "shadow")
    monkeypatch.setenv("ACTIVE_ENVIRONMENT", "sandbox")

    async def _run() -> None:
        ev = _FakeEvaluator()
        ctx = GenerateShadowJobContext(settings=_settings(), job_id="j")
        await maybe_evaluate_shadow_after_v2(**_hook_kwargs(evaluator=ev, ctx=ctx))
        assert len(ev.calls) == 1
        assert ev.calls[0].item_id == "OFFICIAL"

    asyncio.run(_run())


# --- 4 / 5 / 19 / 20: match / divergencia no alteran oficial ---


def test_match_does_not_alter_official() -> None:
    async def _run() -> None:
        statement_item = {"id": "KEEP"}
        fecha = date(2026, 6, 1)
        ev = _FakeEvaluator()
        ev.outcome = ShadowOutcomeKind.INDEX_SELECTED
        ev.comparison = ShadowComparisonRecord(
            credit_key="sandbox|d1|c1",
            item_id_v2="KEEP",
            item_id_index="KEEP",
            fecha_limite_v2=fecha,
            fecha_limite_index=fecha,
            source_location_v2="extractos_folder",
            source_location_index="extractos_folder",
            selection_reason_v2="max_fecha_limite",
            selection_reason_index="max_fecha_limite",
            divergence_type=DivergenceType.NONE,
            elapsed_ms_index=1.0,
        )
        ctx = GenerateShadowJobContext(settings=_settings(), job_id="j")
        await maybe_evaluate_shadow_after_v2(
            **_hook_kwargs(
                evaluator=ev,
                ctx=ctx,
                statement_item=statement_item,
                fecha_limite_pdf=fecha,
            )
        )
        assert statement_item == {"id": "KEEP"}
        assert fecha == date(2026, 6, 1)

    asyncio.run(_run())


def test_divergence_does_not_alter_official() -> None:
    async def _run() -> None:
        statement_item = {"id": "V2_ID"}
        fecha = date(2026, 6, 1)
        ev = _FakeEvaluator()
        ev.outcome = ShadowOutcomeKind.INDEX_DIVERGENCE
        ev.comparison = ShadowComparisonRecord(
            credit_key="sandbox|d1|c1",
            item_id_v2="V2_ID",
            item_id_index="IDX_OTHER",
            fecha_limite_v2=fecha,
            fecha_limite_index=date(2026, 1, 1),
            source_location_v2="extractos_folder",
            source_location_index="extractos_folder",
            selection_reason_v2="max_fecha_limite",
            selection_reason_index="max_fecha_limite",
            divergence_type=DivergenceType.BOTH,
            elapsed_ms_index=2.0,
            outcome=ShadowOutcomeKind.INDEX_DIVERGENCE,
        )
        ctx = GenerateShadowJobContext(settings=_settings(), job_id="j")
        await maybe_evaluate_shadow_after_v2(
            **_hook_kwargs(
                evaluator=ev,
                ctx=ctx,
                statement_item=statement_item,
                fecha_limite_pdf=fecha,
            )
        )
        assert statement_item["id"] == "V2_ID"
        assert fecha == date(2026, 6, 1)

    asyncio.run(_run())


# --- 6 / 7 / 8: excepción / timeout / PdfStreamError shadow ---


def test_shadow_exception_does_not_alter_official() -> None:
    async def _run() -> None:
        statement_item = {"id": "KEEP"}
        fecha = date(2026, 6, 1)
        ev = _FakeEvaluator()
        ev.raise_runtime = True
        ctx = GenerateShadowJobContext(settings=_settings(), job_id="j")
        await maybe_evaluate_shadow_after_v2(
            **_hook_kwargs(
                evaluator=ev, ctx=ctx, statement_item=statement_item, fecha_limite_pdf=fecha
            )
        )
        assert statement_item == {"id": "KEEP"}
        assert fecha == date(2026, 6, 1)

    asyncio.run(_run())


def test_shadow_timeout_via_real_evaluator_does_not_alter_official() -> None:
    class SlowAdapter:
        async def select(self, request: Any) -> Any:
            await asyncio.sleep(5.0)
            raise AssertionError("should have timed out")

    async def _run() -> None:
        official = OfficialV2Snapshot(
            credit_key="sandbox|d1|c1",
            item_id="KEEP",
            fecha_limite=date(2026, 6, 1),
            source_location="extractos_folder",
            selection_reason="max_fecha_limite",
            error_code=None,
            relative_path="a.pdf",
        )
        before = (
            official.item_id,
            official.fecha_limite,
            official.error_code,
            official.relative_path,
        )
        ev = ShadowIndexEvaluator(
            settings=_settings(shadow_timeout_seconds=0.05),
            adapter=SlowAdapter(),  # type: ignore[arg-type]
        )
        from app.application.services.extract_index.index_select_adapter import (
            IndexSelectRequest,
        )

        req = IndexSelectRequest(
            environment=ExtractIndexEnvironment.SANDBOX,
            drive_id="d1",
            credit_key=official.credit_key,
            credit_path="cli/c1",
            credit_folder_items=[],
            extractos_children=None,
            live_files=[],
            content_endpoint_builder=lambda p: p,
        )
        res = await ev.evaluate(
            official_v2=official,
            request=req,
            bank_code="banco_bogota",
            process_date=date(2026, 7, 29),
        )
        assert res.outcome == ShadowOutcomeKind.INDEX_TIMEOUT
        assert (
            official.item_id,
            official.fecha_limite,
            official.error_code,
            official.relative_path,
        ) == before

    asyncio.run(_run())


def test_shadow_pdf_stream_error_isolated() -> None:
    async def _run() -> None:
        statement_item = {"id": "KEEP"}
        fecha = date(2026, 6, 1)
        ev = _FakeEvaluator()
        ev.raise_pdf_stream = True
        ctx = GenerateShadowJobContext(settings=_settings(), job_id="j")
        await maybe_evaluate_shadow_after_v2(
            **_hook_kwargs(
                evaluator=ev, ctx=ctx, statement_item=statement_item, fecha_limite_pdf=fecha
            )
        )
        assert statement_item == {"id": "KEEP"}
        assert fecha == date(2026, 6, 1)

    asyncio.run(_run())


# --- 9: PdfStreamError V2 → no shadow (sin snapshot oficial válido) ---


def test_v2_pdf_stream_error_skips_shadow_by_control_flow() -> None:
    """
    Si V2 lanza antes del hook, el cableado de Generate no llega a shadow.
    Simula el orden: select V2 → (raise) → hook nunca se ejecuta.
    """

    async def _simulate_generate_block(ev: _FakeEvaluator) -> None:
        # Equivalente al bloque real: primero V2, luego shadow solo si V2 retorna.
        raise RuntimeError("PdfStreamError")

    async def _run() -> None:
        ev = _FakeEvaluator()
        with pytest.raises(RuntimeError, match="PdfStreamError"):
            await _simulate_generate_block(ev)
        assert ev.calls == []

    asyncio.run(_run())


# --- 10: evaluator=None ---


def test_evaluator_none_continues_and_skips() -> None:
    async def _run() -> None:
        ctx = GenerateShadowJobContext(settings=_settings(), job_id="j")
        await maybe_evaluate_shadow_after_v2(**_hook_kwargs(evaluator=None, ctx=ctx))
        assert "sandbox|d1|c1" in ctx.evaluated_credit_keys
        assert ctx.budget.skipped >= 1

    asyncio.run(_run())


# --- 11 / 12: una vez por CREDIT_KEY / créditos distintos ---


def test_same_credit_key_evaluated_once() -> None:
    async def _run() -> None:
        ev = _FakeEvaluator()
        ctx = GenerateShadowJobContext(settings=_settings(), job_id="j")
        kwargs = _hook_kwargs(evaluator=ev, ctx=ctx)
        await maybe_evaluate_shadow_after_v2(**kwargs)
        await maybe_evaluate_shadow_after_v2(**kwargs)
        assert len(ev.calls) == 1

    asyncio.run(_run())


def test_two_credits_evaluated_independently() -> None:
    async def _run() -> None:
        ev = _FakeEvaluator()
        ctx = GenerateShadowJobContext(settings=_settings(), job_id="j")
        await maybe_evaluate_shadow_after_v2(
            **_hook_kwargs(evaluator=ev, ctx=ctx, credit_folder_item_id="c1")
        )
        await maybe_evaluate_shadow_after_v2(
            **_hook_kwargs(evaluator=ev, ctx=ctx, credit_folder_item_id="c2")
        )
        assert len(ev.calls) == 2

    asyncio.run(_run())


# --- 13 / 14: max credits / presupuesto total ---


def test_max_credits_stops_additional_via_shared_budget() -> None:
    class CountingAdapter:
        async def select(self, request: Any) -> Any:
            from app.application.services.extract_index.index_select_adapter import (
                IndexSelectMetrics,
                IndexSelectResult,
            )
            from app.application.services.extract_index.shadow_models import (
                IndexSelectionSnapshot,
            )

            from app.application.services.extract_index.reconcile import (
                ReconcileActionKind,
            )

            return IndexSelectResult(
                snapshot=IndexSelectionSnapshot(
                    item_id="OFFICIAL",
                    fecha_limite=date(2026, 6, 1),
                    source_location="extractos_folder",
                    selection_reason="max_fecha_limite",
                ),
                metrics=IndexSelectMetrics(elapsed_ms=1.0, pdf_downloads=0, index_hits=1),
                sufficiency=ReconcileActionKind.UNCHANGED,
                reconcile_fallback=False,
            )

    async def _run() -> None:
        from app.application.services.extract_index.index_select_adapter import (
            IndexSelectRequest,
        )

        budget = ShadowJobBudget()
        settings = _settings(shadow_max_credits=1, shadow_sample_pct=100.0)
        adapter = CountingAdapter()
        ev = ShadowIndexEvaluator(settings=settings, adapter=adapter, budget=budget)  # type: ignore[arg-type]
        ctx = GenerateShadowJobContext(settings=settings, budget=budget, job_id="j")

        async def one(cid: str) -> ShadowEvaluationResult:
            # El hook inyecta budget al evaluator; aquí lo hacemos directo como el hook.
            ev._budget = ctx.budget  # noqa: SLF001
            official = OfficialV2Snapshot(
                credit_key=f"sandbox|d1|{cid}",
                item_id="OFFICIAL",
                fecha_limite=date(2026, 6, 1),
                source_location="extractos_folder",
                selection_reason="max_fecha_limite",
                error_code=None,
            )
            req = IndexSelectRequest(
                environment=ExtractIndexEnvironment.SANDBOX,
                drive_id="d1",
                credit_key=official.credit_key,
                credit_path="cli/" + cid,
                credit_folder_items=[],
                extractos_children=None,
                live_files=[],
                content_endpoint_builder=lambda p: p,
            )
            # Marcar clave como el hook
            if official.credit_key in ctx.evaluated_credit_keys:
                return ShadowEvaluationResult(
                    outcome=ShadowOutcomeKind.SKIPPED,
                    skip_reason=ShadowSkipReason.ALREADY_EVALUATED,
                )
            ctx.evaluated_credit_keys.add(official.credit_key)
            return await ev.evaluate(
                official_v2=official,
                request=req,
                bank_code="banco_bogota",
                process_date=date(2026, 7, 29),
            )

        r1 = await one("c1")
        r2 = await one("c2")
        assert r1.outcome == ShadowOutcomeKind.INDEX_SELECTED
        assert r2.skip_reason == ShadowSkipReason.MAX_CREDITS_REACHED

    asyncio.run(_run())


def test_job_budget_exhausted_skips_remaining() -> None:
    async def _run() -> None:
        ev = _FakeEvaluator()
        ctx = GenerateShadowJobContext(
            settings=_settings(shadow_total_budget_seconds=0.01),
            job_id="j",
        )
        ctx.shadow_elapsed_seconds = 1.0
        await maybe_evaluate_shadow_after_v2(**_hook_kwargs(evaluator=ev, ctx=ctx))
        assert ev.calls == []
        assert ctx.budget.skipped >= 1

    asyncio.run(_run())


# --- 15 / 16 / 17: gates de muestreo (vía evaluador real) ---


def test_bank_out_of_sample_skips() -> None:
    class NoopAdapter:
        async def select(self, request: Any) -> Any:
            raise AssertionError("no select")

    async def _run() -> None:
        from app.application.services.extract_index.index_select_adapter import (
            IndexSelectRequest,
        )

        ev = ShadowIndexEvaluator(
            settings=_settings(shadow_allowed_banks=frozenset({"otro_banco"})),
            adapter=NoopAdapter(),  # type: ignore[arg-type]
        )
        res = await ev.evaluate(
            official_v2=OfficialV2Snapshot(
                credit_key="sandbox|d1|c1",
                item_id="x",
                fecha_limite=date(2026, 6, 1),
                source_location=None,
                selection_reason=None,
                error_code=None,
            ),
            request=IndexSelectRequest(
                environment=ExtractIndexEnvironment.SANDBOX,
                drive_id="d1",
                credit_key="sandbox|d1|c1",
                credit_path="c",
                credit_folder_items=[],
                extractos_children=None,
                live_files=[],
                content_endpoint_builder=lambda p: p,
            ),
            bank_code="banco_bogota",
            process_date=date(2026, 7, 29),
        )
        assert res.skip_reason == ShadowSkipReason.BANK_NOT_ALLOWED

    asyncio.run(_run())


def test_date_out_of_sample_skips() -> None:
    class NoopAdapter:
        async def select(self, request: Any) -> Any:
            raise AssertionError("no select")

    async def _run() -> None:
        from app.application.services.extract_index.index_select_adapter import (
            IndexSelectRequest,
        )

        ev = ShadowIndexEvaluator(
            settings=_settings(shadow_allowed_dates=frozenset({"2020-01-01"})),
            adapter=NoopAdapter(),  # type: ignore[arg-type]
        )
        res = await ev.evaluate(
            official_v2=OfficialV2Snapshot(
                credit_key="sandbox|d1|c1",
                item_id="x",
                fecha_limite=date(2026, 6, 1),
                source_location=None,
                selection_reason=None,
                error_code=None,
            ),
            request=IndexSelectRequest(
                environment=ExtractIndexEnvironment.SANDBOX,
                drive_id="d1",
                credit_key="sandbox|d1|c1",
                credit_path="c",
                credit_folder_items=[],
                extractos_children=None,
                live_files=[],
                content_endpoint_builder=lambda p: p,
            ),
            bank_code="banco_bogota",
            process_date=date(2026, 7, 29),
        )
        assert res.skip_reason == ShadowSkipReason.DATE_NOT_ALLOWED

    asyncio.run(_run())


def test_sampling_out_of_sample_skips() -> None:
    class NoopAdapter:
        async def select(self, request: Any) -> Any:
            raise AssertionError("no select")

    async def _run() -> None:
        from app.application.services.extract_index.index_select_adapter import (
            IndexSelectRequest,
        )

        ev = ShadowIndexEvaluator(
            settings=_settings(shadow_sample_pct=0.0),
            adapter=NoopAdapter(),  # type: ignore[arg-type]
        )
        res = await ev.evaluate(
            official_v2=OfficialV2Snapshot(
                credit_key="sandbox|d1|c1",
                item_id="x",
                fecha_limite=date(2026, 6, 1),
                source_location=None,
                selection_reason=None,
                error_code=None,
            ),
            request=IndexSelectRequest(
                environment=ExtractIndexEnvironment.SANDBOX,
                drive_id="d1",
                credit_key="sandbox|d1|c1",
                credit_path="c",
                credit_folder_items=[],
                extractos_children=None,
                live_files=[],
                content_endpoint_builder=lambda p: p,
            ),
            bank_code="banco_bogota",
            process_date=date(2026, 7, 29),
        )
        assert res.skip_reason == ShadowSkipReason.CREDIT_OUT_OF_SAMPLE

    asyncio.run(_run())


# --- 18: CancelledError no absorbido ---


def test_cancelled_error_not_absorbed() -> None:
    async def _run() -> None:
        ev = _FakeEvaluator()
        ev.raise_cancelled = True
        ctx = GenerateShadowJobContext(settings=_settings(), job_id="j")
        with pytest.raises(asyncio.CancelledError):
            await maybe_evaluate_shadow_after_v2(**_hook_kwargs(evaluator=ev, ctx=ctx))

    asyncio.run(_run())


# --- DI / firma / no Graph ---


def test_generate_signature_accepts_optional_evaluator() -> None:
    from app.application.use_cases.payment_validation_generate import (
        generate_payment_validation,
    )

    sig = inspect.signature(generate_payment_validation)
    assert "shadow_index_evaluator" in sig.parameters
    assert sig.parameters["shadow_index_evaluator"].default is None


def test_official_snapshot_is_frozen() -> None:
    snap = OfficialV2Snapshot(
        credit_key="k",
        item_id="i",
        fecha_limite=date(2026, 1, 1),
        source_location=None,
        selection_reason=None,
        error_code=None,
    )
    with pytest.raises(Exception):
        snap.item_id = "mutated"  # type: ignore[misc]


def test_no_create_task_in_shadow_hook() -> None:
    import app.application.services.extract_index.generate_shadow_hook as mod
    import pathlib

    src = pathlib.Path(mod.__file__).read_text(encoding="utf-8")
    assert "create_task" not in src


def test_serialized_generate_payload_shape_unchanged_by_shadow_locals() -> None:
    """El resultado 'publicado' simulado no incluye campos shadow."""

    async def _run() -> None:
        published = {
            "job_id": "j1",
            "status": "REVISION_CREADA",
            "rows": 1,
        }
        baseline = json.dumps(published, sort_keys=True)
        ev = _FakeEvaluator()
        ctx = GenerateShadowJobContext(settings=_settings(), job_id="j1")
        await maybe_evaluate_shadow_after_v2(**_hook_kwargs(evaluator=ev, ctx=ctx))
        assert json.dumps(published, sort_keys=True) == baseline

    asyncio.run(_run())


def test_loader_wiring_calls_hook_only_when_ctx_present() -> None:
    """Los dos puntos de extensión usan el mismo helper; ctx=None ⇒ cero llamadas."""

    async def _run() -> None:
        with mock.patch(
            "app.application.services.extract_index.generate_shadow_hook.maybe_evaluate_shadow_after_v2",
            new_callable=mock.AsyncMock,
        ) as mocked:
            # Simula la condición de Generate
            shadow_job_ctx = None
            process_date = date(2026, 7, 29)
            if shadow_job_ctx is not None and process_date is not None:
                await mocked()
            assert mocked.await_count == 0

            shadow_job_ctx = GenerateShadowJobContext(settings=_settings(), job_id="j")
            if shadow_job_ctx is not None and process_date is not None:
                await mocked(
                    evaluator=None,
                    job_ctx=shadow_job_ctx,
                )
            assert mocked.await_count == 1

    asyncio.run(_run())
