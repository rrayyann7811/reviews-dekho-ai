"""The backend's responses match what the React frontend reads.

The frontend was built against `frontend/src/demo/demoAnalysis.json`, so every
key in that file must also be present in a live analysis response.
"""
import json

from .conftest import FRONTEND_DEMO_JSON

FRONTEND_API = FRONTEND_DEMO_JSON.parents[1] / "lib/api.js"


def _missing_keys(expected, actual, path=""):
    missing = []
    if isinstance(expected, dict) and isinstance(actual, dict):
        for key, value in expected.items():
            if key not in actual:
                missing.append(f"{path}.{key}")
            else:
                missing += _missing_keys(value, actual[key], f"{path}.{key}")
    elif isinstance(expected, list) and isinstance(actual, list) and expected and actual:
        missing += _missing_keys(expected[0], actual[0], f"{path}[0]")
    return missing


def test_analysis_response_has_every_key_the_frontend_uses(client, product):
    demo = json.loads(FRONTEND_DEMO_JSON.read_text())
    live = client.get(f"/api/products/{product['id']}/analysis").json()
    assert _missing_keys(demo, live) == []


def test_product_summary_has_every_key_the_product_table_uses(client, product):
    [row] = client.get("/api/products").json()
    for key in ("id", "name", "brand", "category", "source", "totalReviews", "averageRating",
                "positivePercent", "analyzedAt"):
        assert key in row
    assert row["source"] in ("upload", "url", "demo", "manual")


def test_preview_has_every_key_the_upload_page_uses(client):
    from .conftest import csv_file

    body = client.post("/api/uploads/preview", files=csv_file()).json()
    for key in ("rowCount", "columns", "sampleRows", "detected", "productName", "warnings"):
        assert key in body
    # The upload page offers these roles and sends them back as the `columns` field.
    assert set(body["detected"]) == {"text", "rating", "date", "title", "reviewer", "productName", "id"}


def test_every_path_in_the_frontend_client_exists(client):
    source = FRONTEND_API.read_text()
    spec_paths = client.get("/openapi.json").json()["paths"]
    for frontend_path, api_path in {
        "'/health'": "/api/health",
        "'/products'": "/api/products",
        "/analysis?include_reviews=false`": "/api/products/{product_id}/analysis",
        "/analyze?include_reviews=false`": "/api/products/{product_id}/analyze",
        "/reviews?${params}`": "/api/products/{product_id}/reviews",
        "/reviews/${encodeURIComponent(reviewId)}": "/api/products/{product_id}/reviews/{review_id}",
        "/refresh`": "/api/products/{product_id}/refresh",
        "'/products/from-url'": "/api/products/from-url",
        "'/uploads/preview'": "/api/uploads/preview",
        "'/uploads/import'": "/api/uploads/import",
        "/report.${format}`": "/api/products/{product_id}/report.csv",
    }.items():
        assert frontend_path in source, frontend_path
        assert api_path in spec_paths, api_path


def test_error_bodies_are_strings_the_frontend_can_show(client):
    for response in (client.get("/api/products/999/analysis"), client.get("/api/products/abc"),
                     client.post("/api/uploads/preview", files={"file": ("a.txt", b"x", "text/plain")})):
        assert isinstance(response.json()["detail"], str)


def test_frontend_site_list_matches_the_backend(client):
    """frontend/src/lib/sites.js gives instant feedback offline; it must agree with the backend adapters."""
    import re

    source = (FRONTEND_API.parent / "sites.js").read_text()
    frontend = {}
    for block in re.findall(r"\{\s*id: '([^']+)',(.*?)\n  \}", source, flags=re.S):
        site_id, body = block
        frontend[site_id] = {
            "hosts": re.findall(r"'([^']+)'", re.search(r"hosts: \[(.*?)\]", body).group(1)),
            "status": re.search(r"status: '(\w+)'", body).group(1),
        }
    backend = {s["id"]: {"hosts": s["hosts"], "status": s["status"]} for s in client.get("/api/sites").json()}
    assert frontend == backend


def test_collected_product_fields_the_analysis_page_uses(client):
    from app.schemas import AnalysisProduct, ProductSummary

    for model in (AnalysisProduct, ProductSummary):
        aliases = {f.alias for f in model.model_fields.values()}
        assert {"sourceUrl", "sourceSiteName", "sourceRegion", "collectedAt"} <= aliases
