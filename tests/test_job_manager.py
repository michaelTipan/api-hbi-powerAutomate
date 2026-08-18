import asyncio
import pytest

try:
    from app.application.job_manager import JobManager
except ImportError:
    JobManager = None

def test_job_manager_singleton():
    if JobManager is None:
        pytest.fail("JobManager not implemented")
    
    manager1 = JobManager()
    manager2 = JobManager()
    assert manager1 is manager2

def test_job_manager_concurrency_lock():
    if JobManager is None:
        pytest.fail("JobManager not implemented")
        
    async def run_test():
        manager = JobManager()
        manager._validation_jobs = {}
        manager._generate_active = False
        manager._finalize_active = False
        manager._notify_active = False
        
        success1 = manager.try_start_generate()
        assert success1 is True
        
        success2 = manager.try_start_generate()
        assert success2 is False
        
        manager.finish_generate()
        
        success3 = manager.try_start_generate()
        assert success3 is True
        manager.finish_generate()
        
    asyncio.run(run_test())

def test_job_manager_status_updates():
    if JobManager is None:
        pytest.fail("JobManager not implemented")
        
    async def run_test():
        manager = JobManager()
        job_id = "test_job_123"
        
        await manager.set_job(job_id, {"status": "running"})
        job = manager.get_job(job_id)
        assert job is not None
        assert job["status"] == "running"
        
    asyncio.run(run_test())


def test_job_manager_persists_and_recovers_orphan(tmp_path, monkeypatch):
    """Persistencia a disco + jobs running huérfanos → failed al reiniciar."""
    if JobManager is None:
        pytest.fail("JobManager not implemented")

    monkeypatch.setenv("PAYMENT_VALIDATION_JOBS_DIR", str(tmp_path))
    JobManager._instance = None

    async def seed():
        manager = JobManager()
        await manager.set_job(
            "orphan-job-001",
            {"job_id": "orphan-job-001", "status": "running", "type": "generate"},
        )
        path = tmp_path / "orphan-job-001.json"
        assert path.is_file()

    asyncio.run(seed())

    # Simula recycle: nueva instancia lee disco y marca el job huérfano.
    JobManager._instance = None
    recovered = JobManager()
    job = recovered.get_job("orphan-job-001")
    assert job is not None
    assert job["status"] == "failed"
    assert job["error"]["type"] == "JobInterruptedByProcessRestart"


def test_find_active_job_by_bank_code():
    if JobManager is None:
        pytest.fail("JobManager not implemented")

    async def run_test():
        manager = JobManager()
        manager._validation_jobs = {}
        await manager.set_job(
            "gen-bank-1",
            {
                "job_id": "gen-bank-1",
                "type": "generate",
                "status": "running",
                "bank_code": "banco_bancolombia",
                "updated_at": "2026-08-18T12:00:00",
            },
        )
        await manager.set_job(
            "fin-other",
            {
                "job_id": "fin-other",
                "type": "finalize",
                "status": "running",
                "bank_code": "banco_bogota",
                "updated_at": "2026-08-18T12:01:00",
            },
        )
        hit = manager.find_active_job_by_bank_code("banco_bancolombia")
        assert hit is not None
        assert hit["job_id"] == "gen-bank-1"
        assert manager.find_active_job_by_bank_code("banco_bogota")["job_id"] == "fin-other"
        assert manager.find_active_job_by_bank_code("banco_desconocido") is None

    asyncio.run(run_test())
