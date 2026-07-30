"""Contrato: paths de ZIP siempre se validan con '/'."""
from __future__ import annotations

import importlib.util
from pathlib import Path


def _load_normalize():
    path = Path("scripts/zip_path_normalize.py")
    spec = importlib.util.spec_from_file_location("zip_path_normalize", path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.normalize_zip_entry_path


def test_normalize_zip_entry_path_windows_and_posix() -> None:
    normalize = _load_normalize()
    assert normalize(r"app\main.py") == "app/main.py"
    assert normalize("app/main.py") == "app/main.py"
    assert (
        normalize(r"app\static\operator-ui\index.html")
        == "app/static/operator-ui/index.html"
    )
    assert (
        normalize("app/static/operator-ui/assets/index.js")
        == "app/static/operator-ui/assets/index.js"
    )
    assert normalize("./app/main.py") == "app/main.py"
    assert normalize("/app/main.py") == "app/main.py"


def test_verify_azure_package_script_exists() -> None:
    text = Path("scripts/verify-azure-package.ps1").read_text(encoding="utf-8")
    assert "Normalize-ZipEntryPath" in text
    assert r"-replace '\\', '/'" in text or "-replace '\\\\', '/'" in text
    assert "SPA_INDEX" in text
    assert "APP_MAIN" in text
    assert "SPA_ASSETS" in text
