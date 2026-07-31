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
        self._notify_active = False
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
        if self._generate_active or self._finalize_active or self._notify_active:
            return False
        self._generate_active = True
        return True

    def finish_generate(self) -> None:
        self._generate_active = False

    def try_start_finalize(self) -> bool:
        """Intenta iniciar un flujo finalize. Retorna True si tiene exito."""
        if self._generate_active or self._finalize_active or self._notify_active:
            return False
        self._finalize_active = True
        return True

    def finish_finalize(self) -> None:
        self._finalize_active = False

    def try_start_notify(self) -> bool:
        """Intenta iniciar Notify. Exclusión mutua con Generate/Finalize/Notify."""
        if self._generate_active or self._finalize_active or self._notify_active:
            return False
        self._notify_active = True
        return True

    def try_claim_notify_for_process(self, process_key: str | None) -> str:
        """Reserva Notify de forma atómica respecto a evidencia de éxito.

        Retorna:
          - ``ok``: lock adquirido; el caller debe ``finish_notify`` al terminar.
          - ``busy``: Generate/Finalize/Notify activo.
          - ``already_notified``: ya hay job Notify exitoso para el ProcessKey
            (no adquiere lock; no crear segundo job).
        """
        if self._generate_active or self._finalize_active or self._notify_active:
            return "busy"
        pk = (process_key or "").strip()
        if pk and self.has_completed_notify(pk):
            return "already_notified"
        self._notify_active = True
        return "ok"

    def finish_notify(self) -> None:
        self._notify_active = False

    def is_notify_active(self) -> bool:
        """Lectura pura para available_actions / gates informativos."""
        return bool(self._notify_active)

    def is_generate_or_finalize_active(self) -> bool:
        """Lectura pura: Generate, Finalize o Notify ocupados (mutex compartido)."""
        return bool(
            self._generate_active or self._finalize_active or self._notify_active
        )

    def _iter_persisted_jobs(self) -> list[dict[str, Any]]:
        """Jobs en memoria + disco (para evidencia post-recycle)."""
        seen: set[str] = set()
        out: list[dict[str, Any]] = []
        for job_id, job in list(self._validation_jobs.items()):
            seen.add(str(job_id))
            out.append(job)
        try:
            if not self._jobs_dir.is_dir():
                return out
            for path in self._jobs_dir.glob("*.json"):
                job_id = path.stem
                if job_id in seen:
                    continue
                loaded = self._load_job_from_disk(job_id)
                if loaded is None:
                    continue
                self._validation_jobs[job_id] = loaded
                seen.add(job_id)
                out.append(loaded)
        except OSError:
            return out
        return out

    @staticmethod
    def _is_notify_job_type(job: dict[str, Any]) -> bool:
        typ = str(job.get("type") or "").strip().lower()
        return "notify" in typ

    @staticmethod
    def _notify_job_process_key(job: dict[str, Any]) -> str:
        pk = str(job.get("process_key") or "").strip()
        if pk:
            return pk
        result = job.get("result")
        if isinstance(result, dict):
            return str(result.get("process_key") or "").strip()
        return ""

    @staticmethod
    def _notify_job_succeeded(job: dict[str, Any]) -> bool:
        """True solo para Notify completed con éxito o SKIPPED_IDEMPOTENT.

        No considera failed (reintento permitido si el control sigue listo).
        """
        if str(job.get("status") or "").strip().lower() != "completed":
            return False
        if not JobManager._is_notify_job_type(job):
            return False
        result = job.get("result")
        if not isinstance(result, dict):
            return False
        err_code = str(result.get("merge_control_error_code") or "").strip().lower()
        if err_code == "already_notified":
            return True
        warning = str(result.get("merge_control_warning") or "").strip().lower()
        if warning == "already_notified":
            return True
        st = str(result.get("status") or "").strip().lower()
        if st in ("ok", "success", "skipped_idempotent"):
            return True
        # sendMail HTTP exitoso sin error de job
        try:
            http_st = int(result.get("graph_sendmail_http_status") or 0)
        except (TypeError, ValueError):
            http_st = 0
        if http_st in (200, 202) and job.get("error") is None:
            return True
        return False

    def find_successful_notify_by_process_key(
        self, process_key: str
    ) -> dict[str, Any] | None:
        """Último job Notify exitoso persistido para el ProcessKey (o None)."""
        want = (process_key or "").strip()
        if not want:
            return None
        best: dict[str, Any] | None = None
        best_finished = ""
        for job in self._iter_persisted_jobs():
            if self._notify_job_process_key(job) != want:
                continue
            if not self._notify_job_succeeded(job):
                continue
            finished = str(job.get("finished_at") or job.get("updated_at") or "")
            if best is None or finished >= best_finished:
                best = job
                best_finished = finished
        return best

    def has_completed_notify(self, process_key: str) -> bool:
        """Evidencia local: Notify exitoso previo para este ProcessKey."""
        return self.find_successful_notify_by_process_key(process_key) is not None


def get_job_manager() -> JobManager:
    """Accessor canónico del singleton compartido por PA y UI."""
    return JobManager()
