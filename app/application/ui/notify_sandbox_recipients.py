"""Destinatarios de prueba para Notify iniciado desde la UI (solo sandbox).

Fail-closed: sin ``UI_NOTIFY_SANDBOX_TO`` no se habilita Notify UI aunque
``UI_NOTIFY_ENABLED=true``. Power Automate no usa este override.
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def _parse_email_list(raw: str) -> tuple[str, ...]:
    """Separa por coma/punto y coma; deduplica preservando orden; ignora inválidos."""
    text = (raw or "").strip()
    if not text:
        return ()
    seen: set[str] = set()
    out: list[str] = []
    for part in re.split(r"[;,]", text):
        email = part.strip()
        if not email:
            continue
        key = email.lower()
        if key in seen:
            continue
        if not _EMAIL_RE.match(email):
            continue
        seen.add(key)
        out.append(email)
    return tuple(out)


@dataclass(frozen=True)
class NotifySandboxRecipients:
    to: tuple[str, ...]
    cc: tuple[str, ...]

    @property
    def configured(self) -> bool:
        """TO no vacío = destinatarios de prueba listos (fail-closed si vacío)."""
        return len(self.to) > 0

    def to_override_csv(self) -> str:
        return "; ".join(self.to)

    def cc_override_csv(self) -> str | None:
        if not self.cc:
            return None
        return "; ".join(self.cc)


def get_ui_notify_sandbox_recipients() -> NotifySandboxRecipients:
    """Lee env; default vacío. No expone valores a la SPA (solo el bool configured)."""
    return NotifySandboxRecipients(
        to=_parse_email_list(os.getenv("UI_NOTIFY_SANDBOX_TO") or ""),
        cc=_parse_email_list(os.getenv("UI_NOTIFY_SANDBOX_CC") or ""),
    )
