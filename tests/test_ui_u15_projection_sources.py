from __future__ import annotations

import asyncio

import pytest

from app.application.ui.business_status import item_from_legacy_row, map_business_status
from app.application.ui.job_read import JobReadResult
from app.application.ui.path_guard import UiAllowedRoots
from app.application.ui.ports import UiDriveItemMeta
from app.application.ui.process_projection import (
    ManifestEvidence,
    PaymentProcessProjectionService,
    ProjectionSources,
    TechnicalJobEvidence,
    derive_steps_from_control,
)
from app.application.ui.process_query import UiProcessQueryService
from tests.fakes.ui_sharepoint_fake import FakeUiSharePointRead, make_fake_control
from tests.ui_fixtures import make_snap

_LEGACY = "INCOMPLETO"


def test_legacy_incomplete_preserved_not_remapped() -> None:
    status, legacy, warning = map_business_status(_LEGACY)
    assert status == "DESCONOCIDO"
    assert legacy == _LEGACY
    assert warning is not None
    assert ("legacy" in warning.lower()) or ("retirado" in warning.lower())
    item = item_from_legacy_row(
        payment_id="1",
        client_name="ACME",
        credit="CREDITO #1",
        application_type="PAGO",
        estado_pago=_LEGACY,
    )
    assert item.business_status == "DESCONOCIDO"
    assert item.legacy_state == _LEGACY


def test_notify_job_404_but_control_sent_is_completed() -> None:
    snap = make_snap(
        estado_proceso="PENDIENTE_ASIENTOS",
        historical_file_path="hist/cartera.xlsx",
        notify_idempotency_key="pk-1",
        email_pdf_path="correos/mail.pdf",
    )
    steps = {s.name: s for s in derive_steps_from_control(snap, jobs=TechnicalJobEvidence())}
    assert steps["notify"].status == "completed"


def test_merge_job_404_manifest_partial_is_partial() -> None:
    snap = make_snap(
        estado_proceso="MERGE_PARCIAL",
        historical_file_path="hist/cartera.xlsx",
        notify_idempotency_key="pk",
        email_pdf_path="correos/x.pdf",
        merge_manifest_path="traz/manifest.json",
        merge_idempotency_key="mk",
    )
    steps = {
        s.name: s
        for s in derive_steps_from_control(
            snap,
            jobs=TechnicalJobEvidence(),
            manifest=ManifestEvidence(
                exists=True,
                status="PARTIAL",
                incomplete_group_count=2,
                complete_group_count=1,
            ),
        )
    }
    assert steps["merge"].status == "partial"
    assert steps["dry_run"].status == "blocked"


def test_job_completed_without_persistent_evidence_is_inconsistent() -> None:
    snap = make_snap(
        estado_proceso="FINALIZADO",
        historical_file_path="hist/cartera.xlsx",
        notify_idempotency_key="",
        email_pdf_path="",
    )
    memory = JobReadResult(
        job_id="n1",
        store="sharepoint_memory",
        payload={"type": "notify_validar_extractos", "status": "completed"},
    )
    steps = {
        s.name: s
        for s in derive_steps_from_control(
            snap,
            jobs=TechnicalJobEvidence(memory_job=memory),
        )
    }
    assert steps["notify"].status == "failed_business"


def test_query_service_uses_fake_reader_no_network(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ACTIVE_ENVIRONMENT", "sandbox")
    root = "INFORMACION CREDITOS-CLIENTES/03 COMWARE PRUEBAS- INFORMACION CREDITOS CLIENTES"
    control_path = (
        f"{root}/02 VALIDACION PAGOS/90 ACCESO RESTRINGIDO/03 CONTROL TECNICO/control.xlsx"
    )
    review_path = f"{root}/02 VALIDACION PAGOS/01 REVISION/val.xlsx"
    snap = make_snap(
        control_file_path=control_path,
        validation_file_path=review_path,
        estado_proceso="REVISION_CREADA",
    )
    fake = FakeUiSharePointRead(
        roots=UiAllowedRoots(environment="sandbox", roots=(root,)),
        controls={"banco_bancolombia": make_fake_control(snap)},
        metas={
            review_path: UiDriveItemMeta(
                path=review_path,
                exists=True,
                web_url="https://sharepoint.example/review?web=1",
                etag='"r1"',
            )
        },
    )
    detail = asyncio.run(UiProcessQueryService(fake).project_bank("banco_bancolombia"))
    assert detail.process_key == snap.process_key
    assert any(l.rel == "review_excel" and l.web_url for l in detail.links)


def test_projection_still_control_first_with_sources() -> None:
    snap = make_snap()
    detail = PaymentProcessProjectionService().project(ProjectionSources(snapshot=snap))
    assert detail.trigger_source is None
