"""Two-account regression tests use offline identities and synthetic reviews only."""
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.database import SessionLocal
from app.main import create_app
from app.models import AnalysisResult, Product, Review

from .conftest import csv_file, import_file
from .test_auth import auth_header, identity
from .test_url_collection import APP_URL, apple


@pytest.fixture
def secure(client, identity):
    with TestClient(create_app()) as secured:
        yield secured


def add(secure, identity, user='alice', **extra):
    headers = auth_header(identity(user))
    response = secure.post('/api/uploads/import', headers=headers, files=csv_file(),
                           data={'product_name': 'Synthetic phone', 'columns': '{"text":"review_text","id":"review_id","rating":"rating"}', **extra})
    assert response.status_code == 201, response.text
    product = response.json()
    run = secure.get(f'/api/products/{product["id"]}/analysis', headers=headers).json()['analysisId']
    return product['id'], run


def blocked_actions(product, run):
    return [
        ('GET', f'/api/products/{product}', None),
        ('GET', f'/api/products/{product}/analysis', None),
        ('POST', f'/api/products/{product}/analyze', None),
        ('POST', f'/api/products/{product}/refresh', None),
        ('PATCH', f'/api/products/{product}', {'name': 'Hijacked', 'ownerId': 'alice'}),
        ('DELETE', f'/api/products/{product}', None),
        ('GET', f'/api/products/{product}/reviews', None),
        ('GET', f'/api/products/{product}/reviews/A1', None),
        ('POST', f'/api/products/{product}/reviews', {'reviews': [{'text': 'Great battery'}]}),
        ('DELETE', f'/api/products/{product}/reviews/A1', None),
        ('GET', f'/api/history/{run}', None),
        ('DELETE', f'/api/history/{run}', None),
        ('GET', f'/api/products/{product}/report.pdf?analysis_id={run}', None),
        ('GET', f'/api/products/{product}/report.csv?analysis_id={run}&include_reviewer=true', None),
        ('GET', f'/api/products/{product}/ai-summary', None),
        ('POST', f'/api/products/{product}/ai-summary', None),
    ]


def test_lists_and_history_are_private_and_cross_owner_access_is_not_found(secure, identity):
    a, ar = add(secure, identity)
    b, br = add(secure, identity, 'bob')
    alice, bob = auth_header(identity()), auth_header(identity('bob'))
    assert [p['id'] for p in secure.get('/api/products', headers=alice).json()] == [a]
    assert [p['id'] for p in secure.get('/api/products', headers=bob).json()] == [b]
    assert [r['id'] for r in secure.get('/api/history', headers=alice).json()] == [ar]
    assert secure.get(f'/api/history?product_id={b}', headers=alice).json() == []
    before = secure.get(f'/api/products/{b}/analysis', headers=bob).json()
    for method, path, body in blocked_actions(b, br):
        response = secure.request(method, path, headers=alice, **({'json': body} if body else {}))
        assert response.status_code == 404, (method, path, response.text)
    assert secure.get(f'/api/products/{b}/analysis', headers=bob).json() == before
    # Both owners can still export their own stored analyses.
    for headers, product, run in [(alice, a, ar), (bob, b, br)]:
        for extension in ['pdf', 'csv']:
            response = secure.get(f'/api/products/{product}/report.{extension}?analysis_id={run}', headers=headers)
            assert response.status_code == 200
            assert 'attachment' in response.headers['content-disposition']


def test_comparisons_and_foreign_run_selectors_are_scoped(secure, identity):
    a, ar = add(secure, identity)
    b, br = add(secure, identity, 'bob')
    c, cr = add(secure, identity)
    headers = auth_header(identity())
    assert secure.get(f'/api/compare?product_a={a}&product_b={c}', headers=headers).status_code == 200
    for query in [f'product_a={a}&product_b={b}', f'product_a={b}&product_b={a}',
                  f'product_a={a}&product_b={c}&analysis_a={br}',
                  f'product_a={a}&product_b={c}&analysis_b={br}']:
        assert secure.get('/api/compare?' + query, headers=headers).status_code == 404
    for path in [f'/api/products/{a}/reviews', f'/api/products/{a}/reviews/A1',
                 f'/api/products/{a}/report.csv', f'/api/products/{a}/report.pdf',
                 f'/api/products/{a}/ai-summary']:
        assert secure.get(path + f'?analysis_id={br}', headers=headers).status_code == 404


def test_all_api_data_routes_require_authentication_before_validation(secure):
    spec = secure.get('/openapi.json').json()
    seen = 0
    for path, operations in spec['paths'].items():
        for method in operations:
            if method.upper() not in {'GET', 'POST', 'PATCH', 'DELETE'}:
                continue
            if method == 'get' and path in {'/api/health', '/api/sites'}:
                continue
            url = path.replace('{product_id}', '1').replace('{review_id}', 'A1').replace('{analysis_id}', '1')
            response = secure.request(method, url)
            assert response.status_code == 401, (method, url, response.text)
            seen += 1
    assert seen == 24


def test_client_supplied_owner_and_subject_fields_never_assign_ownership(secure, identity):
    alice = auth_header(identity(claims={'owner_id': 'bob', 'user_id': 'bob'}))
    r = secure.post('/api/products?owner_id=bob', headers={**alice, 'X-User-ID': 'bob'},
                    json={'name': 'Synthetic manual', 'owner_id': 'bob', 'ownerId': 'bob', 'userId': 'bob'})
    assert r.status_code == 201
    pid = r.json()['id']
    b, _ = add(secure, identity, owner_id='bob', ownerId='bob', user_id='bob')
    for product in [pid, b]:
        assert secure.get(f'/api/products/{product}', headers=auth_header(identity('bob'))).status_code == 404
        assert secure.get(f'/api/products/{product}', headers=auth_header(identity())).status_code == 200
    assert secure.patch(f'/api/products/{pid}', headers=alice, json={'ownerId': 'bob'}).status_code == 200
    assert secure.get(f'/api/products/{pid}', headers=auth_header(identity('bob'))).status_code == 404


def test_local_records_remain_local_and_jwt_records_do_not_leak_into_local_mode(client, secure, identity):
    local = import_file(client).json()['id']
    remote, _ = add(secure, identity)
    assert secure.get(f'/api/products/{local}', headers=auth_header(identity())).status_code == 404
    assert client.get(f'/api/products/{remote}').status_code == 404
    assert [p['id'] for p in client.get('/api/products').json()] == [local]
    with SessionLocal() as db:
        assert db.get(Product, local).owner_id == 'local'
        assert db.get(Product, local).expires_at is None


def test_same_account_survives_app_restart_and_has_fixed_seven_day_data_lifetime(secure, identity):
    pid, _ = add(secure, identity)
    with SessionLocal() as db:
        product = db.get(Product, pid)
        expiry = product.expires_at
        delta = product.expires_at - product.created_at
        assert timedelta(days=7) - timedelta(seconds=2) < delta < timedelta(days=7) + timedelta(seconds=2)
    with TestClient(create_app()) as restarted:
        headers = auth_header(identity())
        assert restarted.get(f'/api/products/{pid}', headers=headers).status_code == 200
        assert restarted.post(f'/api/products/{pid}/analyze', headers=headers).status_code == 200
    with SessionLocal() as db:
        assert db.get(Product, pid).expires_at == expiry


def test_expired_product_and_all_historical_data_are_inaccessible(secure, identity):
    pid, run = add(secure, identity)
    with SessionLocal() as db:
        db.get(Product, pid).expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
        db.commit()
    headers = auth_header(identity())
    assert secure.get('/api/products', headers=headers).json() == []
    assert secure.get('/api/history', headers=headers).json() == []
    for method, path, body in blocked_actions(pid, run):
        assert secure.request(method, path, headers=headers, **({'json': body} if body else {})).status_code == 404
    assert secure.get(f'/api/compare?product_a={pid}&product_b={pid}', headers=headers).status_code == 404
    # Expiring review data does not expire the user's identity/account.
    assert secure.post('/api/products', headers=headers, json={'name': 'New synthetic phone'}).status_code == 201


def test_collected_products_are_unique_per_owner_and_refresh_does_not_extend_retention(secure, identity, apple):
    def collect(user):
        return secure.post('/api/products/from-url', headers=auth_header(identity(user)), json={'url': APP_URL})
    a, b = collect('alice'), collect('bob')
    assert a.status_code == b.status_code == 201
    assert a.json()['id'] != b.json()['id']
    with SessionLocal() as db:
        expiry = db.get(Product, a.json()['id']).expires_at
    again = collect('alice')
    assert again.status_code == 200 and again.json()['id'] == a.json()['id']
    with SessionLocal() as db:
        assert db.get(Product, a.json()['id']).expires_at == expiry
        assert db.scalar(select(func.count()).select_from(Product)) == 2


def test_purge_removes_originals_snapshots_and_ai_but_keeps_local_and_active_data(client, secure, identity):
    from app.models import AiSummary
    from app.services.retention import purge_expired_products
    from app.auth import TokenVerifier
    local = import_file(client).json()['id']
    expired, run = add(secure, identity)
    active, _ = add(secure, identity, 'bob')
    with SessionLocal.begin() as db:
        db.get(Product, expired).expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
        db.add(AiSummary(analysis_id=run, model='synthetic-test-only', prompt_version=1,
                         status='rejected', attempts=1, sentences=[], problems=[]))
    with SessionLocal.begin() as db:
        # Bob's cleanup cannot delete Alice's rows, even when expired.
        assert purge_expired_products(db, owner_id=TokenVerifier().verify(identity('bob')).owner_id) == 0
    with SessionLocal.begin() as db:
        assert purge_expired_products(db) == 1
    with SessionLocal() as db:
        assert db.get(Product, expired) is None
        assert db.get(AnalysisResult, run) is None
        assert db.scalar(select(func.count()).select_from(Review).where(Review.product_id == expired)) == 0
        assert db.scalar(select(func.count()).select_from(AiSummary)) == 0
        assert db.get(Product, local) is not None
        assert db.get(Product, active) is not None
    with SessionLocal.begin() as db:
        assert purge_expired_products(db) == 0


def test_expired_collection_can_be_created_again_without_claiming_other_owners(secure, identity, apple):
    headers = auth_header(identity())
    def collect():
        return secure.post('/api/products/from-url', headers=headers, json={'url': APP_URL})
    first = collect().json()['id']
    # Another active record ensures SQLite doesn't reuse the expired row's primary key in this test.
    other, _ = add(secure, identity, 'bob')
    with SessionLocal.begin() as db:
        db.get(Product, first).expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
    response = collect()
    assert response.status_code == 201
    assert response.json()['id'] != first
    with SessionLocal() as db:
        assert db.get(Product, first) is None
        assert db.get(Product, other) is not None
