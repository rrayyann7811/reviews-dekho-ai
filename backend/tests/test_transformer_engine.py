"""The pretrained transformer engine. Skipped when the model files aren't installed."""
import pytest

from app import config
from app.nlp import engines
from app.nlp.pipeline import analyze_reviews

pytestmark = pytest.mark.skipif(not (config.MODEL_DIR / "model_quantized.onnx").exists(),
                                reason="model not installed (scripts/download_model.py)")


@pytest.fixture(scope="module")
def model():
    engines.reset_engines()
    engine, fallback = engines.get_engine("transformer")
    assert fallback is None
    return engine


def test_three_classes_and_score_range(model):
    results = model.predict(["I love this app, it is perfect", "It arrived on Tuesday.", "Worst app ever, I hate it"])
    assert [r["label"] for r in results] == ["positive", "neutral", "negative"]
    assert results[0]["score"] > 0.5 > -0.5 > results[2]["score"]
    assert all(-1 <= r["score"] <= 1 for r in results)


@pytest.mark.parametrize("text", ["The app keeps crashing after the update", "Customer support never responds",
                                  "I can't log in, OTP never arrives", "Too many ads, very annoying"])
def test_app_complaints(model, text):
    assert model.predict([text])[0]["label"] == "negative"


TEXTS = ["Great", "Terrible battery, really bad", "ok", "I absolutely love the new design, so smooth and clean",
         "It is a phone.", "Awful", "Fantastic camera", "", "Delivery was late and the box was damaged badly"]


def test_a_reviews_result_never_depends_on_the_other_reviews(model):
    together = model.predict(TEXTS)
    alone = [model.predict([t])[0] for t in TEXTS]
    reversed_order = model.predict(TEXTS[::-1])[::-1]
    assert together == alone == reversed_order


def test_larger_batches_still_return_results_in_order(model, monkeypatch):
    monkeypatch.setattr(config, "MODEL_BATCH_SIZE", 4)
    results = model.predict(TEXTS)
    assert len(results) == len(TEXTS) and results[0]["label"] == "positive" and results[5]["label"] == "negative"


def test_long_text_is_truncated_not_rejected(model):
    assert model.predict(["Great phone. " * 400])[0]["label"] == "positive"


def test_pipeline_records_the_model(model):
    analysis = analyze_reviews([{"id": "1", "text": "Great battery, but the camera is terrible"}],
                               engine_preference="transformer")
    assert analysis["engine"]["id"] == "transformer" and analysis["engine"]["fallbackReason"] is None
    assert analysis["engine"]["model"] == "cardiffnlp/twitter-roberta-base-sentiment-latest"
    aspects = {a["aspect"]: a["sentiment"] for a in analysis["reviews"][0]["aspects"]}
    assert aspects == {"Battery": "positive", "Camera": "negative"}


def test_api_uses_the_model_when_configured(client, monkeypatch):
    monkeypatch.setattr(config, "SENTIMENT_ENGINE", "auto")
    product = client.post("/api/products", json={"name": "Notes", "domain": "app"}).json()
    client.post(f"/api/products/{product['id']}/reviews", json={"reviews": [{"text": "Love it, works perfectly"}]})
    analysis = client.get(f"/api/products/{product['id']}/analysis").json()
    assert analysis["engine"]["id"] == "transformer"
    assert client.get("/api/history").json()[0]["engine"]["id"] == "transformer"
