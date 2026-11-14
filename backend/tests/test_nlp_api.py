"""Phase 4 through the API: product type, engine records, language status, compatibility."""
import json

from .conftest import csv_file, import_file


def test_products_have_a_type_that_chooses_the_features(client):
    app = client.post("/api/products", json={"name": "Notes", "domain": "app"}).json()
    assert app["domain"] == "app"
    client.post(f"/api/products/{app['id']}/reviews", json={"reviews": [
        {"text": "I can't log in and the battery drains"}]})
    aspects = {a["aspect"] for a in client.get(f"/api/products/{app['id']}/analysis").json()["aspects"]}
    assert "Login & account" in aspects and "Battery" not in aspects
    assert client.post("/api/products", json={"name": "X", "domain": "car"}).status_code == 422


def test_changing_the_type_applies_from_the_next_run_only(client):
    product = client.post("/api/products", json={"name": "Thing"}).json()
    url = f"/api/products/{product['id']}"
    client.post(f"{url}/reviews", json={"reviews": [{"text": "Great battery but I can't log in"}]})
    first = client.get(f"{url}/analysis").json()
    assert client.patch(url, json={"domain": "app"}).json()["domain"] == "app"
    second = client.post(f"{url}/analyze").json()
    assert {a["aspect"] for a in first["aspects"]} == {"Battery"}
    assert "Login & account" in {a["aspect"] for a in second["aspects"]}
    assert client.get(f"/api/history/{first['analysisId']}").json()["aspects"] == first["aspects"]  # unchanged


def test_upload_can_be_marked_as_app_reviews(client):
    text = "review\nKeeps crashing after the update\nToo many ads\n"
    product = import_file(client, files=csv_file(text), columns={"text": "review"}, domain="app").json()
    assert product["domain"] == "app"
    analysis = client.get(f"/api/products/{product['id']}/analysis").json()
    assert {a["aspect"] for a in analysis["aspects"]} == {"Crashes & stability", "Updates", "Ads"}
    assert analysis["engine"]["domain"] == "app"
    bad = import_file(client, files=csv_file(text), columns={"text": "review"}, domain="spaceship")
    assert bad.status_code == 422


def test_every_run_records_its_engine(client, product):
    analysis = client.get(f"/api/products/{product['id']}/analysis").json()
    assert analysis["engine"]["id"] == "vader" and analysis["engine"]["pipelineVersion"] == 2
    assert analysis["engine"]["fallbackReason"] is None
    [entry] = client.get("/api/history").json()
    assert entry["engine"] == analysis["engine"]


def test_language_status_reaches_the_api_and_the_csv(client):
    text = "review,stars\nExcellent and fast,5\n\"bakwas app hai, paisa barbaad\",1\n"
    product = import_file(client, files=csv_file(text), columns={"text": "review", "rating": "stars"}).json()
    analysis = client.get(f"/api/products/{product['id']}/analysis").json()
    hinglish = analysis["reviews"][1]
    assert hinglish["status"] == "language_not_supported" and hinglish["sentiment"] is None
    assert analysis["stats"]["notAnalysed"] == {"languageNotSupported": 1}
    assert product["positivePercent"] == 100.0
    page = client.get(f"/api/products/{product['id']}/reviews", params={"sentiment": "positive"}).json()
    assert [r["id"] for r in page["items"]] == ["R-1"]
    csv_text = client.get(f"/api/products/{product['id']}/report.csv").content.decode("utf-8-sig")
    assert "bakwas app hai" in csv_text  # original text kept in exports


def test_old_snapshots_without_phase4_fields_are_still_served(client, product):
    """Runs stored before Phase 4 have no status/language/usedTitle per review and no analysedReviews."""
    from sqlalchemy.orm import Session

    from app.database import engine
    from app.models import AnalysisResult

    with Session(engine) as db:
        run = db.get(AnalysisResult, client.get("/api/history").json()[0]["id"])
        run.review_results = [{k: v for k, v in r.items() if k not in ("status", "language", "usedTitle")}
                              for r in run.review_results]
        run.stats = {k: v for k, v in run.stats.items() if k not in ("analysedReviews", "notAnalysed")}
        run.engine = None
        db.commit()
    analysis = client.get(f"/api/products/{product['id']}/analysis")
    assert analysis.status_code == 200
    body = analysis.json()
    assert body["engine"] is None
    assert all(r["status"] == "analysed" and r["usedTitle"] is False for r in body["reviews"])
    assert "analysedReviews" not in body["stats"]
    assert json.dumps(body)


def test_collected_app_store_products_are_apps(client, monkeypatch):
    import httpx

    from app import config
    from app.services import collection

    from .test_url_collection import APP_URL, LOOKUP, FakeApple, entry, feed

    fake = FakeApple(pages={1: feed(entry("1", "I can't log in since the update"), entry("2", "Too many ads"))})
    monkeypatch.setattr(config, "APPLE_PAGE_DELAY_SECONDS", 0)
    monkeypatch.setattr(collection, "make_client", lambda: httpx.Client(transport=httpx.MockTransport(fake.handler)))
    product = client.post("/api/products/from-url", json={"url": APP_URL}).json()
    assert product["domain"] == "app" and LOOKUP
    aspects = {a["aspect"] for a in client.get(f"/api/products/{product['id']}/analysis").json()["aspects"]}
    assert {"Login & account", "Updates", "Ads"} <= aspects
