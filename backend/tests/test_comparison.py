"""Side-by-side comparison of two stored analysis runs (Phase 7)."""
import datetime as dt
import json

import pytest

from app.models import AnalysisResult, Product
from app.services import comparison
from app.services.comparison import (CLEAR, NOT_MEASURABLE, OVERLAPPING, SEPARATION_TEXT, TOO_FEW, compare_runs,
                                     separation, share, wilson_interval)

from .conftest import csv_file, import_file

PRODUCT_FEATURES = ["Battery", "Camera", "Display", "Performance", "Build quality", "Price", "Delivery", "Packaging",
                    "Customer service"]


# ---------- In-memory snapshots (exact control over every figure) ----------

def make_run(run_id=1, *, total=100, analysed=None, positive=60, neutral=10, negative=None, rated=None, average=4.0,
             distribution=None, aspects=(), engine="transformer", pipeline=2, features=PRODUCT_FEATURES,
             date_range=("2026-10-01", "2026-10-31"), not_analysed=None, ingestion=None, legacy=False):
    analysed = total if analysed is None else analysed
    negative = analysed - positive - neutral if negative is None else negative
    rated = total if rated is None else rated
    if legacy:  # Phase 1-3 shape: no analysedReviews / notAnalysed, no engine record
        stats = {"totalReviews": total, "ratedReviews": rated, "averageRating": average,
                 "sentimentCounts": {"positive": positive, "neutral": neutral, "negative": negative},
                 "ratingDistribution": distribution or [{"stars": 5, "count": rated}] + [
                     {"stars": s, "count": 0} for s in (4, 3, 2, 1)],
                 "dateRange": {"from": date_range[0], "to": date_range[1]} if date_range else None}
        engine_record = None
    else:
        stats = {"totalReviews": total, "analysedReviews": analysed,
                 "notAnalysed": not_analysed or {"languageNotSupported": total - analysed},
                 "ratedReviews": rated, "averageRating": average if rated else None,
                 "sentimentCounts": {"positive": positive, "neutral": neutral, "negative": negative},
                 "ratingDistribution": distribution or [{"stars": 5, "count": rated}] + [
                     {"stars": s, "count": 0} for s in (4, 3, 2, 1)],
                 "dateRange": {"from": date_range[0], "to": date_range[1]} if date_range else None}
        engine_record = {"id": engine, "name": "RoBERTa sentiment model" if engine == "transformer" else "VADER",
                         "pipelineVersion": pipeline, "features": list(features) if features else None}
    return AnalysisResult(id=run_id, created_at=dt.datetime(2026, 11, run_id % 28 + 1), total_reviews=total,
                          average_rating=average, positive_percent=0, negative_percent=0, stats=stats,
                          aspects=list(aspects), keywords=[], summary={"version": 2}, ingestion=ingestion,
                          review_results=None, engine=engine_record)


def make_product(product_id=1, runs=(), *, name=None, domain="product", source="upload", site=None, category=None):
    product = Product(id=product_id, name=name or f"Product {product_id}", brand=None, category=category,
                      source=source, domain=domain, source_site=site)
    product.analyses = sorted(runs, key=lambda r: -r.id)
    return product


def aspect(name, positive, neutral=0, negative=0):
    return {"aspect": name, "mentions": positive + neutral + negative, "positive": positive, "neutral": neutral,
            "negative": negative, "verdict": "mixed"}


def compare(run_a, run_b, **product_b):
    a = make_product(1, [run_a])
    b = make_product(2, [run_b], **product_b)
    return compare_runs(a, run_a, b, run_b)


def codes(result):
    return [c["code"] for c in result["caveats"]]


# ---------- Wilson intervals and separation ----------

@pytest.mark.parametrize("count, n, low, high", [
    (5, 10, 0.2366, 0.7634),     # textbook values
    (0, 10, 0.0, 0.2775),
    (10, 10, 0.7225, 1.0),
    (81, 263, 0.2553, 0.3662),
])
def test_wilson_interval_matches_known_values(count, n, low, high):
    interval = wilson_interval(count, n)
    assert interval[0] == pytest.approx(low, abs=5e-5) and interval[1] == pytest.approx(high, abs=5e-5)


def test_zero_base_is_not_measurable_never_zero_percent():
    assert wilson_interval(0, 0) is None
    assert share(0, 0) == {"count": 0, "n": 0, "percent": None, "interval": None}
    assert separation(0, 0, 10, 40) == NOT_MEASURABLE


def test_threshold_is_thirty_on_both_sides():
    assert separation(29, 29, 0, 40) == TOO_FEW       # 29 < 30, however different
    assert separation(30, 30, 0, 30) == CLEAR         # 30 on both sides
    assert separation(15, 30, 16, 30) == OVERLAPPING


def test_touching_intervals_count_as_overlapping(monkeypatch):
    fixed = {(1, 40): (0.40, 0.50), (2, 40): (0.50, 0.60), (3, 40): (0.51, 0.60)}
    monkeypatch.setattr(comparison, "wilson_interval", lambda c, n: fixed[(c, n)])
    assert separation(1, 40, 2, 40) == OVERLAPPING
    assert separation(1, 40, 3, 40) == CLEAR


# ---------- Equal and unequal samples ----------

def test_equal_samples_with_a_large_difference_are_clearly_separated():
    result = compare(make_run(1, total=200, positive=150, neutral=10), make_run(2, total=200, positive=50, neutral=10))
    assert result["sentiment"]["positive"]["separation"] == CLEAR
    assert result["sentiment"]["positive"]["difference"] == 50.0
    assert any(s.startswith("Positive share of analysed reviews: A 75% of 200") and SEPARATION_TEXT in s
               for s in result["statements"])
    assert "size-gap" not in codes(result)


def test_identical_figures_have_no_clear_difference():
    result = compare(make_run(1), make_run(2))
    assert all(v["separation"] == OVERLAPPING and v["difference"] == 0 for v in result["sentiment"].values())
    assert result["statements"][0].startswith("No sentiment or feature figure shows clear separation")
    assert not any(SEPARATION_TEXT in s for s in result["statements"][1:])


def test_size_gap_warning_at_five_times():
    assert "size-gap" in codes(compare(make_run(1, total=30, positive=20), make_run(2, total=150, positive=100)))
    assert "size-gap" not in codes(compare(make_run(1, total=30, positive=20), make_run(2, total=149, positive=100)))
    gap = next(c for c in compare(make_run(1, total=30, positive=20), make_run(2, total=150, positive=100))["caveats"]
               if c["code"] == "size-gap")
    assert "A: 30, B: 150" in gap["message"] and "side A's figures are much less certain" in gap["message"]


def test_small_sample_warns_and_nothing_is_called_clear():
    result = compare(make_run(1, total=29, positive=29, neutral=0), make_run(2, total=300, positive=0, neutral=0))
    assert result["sentiment"]["positive"]["separation"] == TOO_FEW
    assert "small-sample" in codes(result)
    assert result["statements"][0].startswith("No difference is described as clear: at least one side has fewer than 30")


# ---------- Language exclusions and zero analysed ----------

def test_not_analysed_warning_above_ten_percent_only():
    at_ten = make_run(1, total=100, analysed=90, positive=50)
    above = make_run(1, total=100, analysed=89, positive=50)
    assert "not-analysed" not in codes(compare(at_ten, make_run(2)))
    caveat = next(c for c in compare(above, make_run(2))["caveats"] if c["code"] == "not-analysed")
    assert caveat["message"].startswith("Side A: 11 of 100 reviews (11%) weren't analysed")


def test_zero_analysed_is_not_measurable_not_zero_percent():
    nothing = make_run(1, total=12, analysed=0, positive=0, neutral=0, negative=0)
    result = compare(nothing, make_run(2))
    assert result["a"]["sentiment"] is None and result["sentiment"] is None
    assert "nothing-analysed" in codes(result) and "not-analysed" not in codes(result)
    assert "0%" not in json.dumps(result["statements"], default=str)


# ---------- Features ----------

def test_feature_statuses_and_missing_features_are_not_negative():
    a = make_run(1, aspects=[aspect("Battery", 20, 5, 5), aspect("Camera", 2), aspect("Refunds", 4)],
                 features=PRODUCT_FEATURES + ["Refunds"])
    b = make_run(2, aspects=[aspect("Battery", 10, 0, 20), aspect("Display", 5)])
    rows = {r["aspect"]: r for r in compare(a, b)["features"]}
    assert (rows["Battery"]["a"]["status"], rows["Battery"]["b"]["status"]) == ("compared", "compared")
    assert rows["Battery"]["comparable"] and rows["Battery"]["tone"]["positive"]["a"]["n"] == 30
    assert (rows["Camera"]["a"]["status"], rows["Camera"]["b"]["status"]) == ("few-mentions", "not-mentioned")
    assert rows["Camera"]["tone"] is None
    assert rows["Display"]["a"]["status"] == "not-mentioned"
    assert rows["Display"]["a"]["mentionRate"]["percent"] == 0.0          # looked for, not mentioned: a real 0
    refunds = rows["Refunds"]["b"]
    assert refunds["status"] == "not-looked-for" and refunds["mentionRate"] is None and refunds["verdict"] is None
    assert rows["Refunds"]["mentionRate"] is None and not rows["Refunds"]["comparable"]
    assert [r["aspect"] for r in compare(a, b)["features"]][0] == "Battery"   # comparable rows first


def test_older_runs_without_a_feature_list_say_unknown_not_zero():
    legacy = make_run(1, legacy=True, aspects=[aspect("Battery", 10)])
    result = compare(legacy, make_run(2, aspects=[aspect("Camera", 5)]))
    camera = next(r for r in result["features"] if r["aspect"] == "Camera")
    assert camera["a"]["status"] == "unknown" and camera["a"]["mentionRate"] is None
    assert "feature-list-unknown" in codes(result)


def test_feature_tone_separation_uses_mentions_as_the_base():
    a = make_run(1, total=400, aspects=[aspect("Battery", 40, 0, 0)])
    b = make_run(2, total=400, aspects=[aspect("Battery", 0, 0, 40)])
    row = compare(a, b)["features"][0]
    assert row["tone"]["positive"]["separation"] == CLEAR
    assert any(s.startswith("Battery, positive share of its mentions: A 100% of 40 mentions") for s in
               compare(a, b)["statements"])
    few = compare(make_run(1, aspects=[aspect("Battery", 29)]), make_run(2, aspects=[aspect("Battery", 0, 0, 29)]))
    assert few["features"][0]["tone"]["positive"]["separation"] == TOO_FEW


# ---------- Engines, domains, sources, periods, ratings ----------

def test_different_sentiment_engines_are_flagged():
    result = compare(make_run(1, engine="transformer"), make_run(2, engine="vader"))
    assert "engine-differs" in codes(result)
    assert "engine-differs" in codes(compare(make_run(1), make_run(2, legacy=True)))   # same engine id, older pipeline
    assert "engine-differs" not in codes(compare(make_run(1), make_run(2)))


def test_domain_source_and_period_caveats():
    app = make_run(2, features=["Login & account", "Ads"], date_range=("2025-01-01", "2025-02-01"))
    result = compare(make_run(1), app, domain="app", source="url", site="apple_app_store")
    assert {"domain-differs", "source-differs", "app-store-recent", "periods-differ"} <= set(codes(result))
    assert "2026-10-01 to 2026-10-31 vs 2025-01-01 to 2025-02-01" in json.dumps(result["caveats"], default=str)
    assert "period-unknown" in codes(compare(make_run(1, date_range=None), make_run(2)))


def test_missing_ratings_are_not_compared():
    result = compare(make_run(1, rated=0), make_run(2))
    assert result["a"]["ratings"]["average"] is None
    assert all(r["percent"] is None for r in result["a"]["ratings"]["distribution"])
    assert "no-ratings" in codes(result)
    assert not any(s.startswith("Average star rating") for s in result["statements"])


def test_store_rating_is_context_only():
    run = make_run(2, ingestion={"storeRating": 4.53, "storeRatingCount": 1200})
    side = compare(make_run(1), run)["b"]
    assert side["ratings"]["storeRating"] == 4.53 and side["ratings"]["average"] == 4.0


def test_wording_never_claims_significance_representativeness_or_a_winner():
    result = compare(make_run(1, total=500, positive=400), make_run(2, total=500, positive=100))
    claims = json.dumps([result["statements"], result["caveats"]], default=str).lower()
    for banned in ("significan", "winner", "better", "worse", "customers prefer", "all customers", "proves"):
        assert banned not in claims
    assert any(SEPARATION_TEXT in s for s in result["statements"])
    assert "neither side is a random or representative sample of all customers" in result["notes"][0]
    assert "isn't proof of a real difference" in result["notes"][1]


# ---------- API: real snapshots ----------

def upload(client, text, name="Phone", columns=None, **extra):
    response = import_file(client, files=csv_file(text), product_name=name,
                           columns=columns or {"text": "review", "rating": "stars", "id": "id"}, **extra)
    assert response.status_code == 201, response.text
    return response.json()


def reviews(n, text="The battery is excellent and I love it", stars=5, prefix="r"):
    return "".join(f"{prefix}{i},{text} {i},{stars}\n" for i in range(n))


def test_compare_two_products(client):
    a = upload(client, "id,review,stars\n" + reviews(40) + reviews(10, "The camera is terrible", 1, "n"), "Alpha")
    b = upload(client, "id,review,stars\n" + reviews(10) + reviews(40, "The camera is terrible", 1, "n"), "Beta")
    body = client.get("/api/compare", params={"product_a": a["id"], "product_b": b["id"]})
    assert body.status_code == 200
    data = body.json()
    assert data["a"]["product"]["name"] == "Alpha" and data["b"]["product"]["name"] == "Beta"
    assert data["a"]["run"]["isLatest"] and not data["sameProduct"]
    assert data["sentiment"]["positive"]["separation"] == CLEAR
    assert {r["aspect"] for r in data["features"]} >= {"Battery", "Camera"}


def test_same_product_historical_runs_and_integrity(client):
    product = upload(client, "id,review,stars\n" + reviews(40))
    pid = product["id"]
    first = client.get(f"/api/products/{pid}/analysis").json()["analysisId"]
    snapshot_before = client.get(f"/api/history/{first}").json()
    client.post(f"/api/products/{pid}/reviews", json={"reviews": [
        {"text": f"The camera is terrible {i}", "rating": 1} for i in range(40)]})
    second = client.post(f"/api/products/{pid}/analyze").json()["analysisId"]
    assert second != first

    body = client.get("/api/compare", params={"product_a": pid, "product_b": pid, "analysis_a": first}).json()
    assert body["sameProduct"] and not body["sameRun"]
    assert body["a"]["run"]["id"] == first and not body["a"]["run"]["isLatest"]
    assert body["a"]["run"]["latestRunId"] == second and body["b"]["run"]["id"] == second
    assert (body["a"]["counts"]["analysed"], body["b"]["counts"]["analysed"]) == (40, 80)
    assert "same-product" in codes(body)
    # The earlier run is read exactly as stored, and comparing it changes nothing.
    assert client.get(f"/api/history/{first}").json() == snapshot_before
    again = client.get("/api/compare", params={"product_a": pid, "product_b": pid, "analysis_a": first,
                                               "analysis_b": second}).json()
    assert again == body

    same = client.get("/api/compare", params={"product_a": pid, "product_b": pid}).json()
    assert same["sameRun"] and "same-run" in codes(same)
    assert same["statements"] == ["Both sides are the same analysis run, so there are no differences to describe."]


def test_a_run_of_another_product_is_rejected(client):
    a = upload(client, "id,review,stars\n" + reviews(5), "Alpha")
    b = upload(client, "id,review,stars\n" + reviews(5), "Beta")
    run_b = client.get(f"/api/products/{b['id']}/analysis").json()["analysisId"]
    response = client.get("/api/compare", params={"product_a": a["id"], "product_b": b["id"], "analysis_a": run_b})
    assert response.status_code == 404 and "doesn’t belong to this product" in response.json()["detail"]


def test_unknown_unanalysed_and_missing_parameters(client):
    a = upload(client, "id,review,stars\n" + reviews(5))
    assert client.get("/api/compare", params={"product_a": a["id"], "product_b": 9999}).status_code == 404
    empty = client.post("/api/products", json={"name": "Nothing yet"}).json()
    response = client.get("/api/compare", params={"product_a": a["id"], "product_b": empty["id"]})
    assert response.status_code == 409 and "hasn’t been analysed" in response.json()["detail"]
    assert client.get("/api/compare", params={"product_a": a["id"]}).status_code == 422


def test_unsupported_language_reviews_are_left_out_and_flagged(client):
    english = upload(client, "id,review,stars\n" + reviews(40), "English")
    text = "id,review,stars\n" + reviews(20) + "".join(f"h{i},bakwas phone hai yaar battery kharab {i},1\n"
                                                         for i in range(20))
    mixed = upload(client, text, "Mixed")
    body = client.get("/api/compare", params={"product_a": english["id"], "product_b": mixed["id"]}).json()
    counts = body["b"]["counts"]
    assert counts["total"] == 40 and counts["notAnalysed"] > 4 and counts["analysed"] + counts["notAnalysed"] == 40
    assert body["b"]["sentiment"]["positive"]["n"] == counts["analysed"]
    assert "not-analysed" in codes(body)


def test_all_reviews_unsupported_gives_no_sentiment(client):
    english = upload(client, "id,review,stars\n" + reviews(40), "English")
    hinglish = upload(client, "id,review,stars\n" + "".join(f"h{i},bakwas phone hai yaar battery kharab {i},1\n"
                                                            for i in range(10)), "Hinglish")
    body = client.get("/api/compare", params={"product_a": english["id"], "product_b": hinglish["id"]}).json()
    assert body["b"]["counts"]["analysed"] == 0
    assert body["b"]["sentiment"] is None and body["sentiment"] is None
    assert "nothing-analysed" in codes(body)
    assert body["b"]["ratings"]["average"] == 1.0   # star ratings still count


def test_openapi_documents_the_endpoint(client):
    spec = client.get("/openapi.json").json()
    operation = spec["paths"]["/api/compare"]["get"]
    params = {p["name"]: p["required"] for p in operation["parameters"]}
    assert params == {"product_a": True, "product_b": True, "analysis_a": False, "analysis_b": False}
    assert {"200", "404", "409", "422"} <= set(operation["responses"])
    schema = spec["components"]["schemas"]["Comparison"]["properties"]
    assert {"a", "b", "sameProduct", "sameRun", "sentiment", "features", "caveats", "statements"} <= set(schema)
