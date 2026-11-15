"""Synthetic durable jobs, controllable UTC clock, real transactions and no timing sleeps."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from threading import Barrier, Event

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select, delete
from sqlalchemy.orm import Session, sessionmaker

from app import config, database, migrations
from app.auth import Principal
from app.errors import AppError, NotFound
from app.job_worker import run_once, serve
from app.main import create_app
from app.models import Product, Review, AnalysisResult, ProcessingJob
from app.services import jobs, retention, analysis
from .conftest import csv_file, import_file
from .test_auth import identity, auth_header


class Clock:
    def __init__(self): self.now = datetime.now(timezone.utc)
    def __call__(self): return self.now
    def advance(self, seconds): self.now += timedelta(seconds=seconds)


@pytest.fixture
def job_engine(tmp_path):
    engine = database.make_engine(f'sqlite:///{tmp_path / "jobs.db"}')
    database.init_db(engine)
    yield engine
    engine.dispose()


def seed(engine, owner='alice', now=None):
    now = now or datetime.now(timezone.utc)
    with Session(engine) as db:
        p = Product(owner_id=owner, name='Synthetic job product', source='manual', created_at=now,
                    expires_at=None if owner == 'local' else now + timedelta(days=7))
        p.reviews.append(Review(external_id='one', text='Excellent synthetic battery life'))
        db.add(p); db.commit()
        return p.id


def enqueue(engine, product_id, key='request_0001', owner='alice', now=None):
    with Session(engine, expire_on_commit=False) as db:
        db.info['principal'] = Principal(owner, local=owner == 'local')
        job = jobs.create(db, product_id, key, now=now)
        db.commit()
        return job.id


def take(engine, clock):
    with Session(engine) as db:
        claimed = jobs.claim(db, now=clock()); db.commit(); return claimed


def counts(engine):
    with Session(engine) as db:
        return tuple(db.scalar(select(func.count()).select_from(model)) for model in (Product, Review, AnalysisResult, ProcessingJob))


def test_job_success_duplicate_request_and_duplicate_execution(job_engine):
    clock = Clock(); product_id = seed(job_engine, now=clock())
    job_id = enqueue(job_engine, product_id, now=clock())
    assert enqueue(job_engine, product_id, now=clock()) == job_id
    claimed = take(job_engine, clock)
    assert claimed.job_id == job_id
    with Session(job_engine) as db:
        assert jobs.execute(db, claimed, clock=clock)
        db.commit()
    with Session(job_engine) as db:
        assert not jobs.execute(db, claimed, clock=clock)
        db.commit()
        job = db.get(ProcessingJob, job_id)
        assert job.status == 'succeeded' and job.attempts == 1
        assert jobs.out(job)['resultUrl'] == f'/api/history/{job.result["analysis_id"]}'
        assert db.get(Product, product_id).expires_at == clock() + timedelta(days=7)
    assert counts(job_engine) == (1, 1, 1, 1)
    assert enqueue(job_engine, product_id, now=clock()) == job_id


def test_concurrent_claim_and_duplicate_execution_are_serialized(job_engine):
    clock = Clock(); product_id = seed(job_engine, now=clock()); enqueue(job_engine, product_id, now=clock())
    barrier = Barrier(2)
    def claim(_):
        barrier.wait(timeout=5)
        return take(job_engine, clock)
    with ThreadPoolExecutor(max_workers=2) as pool:
        claims = list(pool.map(claim, range(2)))
    [claimed] = [c for c in claims if c is not None]
    barrier = Barrier(2)
    def execute(_):
        barrier.wait(timeout=5)
        with Session(job_engine) as db:
            result = jobs.execute(db, claimed, clock=clock)
            db.commit(); return result
    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(execute, range(2))) == [False, True]
    assert counts(job_engine)[2] == 1


def test_failed_attempt_rolls_back_snapshot_and_retries_to_exhaustion(job_engine, monkeypatch, caplog):
    clock = Clock(); product_id = seed(job_engine, now=clock())
    monkeypatch.setattr(config, 'JOB_MAX_ATTEMPTS', 2)
    job_id = enqueue(job_engine, product_id, now=clock())
    def fail(db, product):
        analysis.run_analysis(db, product)
        raise RuntimeError('private review secret credential')
    assert run_once(job_engine, clock=clock, analyse=fail)
    assert counts(job_engine)[2] == 0
    with Session(job_engine) as db:
        job = db.get(ProcessingJob, job_id)
        assert job.status == 'queued' and job.attempts == 1 and job.result is None
        assert job.available_at == clock() + timedelta(seconds=config.JOB_RETRY_SECONDS)
        assert 'private' not in job.error
    assert not run_once(job_engine, clock=clock, analyse=fail)
    clock.advance(config.JOB_RETRY_SECONDS)
    assert run_once(job_engine, clock=clock, analyse=fail)
    with Session(job_engine) as db:
        job = db.get(ProcessingJob, job_id)
        assert job.status == 'failed' and job.attempts == 2
    assert 'private review' not in caplog.text
    assert counts(job_engine)[2] == 0


def test_process_interruption_recovers_with_fencing_and_no_partial_result(job_engine):
    class Interrupted(BaseException): pass
    clock = Clock(); product_id = seed(job_engine, now=clock()); job_id = enqueue(job_engine, product_id, now=clock())
    claimed = take(job_engine, clock)
    def interrupt(db, product):
        analysis.run_analysis(db, product)
        raise Interrupted()
    with pytest.raises(Interrupted):
        with Session(job_engine) as db:
            jobs.execute(db, claimed, clock=clock, analyse=interrupt)
            db.commit()
    assert counts(job_engine)[2] == 0
    assert take(job_engine, clock) is None
    clock.advance(config.JOB_LEASE_SECONDS)
    recovered = take(job_engine, clock)
    assert recovered.token != claimed.token
    with Session(job_engine) as db:
        assert not jobs.execute(db, claimed, clock=clock)
        assert jobs.execute(db, recovered, clock=clock)
        db.commit()
        assert db.get(ProcessingJob, job_id).attempts == 2
    assert counts(job_engine)[2] == 1


def test_abandoned_final_attempt_is_failed_without_another_execution(job_engine, monkeypatch):
    clock = Clock(); product_id = seed(job_engine, now=clock())
    monkeypatch.setattr(config, 'JOB_MAX_ATTEMPTS', 1)
    job_id = enqueue(job_engine, product_id, now=clock()); assert take(job_engine, clock)
    clock.advance(config.JOB_LEASE_SECONDS)
    assert take(job_engine, clock) is None
    with Session(job_engine) as db: assert db.get(ProcessingJob, job_id).status == 'failed'
    assert counts(job_engine)[2] == 0


def test_cancellation_is_owner_scoped_idempotent_and_queued_only(job_engine):
    product_id = seed(job_engine); job_id = enqueue(job_engine, product_id)
    with Session(job_engine) as db:
        db.info['principal'] = Principal('bob')
        with pytest.raises(NotFound): jobs.cancel(db, job_id)
        db.rollback()
        db.info['principal'] = Principal('alice')
        assert jobs.cancel(db, job_id).status == 'cancelled'
        db.commit()
        assert jobs.cancel(db, job_id).status == 'cancelled'
        db.commit()
    assert not run_once(job_engine)
    enqueue(job_engine, product_id, 'request_0002')
    claimed = take(job_engine, Clock())
    with Session(job_engine) as db:
        db.info['principal'] = Principal('alice')
        with pytest.raises(AppError, match='Only queued'): jobs.cancel(db, claimed.job_id)


@pytest.mark.parametrize('setting', ['JOB_MAX_STORED', 'JOB_MAX_PER_OWNER', 'JOB_MAX_PER_PRODUCT'])
def test_job_storage_quotas_are_checked_before_writes(job_engine, monkeypatch, setting):
    product_id = seed(job_engine)
    monkeypatch.setattr(config, setting, 1)
    enqueue(job_engine, product_id)
    with Session(job_engine) as db:
        db.info['principal'] = Principal('alice'); jobs.cancel(db, 1); db.commit()
    with pytest.raises(AppError) as error: enqueue(job_engine, product_id, 'request_0002')
    assert error.value.status_code == 413 and counts(job_engine)[3] == 1


def test_active_job_and_analysis_quota_interaction(job_engine, monkeypatch):
    product_id = seed(job_engine); job_id = enqueue(job_engine, product_id)
    with pytest.raises(AppError) as error: enqueue(job_engine, product_id, 'request_0002')
    assert error.value.status_code == 409
    # A synchronous run can consume the last history slot while the job waits.
    with Session(job_engine) as db:
        product = db.get(Product, product_id)
        analysis.run_analysis(db, product); db.commit()
    monkeypatch.setattr(config, 'MAX_ANALYSIS_RUNS', 1)
    assert run_once(job_engine)
    with Session(job_engine) as db:
        assert db.get(ProcessingJob, job_id).status == 'failed'
    assert counts(job_engine)[2] == 1


def test_retention_expiry_during_execution_rolls_back_and_cascades(job_engine):
    clock = Clock(); product_id = seed(job_engine, now=clock()); job_id = enqueue(job_engine, product_id, now=clock())
    claimed = take(job_engine, clock)
    def expire(db, product):
        result = analysis.run_analysis(db, product)
        clock.advance(7 * 86400)
        return result
    with pytest.raises(AppError):
        with Session(job_engine) as db:
            jobs.execute(db, claimed, clock=clock, analyse=expire); db.commit()
    assert counts(job_engine)[2] == 0
    with Session(job_engine) as db:
        jobs.failure(db, claimed, retryable=False, now=clock()); db.commit()
        assert db.get(ProcessingJob, job_id).status == 'cancelled'
        db.info['principal'] = Principal('alice')
        # Expiry scope uses real wall time; retention itself accepts our deterministic future cutoff.
    report = retention.run_cleanup(job_engine, now=clock())
    assert report['deleted']['jobs'] == 1 and counts(job_engine) == (0, 0, 0, 0)


def test_deleted_parent_and_expired_parent_are_never_processed(job_engine):
    clock = Clock(); product_id = seed(job_engine, now=clock()); enqueue(job_engine, product_id, now=clock())
    clock.advance(7 * 86400)
    assert take(job_engine, clock) is None
    with Session(job_engine) as db:
        db.execute(delete(Product).where(Product.id == product_id)); db.commit()
    assert counts(job_engine) == (0, 0, 0, 0)


def test_local_products_keep_existing_retention_exemption(job_engine):
    clock = Clock(); product_id = seed(job_engine, 'local', now=clock())
    enqueue(job_engine, product_id, owner='local', now=clock())
    clock.advance(8 * 86400)
    assert run_once(job_engine, clock=clock)
    with Session(job_engine) as db: assert db.get(Product, product_id).expires_at is None


def test_worker_graceful_stop_does_not_poll_or_start_more_work(job_engine, monkeypatch):
    stop = Event(); calls = []
    import app.job_worker as worker
    def once(*args, **kwargs): calls.append(True); stop.set(); return True
    monkeypatch.setattr(worker, 'run_once', once)
    serve(job_engine, stop)
    assert calls == [True]
    serve(job_engine, stop)
    assert calls == [True]


def test_api_auth_owner_result_access_and_cancellation(client, identity, monkeypatch):
    product_id = seed(database.engine)
    with TestClient(create_app()) as secured:
        assert secured.post(f'/api/products/{product_id}/jobs', json={'requestKey': 'request_0001'}).status_code == 401
        alice, bob = auth_header(identity()), auth_header(identity('bob'))
        # The fixture's verified owner hash differs from a literal subject; seed with that verified identity.
        from app.auth import TokenVerifier
        owner = TokenVerifier().verify(identity()).owner_id
        product_id = seed(database.engine, owner)
        response = secured.post(f'/api/products/{product_id}/jobs', headers=alice, json={'requestKey': 'request_0001'})
        assert response.status_code == 202
        job_id = response.json()['id']
        assert 'claimToken' not in response.text and 'requestKey' not in response.text
        assert secured.get(f'/api/jobs/{job_id}', headers=bob).status_code == 404
        assert secured.post(f'/api/jobs/{job_id}/cancel', headers=bob).status_code == 404
        assert secured.get(f'/api/products/{product_id}/jobs', headers=bob).status_code == 404
        assert run_once(database.engine)
        status = secured.get(f'/api/jobs/{job_id}', headers=alice).json()
        assert status['status'] == 'succeeded'
        assert secured.get(status['resultUrl'], headers=alice).status_code == 200
        assert secured.get(status['resultUrl'], headers=bob).status_code == 404
        assert secured.post(f'/api/jobs/{job_id}/cancel', headers=alice).status_code == 409
        assert len(secured.get(f'/api/products/{product_id}/jobs', headers=alice).json()) == 1


def test_job_creation_uses_analysis_rate_limit_and_does_not_queue_rejection(client, monkeypatch):
    monkeypatch.setattr(config, 'RATE_LIMIT_ANALYSIS_REQUESTS', 1)
    with TestClient(create_app()) as limited:
        product_id = seed(database.engine, 'local')
        path = f'/api/products/{product_id}/jobs'
        assert limited.post(path, json={'requestKey': 'request_0001'}).status_code == 202
        response = limited.post(path, json={'requestKey': 'request_0002'})
        assert response.status_code == 429 and int(response.headers['retry-after']) > 0
        assert counts(database.engine)[3] == 1
        assert limited.get('/api/jobs/1').status_code == 200
        assert limited.post('/api/jobs/1/cancel').status_code == 200


@pytest.mark.parametrize('body', [{}, {'requestKey': 'short'}, {'requestKey': '../private/path'},
                                  {'requestKey': 'request_0001', 'kind': 'collect'}])
def test_invalid_job_requests_do_not_persist(client, body):
    product_id = seed(database.engine, 'local')
    assert client.post(f'/api/products/{product_id}/jobs', json=body).status_code == 422
    assert counts(database.engine)[3] == 0


def test_job_migration_preserves_legacy_results_and_disarms_pending(tmp_path, monkeypatch):
    engine = database.make_engine(f'sqlite:///{tmp_path / "v7.db"}')
    # Build a true old table; Base.metadata now describes v8 and cannot create a v7 fixture.
    with engine.begin() as conn:
        for ddl in ('CREATE TABLE products (id INTEGER PRIMARY KEY)',
                    'CREATE TABLE processing_jobs (id INTEGER PRIMARY KEY, product_id INTEGER NOT NULL REFERENCES products(id) ON DELETE CASCADE, created_at DATETIME NOT NULL, status VARCHAR(20) NOT NULL, result JSON)',
                    'CREATE INDEX ix_processing_jobs_product_id ON processing_jobs(product_id)',
                    'INSERT INTO products VALUES(1)',
                    '''INSERT INTO processing_jobs VALUES(1,1,'2026-11-01','pending','{"synthetic":true}')''',
                    'PRAGMA user_version=7'):
            conn.exec_driver_sql(ddl)
    assert migrations.upgrade(engine) == 1
    with engine.connect() as conn:
        row = conn.exec_driver_sql('SELECT status,result,request_key,attempts FROM processing_jobs').one()
        assert row == ('cancelled', '{"synthetic":true}', None, 0)
    engine.dispose()


def test_worker_interruption_releases_connection_and_leaves_recoverable_claim(job_engine):
    class Interrupted(BaseException): pass
    clock = Clock(); product_id = seed(job_engine, now=clock()); job_id = enqueue(job_engine, product_id, now=clock())
    def interrupt(db, product):
        analysis.run_analysis(db, product)
        raise Interrupted()
    with pytest.raises(Interrupted): run_once(job_engine, clock=clock, analyse=interrupt)
    with Session(job_engine) as db:
        assert db.get(ProcessingJob, job_id).status == 'running'
    assert counts(job_engine)[2] == 0
    clock.advance(config.JOB_LEASE_SECONDS)
    assert run_once(job_engine, clock=clock)
    assert counts(job_engine)[2] == 1


def test_graceful_stop_finishes_current_transaction_without_claiming_next(job_engine, monkeypatch):
    import app.job_worker as worker
    first = seed(job_engine); second = seed(job_engine)
    a, b = enqueue(job_engine, first), enqueue(job_engine, second)
    stop = Event()
    real_once = worker.run_once
    def analyse(db, product):
        stop.set()
        return analysis.run_analysis(db, product)
    monkeypatch.setattr(worker, 'run_once', lambda engine, slot: real_once(engine, slot=slot, analyse=analyse))
    worker.serve(job_engine, stop)
    with Session(job_engine) as db:
        assert db.get(ProcessingJob, a).status == 'succeeded'
        assert db.get(ProcessingJob, b).status == 'queued'


def test_expired_job_api_is_hidden_and_unsupported_history_does_not_leak_payload(client, identity):
    from app.auth import TokenVerifier
    with TestClient(create_app()) as secured:
        owner = TokenVerifier().verify(identity()).owner_id
        product_id = seed(database.engine, owner)
        job_id = enqueue(database.engine, product_id, owner=owner)
        with Session(database.engine) as db:
            product = db.get(Product, product_id)
            product.created_at -= timedelta(days=8)
            db.get(ProcessingJob, job_id).result = {'private_review': 'never return this'}
            db.commit()
        headers = auth_header(identity())
        assert secured.get(f'/api/jobs/{job_id}', headers=headers).status_code == 404
        assert secured.get(f'/api/products/{product_id}/jobs', headers=headers).status_code == 404
        assert secured.post(f'/api/jobs/{job_id}/cancel', headers=headers).status_code == 404
        assert secured.post(f'/api/products/{product_id}/jobs', headers=headers,
                            json={'requestKey': 'request_0002'}).status_code == 404


def test_concurrent_creation_respects_final_global_storage_slot(job_engine, monkeypatch):
    monkeypatch.setattr(config, 'JOB_MAX_STORED', 1)
    products = [seed(job_engine, owner) for owner in ('alice', 'bob')]
    barrier = Barrier(2)
    def create(index):
        barrier.wait(timeout=5)
        try:
            enqueue(job_engine, products[index], owner=('alice', 'bob')[index])
            return 'created'
        except AppError as error:
            assert error.status_code == 413
            return 'limited'
    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(create, range(2))) == ['created', 'limited']
    assert counts(job_engine)[3] == 1


def test_empty_reviews_and_storage_limit_rejection_leave_no_jobs(job_engine, monkeypatch):
    product_id = seed(job_engine)
    with Session(job_engine) as db:
        db.execute(delete(Review)); db.commit()
    with pytest.raises(AppError) as error: enqueue(job_engine, product_id)
    assert error.value.status_code == 422 and counts(job_engine)[3] == 0


def test_job_extension_migration_rollback_restores_status_and_schema(tmp_path, monkeypatch):
    from sqlalchemy import inspect
    engine = database.make_engine(f'sqlite:///{tmp_path / "rollback-v8.db"}')
    with engine.begin() as conn:
        conn.exec_driver_sql('CREATE TABLE processing_jobs(id INTEGER PRIMARY KEY, product_id INTEGER NOT NULL, created_at DATETIME NOT NULL, status VARCHAR(20) NOT NULL, result JSON)')
        conn.exec_driver_sql("INSERT INTO processing_jobs VALUES(1,1,'2026-11-01','pending','{}')")
        conn.exec_driver_sql('PRAGMA user_version=7')
    original = migrations._v8_durable_jobs
    def broken(conn):
        original(conn)
        raise RuntimeError('injected migration interruption')
    monkeypatch.setattr(migrations, 'MIGRATIONS', [*migrations.MIGRATIONS[:7], ('broken v8', broken)])
    with pytest.raises(RuntimeError): migrations.upgrade(engine)
    with engine.connect() as conn:
        assert conn.exec_driver_sql('PRAGMA user_version').scalar() == 7
        assert conn.exec_driver_sql('SELECT status FROM processing_jobs').scalar() == 'pending'
        assert 'claim_token' not in {c['name'] for c in inspect(conn).get_columns('processing_jobs')}
    engine.dispose()


def test_deleted_result_reference_cannot_follow_reused_analysis_id(job_engine):
    product_id = seed(job_engine); job_id = enqueue(job_engine, product_id)
    assert run_once(job_engine)
    with Session(job_engine) as db:
        job = db.get(ProcessingJob, job_id)
        old_id = job.result_analysis_id
        db.execute(delete(AnalysisResult).where(AnalysisResult.id == old_id)); db.commit()
        replacement = analysis.run_analysis(db, db.get(Product, product_id)); db.commit()
        assert replacement.id == old_id  # SQLite is allowed to reuse the deleted highest INTEGER PK.
        db.expire_all()
        job = db.get(ProcessingJob, job_id)
        assert job.status == 'succeeded' and job.result_analysis_id is None
        assert jobs.out(job)['analysisId'] is None and jobs.out(job)['resultUrl'] is None


@pytest.mark.parametrize('setting,value', [('JOB_CONCURRENCY','0'), ('JOB_CONCURRENCY','5'),
    ('JOB_LEASE_SECONDS','0'), ('JOB_MAX_ATTEMPTS','6'), ('JOB_MAX_STORED','-1')])
def test_invalid_job_configuration_fails_startup(monkeypatch, setting, value):
    import runpy
    monkeypatch.setenv(setting, value)
    with pytest.raises(ValueError): runpy.run_path(config.__file__)


def test_worker_schema_preflight_is_read_only_and_rejects_partial_v8(job_engine):
    from app.job_worker import check_schema
    from sqlalchemy import inspect
    check_schema(job_engine)
    with job_engine.begin() as conn: conn.exec_driver_sql('ALTER TABLE processing_jobs DROP COLUMN claim_token')
    with pytest.raises(RuntimeError, match='schema is not current'): check_schema(job_engine)
    with job_engine.connect() as conn:
        assert 'claim_token' not in {c['name'] for c in inspect(conn).get_columns('processing_jobs')}


@pytest.mark.parametrize('phase', ['acquisition', 'rollback', 'unlock'])
def test_uncertain_postgres_session_lock_never_returns_to_pool(monkeypatch, phase):
    from unittest.mock import MagicMock
    import app.job_worker as worker
    class Interrupted(BaseException): pass
    engine = MagicMock(); engine.dialect.name = 'postgresql'
    conn = engine.connect.return_value.__enter__.return_value
    locked = MagicMock(); locked.scalar.return_value = True
    if phase == 'acquisition': conn.execute.side_effect = Interrupted()
    elif phase == 'rollback':
        conn.execute.return_value = locked
        conn.rollback.side_effect = Interrupted()
    else: conn.execute.side_effect = [locked, Interrupted()]
    monkeypatch.setattr(worker, 'Session', MagicMock())
    monkeypatch.setattr(worker.jobs, 'claim', lambda *args, **kwargs: None)
    with pytest.raises(Interrupted): worker.run_once(engine)
    conn.invalidate.assert_called_once()


def test_worker_preflight_does_not_create_missing_sqlite_file(tmp_path):
    from app.job_worker import check_schema
    path = tmp_path / 'must-not-create.db'
    engine = database.make_engine(f'sqlite:///{path}')
    with pytest.raises(RuntimeError, match='existing explicitly migrated'): check_schema(engine)
    assert not path.exists()
    engine.dispose()
