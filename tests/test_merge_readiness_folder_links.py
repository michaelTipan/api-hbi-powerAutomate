"""folder_links de merge_readiness: todas las carpetas ASIENTOS del lote."""
from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from openpyxl import Workbook

from app.application.ui.merge_readiness import (
    assess_merge_readiness,
    collect_asientos_folder_links)
from tests.ui_fixtures import make_snap

def _group(
    id_pago: str,
    tipo: str,
    *rows: dict[str, object]) -> tuple[str, str, list[dict[str, object]]]:
    return (id_pago, tipo, list(rows))

def test_collect_two_distinct_credits_two_folder_links() -> None:
    groups = [
        _group(
            "P1",
            "PAGO",
            {
                "credito_digits": "100",
                "ruta_asientos_cell": "clientes/A/CREDITO # 100/ASIENTOS CONTABLES CRED 100",
            }),
        _group(
            "P2",
            "PAGO",
            {
                "credito_digits": "200",
                "ruta_asientos_cell": "clientes/B/CREDITO # 200/ASIENTOS CONTABLES CRED 200",
            }),
    ]
    links = collect_asientos_folder_links(groups)
    assert len(links) == 2
    assert [l["credito"] for l in links] == ["100", "200"]
    assert links[0]["path"].endswith("CRED 100")
    assert links[1]["path"].endswith("CRED 200")

def test_collect_same_credit_two_payments_one_folder_link() -> None:
    path = "clientes/X/CREDITO # 265/ASIENTOS CONTABLES CRED 265"
    groups = [
        _group("P1", "PAGO", {"credito_digits": "265", "ruta_asientos_cell": path}),
        _group("P2", "PAGO", {"credito_digits": "265", "ruta_asientos_cell": path}),
    ]
    links = collect_asientos_folder_links(groups)
    assert len(links) == 1
    assert links[0]["credito"] == "265"
    assert links[0]["path"] == path

def test_collect_dedupes_case_and_slash_variants() -> None:
    groups = [
        _group(
            "P1",
            "PAGO",
            {
                "credito_digits": "10",
                "ruta_asientos_cell": "Clientes/A/CREDITO # 10/ASIENTOS",
            }),
        _group(
            "P2",
            "ABONO",
            {
                "credito_digits": "10",
                "ruta_asientos_cell": "clientes/A/CREDITO # 10/ASIENTOS/",
            }),
    ]
    links = collect_asientos_folder_links(groups)
    assert len(links) == 1

def test_collect_skips_rows_without_ruta() -> None:
    groups = [
        _group(
            "P1",
            "PAGO",
            {"credito_digits": "1", "ruta_asientos_cell": None},
            {
                "credito_digits": "2",
                "ruta_asientos_cell": "clientes/Y/CREDITO # 2/ASIENTOS",
            }),
    ]
    links = collect_asientos_folder_links(groups)
    assert len(links) == 1
    assert links[0]["credito"] == "2"

def _hist_bytes_two_pagos() -> bytes:
    """Histórico mínimo con 2 pagos (Validar=SI) en créditos distintos."""
    from io import BytesIO

    from app.application.services.review_schema import AplicacionPagosCols, InternalPathCols, ReviewSheets
    from tests.test_finalize_validation import make_distrib_row

    wb = Workbook()
    ws = wb.active
    assert ws is not None
    ws.title = ReviewSheets.APLICACION_PAGOS
    headers = list(AplicacionPagosCols.HEADERS) + [InternalPathCols.RUTA_ASIENTOS_CONTABLES]
    ws.append(headers)
    for id_pago, credito, ruta in (
        ("ID-A", "100", "clientes/A/CREDITO # 100/ASIENTOS CONTABLES CRED 100"),
        ("ID-B", "200", "clientes/B/CREDITO # 200/ASIENTOS CONTABLES CRED 200")):
        row, _ = make_distrib_row(
            id_pago=id_pago,
            cliente=f"Cliente {credito}",
            credito=credito,
            ruta_pdf_internal=f"extractos/{credito}.pdf")
        ws.append(list(row) + [ruta])
    buf = BytesIO()
    wb.save(buf)
    return buf.getvalue()

def test_assess_already_merged_still_returns_folder_links(
    monkeypatch: pytest.MonkeyPatch) -> None:
    """already_merged debe seguir exponiendo folder_links (recovery UX)."""
    import app.application.ui.merge_readiness as mr

    snap = make_snap(
        estado_proceso="CONSOLIDADO",
        historical_file_path="hist/demo.xlsx",
        email_pdf_path="out/correo.pdf",
        merge_idempotency_key="mk-1",
        merge_manifest_path="manifests/m.json")
    monkeypatch.setattr(
        mr,
        "resolve_sharepoint_from_env",
        AsyncMock(return_value={"site_id": "s1", "drive_id": "d1"}))
    monkeypatch.setattr(
        mr,
        "_graph_download_by_path",
        AsyncMock(return_value=_hist_bytes_two_pagos()))
    monkeypatch.setattr(mr, "control_indicates_already_merged", lambda _s: True)
    monkeypatch.setattr(
        mr,
        "get_job_manager",
        lambda: SimpleNamespace(has_completed_merge=lambda _pk: True))
    monkeypatch.delenv("GRAPH_VALIDAR_ESTADO_PAGO_CONTAINS", raising=False)

    async def _list_ok(_g, _s, _d, path: str) -> list[dict[str, object]]:
        credit = "100" if "100" in path else "200"
        return [
            {
                "name": f"asiento_{credit}.pdf",
                "file": {},
                "size": 1000 + int(credit),
                "eTag": f'"{credit}"',
                "lastModifiedDateTime": "2026-08-01T12:00:00Z",
            }
        ]

    monkeypatch.setattr(mr, "_list_drive_folder_children", _list_ok)

    result = asyncio.run(assess_merge_readiness(AsyncMock(), snap, "banco_bogota"))
    assert result.status == "already_merged"
    assert len(result.folder_links) == 2
    creditos = {str(fl.get("credito")) for fl in result.folder_links}
    assert creditos == {"100", "200"}
    for fl in result.folder_links:
        assert fl.get("list_ok") is True
        pdfs = fl.get("observed_pdfs") or []
        assert len(pdfs) == 1
        assert str(pdfs[0].get("name", "")).endswith(".pdf")

def test_assess_graph_fail_still_returns_all_folder_links(
    monkeypatch: pytest.MonkeyPatch) -> None:
    """Antes: fallo Graph en la 1.ª carpeta cortaba el loop y perdía el resto."""
    import app.application.ui.merge_readiness as mr

    snap = make_snap(
        estado_proceso="PENDIENTE_ASIENTOS",
        historical_file_path="hist/demo.xlsx",
        email_pdf_path="out/correo.pdf",
        merge_idempotency_key="",
        merge_manifest_path="")

    monkeypatch.setattr(
        mr,
        "resolve_sharepoint_from_env",
        AsyncMock(return_value={"site_id": "s1", "drive_id": "d1"}))
    monkeypatch.setattr(
        mr,
        "_graph_download_by_path",
        AsyncMock(return_value=_hist_bytes_two_pagos()))
    monkeypatch.setattr(mr, "control_indicates_already_merged", lambda _s: False)
    monkeypatch.setattr(
        mr,
        "get_job_manager",
        lambda: SimpleNamespace(has_completed_merge=lambda _pk: False))

    calls: list[str] = []

    async def _list_fail(_g, _s, _d, path: str) -> list[dict[str, object]]:
        calls.append(path)
        raise RuntimeError("graph boom")

    monkeypatch.setattr(mr, "_list_drive_folder_children", _list_fail)
    monkeypatch.delenv("GRAPH_VALIDAR_ESTADO_PAGO_CONTAINS", raising=False)

    result = asyncio.run(assess_merge_readiness(AsyncMock(), snap, "banco_bogota"))

    assert result.status == "unknown"
    assert len(result.folder_links) == 2
    creditos = {str(fl.get("credito")) for fl in result.folder_links}
    assert creditos == {"100", "200"}
    # Ambas carpetas se intentaron listar (loop no aborta tras el 1.er fallo).
    assert len(calls) == 2

def test_assess_ready_exposes_both_folder_links(
    monkeypatch: pytest.MonkeyPatch) -> None:
    import app.application.ui.merge_readiness as mr

    snap = make_snap(
        estado_proceso="PENDIENTE_ASIENTOS",
        historical_file_path="hist/demo.xlsx",
        email_pdf_path="out/correo.pdf",
        merge_idempotency_key="",
        merge_manifest_path="")
    monkeypatch.setattr(
        mr,
        "resolve_sharepoint_from_env",
        AsyncMock(return_value={"site_id": "s1", "drive_id": "d1"}))
    monkeypatch.setattr(
        mr,
        "_graph_download_by_path",
        AsyncMock(return_value=_hist_bytes_two_pagos()))
    monkeypatch.setattr(mr, "control_indicates_already_merged", lambda _s: False)
    monkeypatch.setattr(
        mr,
        "get_job_manager",
        lambda: SimpleNamespace(has_completed_merge=lambda _pk: False))
    monkeypatch.delenv("GRAPH_VALIDAR_ESTADO_PAGO_CONTAINS", raising=False)

    async def _list_ok(_g, _s, _d, path: str) -> list[dict[str, object]]:
        credit = "100" if "100" in path else "200"
        return [{"name": f"asiento_{credit}.pdf", "file": {}}]

    monkeypatch.setattr(mr, "_list_drive_folder_children", _list_ok)

    result = asyncio.run(assess_merge_readiness(AsyncMock(), snap, "banco_bogota"))
    assert result.status == "ready"
    assert len(result.folder_links) == 2

def _patch_assess_common(monkeypatch: pytest.MonkeyPatch, hist_bytes: bytes) -> None:
    import app.application.ui.merge_readiness as mr

    monkeypatch.setattr(
        mr,
        "resolve_sharepoint_from_env",
        AsyncMock(return_value={"site_id": "s1", "drive_id": "d1"}))
    monkeypatch.setattr(
        mr,
        "_graph_download_by_path",
        AsyncMock(return_value=hist_bytes))
    monkeypatch.setattr(mr, "control_indicates_already_merged", lambda _s: False)
    monkeypatch.setattr(
        mr,
        "get_job_manager",
        lambda: SimpleNamespace(has_completed_merge=lambda _pk: False))
    monkeypatch.delenv("GRAPH_VALIDAR_ESTADO_PAGO_CONTAINS", raising=False)

def test_assess_empty_folder_missing_item_not_found(
    monkeypatch: pytest.MonkeyPatch) -> None:
    import app.application.ui.merge_readiness as mr

    snap = make_snap(
        estado_proceso="PENDIENTE_ASIENTOS",
        historical_file_path="hist/demo.xlsx",
        email_pdf_path="out/correo.pdf",
        merge_idempotency_key="",
        merge_manifest_path="")
    _patch_assess_common(monkeypatch, _hist_bytes_two_pagos())

    async def _list_empty(_g, _s, _d, _path: str) -> list[dict[str, object]]:
        return []

    monkeypatch.setattr(mr, "_list_drive_folder_children", _list_empty)

    result = asyncio.run(assess_merge_readiness(AsyncMock(), snap, "banco_bogota"))
    assert result.status == "incomplete"
    codes = {str(i.get("error_code")) for i in result.missing_items}
    assert codes == {"asiento_contable_not_found"}
    assert "nombre" not in result.user_message.lower()

def test_assess_wrong_pdf_name_missing_item_mismatch(
    monkeypatch: pytest.MonkeyPatch) -> None:
    import app.application.ui.merge_readiness as mr

    snap = make_snap(
        estado_proceso="PENDIENTE_ASIENTOS",
        historical_file_path="hist/demo.xlsx",
        email_pdf_path="out/correo.pdf",
        merge_idempotency_key="",
        merge_manifest_path="")
    _patch_assess_common(monkeypatch, _hist_bytes_two_pagos())

    async def _list_mismatch(_g, _s, _d, path: str) -> list[dict[str, object]]:
        # PDF presente pero con otro crédito en el nombre → mismatch.
        return [{"name": "asiento_999.pdf", "file": {}}]

    monkeypatch.setattr(mr, "_list_drive_folder_children", _list_mismatch)

    result = asyncio.run(assess_merge_readiness(AsyncMock(), snap, "banco_bogota"))
    assert result.status == "incomplete"
    codes = {str(i.get("error_code")) for i in result.missing_items}
    assert codes == {"asiento_contable_credit_mismatch"}
    assert "no coincide" in result.user_message.lower()
    assert len(result.missing_items) == 2
    assert {str(i.get("credito")) for i in result.missing_items} == {"100", "200"}
    # Enriquecimiento: nombre del PDF rechazado + hint del crédito en el nombre.
    for item in result.missing_items:
        assert item.get("found_pdf_name") == "asiento_999.pdf"
        assert item.get("found_credit_hint") == "999"

def test_parse_skip_does_not_substring_match_credit_digits() -> None:
    """crédito '2' no debe matchear skip de credito=264."""
    from app.application.services.merge_group_validation import (
        _parse_skip_reason_for_credit)

    line = (
        "asiento_contable_credit_mismatch credito=264 "
        "asiento_pdf_found=asiento_banco_bogota_credito-258.pdf found_credit=258"
    )
    assert _parse_skip_reason_for_credit(line, "2") is None
    assert _parse_skip_reason_for_credit(line, "26") is None
    assert _parse_skip_reason_for_credit(line, "64") is None
    parsed = _parse_skip_reason_for_credit(line, "264")
    assert parsed is not None
    assert parsed["error_code"] == "asiento_contable_credit_mismatch"
    assert parsed["found_pdf_name"] == "asiento_banco_bogota_credito-258.pdf"
    assert parsed["found_credit_hint"] == "258"

def test_assess_mixed_not_found_and_mismatch(
    monkeypatch: pytest.MonkeyPatch) -> None:
    import app.application.ui.merge_readiness as mr

    snap = make_snap(
        estado_proceso="PENDIENTE_ASIENTOS",
        historical_file_path="hist/demo.xlsx",
        email_pdf_path="out/correo.pdf",
        merge_idempotency_key="",
        merge_manifest_path="")
    _patch_assess_common(monkeypatch, _hist_bytes_two_pagos())

    async def _list_mixed(_g, _s, _d, path: str) -> list[dict[str, object]]:
        if "100" in path:
            return []  # ausencia
        return [{"name": "asiento_otro.pdf", "file": {}}]  # mismatch para 200

    monkeypatch.setattr(mr, "_list_drive_folder_children", _list_mixed)

    result = asyncio.run(assess_merge_readiness(AsyncMock(), snap, "banco_bogota"))
    assert result.status == "incomplete"
    by_cred = {
        str(i.get("credito")): str(i.get("error_code")) for i in result.missing_items
    }
    assert by_cred["100"] == "asiento_contable_not_found"
    assert by_cred["200"] == "asiento_contable_credit_mismatch"
    assert "faltan asientos contables o hay nombres" in result.user_message.lower()
