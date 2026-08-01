"""Tests de resolución de site-packages empaquetadas (sin run.sh)."""

from __future__ import annotations

import sys
from pathlib import Path

from application import ensure_packaged_site_packages


def test_ensure_packaged_site_packages_adds_existing_dir(tmp_path: Path) -> None:
    site = tmp_path / ".python_packages" / "lib" / "site-packages"
    site.mkdir(parents=True)
    (site / "marker.txt").write_text("ok", encoding="utf-8")

    # Limpiar path previo de esta corrida
    before = list(sys.path)
    try:
        added = ensure_packaged_site_packages(tmp_path)
        assert str(tmp_path) in added
        assert str(site.resolve()) in added
        assert str(site.resolve()) in sys.path
    finally:
        sys.path[:] = before


def test_ensure_packaged_site_packages_tolerates_missing(tmp_path: Path) -> None:
    before = list(sys.path)
    try:
        added = ensure_packaged_site_packages(tmp_path)
        assert str(tmp_path) in added
        assert not any("site-packages" in p for p in added if p != str(tmp_path))
    finally:
        sys.path[:] = before
