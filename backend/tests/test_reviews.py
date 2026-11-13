"""Review management: list, filter, add, delete."""


def test_list_reviews_with_filters_and_paging(client, product):
    url = f"/api/products/{product['id']}/reviews"
    everything = client.get(url).json()
    assert everything["total"] == 6
    first = everything["items"][0]
    assert first["id"] == "A1" and first["rating"] == 5 and first["date"] == "2026-10-01"
    assert first["sentiment"] == "positive" and first["score"] > 0
    assert {a["aspect"] for a in first["aspects"]} >= {"Battery", "Camera"}

    assert client.get(url, params={"rating": 1}).json()["total"] == 1
    assert client.get(url, params={"search": "BATTERY"}).json()["total"] == 3
    assert client.get(url, params={"search": "100%_"}).json()["total"] == 0  # wildcards are escaped
    negatives = client.get(url, params={"sentiment": "negative"}).json()
    assert negatives["total"] >= 1 and all(r["sentiment"] == "negative" for r in negatives["items"])
    page = client.get(url, params={"offset": 4, "limit": 10}).json()
    assert page["total"] == 6 and [r["id"] for r in page["items"]] == ["A5", "A6"]


def test_list_reviews_rejects_bad_filters(client, product):
    url = f"/api/products/{product['id']}/reviews"
    assert client.get(url, params={"sentiment": "happy"}).status_code == 422
    assert client.get(url, params={"rating": 6}).status_code == 422
    assert client.get(url, params={"limit": 0}).status_code == 422


def test_add_reviews_to_manual_product_runs_analysis(client):
    product = client.post("/api/products", json={"name": "Speaker"}).json()
    response = client.post(f"/api/products/{product['id']}/reviews", json={"reviews": [
        {"text": "Brilliant sound quality, I love it.", "rating": 5, "date": "2026-09-01"},
        {"text": "Terrible battery, it died in an hour.", "rating": 1, "id": "own-7"},
    ]})
    assert response.status_code == 201
    summary = response.json()
    assert summary["totalReviews"] == 2 and summary["averageRating"] == 3.0 and summary["analyzedAt"]

    analysis = client.get(f"/api/products/{product['id']}/analysis").json()
    by_id = {r["id"]: r for r in analysis["reviews"]}
    assert set(by_id) == {"R-1", "own-7"}
    assert by_id["R-1"]["sentiment"] == "positive"
    assert by_id["own-7"]["sentiment"] == "negative"
    assert analysis["ingestion"] is None

    # Adding more reviews later re-runs the analysis on all of them.
    more = client.post(f"/api/products/{product['id']}/reviews", json={"reviews": [{"text": "Okay speaker."}]})
    assert more.json()["totalReviews"] == 3
    ids = [r["id"] for r in client.get(f"/api/products/{product['id']}/analysis").json()["reviews"]]
    assert ids == ["R-1", "own-7", "R-3"]


def test_add_reviews_validation(client, product):
    url = f"/api/products/{product['id']}/reviews"
    assert client.post(url, json={"reviews": []}).status_code == 422
    assert client.post(url, json={"reviews": [{"text": "  "}]}).status_code == 422
    assert client.post(url, json={"reviews": [{"text": "ok", "rating": 6}]}).status_code == 422
    assert client.post(url, json={"reviews": [{"text": "ok", "date": "yesterday"}]}).status_code == 422
    duplicate = client.post(url, json={"reviews": [{"text": "Again", "id": "A1"}]})
    assert duplicate.status_code == 409
    assert "A1" in duplicate.json()["detail"]
    assert client.get(url).json()["total"] == 6  # nothing was added


def test_delete_review_reanalyses(client, product):
    url = f"/api/products/{product['id']}/reviews"
    assert client.delete(f"{url}/A2").status_code == 204
    analysis = client.get(f"/api/products/{product['id']}/analysis").json()
    assert analysis["stats"]["totalReviews"] == 5
    assert "A2" not in [r["id"] for r in analysis["reviews"]]
    assert client.delete(f"{url}/A2").status_code == 404
    assert client.delete(f"{url}/nope").json()["detail"] == "Review nope doesn’t exist for this product."
