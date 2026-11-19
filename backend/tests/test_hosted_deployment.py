import json
import logging
import os
from pathlib import Path
import subprocess
import sys

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.orm import Session

from app import config, database
from app.hosted import admit_expensive_work
from app.main import create_app
from app.model_assets import FILES

from .test_auth import auth_header, identity  # noqa: F401
from .test_postgres_integration import local_test_url, pg  # noqa: F401

BACKEND = Path(__file__).resolve().parents[1]


def test_deployment_configs_keep_model_in_function_and_frontend_is_static():
    backend = json.loads((BACKEND / "vercel.json").read_text())
    function = backend["functions"]["server.py"]
    assert backend["fluid"] and backend["regions"] == ["bom1"] and function["maxDuration"] == 35
    assert backend["buildCommand"] == "MODEL_DIR=models/twitter-roberta-sentiment python scripts/download_model.py"
    assert "models/twitter-roberta-sentiment/**" in function["includeFiles"]
    assert "app/**" in function["includeFiles"]
    assert {"sqlite", "sqlite3", "db"} <= {p.suffix.lstrip(".") for p in map(Path, function["excludeFiles"].strip("{}").split(","))}
    assert set(FILES) == {"onnx/model_quantized.onnx", "config.json", "tokenizer.json"}
    assert (BACKEND / ".python-version").read_text().strip() == "3.14"
    frontend = json.loads((BACKEND.parent / "frontend/vercel.json").read_text())
    assert frontend["buildCommand"] == "npm run build" and frontend["outputDirectory"] == "dist"
    assert frontend["rewrites"] == [{"source": "/(.*)", "destination": "/index.html"}]
    assert not ({"functions", "crons", "env"} & frontend.keys())


def test_vercel_entrypoint_fails_closed_without_contacting_database():
    env = os.environ | {
        "PUBLIC_DEMO": "true", "REQUIRE_TRANSFORMER": "true", "SENTIMENT_ENGINE": "transformer",
        "DATABASE_URL": "postgresql://runtime.fixture:fixture-only@aws-fixture.pooler.supabase.com:6543/postgres?sslmode=verify-full",
        "DB_POOL_MODE": "null", "AUTH_MODE": "jwt", "AUTH_JWKS_FILE": "",
        "AUTH_JWKS_URL": "https://auth.example.invalid/auth/v1/.well-known/jwks.json",
        "AUTH_ISSUER": "https://auth.example.invalid/auth/v1", "AUTH_AUDIENCE": "authenticated",
        "CORS_ORIGINS": "https://demo.example.invalid", "MAX_ROWS": "10", "MAX_REVIEW_CHARS": "1000",
        "MAX_UPLOAD_BYTES": "1048576", "MAX_REQUEST_BYTES": "1310720",
    }
    startup = """
import ssl
from unittest.mock import patch
import sqlalchemy

with patch("sqlalchemy.create_engine", wraps=sqlalchemy.create_engine) as create_engine:
    import server
    assert server.app
    tls = create_engine.call_args.kwargs["connect_args"]
    assert tls["sslmode"] == "verify-full"
    ssl.create_default_context(cafile=tls["sslrootcert"])
"""

    def load(settings):
        return subprocess.run([sys.executable, "-c", startup], cwd=BACKEND,
                              env=settings, capture_output=True, text=True, timeout=10)

    result = load(env)
    assert result.returncode == 0, result.stderr
    for update in ({"PUBLIC_DEMO": "false"}, {"DB_POOL_MODE": "queue"},
                   {"DATABASE_URL": env["DATABASE_URL"].replace(":6543", ":5432")},
                   {"DATABASE_URL": env["DATABASE_URL"].replace("verify-full", "require")}):
        result = load(env | update)
        assert result.returncode != 0 and "Hosted configuration could not initialize" in result.stderr
        assert "fixture-only" not in result.stderr


def test_hosted_optional_features_are_blocked_after_auth(client, identity, monkeypatch):
    monkeypatch.setattr(config, "PUBLIC_DEMO", True)
    frontend_origin = "https://reviews-dekho-ai.vercel.app"
    monkeypatch.setattr(config, "CORS_ORIGINS", [frontend_origin])
    paths = [("POST", "/products/from-url"), ("POST", "/products/1/refresh"),
             ("POST", "/products/1/ai-summary"), ("GET", "/products/1/ai-summary"),
             ("POST", "/products/1/jobs"), ("GET", "/jobs/1"), ("POST", "/jobs/1/cancel")]
    with TestClient(create_app()) as hosted:
        for method, path in paths:
            assert hosted.request(method, "/api" + path).status_code == 401
            response = hosted.request(method, "/api" + path, headers=auth_header(identity()))
            assert response.status_code == 404
            assert "unavailable in the hosted showcase" in response.json()["detail"]
        assert hosted.get("/openapi.json").status_code == 404
        preflight = hosted.options("/api/uploads/import", headers={
            "Origin": frontend_origin,
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "authorization,content-type,idempotency-key",
        })
        assert preflight.status_code == 200
        assert preflight.headers["Access-Control-Allow-Origin"] == frontend_origin
        health = hosted.get("/api/health", headers={"Origin": frontend_origin, **auth_header(identity())})
        assert hosted.get("/api/health").status_code == 401
        assert health.status_code == 200 and health.headers["Cache-Control"] == "private, no-store"
        assert health.headers["Access-Control-Allow-Origin"] == frontend_origin


def test_hosted_unhandled_errors_do_not_expose_exception_values(client, identity, monkeypatch, caplog):
    monkeypatch.setattr(config, "PUBLIC_DEMO", True)
    app = create_app()

    @app.get("/api/failure")
    def failure():
        raise RuntimeError("synthetic credential that must never be logged")

    with caplog.at_level(logging.ERROR), TestClient(app) as hosted:
        response = hosted.get("/api/failure", headers=auth_header(identity()))
    assert response.status_code == 500
    assert response.headers["Cache-Control"] == "private, no-store"
    assert "Hosted request failed (RuntimeError)" in caplog.text
    assert "synthetic credential" not in caplog.text + response.text


def test_postgres_admission_is_shared_and_releases_on_transaction_end(pg, monkeypatch):
    monkeypatch.setattr(config, "PUBLIC_DEMO", True)
    with Session(pg) as first, Session(pg) as second:
        admit_expensive_work(first)
        with pytest.raises(HTTPException) as reject:
            admit_expensive_work(second)
        assert reject.value.status_code == 429 and reject.value.headers["Retry-After"] == "5"
        second.rollback()
        first.rollback()
        admit_expensive_work(second)
        second.commit()
        admit_expensive_work(first)


def test_hosted_pg_applies_timeouts_inside_every_transaction(pg, monkeypatch):
    monkeypatch.setattr(config, "PUBLIC_DEMO", True)
    monkeypatch.setattr(config, "DB_POOL_MODE", "null")
    engine = database.make_engine(local_test_url(os.environ["TEST_POSTGRESQL_URL"]).render_as_string(hide_password=False))
    try:
        with engine.connect() as conn:
            for _ in range(2):
                with conn.begin():
                    assert conn.scalar(text("SHOW timezone")) == "UTC"
                    for name, expect in (("statement_timeout", config.DB_STATEMENT_TIMEOUT_MS),
                                         ("lock_timeout", config.DB_LOCK_TIMEOUT_MS)):
                        assert conn.scalar(text(f"SELECT extract(epoch FROM current_setting('{name}')::interval) * 1000")) == expect
    finally:
        engine.dispose()
