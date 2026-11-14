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


# ---------- Historical integrity: every run is an unchanging snapshot ----------

def _run_ids(client):
    return sorted(h["id"] for h in client.get("/api/history").json())


def test_old_runs_keep_their_review_level_results(client, product):
    url = f"/api/products/{product['id']}"
    [first_id] = _run_ids(client)
    first = client.get(f"/api/history/{first_id}").json()
    assert [r["id"] for r in first["reviews"]] == ["A1", "A2", "A3", "A4", "A5", "A6"]

    client.delete(f"{url}/reviews/A2")
    client.post(f"{url}/reviews", json={"reviews": [{"text": "Brilliant, love it.", "id": "N1"}]})

    again = client.get(f"/api/history/{first_id}").json()
    assert again["reviews"] == first["reviews"]  # unchanged, including the deleted review A2
    assert again["stats"] == first["stats"]
    latest = client.get(f"{url}/analysis").json()
    assert "A2" not in [r["id"] for r in latest["reviews"]] and "N1" in [r["id"] for r in latest["reviews"]]


def test_every_run_is_internally_consistent(client, product):
    url = f"/api/products/{product['id']}"
    client.delete(f"{url}/reviews/A1")
    client.post(f"{url}/reviews", json={"reviews": [{"text": "The camera is terrible.", "id": "N1"}]})
    for run_id in _run_ids(client):
        run = client.get(f"/api/history/{run_id}").json()
        ids = {r["id"] for r in run["reviews"]}
        assert run["stats"]["totalReviews"] == len(run["reviews"]) == run["totalReviews"]
        assert sum(run["stats"]["sentimentCounts"].values()) == len(ids)
        assert set(run["stats"]["ratingSentimentMismatches"]) <= ids
        for aspect in run["aspects"]:  # example quotes always point at a review in the same run
            for example in (aspect["examplePositive"], aspect["exampleNegative"]):
                assert example is None or example["reviewId"] in ids


def test_falling_back_to_an_older_run_shows_that_runs_reviews(client, product):
    url = f"/api/products/{product['id']}"
    client.delete(f"{url}/reviews/A2")
    first_id, second_id = _run_ids(client)
    client.delete(f"/api/history/{second_id}")
    analysis = client.get(f"{url}/analysis").json()
    assert analysis["analysisId"] == first_id
    assert analysis["stats"]["totalReviews"] == len(analysis["reviews"]) == 6
    assert "A2" in [r["id"] for r in analysis["reviews"]]
    assert client.get("/api/products").json()[0]["totalReviews"] == 6  # the list agrees with the page


def test_a_new_engine_never_changes_earlier_runs(client, product, monkeypatch):
    from app.nlp import pipeline

    url = f"/api/products/{product['id']}"
    first = client.get(f"{url}/analysis").json()

    class Fake:
        def describe(self):
            return {"id": "fake", "name": "Fake engine"}

        def predict(self, texts):
            return [{"label": "neutral", "score": 0.0} for _ in texts]

    monkeypatch.setattr(pipeline, "get_engine", lambda preference=None: (Fake(), None))
    second = client.post(f"{url}/analyze").json()
    assert second["engine"]["id"] == "fake"
    assert all(r["sentiment"] == "neutral" for r in second["reviews"])
    old = client.get(f"/api/history/{first['analysisId']}").json()
    assert old["engine"]["id"] == "vader"
    assert old["reviews"] == first["reviews"] and old["stats"] == first["stats"]
