"""Guardrail: la SPA Azure no debe arrancar con mocks efectivos."""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_client_mocks_only_with_exact_true() -> None:
    src = (ROOT / "frontend" / "src" / "api" / "client.ts").read_text(encoding="utf-8")
    # Opt-in estricto: === "true" (no el antiguo !== "false").
    assert '===\n  "true"' in src or '=== "true"' in src.replace("\r\n", "\n")
    assert '!==\n  "false"' not in src.replace("\r\n", "\n")
    assert '!== "false"' not in src
    # Comentario de intención fail-closed.
    assert "opt-in" in src.lower() or "Mocks solo" in src


def test_azure_package_script_forces_vite_mocks_false() -> None:
    script = (ROOT / "scripts" / "build-azure-package.ps1").read_text(encoding="utf-8")
    assert re.search(
        r'\$env:VITE_UI_USE_MOCKS\s*=\s*"false"',
        script,
    ), "build-azure-package.ps1 debe forzar VITE_UI_USE_MOCKS=false"


def test_production_spa_bundle_calls_bootstrap_when_built() -> None:
    """Si existe dist local (build reciente), debe hablar con bootstrap real."""
    dist_assets = ROOT / "frontend" / "dist" / "assets"
    if not dist_assets.is_dir():
        # Sin dist: el script Azure y el source ya están cubiertos arriba.
        return
    js_files = list(dist_assets.glob("*.js"))
    assert js_files, "dist/assets sin JS"
    joined = "\n".join(p.read_text(encoding="utf-8", errors="ignore") for p in js_files)
    assert "/api/ui/v1/bootstrap" in joined
    # Bootstrap mock efectivo hardcodeado como única fuente (login_required:!1 + auth mock)
    # no debe ser el camino por defecto: el bundle real debe poder pedir bootstrap.
    assert "local_session" in joined or "/api/ui/v1/auth/login" in joined
