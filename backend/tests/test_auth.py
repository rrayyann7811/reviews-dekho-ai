"""Offline asymmetric JWT verification. Deterministic test-only keys are generated in memory."""
import hashlib
import json
import time

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from fastapi.testclient import TestClient

from app import config
from app.auth import TokenVerifier
from app.main import create_app

ISSUER = 'https://identity.example.invalid/auth/v1'
AUDIENCE = 'authenticated'


@pytest.fixture
def identity(monkeypatch, tmp_path):
    # Publicly known test seed, never loaded by application code or deployed as a signing key.
    key = Ed25519PrivateKey.from_private_bytes(hashlib.sha256(b'Reviews Dekho TEST ONLY key').digest())
    public = json.loads(jwt.algorithms.OKPAlgorithm.to_jwk(key.public_key()))
    public.update(kid='test-key', alg='EdDSA', use='sig')
    path = tmp_path / 'public-jwks.json'
    path.write_text(json.dumps({'keys': [public]}))
    for name, value in {'AUTH_MODE': 'jwt', 'AUTH_ISSUER': ISSUER, 'AUTH_AUDIENCE': AUDIENCE,
                        'AUTH_ALGORITHM': 'EdDSA', 'AUTH_JWKS_FILE': str(path), 'AUTH_JWKS_URL': ''}.items():
        monkeypatch.setattr(config, name, value)

    def token(user='alice', *, claims=None, headers=None, signing_key=key, algorithm='EdDSA'):
        now = int(time.time())
        payload = {'iss': ISSUER, 'aud': AUDIENCE, 'sub': user, 'role': 'authenticated',
                   'iat': now - 5, 'exp': now + 600, **(claims or {})}
        payload = {k: v for k, v in payload.items() if v is not None}
        return jwt.encode(payload, signing_key, algorithm=algorithm, headers={'kid': 'test-key', **(headers or {})})

    return token


def auth_header(token):
    return {'Authorization': f'Bearer {token}'}


def test_valid_identity_is_derived_only_from_verified_issuer_and_subject(identity):
    verifier = TokenVerifier()
    assert verifier.verify(identity()).owner_id == hashlib.sha256((ISSUER + '\0alice').encode()).hexdigest()
    assert verifier.verify(identity('bob')).owner_id != verifier.verify(identity()).owner_id
    assert verifier.verify(identity(claims={'user_id': 'bob', 'owner_id': 'bob'})) == verifier.verify(identity())


@pytest.mark.parametrize('claims', [
    {'iss': 'https://attacker.invalid'}, {'aud': 'another-api'}, {'exp': 1}, {'exp': None}, {'iat': None},
    {'iat': int(time.time()) + 3600}, {'nbf': int(time.time()) + 3600}, {'sub': None}, {'sub': ''},
    {'sub': 123}, {'role': 'anon'}, {'role': 'service_role'}, {'role': None}, {'exp': '9999999999'},
    {'iat': False}, {'exp': float('inf')}, {'sub': 'x' * 257},
])
def test_invalid_claims_fail_closed(identity, claims):
    with TestClient(create_app()) as client:
        response = client.get('/api/products', headers=auth_header(identity(claims=claims)))
    assert response.status_code == 401
    assert response.headers['www-authenticate'] == 'Bearer'
    assert response.json() == {'detail': 'A valid user access token is required.'}


@pytest.mark.parametrize('headers', [{'kid': 'unknown'}, {'jku': 'https://attacker.invalid/keys'},
                                      {'jwk': {}}, {'x5u': 'https://attacker.invalid'}, {'crit': ['unknown']}])
def test_token_headers_cannot_select_untrusted_keys(identity, headers):
    with TestClient(create_app()) as client:
        assert client.get('/api/products', headers=auth_header(identity(headers=headers))).status_code == 401


def test_unsigned_forged_symmetric_and_malformed_tokens_rejected(identity):
    wrong_key = Ed25519PrivateKey.from_private_bytes(bytes(range(32)))
    tokens = ['garbage', 'x' * 8193, identity(signing_key=wrong_key),
              identity(signing_key=None, algorithm='none'), identity(signing_key='test-only-shared-secret-of-at-least-32-bytes', algorithm='HS256')]
    with TestClient(create_app()) as client:
        for token in tokens:
            assert client.get('/api/products', headers=auth_header(token)).status_code == 401
        assert client.get('/api/products').status_code == 401
        assert client.get('/api/products', headers={'X-User-ID': 'alice'}).status_code == 401
        assert client.get('/api/products', headers=[('Authorization', 'Bearer a'), ('Authorization', 'Bearer b')]).status_code == 401


def test_authentication_happens_before_reading_upload_body(identity):
    async def receive():
        raise AssertionError('unauthenticated body must not be read')

    import asyncio
    from app.auth import AuthMiddleware
    async def endpoint(scope, receive, send):
        raise AssertionError('unauthenticated request reached endpoint')
    messages = []
    async def send(message):
        messages.append(message)
    asyncio.run(AuthMiddleware(endpoint, 'jwt', TokenVerifier())(
        {'type': 'http', 'path': '/api/uploads/import', 'method': 'POST', 'headers': []}, receive, send))
    assert messages[0]['status'] == 401


def test_jwt_configuration_is_explicit_and_fails_closed(identity, monkeypatch):
    for name, value in [('AUTH_MODE', 'typo'), ('AUTH_ISSUER', ''), ('AUTH_AUDIENCE', ''),
                        ('AUTH_ALGORITHM', 'HS256'), ('AUTH_JWKS_FILE', '')]:
        with monkeypatch.context() as patch:
            patch.setattr(config, name, value)
            with pytest.raises(ValueError):
                create_app()


def test_public_metadata_and_cors_preflight_do_not_require_a_token(client, identity):
    with TestClient(create_app()) as secure:
        assert secure.get('/api/health').status_code == 200
        assert secure.get('/api/sites').status_code == 200
        assert secure.get('/api/ai/status').status_code == 401
        r = secure.options('/api/uploads/import', headers={'Origin': 'http://localhost:5173',
            'Access-Control-Request-Method': 'POST', 'Access-Control-Request-Headers': 'authorization,content-type'})
        assert r.status_code == 200
        assert r.headers['access-control-allow-origin'] == 'http://localhost:5173'


def test_local_mode_rejects_non_loopback_clients(monkeypatch):
    monkeypatch.setattr(config, 'AUTH_MODE', 'local')
    with TestClient(create_app(), client=('203.0.113.5', 12345)) as client:
        assert client.get('/api/products').status_code == 403
        assert client.get('/api/products', headers={'X-Forwarded-For': '127.0.0.1'}).status_code == 403


def test_cryptographic_verification_with_supabase_style_es256_keys(identity, monkeypatch, tmp_path):
    from cryptography.hazmat.primitives.asymmetric import ec
    key = ec.derive_private_key(42, ec.SECP256R1())  # public, deterministic TEST ONLY key
    public = json.loads(jwt.algorithms.ECAlgorithm.to_jwk(key.public_key()))
    public.update(kid='test-key', alg='ES256', use='sig')
    path = tmp_path / 'es256-public.json'
    path.write_text(json.dumps({'keys': [public]}))
    monkeypatch.setattr(config, 'AUTH_ALGORITHM', 'ES256')
    monkeypatch.setattr(config, 'AUTH_JWKS_FILE', str(path))
    verifier = TokenVerifier()
    assert verifier.verify(identity(signing_key=key, algorithm='ES256')).owner_id
    with pytest.raises(jwt.InvalidTokenError):
        verifier.verify(identity(signing_key=key, algorithm='ES256', claims={'is_anonymous': True}))


def test_remote_jwks_cache_rotation_and_outage_are_offline_and_fail_closed(identity, monkeypatch):
    import io
    from pathlib import Path
    from types import SimpleNamespace
    from urllib.error import URLError
    data = json.loads(Path(config.AUTH_JWKS_FILE).read_text())
    monkeypatch.setattr(config, 'AUTH_JWKS_FILE', '')
    monkeypatch.setattr(config, 'AUTH_JWKS_URL', ISSUER + '/.well-known/jwks.json')
    calls = []
    def open_keys(request, *, timeout):
        calls.append(request.full_url)
        assert timeout == 3
        return io.BytesIO(json.dumps(data).encode())
    monkeypatch.setattr('urllib.request.build_opener', lambda *args: SimpleNamespace(open=open_keys))
    verifier = TokenVerifier()
    first = verifier.verify(identity())
    assert verifier.verify(identity()) == first
    for _ in range(3):
        with pytest.raises(jwt.PyJWTError):
            verifier.verify(identity(headers={'kid': 'untrusted-key'}))
    assert calls == [config.AUTH_JWKS_URL]  # unknown kid floods cannot bypass the refresh cooldown
    data['keys'][0]['kid'] = 'rotated-key'
    verifier.client._last_successful_fetch = time.monotonic() - 31
    assert verifier.verify(identity(headers={'kid': 'rotated-key'})) == first
    assert calls == [config.AUTH_JWKS_URL] * 2
    def unavailable(request, *, timeout):
        raise URLError('test outage')
    monkeypatch.setattr('urllib.request.build_opener', lambda *args: SimpleNamespace(open=unavailable))
    with pytest.raises(jwt.PyJWTError):
        TokenVerifier().verify(identity())
    # Losing the identity server does not convert a request to local mode or leak error internals.
    with TestClient(create_app()) as client:
        r = client.get('/api/products', headers=auth_header(identity()))
        assert r.status_code == 401 and 'test outage' not in r.text


@pytest.mark.parametrize('url', ['http://localhost/keys', 'https://user:pass@example.invalid/keys'])
def test_remote_key_configuration_requires_https_without_credentials(identity, monkeypatch, url):
    monkeypatch.setattr(config, 'AUTH_JWKS_FILE', '')
    monkeypatch.setattr(config, 'AUTH_JWKS_URL', url)
    with pytest.raises(ValueError):
        create_app()


def test_verifier_rejects_private_key_material_and_duplicate_key_ids(identity, monkeypatch, tmp_path):
    from pathlib import Path
    public = json.loads(Path(config.AUTH_JWKS_FILE).read_text())['keys'][0]
    path = tmp_path / 'invalid-keys.json'
    monkeypatch.setattr(config, 'AUTH_JWKS_FILE', str(path))
    for keys in [[{**public, 'd': 'NOT-A-PRIVATE-KEY'}], [public, public]]:
        path.write_text(json.dumps({'keys': keys}))
        with pytest.raises(ValueError):
            create_app()
