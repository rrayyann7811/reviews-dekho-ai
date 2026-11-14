"""Phase 5: what the analytics dashboard reads from the API."""
import json

import pytest

from app.models import AnalysisResult
from app.services.review_query import query_reviews

from .conftest import BACKEND, csv_file, import_file

CASES = json.loads((BACKEND.parent / "frontend/src/test/fixtures/review-query-cases.json").read_text())


class FakeRun:
    """Stands in for a stored AnalysisResult built from the shared fixture."""
    id = 1
    review_results = CASES["reviews"]
    stats = {"ratingSentimentMismatches": CASES["mismatchIds"]}


@pytest.mark.parametrize("case", CASES["cases"], ids=lambda c: json.dumps(c["filters"]))
def test_server_filtering_matches_the_offline_demo(case):
    f = case["filters"]
    page = query_reviews(FakeRun, sentiment=f.get("sentiment", "all"), rating=f.get("rating", "all"),
                         search=f.get("query", ""), sort=f.get("sort", "newest"), limit=100)
    assert [r["id"] for r in page["items"]] == case["expected"]
    assert page["total"] == len(case["expected"])


def _product(client, text=None, columns=None, **extra):
    text = text or (
        "id,review,stars,when,who\n"
        "1,Excellent battery and great screen,5,2026-10-05,Asha\n"
        "2,Terrible camera and awful support,1,2026-10-01,Ravi\n"
        "3,It is a phone,,2026-10-03,\n"
        "4,\"Great battery, but the camera is terrible\",2,2026-10-04,\n"
        "5,\"bakwas phone hai, paisa barbaad\",1,2026-10-02,\n")
    columns = columns or {"text": "review", "rating": "stars", "date": "when", "id": "id", "reviewer": "who"}
    response = import_file(client, files=csv_file(text), columns=columns, **extra)
    assert response.status_code == 201, response.text
    return response.json()


def test_dashboard_can_load_the_analysis_without_every_review(client):
    product = _product(client)
    full = client.get(f"/api/products/{product['id']}/analysis").json()
    light = client.get(f"/api/products/{product['id']}/analysis", params={"include_reviews": "false"}).json()
    assert full["reviewsIncluded"] is True and len(full["reviews"]) == 5
    assert light["reviewsIncluded"] is False and light["reviews"] == []
    for key in ("stats", "aspects", "keywords", "summary", "engine", "toneByRating", "analysisId"):
        assert light[key] == full[key]


def test_tone_by_rating_comes_from_the_stored_reviews(client):
    product = _product(client)
    analysis = client.get(f"/api/products/{product['id']}/analysis").json()
    rows = {r["stars"]: r for r in analysis["toneByRating"]}
    assert [r["stars"] for r in analysis["toneByRating"]] == [5, 4, 3, 2, 1]
    assert rows[5] == {"stars": 5, "reviews": 1, "positive": 1, "neutral": 0, "negative": 0, "notAnalysed": 0}
    assert rows[1]["reviews"] == 2 and rows[1]["negative"] == 1 and rows[1]["notAnalysed"] == 1  # the Hinglish one
    assert rows[4]["reviews"] == rows[3]["reviews"] == 0
    # It agrees with the run's own numbers.
    by_review = {r["id"]: r for r in analysis["reviews"]}
    assert sum(r["reviews"] for r in rows.values()) == analysis["stats"]["ratedReviews"]
    assert sum(r["notAnalysed"] for r in rows.values()) == sum(
        1 for r in by_review.values() if r["sentiment"] is None and r["rating"] is not None)


def test_review_pages(client):
    product = _product(client)
    url = f"/api/products/{product['id']}/reviews"
    first = client.get(url, params={"limit": 2}).json()
    second = client.get(url, params={"limit": 2, "offset": 2}).json()
    last = client.get(url, params={"limit": 2, "offset": 4}).json()
    assert first["total"] == second["total"] == last["total"] == 5
    ids = [r["id"] for page in (first, second, last) for r in page["items"]]
    assert ids == ["1", "4", "3", "5", "2"]  # newest first, every review exactly once
    assert first["analysisId"] == client.get(f"/api/products/{product['id']}/analysis").json()["analysisId"]
    assert client.get(url, params={"offset": 50}).json()["items"] == []


def test_review_filters_through_the_api(client):
    product = _product(client)
    url = f"/api/products/{product['id']}/reviews"

    def ids(**params):
        return [r["id"] for r in client.get(url, params=params | {"limit": 100}).json()["items"]]

    assert ids(sentiment="unanalysed") == ["5"]
    assert ids(sentiment="mixed") == ["4"]
    assert ids(rating="none") == ["3"]
    assert ids(search="ravi") == ["2"]  # reviewer name
    assert ids(sort="positive")[-1] == "5"  # no score: always last
    mismatches = client.get(f"/api/products/{product['id']}/analysis").json()["stats"]["ratingSentimentMismatches"]
    assert ids(sentiment="mismatch") == mismatches


def test_pages_stay_on_the_run_being_viewed(client):
    product = _product(client)
    url = f"/api/products/{product['id']}"
    viewing = client.get(f"{url}/analysis").json()["analysisId"]
    client.post(f"{url}/reviews", json={"reviews": [{"text": "Brand new review, love it", "id": "new"}]})
    pinned = client.get(f"{url}/reviews", params={"analysis_id": viewing, "limit": 100}).json()
    latest = client.get(f"{url}/reviews", params={"limit": 100}).json()
    assert pinned["analysisId"] == viewing and pinned["total"] == 5
    assert latest["analysisId"] != viewing and latest["total"] == 6
    assert client.get(f"{url}/reviews/new", params={"analysis_id": viewing}).status_code == 404
    assert client.get(f"{url}/reviews/new").json()["text"] == "Brand new review, love it"


def test_single_review(client):
    product = _product(client)
    review = client.get(f"/api/products/{product['id']}/reviews/5").json()
    assert review["status"] == "language_not_supported" and review["sentiment"] is None
    missing = client.get(f"/api/products/{product['id']}/reviews/999")
    assert missing.status_code == 404 and "isn’t part of this analysis" in missing.json()["detail"]


def test_review_query_errors(client):
    product = _product(client)
    other = _product(client)
    url = f"/api/products/{product['id']}/reviews"
    other_run = client.get(f"/api/products/{other['id']}/analysis").json()["analysisId"]
    assert client.get(url, params={"analysis_id": other_run}).status_code == 404
    assert client.get(url, params={"sentiment": "happy"}).status_code == 422
    assert client.get(url, params={"rating": "6"}).status_code == 422
    assert client.get(url, params={"limit": 501}).status_code == 422
    empty = client.post("/api/products", json={"name": "Nothing yet"}).json()
    response = client.get(f"/api/products/{empty['id']}/reviews")
    assert response.status_code == 409 and "hasn’t been analysed yet" in response.json()["detail"]


def test_old_run_without_review_results(client, product):
    from sqlalchemy.orm import Session

    from app.database import engine

    with Session(engine) as db:
        db.query(AnalysisResult).update({"review_results": None})
        db.commit()
    for path in ("analysis", "reviews"):
        response = client.get(f"/api/products/{product['id']}/{path}")
        assert response.status_code == 409 and "Run the analysis again" in response.json()["detail"]
    # Re-analysing fixes it, without touching the old run.
    assert client.post(f"/api/products/{product['id']}/analyze").status_code == 200
    assert client.get(f"/api/products/{product['id']}/reviews").json()["total"] == 6


def test_reanalyse_returns_the_new_run(client):
    product = _product(client)
    url = f"/api/products/{product['id']}"
    before = client.get(f"{url}/analysis").json()
    after = client.post(f"{url}/analyze", params={"include_reviews": "false"}).json()
    assert after["analysisId"] != before["analysisId"] and after["reviews"] == []
    assert after["stats"] == before["stats"] and after["engine"]["id"] == "vader"
    history = client.get("/api/history", params={"product_id": product["id"]}).json()
    assert [h["id"] for h in history] == [after["analysisId"], before["analysisId"]]


def test_all_reviews_in_an_unsupported_language(client):
    product = _product(client, text="review,stars\n\"bakwas app hai, paisa barbaad\",1\nyeh bahut kharab hai yaar,2\n",
                       columns={"text": "review", "rating": "stars"})
    analysis = client.get(f"/api/products/{product['id']}/analysis").json()
    stats = analysis["stats"]
    assert stats["totalReviews"] == 2 and stats["analysedReviews"] == 0
    assert stats["sentimentPercent"] == {"positive": 0.0, "neutral": 0.0, "negative": 0.0}
    assert stats["averageRating"] == 1.5  # stars still count
    assert analysis["aspects"] == [] and analysis["keywords"] == []
    assert analysis["summary"]["notes"][0] == "No review could be analysed, so there is no summary."
    assert product["positivePercent"] is None  # "—", not a misleading 0%
    [entry] = client.get("/api/history", params={"product_id": product["id"]}).json()
    assert entry["positivePercent"] is None and entry["negativePercent"] is None
