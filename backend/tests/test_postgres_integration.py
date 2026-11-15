"""Opt-in, disposable LOCAL PostgreSQL only. Never use a cloud/provider/application database."""
import os
import uuid
from concurrent.futures import ThreadPoolExecutor
from threading import Event
from datetime import datetime, timedelta, timezone

import pytest
from alembic import command
from sqlalchemy import event, inspect, select, text, func
from sqlalchemy.engine import make_url
from sqlalchemy.exc import OperationalError, IntegrityError, TimeoutError as PoolTimeout
from sqlalchemy.orm import Session, sessionmaker
from fastapi.testclient import TestClient

from app.database import make_engine, init_db
from app.postgres_migrations import alembic_config
from app import database, config
from app.auth import Principal
from app.models import Product, Review, AnalysisResult
from app.services.products import get_product
from .test_auth import identity, auth_header
from .conftest import csv_file
from .test_database_compatibility import (
    test_jobs_share_owner_and_parent_deadline_and_cascade_with_all_derived_data as _retention,
    test_concurrent_same_owner_uniqueness_and_separate_owner_operations as _concurrency,
)

MARKER = 'Reviews Dekho disposable PostgreSQL integration test database'


def local_test_url(value):
    url = make_url(value)
    if (url.drivername != 'postgresql+psycopg' or url.host != '127.0.0.1' or url.port != 55432
            or url.database != 'reviews_dekho_test_2b1' or set(url.query) - {'sslmode'}):
        raise ValueError('Integration requires the dedicated loopback database reviews_dekho_test_2b1 on port 55432')
    return url


@pytest.mark.parametrize('value', [
    'postgresql+psycopg://127.0.0.1:55432/postgres',
    'postgresql+psycopg://127.0.0.1:55432/reviews_dekho_test_production',
    'postgresql+psycopg://remote.example.invalid:55432/reviews_dekho_test_2b1',
    'postgresql+psycopg://127.0.0.1:5432/reviews_dekho_test_2b1',
    'postgresql+psycopg://127.0.0.1:55432/reviews_dekho_test_2b1?host=remote.example.invalid',
    'postgresql+psycopg://127.0.0.1:55432/reviews_dekho_test_2b1?service=production',
    'sqlite:///reviews_dekho_test_2b1',
])
def test_integration_guard_rejects_non_disposable_targets_without_connecting(value):
    with pytest.raises(ValueError):
        local_test_url(value)


@pytest.fixture
def pg():
    value = os.getenv('TEST_POSTGRESQL_URL')
    if not value:
        pytest.skip('Local PostgreSQL unavailable: TEST_POSTGRESQL_URL unset; no PostgreSQL integration executed')
    engine = make_engine(local_test_url(value))
    schema = 'rd_test_' + uuid.uuid4().hex
    with engine.begin() as conn:
        marker = conn.exec_driver_sql("SELECT shobj_description(oid, 'pg_database') FROM pg_database WHERE datname=current_database()").scalar()
        if marker != MARKER:
            engine.dispose()
            pytest.fail('Dedicated test database marker is absent; refusing schema writes')
        conn.exec_driver_sql(f'CREATE SCHEMA {schema}')
    def search_path(dbapi, record):
        previous = dbapi.autocommit
        dbapi.autocommit = True
        try:
            with dbapi.cursor() as cursor:
                cursor.execute(f'SET search_path TO {schema}')
        finally:
            dbapi.autocommit = previous
    event.listen(engine, 'connect', search_path)
    engine.dispose()
    try:
        yield engine
    finally:
        engine.dispose()
        with engine.begin() as conn:
            conn.exec_driver_sql(f'DROP SCHEMA {schema} CASCADE')
        engine.dispose()


def upgrade(engine, callback=None):
    cfg = alembic_config()
    with engine.connect() as conn:
        cfg.attributes['connection'] = conn
        cfg.attributes['on_version_apply'] = callback
        command.upgrade(cfg, 'head')


def test_postgres_explicit_migration_and_idempotent_startup(pg):
    with pytest.raises(RuntimeError, match='not current'):
        init_db(pg)
    upgrade(pg)
    init_db(pg)
    upgrade(pg)
    assert 'processing_jobs' in inspect(pg).get_table_names()


def test_postgres_ownership_utc_boundaries_and_physical_cascades(pg, monkeypatch):
    upgrade(pg)
    _retention(pg, monkeypatch)


def test_postgres_concurrent_owner_scoped_uniqueness(pg):
    upgrade(pg)
    _concurrency(pg)


def test_postgres_migration_failure_rolls_back_ddl_and_revision(pg):
    def failure(**kwargs):
        raise RuntimeError('injected version failure')
    with pytest.raises(RuntimeError, match='injected'):
        upgrade(pg, failure)
    assert inspect(pg).get_table_names() == []
    upgrade(pg)
    init_db(pg)


def test_postgres_concurrent_updates_use_real_row_locks(pg):
    upgrade(pg)
    with Session(pg) as db:
        p = Product(name='0', owner_id='alice', expires_at=datetime.now(timezone.utc) + timedelta(days=7))
        db.add(p); db.commit(); product_id = p.id
    locked, attempted, release, done = Event(), Event(), Event(), Event()
    def update(first):
        with Session(pg) as db:
            db.info.update(principal=Principal('alice'), write_request=True)
            if not first: attempted.set()
            p = get_product(db, product_id)
            if first:
                locked.set()
                assert release.wait(timeout=5)
            p.name = str(int(p.name) + 1)
            db.commit()
            if not first: done.set()
    with ThreadPoolExecutor(max_workers=2) as pool:
        a = pool.submit(update, True)
        try:
            assert locked.wait(timeout=5)
            b = pool.submit(update, False)
            assert attempted.wait(timeout=5)
            assert not done.wait(timeout=0.1)  # second writer cannot pass the held row lock
        finally:
            release.set()
        a.result(timeout=5); b.result(timeout=5)
    with Session(pg) as db:
        assert db.get(Product, product_id).name == '2'


def test_postgres_lock_timeout_and_failed_transaction_rollback(pg):
    upgrade(pg)
    with Session(pg) as db:
        p = Product(name='Synthetic rollback', owner_id='alice', expires_at=datetime.now(timezone.utc) + timedelta(days=7))
        db.add(p); db.commit(); product_id = p.id
    with Session(pg) as a, Session(pg) as b:
        for db in (a, b): db.info.update(principal=Principal('alice'), write_request=True)
        get_product(a, product_id)
        b.execute(text("SET LOCAL lock_timeout='100ms'"))
        with pytest.raises(OperationalError) as failure:
            get_product(b, product_id)
        assert failure.value.orig.sqlstate == '55P03'
        b.rollback(); a.rollback()
        p = get_product(b, product_id); p.name = 'Recovered'; b.commit()
        b.add(Review(product_id=product_id + 999999, external_id='orphan', text='synthetic'))
        with pytest.raises(IntegrityError): b.commit()
        b.rollback()
        assert b.get(Product, product_id).name == 'Recovered'
        assert b.scalar(select(func.count()).select_from(Review)) == 0


def test_postgres_pool_exhaustion_and_recovery(pg, monkeypatch):
    monkeypatch.setattr(config, 'DB_POOL_SIZE', 1)
    monkeypatch.setattr(config, 'DB_MAX_OVERFLOW', 0)
    monkeypatch.setattr(config, 'DB_POOL_TIMEOUT', 1)
    engine = make_engine(pg.url)
    try:
        with engine.connect() as held:
            assert held.exec_driver_sql('SELECT 1').scalar() == 1
            with pytest.raises(PoolTimeout):
                engine.connect()
        with engine.connect() as recovered:
            assert recovered.exec_driver_sql('SELECT 1').scalar() == 1
    finally:
        engine.dispose()


def test_postgres_actual_disconnect_invalidates_connection_and_recovers(pg):
    with pg.connect() as victim, pg.connect() as controller:
        pid = victim.exec_driver_sql('SELECT pg_backend_pid()').scalar()
        # Terminate only this test's own connection in the disposable database.
        assert controller.execute(text('SELECT pg_terminate_backend(:pid)'), {'pid': pid}).scalar()
        with pytest.raises(OperationalError) as failure:
            victim.exec_driver_sql('SELECT 1')
        assert failure.value.connection_invalidated
        victim.rollback()
    with pg.connect() as recovered:
        assert recovered.exec_driver_sql('SELECT 1').scalar() == 1


def test_postgres_native_timestamptz_and_non_utc_session_round_trip(pg):
    upgrade(pg)
    assert inspect(pg).get_columns('products')[2]['name'] == 'expires_at'
    types = {c['name']: c['type'] for c in inspect(pg).get_columns('products')}
    assert types['created_at'].timezone and types['expires_at'].timezone
    instant = datetime(2026, 1, 1, tzinfo=timezone.utc)
    with Session(pg) as db:
        assert db.execute(text('SHOW TimeZone')).scalar() == 'UTC'
        db.add(Product(name='Synthetic UTC', created_at=instant.astimezone(timezone(timedelta(hours=5, minutes=30)))))
        db.commit()
        db.execute(text("SET LOCAL TIME ZONE 'Asia/Kolkata'"))
        p = db.scalar(select(Product))
        assert p.created_at == instant and p.created_at.tzinfo == timezone.utc


def test_postgres_jwt_application_api_operations(pg, monkeypatch, identity):
    upgrade(pg)
    monkeypatch.setattr(database, 'engine', pg)
    monkeypatch.setattr(database, 'SessionLocal', sessionmaker(bind=pg, autoflush=False, expire_on_commit=False))
    from app.main import create_app
    alice, bob = auth_header(identity()), auth_header(identity('bob'))
    def upload(client, headers):
        response = client.post('/api/uploads/import', headers=headers, files=csv_file(),
                               data={'product_name': 'Synthetic PostgreSQL phone',
                                     'columns': '{"text":"review_text","id":"review_id","rating":"rating"}'})
        assert response.status_code == 201, response.text
        return response.json()['id']
    with TestClient(create_app()) as client:
        assert client.get('/api/health').status_code == 200
        a, b, foreign = upload(client, alice), upload(client, alice), upload(client, bob)
        with Session(pg) as db:
            p = db.get(Product, a); created, expiry = p.created_at, p.expires_at
            assert expiry - created == timedelta(days=7)
        assert client.patch(f'/api/products/{a}', headers=alice, json={'name': 'Updated synthetic'}).status_code == 200
        assert client.post(f'/api/products/{a}/analyze', headers=alice).status_code == 200
        assert client.get(f'/api/products/{a}/reviews', headers=alice).status_code == 200
        assert client.get('/api/history', headers=alice).status_code == 200
        assert client.get(f'/api/compare?product_a={a}&product_b={b}', headers=alice).status_code == 200
        for fmt in ('pdf', 'csv'):
            response = client.get(f'/api/products/{a}/report.{fmt}', headers=alice)
            assert response.status_code == 200 and response.content
            if fmt == 'pdf': assert response.content.startswith(b'%PDF')
            assert client.get(f'/api/products/{a}/report.{fmt}', headers=bob).status_code == 404
        assert client.get(f'/api/products/{foreign}/analysis', headers=alice).status_code == 404
        assert client.patch(f'/api/products/{a}', headers=bob, json={'name':'forbidden'}).status_code == 404
        assert client.delete(f'/api/products/{a}', headers=bob).status_code == 404
        recovery = auth_header(identity(claims={'amr':[{'method':'recovery','timestamp':1}]}))
        assert client.get(f'/api/products/{a}/analysis', headers=recovery).status_code == 401
        with Session(pg) as db:
            p = db.get(Product, a); assert (p.created_at, p.expires_at) == (created, expiry)
        assert client.delete(f'/api/products/{a}', headers=alice).status_code == 204
        with Session(pg) as db:
            assert db.scalar(select(func.count()).select_from(Review).where(Review.product_id==a)) == 0
            assert db.scalar(select(func.count()).select_from(AnalysisResult).where(AnalysisResult.product_id==a)) == 0
