"""Real temporary SQLite retention tests; no operator/application database is opened."""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import signal
import sqlite3
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import event, select, func
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from app import database
from app.auth import Principal
from app.models import Product, Review, AnalysisResult, AiSummary, ProcessingJob
from app.services import retention, ownership

NOW = datetime(2026, 11, 1, tzinfo=timezone.utc)
CLI = Path(__file__).resolve().parents[1] / 'scripts/purge_expired_data.py'
PRIVATE = 'PRIVATE_REVIEW_CONTENT_NEVER_LOG'


@pytest.fixture
def store(tmp_path):
    engine = database.make_engine(f'sqlite:///{tmp_path / "retention.db"}')
    database.init_db(engine)
    yield engine
    engine.dispose()


def seed(engine, *, owner='alice', created=None, expiry='default', children=True, product_id=None):
    created = created or NOW - timedelta(days=8)
    expires = created + timedelta(days=7) if expiry == 'default' else expiry
    with Session(engine) as db:
        p = Product(name=PRIVATE, owner_id=owner, created_at=created, expires_at=expires)
        if product_id is not None: p.id = product_id
        db.add(p); db.flush()
        if children:
            db.add(Review(product_id=p.id, external_id='synthetic', text=PRIVATE, reviewer=PRIVATE))
            run = AnalysisResult(product_id=p.id, total_reviews=1, positive_percent=100, negative_percent=0,
                created_at=created + timedelta(days=6), stats={}, aspects=[], keywords=[], summary={},
                review_results=[{'text': PRIVATE}])
            db.add(run); db.flush()
            db.add(AiSummary(analysis_id=run.id, model='synthetic', prompt_version=1, status='rejected',
                attempts=1, sentences=[], problems=[]))
            db.add(ProcessingJob(product_id=p.id, created_at=created + timedelta(days=6), result={'text':PRIVATE}))
        db.commit()
        return p.id


def numbers(engine):
    with Session(engine) as db:
        return {name: db.scalar(select(func.count()).select_from(model)) for name, model in zip(
            retention.TABLES, [Product, Review, AnalysisResult, AiSummary, ProcessingJob])}


def test_boundaries_creation_cap_and_local_preservation(store, monkeypatch):
    due = seed(store, created=NOW - timedelta(days=7))
    future = seed(store, created=NOW - timedelta(days=7) + timedelta(microseconds=1))
    extended = seed(store, expiry=NOW + timedelta(days=365))
    missing = seed(store, expiry=None)
    local = seed(store, owner='local', expiry=NOW - timedelta(days=1))
    class Clock:
        @staticmethod
        def now(tz): return NOW
    monkeypatch.setattr(ownership, 'datetime', Clock)
    with Session(store) as db:
        db.info['principal'] = Principal('alice')
        visible = list(db.scalars(select(Product.id).where(ownership.product_scope(db))))
        assert visible == [future]
    report = retention.run_cleanup(store, now=NOW)
    assert report['deleted'] == dict.fromkeys(retention.TABLES, 3)
    assert report['status'] == 'complete' and not report['remaining']
    with Session(store) as db:
        assert set(db.scalars(select(Product.id))) == {future, local}
    assert due != extended != missing


def test_owner_filter_cascades_idempotence_and_identity_preservation(store):
    alice, bob = seed(store), seed(store, owner='bob')
    with store.begin() as conn:
        conn.exec_driver_sql('CREATE TABLE identity_sentinel (subject TEXT PRIMARY KEY)')
        conn.exec_driver_sql("INSERT INTO identity_sentinel VALUES ('persistent-account')")
    report = retention.run_cleanup(store, owner_id='alice', now=NOW)
    assert report['deleted'] == dict.fromkeys(retention.TABLES, 1)
    assert retention.run_cleanup(store, owner_id='alice', now=NOW)['deleted']['products'] == 0
    with store.connect() as conn:
        assert conn.exec_driver_sql('SELECT subject FROM identity_sentinel').scalar() == 'persistent-account'
    with Session(store) as db:
        assert db.get(Product, alice) is None and db.get(Product, bob) is not None
    assert retention.run_cleanup(store, now=NOW)['deleted']['products'] == 1


def test_batch_limit_partial_progress_and_repeated_completion(store):
    for _ in range(5): seed(store)
    first = retention.run_cleanup(store, batch_size=2, max_batches=2, now=NOW)
    assert first['status'] == 'partial' and first['deleted']['products'] == 4
    assert first['batches'] == first['committed_batches'] == 2
    assert retention.run_cleanup(store, now=NOW)['deleted']['products'] == 1
    assert retention.run_cleanup(store, now=NOW)['deleted']['products'] == 0


def test_dry_run_is_read_only_bounded_and_counts_nonpositive_ids_once(store):
    for product_id in [-2, 0, 1]: seed(store, product_id=product_id)
    store.dispose()
    before = hashlib.sha256(Path(store.url.database).read_bytes()).hexdigest()
    first = retention.run_cleanup(store, dry_run=True, batch_size=1, max_batches=2, now=NOW)
    assert first['status'] == 'partial' and first['matched']['products'] == 2
    report = retention.run_cleanup(store, dry_run=True, batch_size=1, now=NOW)
    assert report['matched'] == dict.fromkeys(retention.TABLES, 3)
    assert report['deleted'] == dict.fromkeys(retention.TABLES, 0)
    assert report['committed_batches'] == 0
    assert numbers(store) == dict.fromkeys(retention.TABLES, 3)
    assert hashlib.sha256(Path(store.url.database).read_bytes()).hexdigest() == before
    # No read-only state leaks into a subsequent write checkout.
    assert retention.run_cleanup(store, now=NOW)['deleted']['products'] == 3


def test_dry_run_rejects_accidental_writes_inside_the_transaction(store, monkeypatch):
    seed(store)
    def writes(connection, ids):
        connection.exec_driver_sql("UPDATE products SET name='must not happen'")
    monkeypatch.setattr(retention, '_counts', writes)
    with pytest.raises(retention.RetentionFailure) as failed:
        retention.run_cleanup(store, dry_run=True, now=NOW)
    assert failed.value.report['deleted']['products'] == 0
    with Session(store) as db:
        assert db.scalar(select(Product.name)) == PRIVATE


def test_interruption_after_delete_rolls_back_current_batch_and_preserves_committed_progress(store):
    for _ in range(3): seed(store)
    deleted = 0
    def interrupt(conn, cursor, statement, parameters, context, executemany):
        nonlocal deleted
        if statement.startswith('DELETE FROM products'):
            deleted += 1
            if deleted == 2: raise KeyboardInterrupt
    event.listen(store, 'after_cursor_execute', interrupt)
    try:
        with pytest.raises(retention.RetentionFailure) as failed:
            retention.run_cleanup(store, batch_size=1, now=NOW)
    finally:
        event.remove(store, 'after_cursor_execute', interrupt)
    assert failed.value.interrupted
    assert failed.value.report['committed_batches'] == 1
    assert failed.value.report['deleted'] == dict.fromkeys(retention.TABLES, 1)
    assert numbers(store) == dict.fromkeys(retention.TABLES, 2)
    assert retention.run_cleanup(store, now=NOW)['deleted']['products'] == 2


def test_interruption_after_candidate_select_releases_cursor_and_allows_retry(store):
    seed(store); seed(store)
    def interrupt(conn, cursor, statement, parameters, context, executemany):
        if statement.startswith('SELECT products.id'):
            raise KeyboardInterrupt
    event.listen(store, 'after_cursor_execute', interrupt)
    try:
        with pytest.raises(retention.RetentionFailure) as failed:
            retention.run_cleanup(store, now=NOW)
    finally:
        event.remove(store, 'after_cursor_execute', interrupt)
    assert failed.value.interrupted
    assert numbers(store) == dict.fromkeys(retention.TABLES, 2)
    assert retention.run_cleanup(store, now=NOW)['deleted']['products'] == 2


def test_concurrent_cleaners_serialize_without_double_counting(store):
    for _ in range(5): seed(store)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: retention.run_cleanup(store, batch_size=1, now=NOW), range(2)))
    assert sum(r['deleted']['products'] for r in results) == 5
    assert numbers(store) == dict.fromkeys(retention.TABLES, 0)


def test_concurrent_wal_reader_and_expired_write_during_cleanup(tmp_path):
    path = tmp_path / 'wal.db'
    with sqlite3.connect(path) as conn: conn.execute('PRAGMA journal_mode=WAL')
    engine = database.make_engine(f'sqlite:///{path}'); database.init_db(engine)
    product_id = seed(engine)
    try:
        with Session(engine) as reader:
            assert reader.get(Product, product_id) is not None
            assert retention.run_cleanup(engine, now=NOW)['deleted']['products'] == 1
            # A pre-existing database read snapshot may remain; a fresh transaction sees deletion.
            reader.rollback()
            assert reader.get(Product, product_id) is None
            reader.info.update(principal=Principal('alice'), write_request=True)
            from app.services.products import get_product
            from app.errors import NotFound
            with pytest.raises(NotFound): get_product(reader, product_id)
    finally:
        engine.dispose()


def test_schema_mismatch_and_connection_failure_do_not_delete(store, monkeypatch):
    seed(store)
    with store.begin() as conn: conn.exec_driver_sql('PRAGMA user_version=6')
    with pytest.raises(retention.RetentionFailure) as failed:
        retention.run_cleanup(store, now=NOW)
    assert failed.value.report['error'] == 'schema_mismatch'
    assert numbers(store)['products'] == 1
    with monkeypatch.context() as patch:
        patch.setattr(store, 'connect', lambda: (_ for _ in ()).throw(
            OperationalError('PRIVATE SQL', {}, Exception('PRIVATE PASSWORD'))))
        with pytest.raises(retention.RetentionFailure) as failed:
            retention.run_cleanup(store, now=NOW)
        assert 'PRIVATE' not in json.dumps(failed.value.report)
        assert failed.value.report['deleted']['products'] == 0


def test_summary_and_logging_never_contain_private_data_or_ids(store, caplog):
    seed(store, owner='PRIVATE_OWNER_IDENTIFIER')
    report = retention.run_cleanup(store, now=NOW)
    assert 'PRIVATE' not in json.dumps(report) + caplog.text
    assert report['deleted']['jobs'] == 1


def cli(path, *args, target=None):
    env = {**os.environ, 'DATABASE_URL': target or f'sqlite:///{path}'}
    return subprocess.run([sys.executable, str(CLI), *args], env=env, text=True,
                          capture_output=True, timeout=15)


def test_cli_dry_run_partial_apply_and_idempotence(store):
    for _ in range(3): seed(store, created=datetime.now(timezone.utc)-timedelta(days=8))
    dry = cli(store.url.database, '--dry-run')
    assert dry.returncode == 0 and json.loads(dry.stdout)['matched']['products'] == 3
    assert numbers(store)['products'] == 3
    partial = cli(store.url.database, '--batch-size','1','--max-batches','1')
    assert partial.returncode == 3 and json.loads(partial.stdout)['deleted']['products'] == 1
    done = cli(store.url.database)
    assert done.returncode == 0 and json.loads(done.stdout)['deleted']['products'] == 2
    assert json.loads(cli(store.url.database).stdout)['deleted']['products'] == 0


@pytest.mark.parametrize('args', [('--batch-size','0'),('--batch-size','1001'),('--max-batches','0'),
                               ('--max-batches','1001'),('--owner-id','local'),('--owner-id','private-user'),('--unknown',)])
def test_cli_bad_arguments_fail_without_deletion(store, args):
    seed(store)
    result = cli(store.url.database, *args)
    assert result.returncode == 2 and json.loads(result.stdout)['status'] == 'configuration_error'
    assert numbers(store)['products'] == 1 and not result.stderr


def test_cli_requires_explicit_existing_target_and_current_schema(tmp_path):
    path = tmp_path / 'absent.db'
    result = cli(path)
    assert result.returncode == 2 and not path.exists()
    env = {**os.environ}; env.pop('DATABASE_URL', None)
    result = subprocess.run([sys.executable, str(CLI)], env=env, text=True, capture_output=True, timeout=15)
    assert result.returncode == 2 and json.loads(result.stdout)['error'] == 'invalid_configuration'


def test_cli_connection_error_is_sanitized_and_restores_signal_handlers(store, monkeypatch, capsys):
    spec = importlib.util.spec_from_file_location('retention_cli_test', CLI)
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    monkeypatch.setenv('DATABASE_URL', str(store.url))
    monkeypatch.setattr(database, 'make_engine', lambda _: (_ for _ in ()).throw(
        OperationalError('PRIVATE SQL', {}, Exception('PRIVATE PASSWORD'))))
    previous = signal.getsignal(signal.SIGTERM)
    assert module.main([]) == 4
    assert signal.getsignal(signal.SIGTERM) == previous
    output = capsys.readouterr()
    assert json.loads(output.out)['status'] == 'failed' and 'PRIVATE' not in output.out + output.err


def test_cli_owner_filter_and_schema_failure(store):
    now = datetime.now(timezone.utc)
    seed(store, owner='a'*64, created=now-timedelta(days=8))
    seed(store, owner='b'*64, created=now-timedelta(days=8))
    result = cli(store.url.database, '--owner-id', 'a'*64)
    assert result.returncode == 0 and json.loads(result.stdout)['deleted']['products'] == 1
    assert 'a'*64 not in result.stdout
    with store.begin() as conn: conn.exec_driver_sql('PRAGMA user_version=6')
    failed = cli(store.url.database)
    assert failed.returncode == 2 and json.loads(failed.stdout)['error'] == 'schema_mismatch'
    assert numbers(store)['products'] == 1


def test_missing_cascade_fails_before_deleting_products(store):
    product_id = seed(store)
    with store.begin() as conn:
        conn.exec_driver_sql('DROP TABLE reviews')
        conn.exec_driver_sql('CREATE TABLE reviews (id INTEGER PRIMARY KEY, product_id INTEGER REFERENCES products(id))')
    with pytest.raises(retention.RetentionFailure) as failed:
        retention.run_cleanup(store, now=NOW)
    assert failed.value.report['status'] == 'configuration_error'
    assert failed.value.report['deleted']['products'] == 0
    with Session(store) as db:
        assert db.get(Product, product_id) is not None


def test_cli_disposal_failure_still_emits_sanitized_json(store, monkeypatch, capsys):
    spec = importlib.util.spec_from_file_location('retention_cli_disposal_test', CLI)
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    monkeypatch.setenv('DATABASE_URL', str(store.url))
    monkeypatch.setattr(database, 'make_engine', lambda _: store)
    def broken(): raise RuntimeError('PRIVATE DATABASE DETAILS')
    monkeypatch.setattr(store, 'dispose', broken)
    assert module.main([]) == 4
    output = capsys.readouterr()
    assert json.loads(output.out)['error'] == 'resource_cleanup_failure'
    assert 'PRIVATE' not in output.out + output.err


def test_real_cli_sigterm_rolls_back_and_reports_interruption(store, tmp_path):
    seed(store)
    ready = tmp_path / 'ready'
    code = f'''import importlib.util, time
from pathlib import Path
spec=importlib.util.spec_from_file_location("retention_cli", {str(CLI)!r})
module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
import app.services.retention as retention
def pause(connection, ids):
    Path({str(ready)!r}).write_text("ready")
    time.sleep(30)
retention._counts=pause
raise SystemExit(module.main([]))
'''
    proc = subprocess.Popen([sys.executable, '-c', code], env={**os.environ, 'DATABASE_URL': str(store.url)},
                            text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    try:
        deadline = time.monotonic() + 5
        while not ready.exists() and proc.poll() is None and time.monotonic() < deadline:
            time.sleep(0.02)
        assert ready.exists()
        proc.send_signal(signal.SIGTERM)
        out, err = proc.communicate(timeout=5)
        assert proc.returncode == 143 and json.loads(out)['status'] == 'interrupted'
        assert json.loads(out)['deleted']['products'] == 0 and not err
    finally:
        if proc.poll() is None:
            proc.kill(); proc.communicate()
    assert numbers(store) == dict.fromkeys(retention.TABLES, 1)
