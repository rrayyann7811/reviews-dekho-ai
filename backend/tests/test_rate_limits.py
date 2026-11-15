"""Deterministic budgets and trust boundaries; synthetic data only, no real-time sleeps."""
import asyncio
import hashlib
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app import config
from app.auth import Principal
from app.main import create_app
from app.rate_limits import RateLimitsMiddleware, WindowLimiter, operation_groups, peer_key
from app.resource_limits import ResourceLimitsMiddleware
from .conftest import csv_file, import_file
from .test_auth import identity, auth_header


class Clock:
    now = 100.0
    def __call__(self): return self.now


def test_window_retry_expiry_owner_isolation_and_atomic_budgets():
    clock = Clock()
    limiter = WindowLimiter({'general': 5, 'analysis': 1}, 60, 2, clock)
    assert limiter.check(b'alice', ('general', 'analysis')) == 0
    clock.now += 0.1
    assert limiter.check(b'alice', ('general', 'analysis')) == 60
    assert limiter.entries[b'alice'][1] == {'general': 1, 'analysis': 1}
    clock.now = 159.1
    assert limiter.check(b'alice', ('analysis',)) == 1
    assert limiter.check(b'bob', ('analysis',)) == 0
    clock.now = 160
    assert limiter.check(b'alice', ('general', 'analysis')) == 0


def test_capacity_never_evicts_active_quota_and_expired_entries_reclaimed():
    clock = Clock()
    limiter = WindowLimiter({'general': 1}, 60, 2, clock)
    assert limiter.check(b'a', ('general',)) == limiter.check(b'b', ('general',)) == 0
    assert limiter.check(b'c', ('general',)) == limiter.check(b'a', ('general',)) == 60
    assert len(limiter.entries) == 2
    clock.now += 60
    assert limiter.check(b'c', ('general',)) == 0
    assert len(limiter.entries) == 1


def test_concurrent_threads_cannot_overdraw_budget():
    limiter = WindowLimiter({'general': 3}, 60, 10, Clock())
    barrier = Barrier(12)
    def check(_):
        barrier.wait(timeout=5)
        return limiter.check(b'one-owner', ('general',))
    with ThreadPoolExecutor(max_workers=12) as pool:
        results = list(pool.map(check, range(12)))
    assert results.count(0) == 3 and results.count(60) == 9


@pytest.mark.parametrize('method,path,expected', [
    ('POST', '/api/uploads/preview', ('ingestion',)),
    ('POST', '/api/uploads/import/', ('ingestion', 'analysis')),
    ('POST', '/api/products/from-url', ('collection', 'analysis')),
    ('POST', '/api/products/17/refresh', ('collection', 'analysis')),
    ('POST', '/api/products/17/analyze', ('analysis',)),
    ('POST', '/api/products/17/reviews', ('analysis',)),
    ('DELETE', '/api/products/17/reviews/abc', ('analysis',)),
    ('GET', '/api/products/17/report.csv', ('export',)),
    ('GET', '/api/products/999/report.pdf/', ('export',)),
    ('POST', '/api/products/17/ai-summary', ('ai',)),
    ('GET', '/api/ai/status', ('ai',)),
    ('GET', '/api/products/17/ai-summary', ()),
    ('GET', '/api/products/17/analysis', ()),
    ('POST', '/api/products', ()),
])
def test_operation_categories_include_implicit_analysis(method, path, expected):
    assert operation_groups({'method': method, 'path': path}) == expected


def owner_limiter(app):
    current = app.middleware_stack
    while current is not None:
        if isinstance(current, RateLimitsMiddleware) and current.phase == 'owner': return current.limiter
        current = getattr(current, 'app', None)
    raise AssertionError('Owner middleware missing')


def test_owner_identity_not_token_ip_or_headers(client, identity, monkeypatch):
    monkeypatch.setattr(config, 'RATE_LIMIT_GENERAL_REQUESTS', 2)
    with TestClient(create_app()) as secured:
        assert secured.get('/api/products', headers=auth_header(identity())).status_code == 200
        changed = {**auth_header(identity(claims={'owner_id': 'bob', 'user_id': 'bob'})),
                   'X-Owner-ID': 'bob', 'X-Forwarded-For': '203.0.113.1', 'Forwarded': 'for=203.0.113.2'}
        assert secured.get('/api/products?owner_id=bob', headers=changed).status_code == 200
        denied = secured.get('/api/history', headers=changed)
        assert denied.status_code == 429 and int(denied.headers['retry-after']) >= 1
        assert denied.json() == {'detail': 'Too many requests. Please retry shortly.'}
        assert secured.get('/api/products', headers=auth_header(identity('bob'))).status_code == 200
        assert secured.get('/api/products', headers={'X-Owner-ID': 'bob'}).status_code == 401
        limiter = owner_limiter(secured.app)
        assert len(limiter.entries) == 2 and all(len(key) == 32 for key in limiter.entries)


def test_local_workspace_recovery_uses_fake_clock(client, monkeypatch):
    monkeypatch.setattr(config, 'RATE_LIMIT_GENERAL_REQUESTS', 1)
    with TestClient(create_app()) as local:
        assert local.get('/api/products').status_code == 200
        limiter = owner_limiter(local.app)
        clock = Clock()
        limiter.clock = clock
        limiter.entries.clear()
        limiter.next_sweep = 0
        assert local.get('/api/products').status_code == 200
        response = local.get('/api/products')
        assert response.status_code == 429 and response.headers['retry-after'] == '60'
        clock.now = 159.2
        assert local.get('/api/products').headers['retry-after'] == '1'
        clock.now = 160
        assert local.get('/api/products').status_code == 200


def test_anonymous_and_failed_auth_share_peer_limit(identity, monkeypatch):
    monkeypatch.setattr(config, 'RATE_LIMIT_PEER_REQUESTS', 2)
    with TestClient(create_app()) as secured:
        assert secured.get('/api/health').status_code == 200
        assert secured.get('/api/products', headers={'Authorization': 'Bearer private-secret'}).status_code == 401
        response = secured.post('/api/uploads/import', files=csv_file(),
                                headers={'Authorization': 'Bearer private-secret', 'X-Forwarded-For': '198.51.100.1'})
        assert response.status_code == 429 and 'private-secret' not in response.text
        assert secured.get('/docs').status_code == 429


def test_peer_and_global_budgets_ignore_forwarded_headers(monkeypatch):
    monkeypatch.setattr(config, 'RATE_LIMIT_PEER_REQUESTS', 1)
    monkeypatch.setattr(config, 'RATE_LIMIT_GLOBAL_REQUESTS', 3)
    async def run():
        called, output = [], []
        async def endpoint(scope, receive, send): called.append(scope['client'][0])
        async def receive(): raise AssertionError('limiter must not read a body')
        async def send(message): output.append(message)
        middleware = RateLimitsMiddleware(endpoint, phase='peer')
        def scope(ip, forwarded):
            return {'type': 'http', 'method': 'GET', 'path': '/api/health', 'client': (ip, 1),
                    'headers': [(b'x-forwarded-for', forwarded)]}
        await middleware(scope('127.0.0.1', b'1.1.1.1'), receive, send)
        await middleware(scope('127.0.0.1', b'2.2.2.2'), receive, send)
        assert output[0]['status'] == 429
        await middleware(scope('127.0.0.2', b'1.1.1.1'), receive, send)
        await middleware(scope('127.0.0.3', b'1.1.1.1'), receive, send)
        assert called == ['127.0.0.1', '127.0.0.2'] and output[-2]['status'] == 429
    asyncio.run(run())
    assert peer_key({'client': ('127.0.0.1', 1)}) == peer_key({'client': ('::ffff:127.0.0.1', 2)})
    assert peer_key({}) == peer_key({'client': ('untrusted-hostname', 1)})


def test_rejected_import_never_opens_database_or_reads_body(client, monkeypatch):
    from app.database import get_db
    monkeypatch.setattr(config, 'RATE_LIMIT_INGESTION_REQUESTS', 1)
    with TestClient(create_app()) as limited:
        assert limited.post('/api/uploads/preview', files=csv_file()).status_code == 200
        def forbidden_db(): raise AssertionError('rejected request opened a DB session')
        limited.app.dependency_overrides[get_db] = forbidden_db
        assert import_file(limited).status_code == 429
        limited.app.dependency_overrides.clear()
        assert limited.get('/api/products').json() == []
    async def run():
        async def forbidden(*args): raise AssertionError('body/endpoint invoked')
        messages = []
        async def send(message): messages.append(message)
        middleware = RateLimitsMiddleware(forbidden, phase='owner')
        scope = {'type': 'http', 'method': 'POST', 'path': '/api/uploads/import',
                 'state': {'principal': Principal('alice')}}
        middleware.limiter.check(hashlib.sha256(b'alice').digest(), ('ingestion',))
        await middleware(scope, forbidden, send)
        assert messages[0]['status'] == 429
    asyncio.run(run())


def test_rejected_analysis_leaves_reviews_and_snapshots_unchanged(client, monkeypatch):
    from app import database
    from app.models import Product, Review, AnalysisResult
    monkeypatch.setattr(config, 'RATE_LIMIT_ANALYSIS_REQUESTS', 1)
    with TestClient(create_app()) as limited:
        product = import_file(limited).json()
        response = limited.post(f'/api/products/{product["id"]}/reviews', json={'reviews': [{'text': 'Synthetic extra'}]})
        assert response.status_code == 429
        with Session(database.engine) as db:
            assert [db.scalar(select(func.count()).select_from(model)) for model in (Product, Review, AnalysisResult)] == [1, 6, 1]
        assert limited.get(f'/api/products/{product["id"]}/analysis').json()['stats']['totalReviews'] == 6


def test_exports_share_budget_across_formats_ids_queries_and_decoded_paths(client, monkeypatch):
    monkeypatch.setattr(config, 'RATE_LIMIT_EXPORT_REQUESTS', 1)
    with TestClient(create_app()) as limited:
        product = import_file(limited).json()
        assert limited.get(f'/api/products/{product["id"]}/report.csv').status_code == 200
        for path in (f'/api/products/{product["id"]}/report.pdf?analysis_id=1',
                     '/api/products/999/report.csv/', '/api/products/1/report%2Epdf'):
            assert limited.get(path).status_code == 429
        assert limited.get('/api/products').status_code == 200


@pytest.mark.parametrize("phase", ["peer", "owner"])
def test_internal_failure_is_closed_sanitized_and_does_not_catch_endpoint_errors(caplog, phase):
    async def run():
        called, messages = [], []
        async def endpoint(*args): called.append(True)
        async def receive(): raise AssertionError('body read')
        async def send(message): messages.append(message)
        middleware = RateLimitsMiddleware(endpoint, phase=phase)
        def broken(*args): raise RuntimeError('private-review secret credential')
        middleware.limiter.check = broken
        await middleware({'type': 'http', 'method': 'POST', 'path': '/api/uploads/import',
                          'client': ('127.0.0.1', 1), 'state': {'principal': Principal('alice')}}, receive, send)
        assert messages[0]['status'] == 503 and not called
        assert (b'retry-after', b'5') in messages[0]['headers']
        assert 'private-review' not in str(messages) + caplog.text
        middleware.limiter.check = lambda *args: 0
        middleware.app = broken
        with pytest.raises(RuntimeError, match='private-review'):
            await middleware({'type': 'http', 'method': 'POST', 'path': '/api/uploads/import',
                          'client': ('127.0.0.1', 1), 'state': {'principal': Principal('alice')}}, receive, send)
    asyncio.run(run())


@pytest.mark.parametrize('path', ['/api/products/1/report.pdf', '/api/products/1/report.csv', '/api/ai/status'])
def test_expensive_gets_share_admission_and_release_on_cancel(path):
    async def run():
        entered, release = asyncio.Event(), asyncio.Event()
        messages = []
        async def endpoint(*args):
            entered.set()
            await release.wait()
        async def receive(): return {'type': 'http.request', 'body': b''}
        async def send(message): messages.append(message)
        middleware = ResourceLimitsMiddleware(endpoint)
        scope = {'type': 'http', 'method': 'GET', 'path': path, 'headers': [],
                 'state': {'principal': Principal('alice')}}
        first = asyncio.create_task(middleware(scope, receive, send))
        await entered.wait()
        await middleware({**scope, 'method': 'POST', 'path': '/api/uploads/import'}, receive, send)
        assert messages[0]['status'] == 429 and middleware.active == 1
        first.cancel()
        with pytest.raises(asyncio.CancelledError): await first
        assert middleware.active == 0 and not middleware.owners
        release.set()
        await middleware(scope, receive, send)
        assert middleware.active == 0
    asyncio.run(run())


def test_retry_after_exposed_to_browser_and_sanitized(client, monkeypatch):
    monkeypatch.setattr(config, 'RATE_LIMIT_GENERAL_REQUESTS', 1)
    with TestClient(create_app()) as limited:
        headers = {'Origin': 'http://localhost:5173'}
        assert limited.get('/api/products', headers=headers).status_code == 200
        response = limited.get('/api/products?search=private-review', headers=headers)
        assert response.status_code == 429
        assert 'Retry-After' in response.headers['access-control-expose-headers']
        assert 'private-review' not in response.text


def test_explicit_local_disable_and_non_http_passthrough(monkeypatch):
    monkeypatch.setattr(config, 'RATE_LIMIT_ENABLED', False)
    async def run():
        called = []
        async def endpoint(*args): called.append(True)
        middleware = RateLimitsMiddleware(endpoint, phase='peer')
        def forbidden(*args): raise AssertionError('disabled limiter invoked')
        middleware.limiter.check = forbidden
        await middleware({'type': 'http'}, None, None)
        middleware.enabled = True
        await middleware({'type': 'lifespan'}, None, None)
        assert called == [True, True]
    asyncio.run(run())


def test_collection_budget_blocks_before_adapter_and_spans_refresh(client, monkeypatch):
    from app.services import collection
    from app.errors import AppError
    monkeypatch.setattr(config, 'RATE_LIMIT_COLLECTION_REQUESTS', 1)
    calls = []
    def reject(*args):
        calls.append(True)
        raise AppError('Synthetic unavailable source.', 422)
    monkeypatch.setattr(collection, 'collect_from_url', reject)
    with TestClient(create_app()) as limited:
        assert limited.post('/api/products/from-url', json={'url': 'https://apps.apple.com/us/app/id123'}).status_code == 422
        assert limited.post('/api/products/from-url', json={'url': 'https://apps.apple.com/us/app/id456'}).status_code == 429
        assert limited.post('/api/products/999/refresh').status_code == 429
        assert calls == [True] and limited.get('/api/products').json() == []


def test_ai_status_and_generation_share_budget_without_model_calls(client, monkeypatch):
    from app.services import ai_summary
    monkeypatch.setattr(config, 'RATE_LIMIT_AI_REQUESTS', 1)
    calls = []
    def available():
        calls.append(True)
        return {'enabled': False}
    monkeypatch.setattr(ai_summary, 'availability', available)
    with TestClient(create_app()) as limited:
        assert limited.get('/api/ai/status').status_code == 200
        assert limited.post('/api/products/999/ai-summary').status_code == 429
        assert limited.get('/api/ai/status').status_code == 429
        assert calls == [True]


def test_peer_gate_rejects_before_jwt_verifier(identity, monkeypatch):
    from app.auth import TokenVerifier
    monkeypatch.setattr(config, 'RATE_LIMIT_PEER_REQUESTS', 1)
    with TestClient(create_app()) as secured:
        assert secured.get('/api/sites').status_code == 200
        def forbidden(*args): raise AssertionError('limited peer reached JWT verification')
        monkeypatch.setattr(TokenVerifier, 'verify', forbidden)
        assert secured.get('/api/products', headers=auth_header(identity())).status_code == 429


@pytest.mark.parametrize('setting,value', [
    ('RATE_LIMIT_GENERAL_REQUESTS', '0'),
    ('RATE_LIMIT_WINDOW_SECONDS', '-1'),
    ('RATE_LIMIT_MAX_IDENTITIES', '0'),
    ('RATE_LIMIT_EXPORT_REQUESTS', 'invalid'),
    ('RATE_LIMIT_ENABLED', 'maybe'),
])
def test_invalid_configuration_fails_startup_without_database_access(monkeypatch, setting, value):
    import runpy
    monkeypatch.setenv(setting, value)
    with pytest.raises(ValueError):
        runpy.run_path(config.__file__)


def test_shared_peer_budget_health_and_preflight_policy(client, identity, monkeypatch):
    monkeypatch.setattr(config, 'RATE_LIMIT_PEER_REQUESTS', 2)
    with TestClient(create_app()) as secured:
        assert secured.get('/api/products', headers=auth_header(identity('alice'))).status_code == 200
        assert secured.get('/api/products', headers=auth_header(identity('bob'))).status_code == 200
        for user in ('alice', 'bob'):
            assert secured.get('/api/products', headers=auth_header(identity(user))).status_code == 429
        assert secured.get('/api/health').status_code == 429
        # CORS-only preflight remains cheap and usable even after the peer budget is spent.
        preflight = secured.options('/api/uploads/import', headers={
            'Origin': 'http://localhost:5173', 'Access-Control-Request-Method': 'POST'})
        assert preflight.status_code == 200
        assert secured.options('/api/uploads/import').status_code == 429
        assert secured.get('/api/health').status_code == 429


def test_staggered_capacity_expiry_preserves_other_identity_budget():
    clock = Clock()
    limiter = WindowLimiter({'general': 1}, 60, 2, clock)
    assert limiter.check(b'a', ('general',)) == 0
    clock.now = 130
    assert limiter.check(b'b', ('general',)) == 0
    clock.now = 159.9
    assert limiter.check(b'c', ('general',)) == 1
    clock.now = 160
    assert limiter.check(b'c', ('general',)) == 0
    assert limiter.check(b'b', ('general',)) == 30
    assert len(limiter.entries) == 2


@pytest.mark.parametrize('operation', ['collection', 'ai'])
def test_source_failures_release_admission_but_do_not_refund_rate_budget(client, monkeypatch, operation):
    from app.errors import AppError
    from app.services import collection, ai_summary
    calls = []
    def fail(*args):
        calls.append(True)
        raise AppError('Synthetic service unavailable.', 503)
    if operation == 'collection':
        monkeypatch.setattr(config, 'RATE_LIMIT_COLLECTION_REQUESTS', 1)
        monkeypatch.setattr(collection, 'collect_from_url', fail)
    else:
        monkeypatch.setattr(config, 'RATE_LIMIT_AI_REQUESTS', 1)
        monkeypatch.setattr(ai_summary, 'availability', fail)
    with TestClient(create_app()) as limited:
        def request():
            if operation == 'collection':
                return limited.post('/api/products/from-url', json={'url': 'https://apps.apple.com/us/app/id123'})
            return limited.get('/api/ai/status')
        assert request().status_code == 503
        current = limited.app.middleware_stack
        while not isinstance(current, ResourceLimitsMiddleware): current = current.app
        assert current.active == 0 and not current.owners
        assert request().status_code == 429
        assert current.active == 0 and not current.owners
        assert limited.post('/api/uploads/preview', files=csv_file()).status_code == 200
        assert calls == [True]


# Same strict loopback, dedicated database and marker guard used by other integration modules.
from .test_postgres_integration import pg, upgrade


def test_postgres_rate_rejection_preserves_data_owner_and_retention(pg, monkeypatch, identity):
    from datetime import timedelta
    from sqlalchemy.orm import sessionmaker
    from app import database
    from app.models import Product, Review, AnalysisResult
    upgrade(pg)
    monkeypatch.setattr(database, 'engine', pg)
    monkeypatch.setattr(database, 'SessionLocal', sessionmaker(bind=pg, autoflush=False, expire_on_commit=False))
    monkeypatch.setattr(config, 'RATE_LIMIT_ANALYSIS_REQUESTS', 1)
    monkeypatch.setattr(config, 'RATE_LIMIT_INGESTION_REQUESTS', 1)
    with TestClient(create_app()) as secured:
        def upload(user):
            return secured.post('/api/uploads/import', headers=auth_header(identity(user)), files=csv_file(),
                                data={'product_name': 'Synthetic rate test', 'columns': '{"text":"review_text"}'})
        alice, bob = upload('alice'), upload('bob')
        assert alice.status_code == bob.status_code == 201
        product_id = alice.json()['id']
        with Session(pg) as db:
            product = db.get(Product, product_id)
            deadline = (product.created_at, product.expires_at)
            assert deadline[1] - deadline[0] == timedelta(days=7)
        assert upload('alice').status_code == 429
        assert secured.post(f'/api/products/{product_id}/reviews', headers=auth_header(identity()),
                            json={'reviews': [{'text': 'Synthetic rejected row'}]}).status_code == 429
        assert secured.get(f'/api/products/{product_id}', headers=auth_header(identity('bob'))).status_code == 404
        with Session(pg) as db:
            assert [db.scalar(select(func.count()).select_from(model))
                    for model in (Product, Review, AnalysisResult)] == [2, 12, 2]
            product = db.get(Product, product_id)
            assert (product.created_at, product.expires_at) == deadline
