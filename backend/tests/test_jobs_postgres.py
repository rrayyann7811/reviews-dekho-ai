"""Opt-in jobs tests on the existing guarded loopback disposable database only."""
from concurrent.futures import ThreadPoolExecutor
from threading import Event

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session
from alembic import command

from app import config
from app.models import ProcessingJob
from app.job_worker import run_once
from app.services import analysis
from app.postgres_migrations import alembic_config
from .test_postgres_integration import pg, upgrade
from . import test_jobs as checks


@pytest.mark.parametrize('case', ['success', 'concurrent', 'failure', 'fencing', 'interruption', 'retention'])
def test_postgres_job_transactions(pg, monkeypatch, caplog, case):
    upgrade(pg)
    if case == 'success': checks.test_job_success_duplicate_request_and_duplicate_execution(pg)
    elif case == 'concurrent': checks.test_concurrent_claim_and_duplicate_execution_are_serialized(pg)
    elif case == 'failure': checks.test_failed_attempt_rolls_back_snapshot_and_retries_to_exhaustion(pg, monkeypatch, caplog)
    elif case == 'fencing': checks.test_process_interruption_recovers_with_fencing_and_no_partial_result(pg)
    elif case == 'interruption': checks.test_worker_interruption_releases_connection_and_leaves_recoverable_claim(pg)
    else: checks.test_retention_expiry_during_execution_rolls_back_and_cascades(pg)


def test_postgres_worker_slot_and_locked_expired_claim_prevent_duplicate_work(pg):
    upgrade(pg)
    clock = checks.Clock(); product_id = checks.seed(pg, now=clock())
    job_id = checks.enqueue(pg, product_id, now=clock())
    entered, release = Event(), Event()
    def blocked(db, product):
        entered.set()
        assert release.wait(timeout=10)
        return analysis.run_analysis(db, product)
    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(run_once, pg, clock=clock, analyse=blocked)
        try:
            assert entered.wait(timeout=5)
            clock.advance(config.JOB_LEASE_SECONDS)
            assert not run_once(pg, clock=clock)  # shared advisory slot is still owned
            assert checks.take(pg, clock) is None  # expired lease cannot bypass held product lock
        finally:
            release.set()
        assert first.result(timeout=10)
    with Session(pg) as db:
        assert db.get(ProcessingJob, job_id).status == 'succeeded'
    assert checks.counts(pg)[2] == 1


def test_postgres_job_extension_preserves_legacy_data(pg):
    cfg = alembic_config()
    with pg.connect() as conn:
        cfg.attributes['connection'] = conn
        command.upgrade(cfg, '0001_postgres')
    product_id = checks.seed(pg)
    with pg.begin() as conn:
        conn.exec_driver_sql("INSERT INTO processing_jobs(product_id,created_at,status,result) VALUES (%s,now(),'pending','{\"synthetic\":true}')", (product_id,))
    upgrade(pg)
    with Session(pg) as db:
        job = db.scalar(select(ProcessingJob))
        assert job.status == 'cancelled' and job.request_key is None
        assert job.result == {'synthetic': True}


def test_postgres_global_queue_quota_is_atomic(pg, monkeypatch):
    upgrade(pg)
    checks.test_concurrent_creation_respects_final_global_storage_slot(pg, monkeypatch)
