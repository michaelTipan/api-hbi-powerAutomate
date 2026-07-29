"""Estado de jobs de validación de pagos.

Persiste a disco para sobrevivir reciclajes del App Service. Tras un restart,
los jobs que quedaron en queued/running se marcan como failed (el BackgroundTask
ya no existe).
"""
from __future__ import annotations

import asyncio
import json
import os
import re
from pathlib import Path
from typing import Any

_SAFE_JOB_ID = re.compile(r"^[A-Za-z0-9_.-]{1,128}$")


def _jobs_dir() -> Path:
    raw = (os.getenv("PAYMENT_VALIDATION_JOBS_DIR") or "").strip()
    if raw:
        return Path(raw)
    # Azure App Service: ruta fija (HOME/wwwroot check puede fallar según sandbox).
    if (os.getenv("WEBSITE_INSTANCE_ID") or "").strip():
        return Path("/home/site/wwwroot/.payment_validation_jobs")
    home = (os.getenv("HOME") or "").strip()
    wwwroot = Path(home) / "site" / "wwwroot" if home else None
    if wwwroot is not None and wwwroot.is_dir():
        return wwwroot / ".payment_validation_jobs"
    import tempfile

    return Path(tempfile.gettempdir()) / "hbi_payment_validation_jobs"


def _utc_now_iso() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat()


class JobManager:
    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(JobManager, cls).__new__(cls)
            cls._instance._init_state()
        return cls._instance

    def _init_state(self):
        self._job_lock = asyncio.Lock()
        self._validation_jobs: dict[str, dict[str, Any]] = {}
        # Concurrency flags for human-in-the-loop workflows
        self._generate_active = False
        self._finalize_active = False
        self._jobs_dir = _jobs_dir()
        self._reconcile_persisted_jobs()

    def _job_path(self, job_id: str) -> Path | None:
        if not _SAFE_JOB_ID.match(job_id):
            return None
        return self._jobs_dir / f"{job_id}.json"

    def _persist_job_unlocked(self, job_id: str, payload: dict[str, Any]) -> None:
        path = self._job_path(job_id)
        if path is None:
            return
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp = path.with_suffix(".json.tmp")
            tmp.write_text(
                json.dumps(payload, ensure_ascii=False, default=str),
                encoding="utf-8",
            )
            tmp.replace(path)
        except OSError:
            # No bloquear el flujo si el disco falla; el estado en memoria sigue.
            pass

    def _load_job_from_disk(self, job_id: str) -> dict[str, Any] | None:
        path = self._job_path(job_id)
        if path is None or not path.is_file():
            return None
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        if not isinstance(raw, dict):
            return None
        return raw

    def _reconcile_persisted_jobs(self) -> None:
        """Al arrancar: jobs queued/running quedan huérfanos → failed."""
        try:
            if not self._jobs_dir.is_dir():
                return
            for path in self._jobs_dir.glob("*.json"):
                try:
                    raw = json.loads(path.read_text(encoding="utf-8"))
                except (OSError, ValueError):
                    continue
                if not isinstance(raw, dict):
                    continue
                job_id = str(raw.get("job_id") or path.stem)
                st = str(raw.get("status") or "")
                if st in ("queued", "running"):
                    raw["status"] = "failed"
                    raw["finished_at"] = _utc_now_iso()
                    raw["updated_at"] = _utc_now_iso()
                    raw["error"] = {
                        "type": "JobInterruptedByProcessRestart",
                        "message": (
                            "El App Service se reinició o recicló mientras el job "
                            "estaba en curso. Reencolar el mismo paso."
                        ),
                    }
                    try:
                        path.write_text(
                            json.dumps(raw, ensure_ascii=False, default=str),
                            encoding="utf-8",
                        )
                    except OSError:
                        pass
                self._validation_jobs[job_id] = raw
        except OSError:
            return

    async def set_job(self, job_id: str, updates: dict[str, Any]) -> None:
        async with self._job_lock:
            current = self._validation_jobs.get(job_id)
            if current is None:
                current = self._load_job_from_disk(job_id) or {}
            current.update(updates)
            if "job_id" not in current:
                current["job_id"] = job_id
            self._validation_jobs[job_id] = current
            self._persist_job_unlocked(job_id, current)

    def get_job(self, job_id: str) -> dict[str, Any] | None:
        hit = self._validation_jobs.get(job_id)
        if hit is not None:
            return hit
        loaded = self._load_job_from_disk(job_id)
        if loaded is not None:
            self._validation_jobs[job_id] = loaded
        return loaded

    def try_start_generate(self) -> bool:
        """Intenta iniciar un flujo generate. Retorna True si tiene exito."""
        if self._generate_active or self._finalize_active:
            return False
        self._generate_active = True
        return True

    def finish_generate(self) -> None:
        self._generate_active = False

    def try_start_finalize(self) -> bool:
        """Intenta iniciar un flujo finalize. Retorna True si tiene exito."""
        if self._generate_active or self._finalize_active:
            return False
        self._finalize_active = True
        return True

    def finish_finalize(self) -> None:
        self._finalize_active = False
