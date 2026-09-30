"""Registro de decisiones del operador por proceso (exclusiones, confirmaciones, asignaciones).

Un JSON por proceso en la misma carpeta fechada de trazabilidad del manifest de
consolidación (``…/YYYY/MM/YYYY-MM-DD/decisiones_{banco}_{fecha}_{id8}.json``).
Control guarda solo la ruta (``DecisionsRegistryPath``).

Las entradas nunca se borran: deshacer marca ``status="undone"`` y conserva el historial.
Fase 3 (consolidar) registra exclusiones, confirmaciones, asignaciones asiento→pago,
asientos que no corresponden y tipo corregido; se bloquean al consolidar. Fase 4
(amortización) lo lee en cada simulación y respeta esas decisiones.
"""

from __future__ import annotations

import asyncio
import copy
import json
import logging
import posixpath
import time
import uuid
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any

import httpx

from app.application.config.payment_validation_settings import resolve_logs_folder_path
from app.application.services.colombia_time import now_colombia_iso
from app.application.services.dated_artifact_layout import (
    ensure_parent_folders,
    join_dated_artifact_path,
    short_process_id,
)
from app.application.services.review_schema import normalize_credito_digits
from app.application.sharepoint_resolution import encode_graph_drive_path
from app.domain.ports.graph import GraphApiPort

logger = logging.getLogger(__name__)

REGISTRY_SCHEMA_VERSION = 1
REGISTRY_KIND = "amortization_decisions"
CONTROL_COLUMN = "DecisionsRegistryPath"

STATUS_ACTIVE = "active"
STATUS_UNDONE = "undone"

FASE_AMORTIZACION = "amortizacion"
FASE_CONSOLIDACION = "consolidacion"

MOTIVOS_NO_USADO: dict[str, str] = {
    "OTRO_CREDITO": "Asiento de otro crédito",
    "PAGO_ANTERIOR": "Asiento de un pago anterior",
    "NO_CORRESPONDE": "No corresponde a este pago",
}

MOTIVO_OTRO = "OTRO"
MOTIVOS_EXCLUSION: dict[str, str] = {
    "FALTA_ASIENTO": "Falta el asiento de Contabilidad",
    "ASIENTO_CON_ERROR": "Asiento con error, pendiente de corrección",
    "TABLA_CON_ERROR": "Tabla de amortización con error",
    "APLICACION_MANUAL": "Se aplicará manualmente",
    MOTIVO_OTRO: "Otro",
}
NOTA_MAX_LEN = 300

_CENT = Decimal("0.01")
_CACHE_TTL_SECONDS = 20.0


class DecisionsRegistryError(Exception):
    """Error de negocio al modificar el registro (mensaje apto para el operador)."""

    def __init__(self, error_code: str, user_message: str, *, status_code: int = 409) -> None:
        super().__init__(error_code)
        self.error_code = error_code
        self.user_message = user_message
        self.status_code = status_code


class DecisionsRegistryUnavailableError(Exception):
    """El registro declarado en Control no se pudo leer (fail-closed)."""

    def __init__(self, path: str, reason: str) -> None:
        super().__init__(f"decisions_registry_unavailable|{path}|{reason}")
        self.path = path
        self.reason = reason


def credit_token(value: Any) -> str:
    raw = str(value or "").strip()
    return normalize_credito_digits(raw) or raw


def money(value: Any) -> Decimal | None:
    if value is None or value == "":
        return None
    try:
        return Decimal(str(value)).quantize(_CENT)
    except (InvalidOperation, ValueError):
        return None


def money_str(value: Any) -> str:
    amount = money(value)
    return format(amount, "f") if amount is not None else ""


def group_key_for_credits(credits: list[str] | tuple[str, ...] | set[str]) -> str:
    tokens = sorted({credit_token(c) for c in credits if credit_token(c)}, key=_credit_sort_key)
    return "+".join(tokens)


def _credit_sort_key(token: str) -> tuple[int, int | str]:
    return (0, int(token)) if token.isdigit() else (1, token)


def conciliation_key(group_key: str, fecha_banco: str) -> str:
    return f"{group_key}|{(fecha_banco or '').strip()}"


def _process_short_id(process_key: str) -> str:
    """Id corto del lote (último segmento del ProcessKey; misma regla que otros artefactos)."""
    parts = [p.strip() for p in str(process_key or "").split("|") if p.strip()]
    return short_process_id(parts[-1] if len(parts) >= 4 else str(process_key or ""))


def registry_filename(bank_code: str, report_date_iso: str, process_key: str) -> str:
    return f"decisiones_{bank_code}_{report_date_iso}_{_process_short_id(process_key)}.json"


def registry_path_belongs_to(path: str, process_key: str) -> bool:
    """El nombre del registro termina con el id corto del proceso."""
    name = posixpath.basename(str(path or "").strip().strip("/"))
    return name.endswith(f"_{_process_short_id(process_key)}.json")


def resolve_registry_path(
    *,
    bank_code: str,
    report_date_iso: str,
    process_key: str,
    merge_manifest_path: str = "",
) -> str:
    """Misma carpeta de trazabilidad del manifest; si falta, carpeta fechada de logs."""
    name = registry_filename(bank_code, report_date_iso, process_key)
    manifest = (merge_manifest_path or "").strip().strip("/")
    if manifest and "/" in manifest:
        return f"{posixpath.dirname(manifest)}/{name}"
    return join_dated_artifact_path(resolve_logs_folder_path(), report_date_iso, name)


def empty_registry(*, process_key: str, bank_code: str, report_date_iso: str) -> dict[str, Any]:
    now = now_colombia_iso()
    return {
        "schema_version": REGISTRY_SCHEMA_VERSION,
        "kind": REGISTRY_KIND,
        "process_key": process_key,
        "bank_code": bank_code,
        "report_date_iso": report_date_iso,
        "created_at": now,
        "updated_at": now,
        "exclusions": [],
        "confirmations": [],
        "assignments": [],
        "asientos_no_usados": [],
        "tipo_corrections": [],
        "closure": None,
    }


_LIST_KEYS = ("exclusions", "confirmations", "assignments", "asientos_no_usados", "tipo_corrections")


def normalize_registry(raw: Any) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise ValueError("decisions_registry_invalid")
    out = dict(raw)
    for key in _LIST_KEYS:
        value = out.get(key)
        out[key] = [dict(v) for v in value if isinstance(v, dict)] if isinstance(value, list) else []
    out.setdefault("closure", None)
    return out


# --- consultas -------------------------------------------------------------


def active_exclusions(registry: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not registry:
        return []
    return [e for e in registry.get("exclusions") or [] if e.get("status") == STATUS_ACTIVE]


def active_confirmations(registry: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not registry:
        return []
    return [c for c in registry.get("confirmations") or [] if c.get("status") == STATUS_ACTIVE]


def excluded_credit_tokens(registry: dict[str, Any] | None) -> set[str]:
    out: set[str] = set()
    for exc in active_exclusions(registry):
        for cred in exc.get("credits") or []:
            tok = credit_token(cred)
            if tok:
                out.add(tok)
    return out


def exclusion_for_credit(registry: dict[str, Any] | None, credit: str) -> dict[str, Any] | None:
    tok = credit_token(credit)
    for exc in active_exclusions(registry):
        if tok in {credit_token(c) for c in exc.get("credits") or []}:
            return exc
    return None


def find_confirmation(
    registry: dict[str, Any] | None,
    *,
    key: str,
    monto_banco: Any,
    monto_asientos: Any,
) -> dict[str, Any] | None:
    """Confirmación vigente solo si banco y asientos no cambiaron desde que se confirmó."""
    bank = money_str(monto_banco)
    cash = money_str(monto_asientos)
    for conf in active_confirmations(registry):
        if str(conf.get("conciliation_key") or "") != key:
            continue
        if money_str(conf.get("monto_banco")) == bank and money_str(conf.get("monto_asientos")) == cash:
            return conf
    return None


def explicit_assignments(registry: dict[str, Any] | None) -> list[dict[str, Any]]:
    """Asignaciones asiento→pago decididas por el operador (Entrega 2)."""
    if not registry:
        return []
    return [a for a in registry.get("assignments") or [] if a.get("status", STATUS_ACTIVE) == STATUS_ACTIVE]


def unused_asientos(registry: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not registry:
        return []
    return [
        a
        for a in registry.get("asientos_no_usados") or []
        if a.get("status", STATUS_ACTIVE) == STATUS_ACTIVE and str(a.get("path") or "").strip()
    ]


# --- mutaciones (puras, sobre copia) --------------------------------------------


def _touch(registry: dict[str, Any]) -> None:
    registry["updated_at"] = now_colombia_iso()


def resolve_motivo(motivo_codigo: str, nota: str) -> tuple[str, str, str]:
    code = str(motivo_codigo or "").strip().upper()
    if code not in MOTIVOS_EXCLUSION:
        raise DecisionsRegistryError(
            "exclusion_reason_invalid",
            "Seleccione un motivo de exclusión de la lista.",
            status_code=422,
        )
    note = str(nota or "").strip()
    if len(note) > NOTA_MAX_LEN:
        raise DecisionsRegistryError(
            "decision_note_too_long",
            "La nota es demasiado larga. Resúmala en pocas palabras.",
            status_code=422,
        )
    if code == MOTIVO_OTRO and not note:
        raise DecisionsRegistryError(
            "exclusion_reason_text_required",
            "Escriba el motivo de la exclusión.",
            status_code=422,
        )
    label = note if code == MOTIVO_OTRO else MOTIVOS_EXCLUSION[code]
    return code, label, note


def add_exclusion(
    registry: dict[str, Any],
    *,
    credits: list[str],
    clientes: dict[str, str],
    id_pagos: list[str],
    tablas: dict[str, str],
    motivo_codigo: str,
    nota: str,
    quien: str,
    issue_codes: list[str] | None = None,
    fase: str = FASE_AMORTIZACION,
    asientos_dirs: dict[str, str] | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Agrega (o devuelve la vigente) exclusión del grupo. Idempotente por grupo."""
    tokens = sorted({credit_token(c) for c in credits if credit_token(c)}, key=_credit_sort_key)
    if not tokens:
        raise DecisionsRegistryError(
            "exclusion_credit_required", "Indique el crédito a excluir.", status_code=422
        )
    code, label, note = resolve_motivo(motivo_codigo, nota)
    out = copy.deepcopy(registry)
    for exc in active_exclusions(out):
        existing = {credit_token(c) for c in exc.get("credits") or []}
        if existing & set(tokens):
            return out, exc
    entry = {
        "exclusion_id": uuid.uuid4().hex[:12],
        "status": STATUS_ACTIVE,
        "credits": tokens,
        "group_key": group_key_for_credits(tokens),
        "clientes": {t: str(clientes.get(t) or "").strip() for t in tokens},
        "id_pagos": sorted({str(p).strip() for p in id_pagos if str(p).strip()}),
        "tablas": {t: str(tablas.get(t) or "").strip().strip("/") for t in tokens},
        "motivo_codigo": code,
        "motivo": label,
        "nota": note,
        "quien": quien,
        "cuando": now_colombia_iso(),
        "fase": fase,
        "issue_codes": sorted({str(c) for c in issue_codes or [] if str(c).strip()}),
        "locked_at": None,
        "locked_attempt_id": None,
    }
    if asientos_dirs:
        entry["asientos_dirs"] = {
            t: str(asientos_dirs.get(t) or "").strip().strip("/") for t in tokens
        }
    out["exclusions"].append(entry)
    _touch(out)
    return out, entry


_LOCKED_GENERIC = "Esta decisión ya se aplicó; no se puede deshacer."


def _locked_message(entry: dict[str, Any], *, amortizacion: str) -> str:
    if entry.get("fase") == FASE_CONSOLIDACION:
        return "Los consolidados ya se generaron con esta decisión; no se puede deshacer."
    return amortizacion


def undo_exclusion(
    registry: dict[str, Any], *, credit: str, quien: str
) -> tuple[dict[str, Any], dict[str, Any] | None]:
    out = copy.deepcopy(registry)
    tok = credit_token(credit)
    for exc in active_exclusions(out):
        if tok not in {credit_token(c) for c in exc.get("credits") or []}:
            continue
        if exc.get("locked_at"):
            raise DecisionsRegistryError(
                "exclusion_locked",
                _locked_message(
                    exc,
                    amortizacion=(
                        "La amortización ya se procesó con este crédito excluido; "
                        "no se puede deshacer."
                    ),
                ),
            )
        exc["status"] = STATUS_UNDONE
        exc["undone_at"] = now_colombia_iso()
        exc["undone_by"] = quien
        _touch(out)
        return out, exc
    return out, None


def add_confirmation(
    registry: dict[str, Any],
    *,
    key: str,
    credits: list[str],
    clientes: dict[str, str],
    fecha_banco: str,
    monto_banco: Any,
    monto_asientos: Any,
    nota: str,
    quien: str,
    fase: str = FASE_AMORTIZACION,
    origen: str = "",
) -> tuple[dict[str, Any], dict[str, Any]]:
    note = str(nota or "").strip()
    if len(note) > NOTA_MAX_LEN:
        raise DecisionsRegistryError(
            "decision_note_too_long",
            "La nota es demasiado larga. Resúmala en pocas palabras.",
            status_code=422,
        )
    bank = money(monto_banco)
    cash = money(monto_asientos)
    if bank is None or cash is None or cash >= bank:
        raise DecisionsRegistryError(
            "confirmation_not_applicable",
            "Solo se puede continuar con los asientos cuando el banco recibió más que lo registrado.",
        )
    out = copy.deepcopy(registry)
    existing = find_confirmation(out, key=key, monto_banco=bank, monto_asientos=cash)
    if existing is not None:
        return out, existing
    for conf in active_confirmations(out):
        if str(conf.get("conciliation_key") or "") == key:
            conf["status"] = STATUS_UNDONE
            conf["undone_at"] = now_colombia_iso()
            conf["undone_by"] = quien
            conf["undone_reason"] = "montos_cambiaron"
    tokens = sorted({credit_token(c) for c in credits if credit_token(c)}, key=_credit_sort_key)
    entry = {
        "confirmation_id": uuid.uuid4().hex[:12],
        "status": STATUS_ACTIVE,
        "conciliation_key": key,
        "credits": tokens,
        "clientes": {t: str(clientes.get(t) or "").strip() for t in tokens},
        "fecha_banco": fecha_banco,
        "monto_banco": format(bank, "f"),
        "monto_asientos": format(cash, "f"),
        "monto_sin_aplicar": format(bank - cash, "f"),
        "nota": note,
        "quien": quien,
        "cuando": now_colombia_iso(),
        "fase": fase,
        "locked_at": None,
    }
    if origen:
        entry["origen"] = origen
    out["confirmations"].append(entry)
    _touch(out)
    return out, entry


def undo_confirmation(
    registry: dict[str, Any], *, key: str, quien: str
) -> tuple[dict[str, Any], dict[str, Any] | None]:
    out = copy.deepcopy(registry)
    for conf in active_confirmations(out):
        if str(conf.get("conciliation_key") or "") != key:
            continue
        if conf.get("locked_at"):
            raise DecisionsRegistryError(
                "confirmation_locked",
                _locked_message(
                    conf,
                    amortizacion=(
                        "La amortización ya se procesó con esta confirmación; "
                        "no se puede deshacer."
                    ),
                ),
            )
        conf["status"] = STATUS_UNDONE
        conf["undone_at"] = now_colombia_iso()
        conf["undone_by"] = quien
        _touch(out)
        return out, conf
    return out, None


def add_unused_asiento(
    registry: dict[str, Any],
    *,
    path: str,
    credito_carpeta: str,
    nota: str,
    quien: str,
    motivo_codigo: str = "",
    fase: str = FASE_AMORTIZACION,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Asiento que no corresponde: al cerrar va a PROCESADOS/NO USADOS (nunca se elimina)."""
    norm = str(path or "").strip().strip("/")
    if not norm:
        raise DecisionsRegistryError(
            "unused_asiento_path_required", "Indique el asiento.", status_code=422
        )
    code = str(motivo_codigo or "").strip().upper()
    if code and code not in MOTIVOS_NO_USADO:
        raise DecisionsRegistryError(
            "unused_asiento_reason_invalid", "Motivo no válido para el asiento.", status_code=422
        )
    out = copy.deepcopy(registry)
    for entry in unused_asientos(out):
        if str(entry.get("path") or "").strip().strip("/").casefold() == norm.casefold():
            return out, entry
    note = str(nota or "").strip()[:NOTA_MAX_LEN] or MOTIVOS_NO_USADO.get(code, "")
    entry = {
        "path": norm,
        "status": STATUS_ACTIVE,
        "credito_carpeta": credit_token(credito_carpeta),
        "nota": note,
        "quien": quien,
        "cuando": now_colombia_iso(),
        "fase": fase,
        "locked_at": None,
    }
    if code:
        entry["motivo_codigo"] = code
        entry["motivo"] = MOTIVOS_NO_USADO[code]
    out["asientos_no_usados"].append(entry)
    _touch(out)
    return out, entry


def undo_unused_asiento(
    registry: dict[str, Any], *, path: str, quien: str
) -> tuple[dict[str, Any], dict[str, Any] | None]:
    norm = str(path or "").strip().strip("/").casefold()
    out = copy.deepcopy(registry)
    for entry in unused_asientos(out):
        if str(entry.get("path") or "").strip().strip("/").casefold() != norm:
            continue
        if entry.get("locked_at"):
            raise DecisionsRegistryError(
                "unused_asiento_locked", _locked_message(entry, amortizacion=_LOCKED_GENERIC)
            )
        entry["status"] = STATUS_UNDONE
        entry["undone_at"] = now_colombia_iso()
        entry["undone_by"] = quien
        _touch(out)
        return out, entry
    return out, None


def unused_asiento_paths(registry: dict[str, Any] | None) -> set[str]:
    """Rutas normalizadas (casefold) de asientos marcados como no usados."""
    return {str(a.get("path") or "").strip().strip("/").casefold() for a in unused_asientos(registry)}


# --- asignaciones asiento → pago (fase 3) ---------------------------------------


def group_assignments(registry: dict[str, Any] | None, group_key: str) -> list[dict[str, Any]]:
    return [a for a in explicit_assignments(registry) if str(a.get("group_key") or "") == group_key]


def set_group_assignments(
    registry: dict[str, Any],
    *,
    group_key: str,
    items: list[dict[str, Any]],
    quien: str,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Reemplaza la asignación vigente del grupo (la anterior queda en el historial)."""
    if not items:
        raise DecisionsRegistryError(
            "assignment_empty", "Asigne cada asiento a un pago.", status_code=422
        )
    out = copy.deepcopy(registry)
    now = now_colombia_iso()
    previous = group_assignments(out, group_key)
    if previous and _same_assignment(previous, items):
        return out, previous
    for entry in previous:
        if entry.get("locked_at"):
            raise DecisionsRegistryError(
                "assignment_locked", _locked_message(entry, amortizacion=_LOCKED_GENERIC)
            )
    for entry in previous:
        entry["status"] = STATUS_UNDONE
        entry["undone_at"] = now
        entry["undone_by"] = quien
        entry["undone_reason"] = "modificada"
    assignment_id = uuid.uuid4().hex[:12]
    created: list[dict[str, Any]] = []
    for item in items:
        entry = {
            "assignment_id": assignment_id,
            "status": STATUS_ACTIVE,
            "group_key": group_key,
            "credito": credit_token(item.get("credito")),
            "asiento_pdf_path": str(item.get("asiento_pdf_path") or "").strip().strip("/"),
            "id_pago": str(item.get("id_pago") or "").strip(),
            "fecha_banco": str(item.get("fecha_banco") or "").strip(),
            "quien": quien,
            "cuando": now,
            "fase": FASE_CONSOLIDACION,
            "locked_at": None,
        }
        out["assignments"].append(entry)
        created.append(entry)
    _touch(out)
    return out, created


def _same_assignment(previous: list[dict[str, Any]], items: list[dict[str, Any]]) -> bool:
    def _key(a: dict[str, Any]) -> tuple[str, str]:
        return (
            str(a.get("asiento_pdf_path") or "").strip().strip("/").casefold(),
            str(a.get("id_pago") or "").strip(),
        )

    return sorted(map(_key, previous)) == sorted(map(_key, items))


def undo_group_assignments(
    registry: dict[str, Any], *, group_key: str, quien: str
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    out = copy.deepcopy(registry)
    current = group_assignments(out, group_key)
    for entry in current:
        if entry.get("locked_at"):
            raise DecisionsRegistryError(
                "assignment_locked", _locked_message(entry, amortizacion=_LOCKED_GENERIC)
            )
    now = now_colombia_iso()
    for entry in current:
        entry["status"] = STATUS_UNDONE
        entry["undone_at"] = now
        entry["undone_by"] = quien
    if current:
        _touch(out)
    return out, current


# --- tipo de aplicación corregido (fase 3, ya no se usa) ----------------------------
# Los registros de lotes anteriores pueden traer correcciones; se conservan y se bloquean
# al consolidar, pero el tipo aplicado es siempre el del Excel de revisión.


def active_tipo_corrections(registry: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not registry:
        return []
    return [t for t in registry.get("tipo_corrections") or [] if t.get("status") == STATUS_ACTIVE]


def lock_consolidation_decisions(
    registry: dict[str, Any], *, attempt_id: str
) -> tuple[dict[str, Any], bool]:
    """Al consolidar: las decisiones de fase 3 vigentes dejan de poder deshacerse."""
    out = copy.deepcopy(registry)
    now = now_colombia_iso()
    changed = False
    entries = (
        active_exclusions(out)
        + active_confirmations(out)
        + explicit_assignments(out)
        + unused_asientos(out)
        + active_tipo_corrections(out)
    )
    for entry in entries:
        if entry.get("fase") != FASE_CONSOLIDACION or entry.get("locked_at"):
            continue
        entry["locked_at"] = now
        entry["locked_attempt_id"] = attempt_id
        changed = True
    if changed:
        _touch(out)
    return out, changed


def lock_active_decisions(
    registry: dict[str, Any], *, attempt_id: str, ids: set[str] | None = None
) -> tuple[dict[str, Any], bool]:
    """Al procesar la amortización: las decisiones vigentes dejan de poder deshacerse.

    ``ids``: solo las decisiones que usó esa ejecución (una tomada mientras procesaba
    sigue pudiendo deshacerse).
    """
    out = copy.deepcopy(registry)
    now = now_colombia_iso()
    changed = False
    for entry in active_exclusions(out) + active_confirmations(out):
        if entry.get("locked_at"):
            continue
        entry_id = str(entry.get("exclusion_id") or entry.get("confirmation_id") or "")
        if ids is not None and entry_id not in ids:
            continue
        entry["locked_at"] = now
        entry["locked_attempt_id"] = attempt_id
        changed = True
    if changed:
        _touch(out)
    return out, changed


def record_closure(
    registry: dict[str, Any],
    *,
    estado: str,
    creditos_sin_amortizar: list[dict[str, Any]],
    asiento_moves: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    out = copy.deepcopy(registry)
    out["closure"] = {
        "estado": estado,
        "cuando": now_colombia_iso(),
        "creditos_sin_amortizar": creditos_sin_amortizar,
        "movimientos_asientos": list(asiento_moves or []),
    }
    _touch(out)
    return out


# --- persistencia SharePoint ------------------------------------------------------


def _content_endpoint(site_id: str, drive_id: str, path: str) -> str:
    return f"/sites/{site_id}/drives/{drive_id}/root:/{encode_graph_drive_path(path)}:/content"


def _item_endpoint(site_id: str, drive_id: str, path: str) -> str:
    return f"/sites/{site_id}/drives/{drive_id}/root:/{encode_graph_drive_path(path)}"


def _is_not_found(exc: BaseException) -> bool:
    if isinstance(exc, FileNotFoundError):
        return True
    if isinstance(exc, httpx.HTTPStatusError):
        return bool(exc.response is not None and exc.response.status_code == 404)
    return False


def _is_precondition_failed(exc: BaseException) -> bool:
    return bool(
        isinstance(exc, httpx.HTTPStatusError)
        and exc.response is not None
        and exc.response.status_code == 412
    )


@dataclass
class LoadedRegistry:
    path: str
    data: dict[str, Any] | None
    etag: str | None


_cache: dict[str, tuple[float, LoadedRegistry]] = {}
_locks: dict[str, asyncio.Lock] = {}


def _cache_get(path: str) -> LoadedRegistry | None:
    hit = _cache.get(path)
    if hit is None:
        return None
    stamp, loaded = hit
    if time.monotonic() - stamp > _CACHE_TTL_SECONDS:
        _cache.pop(path, None)
        return None
    return LoadedRegistry(path=loaded.path, data=copy.deepcopy(loaded.data), etag=loaded.etag)


def _cache_put(loaded: LoadedRegistry) -> None:
    _cache[loaded.path] = (
        time.monotonic(),
        LoadedRegistry(path=loaded.path, data=copy.deepcopy(loaded.data), etag=loaded.etag),
    )


def clear_registry_cache() -> None:
    _cache.clear()


def registry_lock(path: str) -> asyncio.Lock:
    lock = _locks.get(path)
    if lock is None:
        lock = asyncio.Lock()
        _locks[path] = lock
    return lock


async def load_registry(
    graph: GraphApiPort,
    site_id: str,
    drive_id: str,
    path: str,
    *,
    use_cache: bool = False,
) -> LoadedRegistry:
    """Lee el registro. ``data=None`` si el archivo no existe; otros errores se propagan."""
    rel = (path or "").strip().strip("/")
    if not rel:
        return LoadedRegistry(path="", data=None, etag=None)
    if use_cache:
        cached = _cache_get(rel)
        if cached is not None:
            return cached
    etag: str | None = None
    try:
        meta = await graph.get(_item_endpoint(site_id, drive_id, rel))
        if isinstance(meta, dict):
            etag = str(meta.get("eTag") or meta.get("etag") or "").strip() or None
    except Exception as exc:
        if _is_not_found(exc):
            loaded = LoadedRegistry(path=rel, data=None, etag=None)
            _cache_put(loaded)
            return loaded
        logger.debug("decisions registry metadata no disponible %s: %s", rel, exc)
    try:
        raw = await graph.get_bytes(_content_endpoint(site_id, drive_id, rel))
    except Exception as exc:
        if _is_not_found(exc):
            loaded = LoadedRegistry(path=rel, data=None, etag=None)
            _cache_put(loaded)
            return loaded
        raise
    data = normalize_registry(json.loads(bytes(raw).decode("utf-8")))
    loaded = LoadedRegistry(path=rel, data=data, etag=etag)
    _cache_put(loaded)
    return loaded


async def save_registry(
    graph: GraphApiPort,
    site_id: str,
    drive_id: str,
    path: str,
    data: dict[str, Any],
    *,
    etag: str | None,
) -> LoadedRegistry:
    rel = (path or "").strip().strip("/")
    body = json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8")
    if etag is None:
        await ensure_parent_folders(graph, site_id, drive_id, rel)
    resp = await graph.put_bytes(
        _content_endpoint(site_id, drive_id, rel),
        body,
        content_type="application/json",
        if_match=etag,
    )
    new_etag = None
    if isinstance(resp, dict):
        new_etag = str(resp.get("eTag") or resp.get("etag") or "").strip() or None
    loaded = LoadedRegistry(path=rel, data=copy.deepcopy(data), etag=new_etag)
    _cache_put(loaded)
    return loaded


async def mutate_registry(
    graph: GraphApiPort,
    site_id: str,
    drive_id: str,
    *,
    path: str,
    process_key: str,
    bank_code: str,
    report_date_iso: str,
    mutate,
    attempts: int = 3,
) -> tuple[LoadedRegistry, Any]:
    """Lee → aplica ``mutate(registry) -> (nuevo, resultado)`` → guarda con If-Match (reintenta 412)."""
    rel = (path or "").strip().strip("/")
    async with registry_lock(rel):
        last_exc: BaseException | None = None
        for _ in range(max(1, attempts)):
            loaded = await load_registry(graph, site_id, drive_id, rel)
            current = loaded.data
            if current is not None and str(current.get("process_key") or "") not in ("", process_key):
                raise DecisionsRegistryError(
                    "decisions_registry_process_mismatch",
                    "El registro de decisiones pertenece a otro proceso. Actualice la página.",
                )
            if current is None:
                current = empty_registry(
                    process_key=process_key, bank_code=bank_code, report_date_iso=report_date_iso
                )
            new_data, result = mutate(current)
            if new_data == current and loaded.data is not None:
                return loaded, result
            try:
                saved = await save_registry(graph, site_id, drive_id, rel, new_data, etag=loaded.etag)
                return saved, result
            except Exception as exc:
                if _is_precondition_failed(exc):
                    _cache.pop(rel, None)
                    last_exc = exc
                    continue
                raise
        raise DecisionsRegistryError(
            "decisions_registry_conflict",
            "Otro usuario modificó las decisiones al mismo tiempo. Vuelva a intentar.",
        ) from last_exc


async def load_registry_for_process(
    graph: GraphApiPort,
    site_id: str,
    drive_id: str,
    *,
    registry_path: str,
    process_key: str,
    use_cache: bool = False,
) -> dict[str, Any] | None:
    """Registro del proceso declarado en Control (fail-closed si la ruta existe y no se lee)."""
    rel = (registry_path or "").strip().strip("/")
    if not rel:
        return None
    if process_key and not registry_path_belongs_to(rel, process_key):
        # Ruta heredada de un proceso anterior del banco (Control no se limpió).
        logger.info("decisions registry de otro proceso ignorado path=%s", rel)
        return None
    try:
        loaded = await load_registry(graph, site_id, drive_id, rel, use_cache=use_cache)
    except Exception as exc:
        raise DecisionsRegistryUnavailableError(rel, type(exc).__name__) from exc
    if loaded.data is None:
        raise DecisionsRegistryUnavailableError(rel, "not_found")
    owner = str(loaded.data.get("process_key") or "").strip()
    if owner and process_key and owner != process_key:
        logger.warning(
            "decisions registry de otro proceso ignorado path=%s owner=%s current=%s",
            rel,
            owner,
            process_key,
        )
        return None
    return loaded.data
