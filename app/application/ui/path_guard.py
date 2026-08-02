"""Guardas de path para lecturas UI: no escapar de raíces del ambiente activo."""
from __future__ import annotations

import os
from dataclasses import dataclass

from app.application.config.payment_validation_settings import (
    get_payment_validation_paths,
    list_payment_banks,
    resolve_bank_control_file_path,
    resolve_bank_input_file_path,
    resolve_followup_workbook_path,
)
from app.application.config.payment_validation_settings import DEFAULT_FOLLOWUP_ADELANTADOS
from app.application.ui.environment import resolve_active_environment


class UiPathEscapeError(ValueError):
    """Path fuera de las raíces permitidas del ambiente activo."""

    def __init__(self, path: str, reason: str) -> None:
        self.path = path
        self.reason = reason
        super().__init__(reason)


def _norm(path: str) -> str:
    text = str(path or "").replace("\\", "/").strip().strip("/")
    while "//" in text:
        text = text.replace("//", "/")
    return text


def _is_under(path: str, root: str) -> bool:
    p = _norm(path).lower()
    r = _norm(root).lower()
    if not p or not r:
        return False
    return p == r or p.startswith(r + "/")


@dataclass(frozen=True)
class UiAllowedRoots:
    environment: str
    roots: tuple[str, ...]


def collect_allowed_roots_from_env() -> UiAllowedRoots:
    """Raíces permitidas derivadas del overlay activo (sin hardcode sandbox/prod)."""
    env = resolve_active_environment()
    roots: list[str] = []

    def add(raw: str | None) -> None:
        n = _norm(raw or "")
        if n and n not in roots:
            roots.append(n)

    add(os.getenv("GRAPH_CLIENTS_BASE_PATH"))
    add(os.getenv("PAYMENT_VALIDATION_BASE_FOLDER"))
    add(os.getenv("GRAPH_SHAREPOINT_FILE_PATH"))
    # Carpeta padre del Excel banco / followups / IBR / correos
    for key in (
        "GRAPH_VALIDAR_NOTIFY_CORREOS_XLSX_PATH",
        "GRAPH_IBR_DIARIO_PATH",
        "GRAPH_FOLLOWUP_PAGOS_ADELANTADOS_PATH",
    ):
        add(os.getenv(key))
        parent = "/".join(_norm(os.getenv(key) or "").split("/")[:-1])
        add(parent)

    try:
        paths = get_payment_validation_paths()
        add(paths.base_folder)
        add(paths.control)
        add(paths.review)
        add(paths.historical)
        add(paths.logs)
        add(paths.email)
        add(paths.asientos)
        add(paths.archive)
    except Exception:
        pass

    try:
        for bank in list_payment_banks():
            add(resolve_bank_control_file_path(bank.bank_code))
            add(resolve_bank_input_file_path(bank.bank_code))
            parent = "/".join(_norm(resolve_bank_input_file_path(bank.bank_code)).split("/")[:-1])
            add(parent)
    except Exception:
        pass

    try:
        add(resolve_followup_workbook_path(DEFAULT_FOLLOWUP_ADELANTADOS))
    except Exception:
        pass

    return UiAllowedRoots(environment=env.environment, roots=tuple(roots))


def assert_path_allowed(relative_path: str, *, roots: UiAllowedRoots | None = None) -> str:
    """Fail-closed: rechaza path vacío, `..`, absolutos y escapes de raíces."""
    raw = str(relative_path or "").strip()
    if not raw:
        raise UiPathEscapeError(raw, "path_empty")
    if raw.startswith("/") or raw.startswith("\\") or ":" in raw[:3]:
        raise UiPathEscapeError(raw, "path_absolute_forbidden")
    if ".." in raw.replace("\\", "/").split("/"):
        raise UiPathEscapeError(raw, "path_traversal_forbidden")

    normalized = _norm(raw)
    bundle = roots or collect_allowed_roots_from_env()
    if not bundle.roots:
        raise UiPathEscapeError(
            normalized,
            "no_allowed_roots_configured",
        )
    if not any(_is_under(normalized, root) for root in bundle.roots):
        raise UiPathEscapeError(normalized, "path_outside_environment_roots")
    return normalized
