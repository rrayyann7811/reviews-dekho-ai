"""Analysis history endpoints."""


def test_history_lists_runs_newest_first(client, product):
    other = client.post("/api/products", json={"name": "Other"}).json()
    client.post(f"/api/products/{other['id']}/reviews", json={"reviews": [{"text": "Nice and sturdy."}]})
    client.post(f"/api/products/{product['id']}/analyze")

    history = client.get("/api/history").json()
    assert len(history) == 3
    assert [h["productId"] for h in history] == [product["id"], other["id"], product["id"]]
    entry = history[0]
    assert entry["productName"] == "Test Phone" and entry["source"] == "upload"
    assert entry["totalReviews"] == 6 and entry["averageRating"] == 3.33
    assert entry["positivePercent"] + entry["negativePercent"] <= 100

    only_other = client.get("/api/history", params={"product_id": other["id"]}).json()
    assert [h["productName"] for h in only_other] == ["Other"]
    assert len(client.get("/api/history", params={"limit": 1}).json()) == 1


def test_history_detail_returns_stored_results(client, product):
    [entry] = client.get("/api/history").json()
    detail = client.get(f"/api/history/{entry['id']}").json()
    current = client.get(f"/api/products/{product['id']}/analysis").json()
    for key in ("stats", "aspects", "keywords", "summary", "ingestion"):
        assert detail[key] == current[key]


def test_old_runs_keep_their_own_results(client, product):
    client.post(f"/api/products/{product['id']}/reviews", json={"reviews": [{"text": "Awful, broken, useless."}]})
    old, new = sorted(client.get("/api/history").json(), key=lambda h: h["id"])
    assert old["totalReviews"] == 6 and new["totalReviews"] == 7
    assert client.get(f"/api/history/{old['id']}").json()["stats"]["totalReviews"] == 6


def test_delete_history_entry(client, product):
    client.post(f"/api/products/{product['id']}/analyze")
    old, new = sorted(client.get("/api/history").json(), key=lambda h: h["id"])
    assert client.delete(f"/api/history/{new['id']}").status_code == 204
    assert [h["id"] for h in client.get("/api/history").json()] == [old["id"]]
    # The product falls back to the earlier run.
    assert client.get(f"/api/products/{product['id']}/analysis").json()["analysisId"] == old["id"]


def test_history_errors(client):
    assert client.get("/api/history/999").status_code == 404
    assert client.delete("/api/history/999").json()["detail"] == "Analysis 999 doesn’t exist."
    assert client.get("/api/history", params={"limit": 0}).status_code == 422
