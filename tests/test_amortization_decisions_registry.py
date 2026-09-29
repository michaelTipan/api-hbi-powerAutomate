"""Registro de decisiones por proceso (exclusiones, confirmaciones, asientos no usados)."""

from __future__ import annotations

import asyncio
import json
from typing import Any
from urllib.parse import unquote

import httpx
import pytest

from app.application.services import amortization_decisions as reg_mod
from app.application.services.amortization_decisions import (
    DecisionsRegistryError,
    DecisionsRegistryUnavailableError,
    active_exclusions,
    add_confirmation,
    add_exclusion,
    add_unused_asiento,
    conciliation_key,
    empty_registry,
    exclusion_for_credit,
    excluded_credit_tokens,
    find_confirmation,
    group_key_for_credits,
    load_registry_for_process,
    lock_active_decisions,
    mutate_registry,
    normalize_registry,
    record_closure,
    registry_filename,
    registry_path_belongs_to,
    resolve_motivo,
    resolve_registry_path,
    undo_confirmation,
    undo_exclusion,
    unused_asientos,
)

PK = "payment-validation|banco_bogota|2026-08-01|abc12345-0000"
PK_OTHER = "payment-validation|banco_bogota|2026-07-31|zzz99999-0000"


@pytest.fixture(autouse=True)
def _clear_cache():
    reg_mod.clear_registry_cache()
    yield
    reg_mod.clear_registry_cache()


def _registry() -> dict[str, Any]:
    return empty_registry(process_key=PK, bank_code="banco_bogota", report_date_iso="2026-08-01")


def _exclude(reg, credits=("133", "102"), motivo="FALTA_ASIENTO", nota=""):
    return add_exclusion(
        reg,
        credits=list(credits),
        clientes={"102": "JASP", "133": "JASP"},
        id_pagos=["P1"],
        tablas={"102": "T/102.xlsx", "133": "/T/133.xlsx/"},
        motivo_codigo=motivo,
        nota=nota,
        quien="operador",
    )


class FakeDrive:
    """Graph mínimo para el JSON del registro (ETag + If-Match)."""

    def __init__(self) -> None:
        self.files: dict[str, bytes] = {}
        self.etags: dict[str, str] = {}
        self.puts: list[tuple[str, str | None]] = []
        self.fail_get_bytes: Exception | None = None
        self.conflicts_left = 0

    @staticmethod
    def _path(endpoint: str) -> str:
        rest = endpoint.split("root:/", 1)[1]
        rest = rest.rsplit(":/content", 1)[0] if rest.endswith(":/content") else rest
        return unquote(rest)

    async def get(self, endpoint: str, **_k):
        path = self._path(endpoint)
        if path not in self.files:
            raise FileNotFoundError(path)
        return {"eTag": self.etags[path]}

    async def get_bytes(self, endpoint: str, **_k):
        if self.fail_get_bytes is not None:
            raise self.fail_get_bytes
        path = self._path(endpoint)
        if path not in self.files:
            raise FileNotFoundError(path)
        return self.files[path]

    async def put_bytes(self, endpoint: str, body: bytes, *, content_type=None, if_match=None, **_k):
        path = self._path(endpoint)
        self.puts.append((path, if_match))
        if self.conflicts_left > 0:
            self.conflicts_left -= 1
            self.etags[path] = f"external-{self.conflicts_left}"
            req = httpx.Request("PUT", "https://graph.test")
            raise httpx.HTTPStatusError("412", request=req, response=httpx.Response(412, request=req))
        if if_match is not None and self.etags.get(path) != if_match:
            req = httpx.Request("PUT", "https://graph.test")
            raise httpx.HTTPStatusError("412", request=req, response=httpx.Response(412, request=req))
        self.files[path] = body
        self.etags[path] = f"etag-{len(self.puts)}"
        return {"eTag": self.etags[path]}

    async def post_json(self, endpoint: str, body: dict[str, Any], **_k):
        return {"id": "folder"}

    async def patch_json(self, endpoint: str, body: dict[str, Any], **_k):
        return {}


# --- reglas puras -------------------------------------------------------------


def test_nombre_y_ruta_en_carpeta_de_trazabilidad_del_manifest():
    name = registry_filename("banco_bogota", "2026-08-01", PK)
    assert name.startswith("decisiones_banco_bogota_2026-08-01_")
    assert name.endswith(".json")
    path = resolve_registry_path(
        bank_code="banco_bogota",
        report_date_iso="2026-08-01",
        process_key=PK,
        merge_manifest_path="/LOGS/2026/08/01/merge_manifest_2026-08-01.json",
    )
    assert path == f"LOGS/2026/08/01/{name}"
    assert registry_path_belongs_to(path, PK)
    assert not registry_path_belongs_to(path, PK_OTHER)


def test_motivos_catalogo_y_otro_requiere_texto():
    assert resolve_motivo("falta_asiento", "")[1] == "Falta el asiento de Contabilidad"
    assert resolve_motivo("APLICACION_MANUAL", "")[1] == "Se aplicará manualmente"
    assert resolve_motivo("OTRO", " Cliente en acuerdo ")[1:] == ("Cliente en acuerdo", "Cliente en acuerdo")
    with pytest.raises(DecisionsRegistryError) as exc:
        resolve_motivo("OTRO", "   ")
    assert exc.value.error_code == "exclusion_reason_text_required"
    assert exc.value.status_code == 422
    with pytest.raises(DecisionsRegistryError):
        resolve_motivo("INVENTADO", "")
    with pytest.raises(DecisionsRegistryError) as exc:
        resolve_motivo("TABLA_CON_ERROR", "x" * 301)
    assert exc.value.error_code == "decision_note_too_long"


def test_exclusion_de_grupo_idempotente_y_undo():
    reg = _registry()
    reg1, entry = _exclude(reg)
    assert reg["exclusions"] == []  # mutación sobre copia
    assert entry["credits"] == ["102", "133"]
    assert entry["group_key"] == "102+133"
    assert entry["tablas"]["133"] == "T/133.xlsx"
    assert excluded_credit_tokens(reg1) == {"102", "133"}
    assert exclusion_for_credit(reg1, "CREDITO # 0102") is entry or exclusion_for_credit(reg1, "102")

    reg2, again = _exclude(reg1, credits=("102",))
    assert again["exclusion_id"] == entry["exclusion_id"]
    assert len(reg2["exclusions"]) == 1

    reg3, undone = undo_exclusion(reg2, credit="133", quien="operador")
    assert undone is not None and undone["status"] == "undone"
    assert active_exclusions(reg3) == []
    assert len(reg3["exclusions"]) == 1  # historial conservado
    _, none = undo_exclusion(reg3, credit="133", quien="operador")
    assert none is None


def test_lock_impide_deshacer_despues_de_procesar():
    reg, _ = _exclude(_registry())
    key = conciliation_key("87", "2026-09-23")
    reg, _ = add_confirmation(
        reg,
        key=key,
        credits=["87"],
        clientes={"87": "CARBONERA"},
        fecha_banco="2026-09-23",
        monto_banco=22_044_688,
        monto_asientos=22_032_455,
        nota="",
        quien="operador",
    )
    locked, changed = lock_active_decisions(reg, attempt_id="apply-1")
    assert changed
    again, changed_again = lock_active_decisions(locked, attempt_id="apply-2")
    assert not changed_again
    assert again["exclusions"][0]["locked_attempt_id"] == "apply-1"
    with pytest.raises(DecisionsRegistryError) as exc:
        undo_exclusion(locked, credit="102", quien="operador")
    assert exc.value.error_code == "exclusion_locked"
    with pytest.raises(DecisionsRegistryError) as exc:
        undo_confirmation(locked, key=key, quien="operador")
    assert exc.value.error_code == "confirmation_locked"


def test_lock_solo_bloquea_las_decisiones_usadas_por_la_ejecucion():
    reg, used = _exclude(_registry(), credits=("102",))
    reg, later = _exclude(reg, credits=("250",))
    locked, changed = lock_active_decisions(reg, attempt_id="apply-1", ids={used["exclusion_id"]})
    assert changed
    by_id = {e["exclusion_id"]: e for e in locked["exclusions"]}
    assert by_id[used["exclusion_id"]]["locked_at"]
    assert by_id[later["exclusion_id"]]["locked_at"] is None
    reg2, undone = undo_exclusion(locked, credit="250", quien="operador")
    assert undone is not None


def test_confirmacion_vale_solo_con_los_mismos_montos():
    key = conciliation_key("87", "2026-09-23")
    reg, entry = add_confirmation(
        _registry(),
        key=key,
        credits=["87"],
        clientes={},
        fecha_banco="2026-09-23",
        monto_banco="22044688",
        monto_asientos=22032455.0,
        nota="Diferencia no aplicada",
        quien="operador",
    )
    assert entry["monto_sin_aplicar"] == "12233.00"
    assert find_confirmation(reg, key=key, monto_banco=22_044_688, monto_asientos=22_032_455) is entry
    # Cambió el asiento → la confirmación ya no aplica.
    assert find_confirmation(reg, key=key, monto_banco=22_044_688, monto_asientos=22_032_000) is None
    # Reconfirmar con montos nuevos reemplaza la anterior.
    reg2, entry2 = add_confirmation(
        reg,
        key=key,
        credits=["87"],
        clientes={},
        fecha_banco="2026-09-23",
        monto_banco=22_044_688,
        monto_asientos=22_032_000,
        nota="",
        quien="operador",
    )
    statuses = [c["status"] for c in reg2["confirmations"]]
    assert statuses == ["undone", "active"]
    assert reg2["confirmations"][0]["undone_reason"] == "montos_cambiaron"
    assert entry2["monto_sin_aplicar"] == "12688.00"


@pytest.mark.parametrize("bank,cash", [(100, 100), (100, 120), (None, 10)])
def test_confirmacion_solo_si_banco_mayor(bank, cash):
    with pytest.raises(DecisionsRegistryError) as exc:
        add_confirmation(
            _registry(),
            key="k",
            credits=["1"],
            clientes={},
            fecha_banco="2026-08-01",
            monto_banco=bank,
            monto_asientos=cash,
            nota="",
            quien="operador",
        )
    assert exc.value.error_code == "confirmation_not_applicable"


def test_asiento_no_usado_sin_duplicados_y_cierre():
    reg, entry = add_unused_asiento(
        _registry(),
        path="/clientes/X/CREDITO # 87/ASIENTOS/4700.pdf/",
        credito_carpeta="CREDITO # 087",
        nota="Asiento del crédito 90",
        quien="operador",
    )
    assert entry["path"] == "clientes/X/CREDITO # 87/ASIENTOS/4700.pdf"
    assert entry["credito_carpeta"] == "87"
    reg2, same = add_unused_asiento(
        reg, path="CLIENTES/X/CREDITO # 87/ASIENTOS/4700.PDF", credito_carpeta="87", nota="", quien="x"
    )
    assert same is not None and len(unused_asientos(reg2)) == 1
    closed = record_closure(
        reg2,
        estado="CERRADO_AMORTIZACION_INCOMPLETA",
        creditos_sin_amortizar=[{"credito": "133", "motivo": "Falta el asiento de Contabilidad"}],
    )
    assert closed["closure"]["estado"] == "CERRADO_AMORTIZACION_INCOMPLETA"
    assert reg2["closure"] is None


def test_normalize_registry_tolera_formato_parcial():
    reg = normalize_registry({"process_key": PK, "exclusions": [{"status": "active"}, "basura"]})
    assert reg["exclusions"] == [{"status": "active"}]
    assert reg["confirmations"] == [] and reg["assignments"] == [] and reg["closure"] is None
    with pytest.raises(ValueError):
        normalize_registry([])


def test_group_key_ordena_numericamente():
    assert group_key_for_credits(["133", "CREDITO # 102", "95"]) == "95+102+133"


# --- persistencia ------------------------------------------------------------------


def _path() -> str:
    return f"LOGS/2026/08/01/{registry_filename('banco_bogota', '2026-08-01', PK)}"


def test_mutate_crea_archivo_y_luego_usa_if_match():
    drive = FakeDrive()
    path = _path()
    loaded, entry = asyncio.run(
        mutate_registry(
            drive, "s", "d", path=path, process_key=PK, bank_code="banco_bogota",
            report_date_iso="2026-08-01", mutate=lambda r: _exclude(r),
        )
    )
    assert entry["credits"] == ["102", "133"]
    assert drive.puts == [(path, None)]
    stored = json.loads(drive.files[path].decode("utf-8"))
    assert stored["process_key"] == PK and stored["kind"] == "amortization_decisions"

    reg_mod.clear_registry_cache()
    asyncio.run(
        mutate_registry(
            drive, "s", "d", path=path, process_key=PK, bank_code="banco_bogota",
            report_date_iso="2026-08-01",
            mutate=lambda r: undo_exclusion(r, credit="102", quien="operador"),
        )
    )
    assert drive.puts[-1] == (path, "etag-1")


def test_mutate_reintenta_conflicto_412():
    drive = FakeDrive()
    path = _path()
    asyncio.run(
        mutate_registry(
            drive, "s", "d", path=path, process_key=PK, bank_code="banco_bogota",
            report_date_iso="2026-08-01", mutate=lambda r: _exclude(r),
        )
    )
    drive.conflicts_left = 1
    reg_mod.clear_registry_cache()
    asyncio.run(
        mutate_registry(
            drive, "s", "d", path=path, process_key=PK, bank_code="banco_bogota",
            report_date_iso="2026-08-01",
            mutate=lambda r: undo_exclusion(r, credit="102", quien="operador"),
        )
    )
    stored = json.loads(drive.files[path].decode("utf-8"))
    assert active_exclusions(stored) == []


def test_mutate_rechaza_registro_de_otro_proceso():
    drive = FakeDrive()
    path = _path()
    other = empty_registry(process_key=PK_OTHER, bank_code="banco_bogota", report_date_iso="2026-07-31")
    drive.files[path] = json.dumps(other).encode("utf-8")
    drive.etags[path] = "e0"
    with pytest.raises(DecisionsRegistryError) as exc:
        asyncio.run(
            mutate_registry(
                drive, "s", "d", path=path, process_key=PK, bank_code="banco_bogota",
                report_date_iso="2026-08-01", mutate=lambda r: _exclude(r),
            )
        )
    assert exc.value.error_code == "decisions_registry_process_mismatch"


def test_load_for_process_ruta_vacia_o_de_otro_proceso_se_ignora():
    drive = FakeDrive()
    assert asyncio.run(load_registry_for_process(drive, "s", "d", registry_path="", process_key=PK)) is None
    stale = f"LOGS/2026/07/31/{registry_filename('banco_bogota', '2026-07-31', PK_OTHER)}"
    assert (
        asyncio.run(load_registry_for_process(drive, "s", "d", registry_path=stale, process_key=PK))
        is None
    )


def test_load_for_process_fail_closed_si_la_ruta_existe_y_no_se_lee():
    drive = FakeDrive()
    path = _path()
    with pytest.raises(DecisionsRegistryUnavailableError):
        asyncio.run(load_registry_for_process(drive, "s", "d", registry_path=path, process_key=PK))
    drive.files[path] = json.dumps(_registry()).encode("utf-8")
    drive.etags[path] = "e1"
    drive.fail_get_bytes = RuntimeError("timeout")
    with pytest.raises(DecisionsRegistryUnavailableError):
        asyncio.run(load_registry_for_process(drive, "s", "d", registry_path=path, process_key=PK))
    drive.fail_get_bytes = None
    reg_mod.clear_registry_cache()
    data = asyncio.run(load_registry_for_process(drive, "s", "d", registry_path=path, process_key=PK))
    assert data is not None and data["process_key"] == PK
