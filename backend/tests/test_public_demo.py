import json
import os
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from threading import Event
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from app import config, database, model_assets
from app.errors import AppError
from app.main import create_app
from app.models import AnalysisResult, ImportReceipt, Product, Review
from app.nlp import engines
from app.services import analysis, retention

from .conftest import DEFAULT_COLUMNS, csv_file
from .test_auth import auth_header, identity  # noqa: F401
from .test_postgres_integration import pg, upgrade  # noqa: F401

KEY = "b1f7c70b-4278-4793-bd82-99e54f17095a"


@pytest.fixture(params=["sqlite", "postgresql"])
def store(request, tmp_path, monkeypatch):
    if request.param == "sqlite":
        engine = database.make_engine(f"sqlite:///{tmp_path / 'demo.sqlite3'}")
        database.init_db(engine)
    else:
        engine = request.getfixturevalue("pg")
        upgrade(engine)
    monkeypatch.setattr(database, "engine", engine)
    monkeypatch.setattr(database, "SessionLocal", sessionmaker(bind=engine, autoflush=False, expire_on_commit=False))
    yield engine
    if request.param == "sqlite":
        engine.dispose()


def post(client, identity, *, key=KEY, owner="alice", name="Demo", columns=None, files=None):
    headers = auth_header(identity(owner))
    if key is not None:
        headers["Idempotency-Key"] = key
    return client.post("/api/uploads/import", headers=headers, files=files or csv_file(),
                       data={"product_name": name, "columns": json.dumps(columns or DEFAULT_COLUMNS)})


def counts(engine):
    with Session(engine) as db:
        return tuple(db.scalar(select(func.count()).select_from(model))
                     for model in (Product, Review, AnalysisResult, ImportReceipt))


def test_replay_conflict_status_and_owner_isolation(store, identity):
    with TestClient(create_app()) as client:
        url = f"/api/uploads/import-status/{KEY}"
        alice, bob = auth_header(identity("alice")), auth_header(identity("bob"))
        assert client.get(url).status_code == 401
        assert post(client, identity, key="too-short").status_code == 422
        first = post(client, identity)
        assert first.status_code == 201, first.text
        assert client.get(url, headers=bob).status_code == 404
        assert client.get(url, headers=alice).json() == first.json()
        assert client.patch(f"/api/products/{first.json()['id']}", headers=alice, json={"name": "Edited"}).status_code == 200
        reordered = dict(reversed(list(DEFAULT_COLUMNS.items())))
        assert post(client, identity, name=" Demo ", columns=reordered).json() == first.json()
        assert post(client, identity, name="Other").status_code == 409
        assert post(client, identity, files=csv_file(name="other.csv")).status_code == 409
        other = post(client, identity, owner="bob")
        assert other.status_code == 201 and other.json()["id"] != first.json()["id"]
        assert client.get(url, headers=bob).json() == other.json()
    assert counts(store) == (2, 12, 2, 2)


def test_two_instances_share_the_same_import_claim(store, identity, monkeypatch):
    entered, release, contending = Event(), Event(), Event()
    original = analysis.run_analysis
    from app.services import import_receipts
    original_claim = import_receipts.claim

    def claim(db, key, fingerprint):
        if entered.is_set():
            contending.set()
        return original_claim(db, key, fingerprint)

    def hold(*args, **kwargs):
        entered.set()
        assert release.wait(5)
        return original(*args, **kwargs)

    monkeypatch.setattr(analysis, "run_analysis", hold)
    monkeypatch.setattr(import_receipts, "claim", claim)
    with TestClient(create_app()) as first, TestClient(create_app()) as second, ThreadPoolExecutor(2) as pool:
        one = pool.submit(post, first, identity)
        try:
            assert entered.wait(5)
            two = pool.submit(post, second, identity)
            assert contending.wait(5)
        finally:
            release.set()
        first_result, second_result = one.result(timeout=8), two.result(timeout=8)
    assert first_result.status_code == second_result.status_code == 201
    assert first_result.json() == second_result.json()
    assert counts(store) == (1, 6, 1, 1)


def test_rollback_then_recover_without_the_import_response(store, identity, monkeypatch):
    original = analysis.run_analysis

    def fail(*args, **kwargs):
        original(*args, **kwargs)
        raise AppError("Synthetic pre-commit failure", 503)

    with TestClient(create_app()) as client:
        with monkeypatch.context() as patch:
            patch.setattr(analysis, "run_analysis", fail)
            assert post(client, identity).status_code == 503
            assert counts(store) == (0, 0, 0, 0)
        # Drop the response at the ASGI boundary after the database transaction has committed.
        async def drop_response(scope, receive, send):
            async def discard(message):
                if scope["type"] == "http" and scope["path"] == "/api/uploads/import":
                    raise OSError("Synthetic lost response")
                await send(message)
            await client.app(scope, receive, discard)

        with TestClient(drop_response) as interrupted:
            with pytest.raises(OSError, match="Synthetic lost response"):
                post(interrupted, identity)
        recovered = client.get(f"/api/uploads/import-status/{KEY}", headers=auth_header(identity()))
        assert recovered.status_code == 200
        assert post(client, identity).json() == recovered.json()
        assert counts(store) == (1, 6, 1, 1)


def test_deleted_receipt_survives_until_expiry(store, identity):
    with TestClient(create_app()) as client:
        product = post(client, identity).json()
        headers = auth_header(identity())
        assert client.delete(f"/api/products/{product['id']}", headers=headers).status_code == 204
        assert client.get(f"/api/uploads/import-status/{KEY}", headers=headers).status_code == 410
        assert post(client, identity).status_code == 410
        assert counts(store) == (0, 0, 0, 1)
        with Session(store) as db:
            receipt = db.scalars(select(ImportReceipt)).one()
            assert receipt.product_id is None and receipt.result is None
            expiry = receipt.expires_at
        assert retention.run_cleanup(store, now=expiry - timedelta(seconds=1))["receipts"]["deleted"] == 0
        assert retention.run_cleanup(store, now=expiry, dry_run=True)["receipts"]["matched"] == 1
        assert retention.run_cleanup(store, now=expiry)["receipts"]["deleted"] == 1
    assert counts(store) == (0, 0, 0, 0)


def test_demo_requires_key_and_returns_actual_limits(client, identity, monkeypatch):
    monkeypatch.setattr(config, "PUBLIC_DEMO", True)
    monkeypatch.setattr(config, "MAX_ROWS", 10)
    with TestClient(create_app()) as secure:
        assert post(secure, identity, key=None).status_code == 422
        response = secure.get("/api/uploads/limits", headers=auth_header(identity()))
        assert response.json()["maxRows"] == 10
        cors = secure.options("/api/uploads/import", headers={
            "Origin": config.CORS_ORIGINS[0], "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "Authorization, Idempotency-Key",
        })
        assert cors.status_code == 200
        assert "Idempotency-Key" in cors.headers["Access-Control-Allow-Headers"]


def test_model_manifest_detects_damage(tmp_path, monkeypatch):
    path = tmp_path / "weights.onnx"
    path.write_bytes(b"disposable fixture")
    monkeypatch.setattr(model_assets, "FILES", {"onnx/weights.onnx": model_assets.sha256(path)})
    model_assets.verify_model_files(tmp_path)
    path.write_bytes(b"changed")
    with pytest.raises(ValueError, match="checksum"):
        model_assets.verify_model_files(tmp_path)


@pytest.mark.parametrize("failure", ["integrity", "load", "provider", "predict"])
def test_strict_model_failures_never_commit_or_fall_back(client, monkeypatch, tmp_path, failure):
    product = client.post("/api/uploads/import", files=csv_file(), data={
        "product_name": "Before", "columns": json.dumps(DEFAULT_COLUMNS),
    }).json()
    before = client.get(f"/api/products/{product['id']}/analysis").json()
    (tmp_path / "model_quantized.onnx").touch()

    def fail():
        raise RuntimeError("private path must not leak")

    def create_engine():
        if failure == "load":
            fail()
        provider = "OtherProvider" if failure == "provider" else "CPUExecutionProvider"
        return SimpleNamespace(session=SimpleNamespace(get_providers=lambda: [provider]), predict=lambda _: fail())

    listen = []
    monkeypatch.setattr(config, "REQUIRE_TRANSFORMER", True)
    monkeypatch.setattr(config, "MODEL_DIR", tmp_path)
    monkeypatch.setattr(engines, "verify_model_files", lambda path: fail() if failure == "integrity" else listen.append(path))
    monkeypatch.setattr(engines, "TransformerEngine", create_engine)
    monkeypatch.setattr(engines._vader, "predict", lambda _: pytest.fail("VADER ran"))
    engines.reset_engines()
    try:
        failed = client.post("/api/uploads/import", files=csv_file(), data={
            "product_name": "Failed", "columns": json.dumps(DEFAULT_COLUMNS),
        })
        reanalysis = client.post(f"/api/products/{product['id']}/analyze")
        for response in (failed, reanalysis):
            assert response.status_code == 503
            assert response.json() == {"detail": engines.ONNX_UNAVAILABLE}
        assert listen == ([] if failure == "integrity" else [tmp_path])
        assert len(client.get("/api/products").json()) == 1
        assert client.get(f"/api/products/{product['id']}/analysis").json() == before
    finally:
        engines.reset_engines()


def test_invalid_demo_profiles_fail_closed():
    code = "from app import config; assert config.PUBLIC_DEMO"
    env = os.environ | {
        "PUBLIC_DEMO": "true", "REQUIRE_TRANSFORMER": "true", "SENTIMENT_ENGINE": "transformer",
        "AUTH_MODE": "jwt", "DATABASE_URL": "postgresql://db.example.invalid/showcase",
        "CORS_ORIGINS": "https://demo.example.invalid", "MAX_ROWS": "10",
        "MAX_REVIEW_CHARS": "1000", "MAX_UPLOAD_BYTES": "1048576", "MAX_REQUEST_BYTES": "1310720",
    }
    assert subprocess.run([sys.executable, "-c", code], env=env, capture_output=True).returncode == 0
    for name, invalid in (("MAX_ROWS", "25"), ("REQUIRE_TRANSFORMER", "false"), ("AUTH_MODE", "local"),
                          ("CORS_ORIGINS", "*"), ("RATE_LIMIT_ENABLED", "false"), ("MAX_EXPENSIVE_REQUESTS", "2")):
        result = subprocess.run([sys.executable, "-c", code], env=env | {name: invalid}, capture_output=True)
        assert result.returncode != 0
        assert b"PUBLIC_DEMO" in result.stderr
