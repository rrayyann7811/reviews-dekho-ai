"""Health check, error format and CORS."""
from fastapi import APIRouter
from fastapi.testclient import TestClient

from app.main import app


def test_health(client):
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "database": "ok", "version": "0.4.0"}


def test_unknown_path_returns_readable_404(client):
    response = client.get("/api/nothing-here")
    assert response.status_code == 404
    assert response.json() == {"detail": "This address doesn’t exist on the API."}


def test_validation_errors_are_a_readable_string(client):
    response = client.get("/api/products/not-a-number")
    assert response.status_code == 422
    body = response.json()
    assert isinstance(body["detail"], str) and "product_id" in body["detail"]
    assert body["errors"][0]["field"] == "product_id"


def test_wrong_method_is_405(client):
    assert client.put("/api/products").status_code == 405


def test_cors_allows_the_frontend_origin(client):
    response = client.options("/api/products", headers={
        "Origin": "http://localhost:5173", "Access-Control-Request-Method": "POST"})
    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://localhost:5173"
    simple = client.get("/api/health", headers={"Origin": "http://localhost:5173"})
    assert simple.headers["access-control-allow-origin"] == "http://localhost:5173"


def test_cors_rejects_other_origins(client):
    response = client.get("/api/health", headers={"Origin": "https://evil.example"})
    assert "access-control-allow-origin" not in response.headers


def test_unexpected_errors_return_500_without_internals(client):
    router = APIRouter()

    @router.get("/api/test-crash")
    def crash():
        raise RuntimeError("secret internal detail")

    app.include_router(router)
    try:
        with TestClient(app, raise_server_exceptions=False) as c:
            response = c.get("/api/test-crash")
        assert response.status_code == 500
        assert "secret" not in response.text
        assert response.json()["detail"].startswith("Something went wrong")
    finally:
        app.router.routes[:] = [r for r in app.router.routes if getattr(r, "path", "") != "/api/test-crash"]


def test_swagger_docs_are_served(client):
    assert client.get("/docs").status_code == 200
    spec = client.get("/openapi.json").json()
    assert spec["info"]["title"] == "Reviews Dekho AI API"
    assert "/api/uploads/import" in spec["paths"]
