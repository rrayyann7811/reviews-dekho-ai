"""The API runs the existing NLP pipeline on the uploaded reviews themselves."""
from app.nlp.pipeline import analyze_reviews

from .conftest import csv_file, import_file


def _analysis(client, text, columns=None):
    product = import_file(client, files=csv_file(text), columns=columns or {"text": "review"}).json()
    return client.get(f"/api/products/{product['id']}/analysis").json()


def test_api_result_equals_running_the_pipeline_directly(client, product):
    api_result = client.get(f"/api/products/{product['id']}/analysis").json()
    direct = analyze_reviews([
        {"id": r["id"], "text": r["text"], "rating": r["rating"], "date": r["date"],
         "title": r["title"], "reviewer": r["reviewer"]} for r in api_result["reviews"]])
    for key in ("stats", "aspects", "keywords", "summary"):
        assert api_result[key] == direct[key], key
    for api_review, direct_review in zip(api_result["reviews"], direct["reviews"]):
        for key in ("sentiment", "score", "mixed", "aspects"):
            assert api_review[key] == direct_review[key]


def test_sentiment_reflects_the_uploaded_text(client):
    text = ("review\n"
            "Absolutely love it. Excellent quality and great value.\n"
            "\"Worst purchase ever. Broken on arrival, terrible support.\"\n"
            "It arrived on Tuesday in a box.\n")
    analysis = _analysis(client, text)
    assert [r["sentiment"] for r in analysis["reviews"]] == ["positive", "negative", "neutral"]
    assert analysis["stats"]["sentimentCounts"] == {"positive": 1, "neutral": 1, "negative": 1}
    assert analysis["stats"]["averageRating"] is None and analysis["stats"]["ratedReviews"] == 0


def test_different_files_give_different_results(client):
    good = _analysis(client, "review\n\"Great product, love it\"\n\"Excellent, works perfectly\"\n")
    bad = _analysis(client, "review\n\"Terrible product, hate it\"\n\"Awful, broke immediately\"\n")
    assert good["stats"]["sentimentPercent"]["positive"] == 100.0
    assert bad["stats"]["sentimentPercent"]["negative"] == 100.0


def test_aspects_mixed_opinions_and_mismatches(client):
    text = ("review,stars\n"
            "\"Great battery, but the camera is terrible.\",3\n"
            "\"The battery is excellent and lasts all day.\",5\n"
            "\"Battery life is superb, really impressive.\",4\n"
            "\"I love this phone, it is fantastic.\",1\n")
    analysis = _analysis(client, text, {"text": "review", "rating": "stars"})
    first = analysis["reviews"][0]
    assert first["mixed"] is True
    assert {a["aspect"]: a["sentiment"] for a in first["aspects"]} == {"Battery": "positive", "Camera": "negative"}
    battery = next(a for a in analysis["aspects"] if a["aspect"] == "Battery")
    assert battery["mentions"] == 3 and battery["verdict"] == "positive"
    assert analysis["stats"]["ratingSentimentMismatches"] == ["R-4"]


def test_small_samples_get_an_honest_summary(client):
    analysis = _analysis(client, "review\nNice\nGood\n")
    assert analysis["summary"]["overview"] is None
    assert "At least 5" in analysis["summary"]["notes"][0]
