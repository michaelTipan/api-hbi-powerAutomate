"""Preservación de .payment_validation_jobs en actualizaciones de release."""

from __future__ import annotations

import json
import shutil
from pathlib import Path


def _stage_release(wwwroot: Path, code_src: Path) -> None:
    """Simula actualizar código sin borrar el directorio de jobs."""
    jobs = wwwroot / ".payment_validation_jobs"
    assert jobs.is_dir()
    # Actualizar solo application.py / app/ (no tocar jobs).
    shutil.copy2(code_src / "application.py", wwwroot / "application.py")
    app_dst = wwwroot / "app"
    if app_dst.exists():
        # no delete jobs sibling
        pass
    (wwwroot / "app").mkdir(exist_ok=True)
    (wwwroot / "app" / "marker_release.txt").write_text("u4-rc-r1\n", encoding="utf-8")


def test_release_staging_preserves_payment_validation_jobs(tmp_path: Path) -> None:
    wwwroot = tmp_path / "wwwroot"
    wwwroot.mkdir()
    jobs = wwwroot / ".payment_validation_jobs"
    jobs.mkdir()
    sample = {
        "job_id": "job-preserve-1",
        "status": "succeeded",
        "bank_code": "banco_bogota",
    }
    (jobs / "job-preserve-1.json").write_text(
        json.dumps(sample), encoding="utf-8"
    )
    (wwwroot / "application.py").write_text("old\n", encoding="utf-8")

    code_src = tmp_path / "release"
    code_src.mkdir()
    (code_src / "application.py").write_text("new-release\n", encoding="utf-8")

    _stage_release(wwwroot, code_src)

    assert (jobs / "job-preserve-1.json").is_file()
    saved = json.loads((jobs / "job-preserve-1.json").read_text(encoding="utf-8"))
    assert saved["job_id"] == "job-preserve-1"
    assert (wwwroot / "application.py").read_text(encoding="utf-8") == "new-release\n"
    assert (wwwroot / "app" / "marker_release.txt").read_text(encoding="utf-8").startswith(
        "u4-rc-r1"
    )
