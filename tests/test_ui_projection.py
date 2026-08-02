from __future__ import annotations

from app.application.ui.job_read import JobReadResult
from app.application.ui.process_projection import (
    ManifestEvidence,
    ManifestOutputRef,
    PaymentProcessProjectionService,
    ProjectionSources,
    derive_steps_from_control,
)
from tests.ui_fixtures import make_snap


def test_review_stage_from_revision_creada() -> None:
    snap = make_snap(estado_proceso="REVISION_CREADA")
    steps = {s.name: s for s in derive_steps_from_control(snap)}
    assert steps["generate"].status == "completed"
    assert steps["review"].status == "in_progress"
    assert steps["finalize"].status == "not_started"
    assert steps["notify"].status == "not_started"


def test_finalize_ok_notify_failed_retryable_no_rerun_finalize() -> None:
    snap = make_snap(
        estado_proceso="ERROR_NOTIFY",
        historical_file_path="historico/cartera.xlsx",
        secretary_file_path="historico/Asientos_Pendientes.xlsx",
        notify_idempotency_key="",
        email_pdf_path="",
    )
    detail = PaymentProcessProjectionService().project(ProjectionSources(snapshot=snap))
    by = {s.name: s for s in detail.steps}
    assert by["finalize"].status == "completed"
    assert by["notify"].status == "failed_retryable"
    assert by["notify"].can_retry is True
    assert by["notify"].retry_action == "retry_notify"
    assert detail.operational_status == "ERROR_RECUPERABLE"
    assert any(a.code == "retry_notify" for a in detail.next_actions)
    # Mutaciones no habilitadas en U1
    retry = next(a for a in detail.next_actions if a.code == "retry_notify")
    assert retry.enabled is False


def test_notify_completed_requires_persistent_control_not_memory_job() -> None:
    snap = make_snap(
        estado_proceso="FINALIZADO",
        historical_file_path="historico/cartera.xlsx",
        notify_idempotency_key="",
        email_pdf_path="",
    )
    # Job memoria “completed” NO debe marcar notify completed.
    memory_job = JobReadResult(
        job_id="j1",
        store="sharepoint_memory",
        payload={"type": "notify_validar_extractos", "status": "completed"},
    )
    steps = {s.name: s for s in derive_steps_from_control(snap, active_job=memory_job)}
    assert steps["notify"].status == "sync_pending"

    snap2 = make_snap(
        estado_proceso="PENDIENTE_ASIENTOS",
        historical_file_path="historico/cartera.xlsx",
        notify_idempotency_key="payment-validation|banco_bancolombia|2026-07-29|abc-123",
        email_pdf_path="correos/ABONOS.pdf",
        secretary_file_path="historico/Asientos_Pendientes.xlsx",
    )
    steps2 = {s.name: s for s in derive_steps_from_control(snap2)}
    assert steps2["notify"].status == "completed"


def test_merge_partial_blocks_dry_run() -> None:
    snap = make_snap(
        estado_proceso="MERGE_PARCIAL",
        historical_file_path="historico/cartera.xlsx",
        notify_idempotency_key="pk",
        email_pdf_path="correos/x.pdf",
        merge_manifest_path="trazabilidad/manifest.json",
        secretary_file_path="historico/Asientos.xlsx",
    )
    detail = PaymentProcessProjectionService().project(ProjectionSources(snapshot=snap))
    by = {s.name: s for s in detail.steps}
    assert by["merge"].status == "partial"
    assert by["dry_run"].status == "blocked"
    assert detail.operational_status == "FINALIZADO_PARCIALMENTE"
    assert detail.trigger_source is None
    assert detail.requested_by is None


def test_active_job_only_marks_in_progress() -> None:
    snap = make_snap(
        estado_proceso="FINALIZADO",
        historical_file_path="h.xlsx",
    )
    job = JobReadResult(
        job_id="n1",
        store="sharepoint_memory",
        payload={
            "type": "notify_validar_extractos",
            "status": "running",
            "started_at": "2026-07-29T12:00:00-05:00",
        },
    )
    detail = PaymentProcessProjectionService().project(
        ProjectionSources(snapshot=snap, active_job=job)
    )
    by = {s.name: s for s in detail.steps}
    assert by["notify"].status == "in_progress"
    assert detail.active_job is not None
    assert detail.active_job.store == "sharepoint_memory"
    assert detail.active_job.poll_path_ui == "/api/ui/v1/jobs/n1"


def test_legacy_compatible_without_trigger_fields() -> None:
    snap = make_snap()
    detail = PaymentProcessProjectionService().project(ProjectionSources(snapshot=snap))
    dumped = detail.model_dump()
    assert "trigger_source" in dumped
    assert dumped["trigger_source"] is None
    assert dumped["requested_by"] is None


def test_merge_pdf_link_uses_manifest_primary_output_not_json() -> None:
    """«Abrir PDF consolidado» apunta al PDF del merge, no al JSON del manifiesto."""
    snap = make_snap(
        estado_proceso="CONSOLIDADO",
        historical_file_path="historico/cartera.xlsx",
        notify_idempotency_key="pk",
        email_pdf_path="correos/x.pdf",
        merge_manifest_path="trazabilidad/manifest.json",
        secretary_file_path="historico/Asientos.xlsx",
    )
    pdf_path = "01 TRAZABILIDAD/PDF consolidado bancolombia.pdf"
    detail = PaymentProcessProjectionService().project(
        ProjectionSources(
            snapshot=snap,
            manifest=ManifestEvidence(
                exists=True,
                status="COMPLETE",
                primary_output_path=pdf_path,
                output_pdfs=(ManifestOutputRef(path=pdf_path, credito="265"),),
            ),
            web_urls={"merge_pdf": "https://sharepoint.example/merged.pdf"},
        )
    )
    merge_links = [lnk for lnk in detail.links if lnk.rel == "merge_pdf"]
    assert len(merge_links) == 1
    assert merge_links[0].label == "Abrir PDF consolidado · Crédito 265"
    assert merge_links[0].path == pdf_path
    assert merge_links[0].web_url == "https://sharepoint.example/merged.pdf"
    assert not any(lnk.rel == "merge_manifest" for lnk in detail.links)


def test_merge_projects_all_output_pdfs_not_only_primary() -> None:
    """Con varios outputs[] se proyecta un enlace operativo por PDF."""
    snap = make_snap(
        estado_proceso="CONSOLIDADO",
        historical_file_path="historico/cartera.xlsx",
        notify_idempotency_key="pk",
        email_pdf_path="correos/x.pdf",
        merge_manifest_path="trazabilidad/manifest.json",
        secretary_file_path="historico/Asientos.xlsx",
    )
    pdf_a = "01 TRAZABILIDAD/consolidado_265.pdf"
    pdf_b = "01 TRAZABILIDAD/consolidado_310.pdf"
    detail = PaymentProcessProjectionService().project(
        ProjectionSources(
            snapshot=snap,
            manifest=ManifestEvidence(
                exists=True,
                status="COMPLETE",
                primary_output_path=pdf_a,
                output_pdfs=(
                    ManifestOutputRef(
                        path=pdf_a,
                        credito="265",
                        web_url="https://sharepoint.example/a.pdf",
                    ),
                    ManifestOutputRef(
                        path=pdf_b,
                        credito="310",
                        web_url="https://sharepoint.example/b.pdf",
                    ),
                ),
            ),
            web_urls={
                "merge_pdf:0": "https://sharepoint.example/a.pdf",
                "merge_pdf:1": "https://sharepoint.example/b.pdf",
            },
        )
    )
    merge_links = [lnk for lnk in detail.links if lnk.rel.startswith("merge_pdf")]
    assert [lnk.rel for lnk in merge_links] == ["merge_pdf:0", "merge_pdf:1"]
    assert merge_links[0].label == "Abrir PDF consolidado · Crédito 265"
    assert merge_links[0].path == pdf_a
    assert merge_links[0].web_url == "https://sharepoint.example/a.pdf"
    assert merge_links[1].label == "Abrir PDF consolidado · Crédito 310"
    assert merge_links[1].path == pdf_b
    assert merge_links[1].web_url == "https://sharepoint.example/b.pdf"
    assert not any(lnk.rel == "merge_manifest" for lnk in detail.links)


def test_merge_same_credito_multiple_id_pago_gets_pago_suffix() -> None:
    snap = make_snap(
        estado_proceso="CONSOLIDADO",
        historical_file_path="historico/cartera.xlsx",
        notify_idempotency_key="pk",
        email_pdf_path="correos/x.pdf",
        merge_manifest_path="trazabilidad/manifest.json",
    )
    detail = PaymentProcessProjectionService().project(
        ProjectionSources(
            snapshot=snap,
            manifest=ManifestEvidence(
                exists=True,
                primary_output_path="m/a.pdf",
                output_pdfs=(
                    ManifestOutputRef(path="m/a.pdf", credito="265", id_pago="pago-aaa"),
                    ManifestOutputRef(path="m/b.pdf", credito="265", id_pago="pago-bbb"),
                ),
            ),
            web_urls={"merge_pdf:0": "https://sharepoint.example/a.pdf"},
        )
    )
    merge_links = [lnk for lnk in detail.links if lnk.rel.startswith("merge_pdf")]
    assert [lnk.label for lnk in merge_links] == [
        "Abrir PDF consolidado · Crédito 265 · Pago 1",
        "Abrir PDF consolidado · Crédito 265 · Pago 2",
    ]
    # Se mantienen ambos aunque solo uno tenga web_url resuelta.
    assert merge_links[0].web_url == "https://sharepoint.example/a.pdf"
    assert merge_links[1].web_url is None
    assert merge_links[1].path == "m/b.pdf"


def test_correos_link_only_when_web_url_present() -> None:
    snap = make_snap(estado_proceso="FINALIZADO", historical_file_path="h.xlsx")
    detail = PaymentProcessProjectionService().project(
        ProjectionSources(
            snapshot=snap,
            web_urls={"correos": "https://sharepoint.example/CORREOS.xlsx"},
        )
    )
    correos = [lnk for lnk in detail.links if lnk.rel == "correos"]
    assert len(correos) == 1
    assert correos[0].label == "Revisar destinatarios"
    assert correos[0].web_url == "https://sharepoint.example/CORREOS.xlsx"


def test_merge_does_not_duplicate_primary_when_present_in_outputs() -> None:
    snap = make_snap(
        estado_proceso="CONSOLIDADO",
        historical_file_path="historico/cartera.xlsx",
        notify_idempotency_key="pk",
        email_pdf_path="correos/x.pdf",
        merge_manifest_path="trazabilidad/manifest.json",
    )
    pdf = "m/only.pdf"
    detail = PaymentProcessProjectionService().project(
        ProjectionSources(
            snapshot=snap,
            manifest=ManifestEvidence(
                exists=True,
                primary_output_path=pdf,
                output_pdfs=(ManifestOutputRef(path=pdf, credito="99"),),
            ),
            web_urls={"merge_pdf": "https://sharepoint.example/only.pdf"},
        )
    )
    merge_links = [lnk for lnk in detail.links if lnk.rel.startswith("merge_pdf")]
    assert len(merge_links) == 1
    assert merge_links[0].rel == "merge_pdf"
    assert merge_links[0].label == "Abrir PDF consolidado · Crédito 99"
