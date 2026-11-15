"""Offline PostgreSQL compilation/mocks are NOT PostgreSQL integration results."""
import importlib.util
import io
import sqlite3
import subprocess
import sys
import os
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path
from threading import Barrier
from unittest.mock import MagicMock

import pytest
from alembic import command
from alembic.migration import MigrationContext
from alembic.operations import Operations
from fastapi.testclient import TestClient
from sqlalchemy import inspect, select, text, func
from sqlalchemy.dialects import postgresql
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.orm import Session

from app import config, database, migrations, postgres_migrations
from app.auth import Principal
from app.database import make_engine, init_db
from app.main import create_app
from app.models import Product, Review, AnalysisResult, AiSummary, ProcessingJob
from app.services import ownership
from app.services.products import get_product
from app.services.retention import purge_expired_products


@pytest.fixture
def sqlite(tmp_path):
    engine = make_engine(f'sqlite:///{tmp_path / "compat.db"}')
    init_db(engine)
    yield engine
    engine.dispose()


def baseline_revision():
    path = Path(__file__).resolve().parents[1] / 'alembic/versions/0001_postgres_foundation.py'
    spec = importlib.util.spec_from_file_location('test_pg_revision', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_postgres_urls_pooling_and_driver_are_configured_without_connecting(monkeypatch):
    factory = MagicMock()
    monkeypatch.setattr(database, 'create_engine', factory)
    database.make_engine('postgresql://localhost/offline_test')
    args, kwargs = factory.call_args
    assert args[0].drivername == 'postgresql+psycopg'
    assert kwargs['pool_pre_ping'] and kwargs['hide_parameters']
    assert kwargs['pool_size'] == 2 and kwargs['max_overflow'] == 0
    assert kwargs['connect_args']['prepare_threshold'] is None
    assert 'timezone=UTC' in kwargs['connect_args']['options']
    monkeypatch.setattr(config, 'DB_POOL_MODE', 'null')
    database.make_engine('postgresql+psycopg://db.example.invalid/offline_test')
    assert factory.call_args.kwargs['poolclass'] is database.NullPool
    assert factory.call_args.kwargs['connect_args']['sslmode'] == 'verify-full'


@pytest.mark.parametrize('url', ['mysql://localhost/test', 'postgresql+psycopg2://localhost/test',
                               'postgresql://db.example.invalid/test?sslmode=disable',
                               'postgresql://localhost/test?host=remote.example.invalid'])
def test_unsupported_or_insecure_database_configuration_fails_closed(url):
    with pytest.raises(ValueError):
        make_engine(url)


def test_postgres_startup_is_read_only_and_never_runs_legacy_migrations(monkeypatch):
    engine = MagicMock(); engine.dialect.name = 'postgresql'
    check = MagicMock(side_effect=RuntimeError('schema not current'))
    monkeypatch.setattr(postgres_migrations, 'check_schema', check)
    with pytest.raises(RuntimeError, match='not current'):
        init_db(engine)
    check.assert_called_once_with(engine)
    with pytest.raises(RuntimeError, match='SQLite only'):
        migrations.upgrade(engine)


@pytest.mark.parametrize('heads,tables', [([], []), (['unknown_revision'], ['products'])])
def test_postgres_schema_gate_rejects_missing_unknown_or_partial_schema(monkeypatch, heads, tables):
    engine = MagicMock()
    context = MagicMock(); context.get_current_heads.return_value = heads
    monkeypatch.setattr(postgres_migrations.MigrationContext, 'configure', lambda _: context)
    reflection = MagicMock(); reflection.get_table_names.return_value = tables
    monkeypatch.setattr(postgres_migrations, 'inspect', lambda _: reflection)
    with pytest.raises(RuntimeError, match='back up'):
        postgres_migrations.check_schema(engine)
    assert not engine.begin.called


def test_postgres_connection_failure_does_not_fall_back_to_sqlite(monkeypatch):
    engine = MagicMock(); engine.dialect.name = 'postgresql'
    engine.connect.side_effect = OperationalError('SELECT 1', {}, Exception('TEST DSN detail'))
    with pytest.raises(OperationalError):
        init_db(engine)


def test_alembic_generates_transactional_postgresql_schema_without_connecting(monkeypatch):
    monkeypatch.setenv('DATABASE_URL', 'postgresql+psycopg://localhost/offline_test')
    output = io.StringIO()
    cfg = postgres_migrations.alembic_config(); cfg.output_buffer = output
    command.upgrade(cfg, 'head', sql=True)
    sql = output.getvalue()
    assert 'BEGIN;' in sql and 'COMMIT;' in sql
    assert 'TIMESTAMP WITH TIME ZONE' in sql and 'CREATE TABLE processing_jobs' in sql
    assert sql.count('ON DELETE CASCADE') == 4
    assert 'UNIQUE INDEX uq_collected_product ON products (owner_id,' in sql
    assert 'PRAGMA' not in sql and 'alembic_version' in sql


def test_actual_alembic_cli_handles_repository_paths_with_spaces(tmp_path):
    ini = Path(__file__).resolve().parents[1] / 'alembic.ini'
    env = {**os.environ, 'DATABASE_URL': 'postgresql+psycopg://localhost/offline_test'}
    result = subprocess.run([sys.executable, '-m', 'alembic', '-c', str(ini), 'upgrade', 'head', '--sql'],
                            cwd=tmp_path, env=env, text=True, capture_output=True, timeout=30)
    assert result.returncode == 0, result.stderr
    assert 'CREATE TABLE processing_jobs' in result.stdout and 'COMMIT;' in result.stdout


def test_alembic_refuses_sqlite_and_destructive_baseline_downgrade(monkeypatch):
    monkeypatch.setenv('DATABASE_URL', 'sqlite:///:memory:')
    with pytest.raises(RuntimeError, match='explicit PostgreSQL'):
        command.upgrade(postgres_migrations.alembic_config(), 'head', sql=True)
    with pytest.raises(RuntimeError, match='Restore'):
        baseline_revision().downgrade()


def test_frozen_baseline_matches_orm_schema_on_sqlite_test_engine(tmp_path):
    # Exercises the revision's operations on SQLite only; PostgreSQL execution is tested separately.
    engine = make_engine(f'sqlite:///{tmp_path / "revision.db"}')
    with engine.begin() as conn:
        with Operations.context(MigrationContext.configure(conn)):
            baseline_revision().upgrade()
    actual = inspect(engine)
    assert set(actual.get_table_names()) == set(database.Base.metadata.tables)
    for name, table in database.Base.metadata.tables.items():
        columns = {c['name']: c for c in actual.get_columns(name)}
        assert set(columns) == set(table.columns.keys())
        assert {k: v['nullable'] for k, v in columns.items()} == {c.name: c.nullable for c in table.columns}
        assert len(actual.get_foreign_keys(name)) == len(table.foreign_key_constraints)
    engine.dispose()


def test_job_migration_failure_rolls_back_version_and_keeps_existing_data(tmp_path, monkeypatch):
    engine = make_engine(f'sqlite:///{tmp_path / "rollback.db"}')
    with monkeypatch.context() as patch:
        patch.setattr(migrations, 'MIGRATIONS', migrations.MIGRATIONS[:6])
        patch.setattr(migrations, 'LATEST_VERSION', 6)
        # Old metadata must not create the new table for this fixture.
        database.Base.metadata.create_all(engine, tables=[t for n, t in database.Base.metadata.tables.items() if n != 'processing_jobs'])
        with engine.begin() as conn:
            conn.exec_driver_sql('PRAGMA user_version=6')
    with Session(engine) as db:
        db.add(Product(name='Synthetic local')); db.commit()
    def broken(conn):
        migrations._v7_product_jobs(conn)
        raise RuntimeError('injected failure')
    monkeypatch.setattr(migrations, 'MIGRATIONS', [*migrations.MIGRATIONS[:6], ('failure', broken)])
    with pytest.raises(RuntimeError, match='injected'):
        migrations.upgrade(engine)
    with engine.connect() as conn:
        assert migrations.get_version(conn) == 6
        assert conn.execute(text('SELECT name FROM products')).scalar() == 'Synthetic local'
    assert 'processing_jobs' not in inspect(engine).get_table_names()
    engine.dispose()


def test_existing_sqlite_requires_explicit_upgrade_and_keeps_file_untouched(tmp_path):
    engine = make_engine(f'sqlite:///{tmp_path / "old.db"}')
    with engine.begin() as conn:
        conn.exec_driver_sql('CREATE TABLE synthetic_marker (value TEXT)')
        conn.exec_driver_sql("INSERT INTO synthetic_marker VALUES ('preserve me')")
        conn.exec_driver_sql('PRAGMA user_version=6')
    with pytest.raises(RuntimeError, match='migrate_sqlite'):
        init_db(engine)
    with engine.connect() as conn:
        assert migrations.get_version(conn) == 6
        assert conn.exec_driver_sql('SELECT value FROM synthetic_marker').scalar() == 'preserve me'
    assert inspect(engine).get_table_names() == ['synthetic_marker']
    engine.dispose()


def test_sqlite_backup_includes_committed_wal_pages(tmp_path):
    path = tmp_path / 'wal.db'
    engine = make_engine(f'sqlite:///{path}')
    with sqlite3.connect(path) as writer:
        writer.execute('PRAGMA journal_mode=WAL')
        writer.execute('CREATE TABLE synthetic_marker (value TEXT)')
        writer.execute("INSERT INTO synthetic_marker VALUES ('committed WAL')")
        writer.commit()
        backup = migrations._backup(engine, 6)
        with sqlite3.connect(backup) as saved:
            assert saved.execute('SELECT value FROM synthetic_marker').fetchone()[0] == 'committed WAL'
        assert backup.stat().st_mode & 0o777 == 0o600
    engine.dispose()


def test_exact_creation_deadline_and_utc_round_trip(sqlite, monkeypatch):
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    class Clock:
        @staticmethod
        def now(tz): return now
    monkeypatch.setattr(ownership, 'datetime', Clock)
    with Session(sqlite) as db:
        db.info['principal'] = Principal('alice')
        identity = ownership.new_product_identity(db)
        assert identity['created_at'] == now and identity['expires_at'] == now + timedelta(days=7)
        product = Product(name='Synthetic', **identity)
        db.add(product); db.commit(); db.expire_all()
        assert product.created_at.tzinfo == timezone.utc
        product.collected_at = now.astimezone(timezone(timedelta(hours=5, minutes=30)))
        db.commit(); db.expire_all()
        assert product.collected_at == now
        assert product.expires_at == identity['expires_at']


def test_jobs_share_owner_and_parent_deadline_and_cascade_with_all_derived_data(sqlite, monkeypatch):
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    class Clock:
        @staticmethod
        def now(tz): return now
    monkeypatch.setattr(ownership, 'datetime', Clock)
    with Session(sqlite) as db:
        db.info['principal'] = Principal('alice')
        p = Product(name='Synthetic', **ownership.new_product_identity(db)); db.add(p); db.flush()
        db.add_all([Review(product_id=p.id, external_id='synthetic-1', text='synthetic review'),
                    ProcessingJob(product_id=p.id, result={'synthetic': True}, created_at=now + timedelta(days=6))])
        run = AnalysisResult(product_id=p.id, total_reviews=1, positive_percent=100, negative_percent=0,
                             stats={}, aspects=[], keywords=[], summary={})
        db.add(run); db.flush()
        db.add(AiSummary(analysis_id=run.id, model='synthetic', prompt_version=1, status='rejected',
                         attempts=1, sentences=[], problems=[])); db.commit()
        assert len(db.scalars(ownership.job_query(db)).all()) == 1
        db.info['principal'] = Principal('bob')
        assert db.scalars(ownership.job_query(db)).all() == []
        db.info['principal'] = Principal('alice')
        now += timedelta(days=7) - timedelta(microseconds=1)
        assert db.scalar(ownership.job_query(db)) is not None
        now += timedelta(microseconds=1)
        assert db.scalars(ownership.job_query(db)).all() == []
        assert purge_expired_products(db, now=now) == 1
        db.commit()
        for table in [Product, Review, AnalysisResult, AiSummary, ProcessingJob]:
            assert db.scalar(select(func.count()).select_from(table)) == 0
        # Identity is not a table in this application; it remains usable after cleanup.
        db.add(Product(name='Next synthetic', **ownership.new_product_identity(db))); db.commit()


def test_postgres_write_lock_preserves_owner_filter_and_read_queries_remain_unlocked():
    db = MagicMock(); db.get_bind.return_value.dialect.name = 'postgresql'
    db.info = {'principal': Principal('alice'), 'write_request': True}
    query = select(Product).where(ownership.product_scope(db))
    sql = str(ownership.lock_owned_product(db, query).compile(dialect=postgresql.dialect()))
    assert 'owner_id =' in sql and 'expires_at >' in sql and 'FOR UPDATE OF products' in sql
    db.info['write_request'] = False
    assert 'FOR UPDATE' not in str(ownership.lock_owned_product(db, query).compile(dialect=postgresql.dialect()))


def test_concurrent_same_owner_uniqueness_and_separate_owner_operations(sqlite):
    def race(owners):
        barrier = Barrier(2)
        def create(owner):
            with Session(sqlite) as db:
                db.info['principal'] = Principal(owner)
                # Start requests together; SQLite quota checks now reserve the writer before reading.
                barrier.wait(timeout=5)
                p = Product(name='Synthetic race', source_site='test', external_product_id='1', source_region='IN',
                            **ownership.new_product_identity(db))
                db.add(p)
                try: db.commit(); return 'created'
                except IntegrityError: db.rollback(); return 'conflict'
        with ThreadPoolExecutor(max_workers=2) as pool:
            return list(pool.map(create, owners))
    assert sorted(race(['alice', 'alice'])) == ['conflict', 'created']
    assert race(['bob', 'carol']) == ['created', 'created']
    with Session(sqlite) as db:
        db.info['principal'] = Principal('outsider')
        with pytest.raises(Exception, match='doesn’t exist'):
            get_product(db, 1)


def test_connection_failure_is_generic_503_and_does_not_leak_dsn(client):
    from app.database import get_db
    from app.main import app
    def unavailable():
        raise OperationalError('SELECT secret_review', {}, Exception('TEST-password-never-return'))
    app.dependency_overrides[get_db] = unavailable
    try:
        response = client.get('/api/health')
        assert response.status_code == 503
        assert 'TEST-password' not in response.text and 'secret_review' not in response.text
    finally:
        app.dependency_overrides.clear()
