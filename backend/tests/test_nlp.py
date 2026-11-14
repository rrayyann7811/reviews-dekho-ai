"""NLP engine (Phase 4): rules, language check, aspects, pipeline and engine fallback.

These run with VADER (deterministic, no model files needed). The pretrained model is
tested in test_transformer_engine.py.
"""
import pytest

from app import config
from app.nlp import engines
from app.nlp.aspects import APP_ASPECTS, PRODUCT_ASPECTS, choose_vocabulary, find_mentions
from app.nlp.keywords import extract_keywords, name_stopwords
from app.nlp.language import NOT_SUPPORTED, SUPPORTED, detect_language
from app.nlp.pipeline import analyze_reviews
from app.nlp.preprocess import tidy_for_analysis
from app.nlp.sentiment import score_text


def label(text):
    return score_text(text)["label"]


def one(text, **kwargs):
    kwargs.setdefault("engine_preference", "vader")
    return analyze_reviews([{"id": "r1", "text": text, **kwargs.pop("extra", {})}], **kwargs)


# ---------- Sentiment basics ----------

@pytest.mark.parametrize("text", ["I love this, it is excellent", "Great value and works perfectly",
                                  "Love it 😍", "Goooood", "👍", "Super fast delivery, very happy"])
def test_positive(text):
    assert label(text) == "positive"


@pytest.mark.parametrize("text", ["Terrible, worst purchase ever", "It broke after a week, very disappointed",
                                  "Worst app 😡", "👎", "Waste of money"])
def test_negative(text):
    assert label(text) == "negative"


@pytest.mark.parametrize("text", ["It arrived on Tuesday.", "The phone is black.", "I use it for calls."])
def test_neutral(text):
    assert label(text) == "neutral"


# ---------- Negation and review phrases that plain VADER gets wrong ----------

@pytest.mark.parametrize("text", [
    "The app is not working", "Keeps crashing when I open it", "I can't log in", "Unable to make a payment",
    "Customer support never responds", "The app doesn't open after the update", "Too many ads",
    "Notifications don't work", "It freezes constantly", "The order never arrived", "No response from support",
    "sooooo slow",
])
def test_review_phrases_are_negative(text):
    assert label(text) == "negative"


@pytest.mark.parametrize("text", ["No issues at all", "Never had any problems", "Not bad"])
def test_negated_complaints_are_positive(text):
    assert label(text) == "positive"


def test_original_text_is_never_rewritten():
    analysis = one("Keeps crashing!!!!!!!! 👎")
    assert analysis["reviews"][0]["text"] == "Keeps crashing!!!!!!!! 👎"
    assert tidy_for_analysis("Good!!!!!!!!") == "Good!!!"


# ---------- Language ----------

@pytest.mark.parametrize(("text", "language"), [
    ("bakwas app hai", "hinglish"), ("OTP nahi aa raha bhai", "hinglish"), ("yeh app bahut accha hai", "hinglish"),
    ("यह ऐप बहुत अच्छा है", "devanagari script"),
    ("La aplicación es muy buena y funciona perfectamente siempre", "unknown"),
    ("Das ist eine sehr gute App und funktioniert immer", "unknown"),
    ("offer bht acche ate hai", "hinglish"),
])
def test_unsupported_languages_are_flagged(text, language):
    result = detect_language(text)
    assert result["status"] == NOT_SUPPORTED and result["language"] == language and result["reason"]


@pytest.mark.parametrize("text", ["Good", "Fast delivery", "Bahut good phone", "Lag is terrible plz fix",
                                  "The ram is 8 GB and the main camera is great", "Worst app ever, I hate it 😡", "",
                                  # telegraphic English (title + short text) once flagged as "unknown" (synthetic examples of a pattern seen live)
                                  "Brilliant app. Well done dev team", "Terrible. Terrible delivery partner",
                                  "Superb. Really Quick Food Delivery", "Top marks. Nice simple quick checkout"])
def test_english_is_not_flagged(text):
    assert detect_language(text)["status"] == SUPPORTED


def test_unsupported_reviews_get_no_sentiment_and_are_left_out_of_percentages():
    analysis = analyze_reviews([
        {"id": "1", "text": "Excellent app, love it", "rating": 5},
        {"id": "2", "text": "bakwas app hai, paisa barbaad", "rating": 1},
        {"id": "3", "text": "Terrible, keeps crashing", "rating": 1},
    ], domain="app", engine_preference="vader")
    hinglish = analysis["reviews"][1]
    assert hinglish["status"] == "language_not_supported" and hinglish["language"] == "hinglish"
    assert hinglish["sentiment"] is None and hinglish["score"] is None and hinglish["aspects"] == []
    stats = analysis["stats"]
    assert stats["totalReviews"] == 3 and stats["analysedReviews"] == 2
    assert stats["notAnalysed"] == {"languageNotSupported": 1}
    assert stats["sentimentCounts"] == {"positive": 1, "neutral": 0, "negative": 1}
    assert stats["sentimentPercent"]["positive"] == 50.0
    assert stats["ratedReviews"] == 3 and stats["averageRating"] == round(7 / 3, 2)  # stars count in any language
    assert "2" not in stats["ratingSentimentMismatches"]
    assert any("not in English" in note for note in analysis["summary"]["notes"])
    assert all("bakwas" not in k["term"] for k in analysis["keywords"])


# ---------- Short reviews and titles ----------

def test_short_review_uses_its_title():
    analysis = one("Trustworthy", extra={"title": "Terrible update, everything is broken"})
    review = analysis["reviews"][0]
    assert review["usedTitle"] is True and review["sentiment"] == "negative"
    assert review["text"] == "Trustworthy"  # display text unchanged


def test_long_review_ignores_its_title():
    analysis = one("The battery easily lasts two full days with heavy use", extra={"title": "Awful"})
    assert analysis["reviews"][0]["usedTitle"] is False
    assert analysis["reviews"][0]["sentiment"] != "negative"


# ---------- Aspects ----------

def test_vocabulary_follows_the_product_type():
    assert choose_vocabulary("product") is PRODUCT_ASPECTS
    assert set(choose_vocabulary("app")) == set(APP_ASPECTS)
    assert "Orders & delivery" in choose_vocabulary("app", "Food & Drink")
    assert "Refunds & returns" in choose_vocabulary("app", "Shopping")
    assert choose_vocabulary("something else") is PRODUCT_ASPECTS


def test_app_reviews_never_show_phone_features_and_vice_versa():
    text = "The battery drain is bad and the camera filter crashes. Login is easy."
    app = {a["aspect"] for a in one(text, domain="app")["reviews"][0]["aspects"]}
    product = {a["aspect"] for a in one(text, domain="product")["reviews"][0]["aspects"]}
    assert not app & {"Battery", "Camera"} and {"Crashes & stability", "Login & account"} <= app
    assert not product & set(APP_ASPECTS) and {"Battery", "Camera"} <= product


@pytest.mark.parametrize(("text", "expected"), [
    ("I can't log in, OTP never arrives", {"Login & account": "negative"}),
    ("Keeps crashing after every update", {"Crashes & stability": "negative", "Updates": "negative"}),
    ("Customer support never responds", {"Customer support": "negative"}),
    ("Too many ads", {"Ads": "negative"}),
    ("Love the clean interface", {"Design & ease of use": "positive"}),
])
def test_app_aspects(text, expected):
    aspects = {a["aspect"]: a["sentiment"] for a in one(text, domain="app")["reviews"][0]["aspects"]}
    assert aspects == expected


def test_each_aspect_is_scored_on_its_own_words_not_the_whole_review():
    review = one("Great battery, but the camera is terrible in low light")["reviews"][0]
    aspects = {a["aspect"]: (a["sentiment"], a["snippet"]) for a in review["aspects"]}
    assert aspects["Battery"] == ("positive", "Great battery")
    assert aspects["Camera"] == ("negative", "the camera is terrible in low light")
    assert review["mixed"] is True


def test_payments_good_notifications_bad_is_mixed():
    review = one("Payments are quick and easy, but notifications never arrive", domain="app")["reviews"][0]
    aspects = {a["aspect"]: a["sentiment"] for a in review["aspects"]}
    assert aspects["Payments & pricing"] == "positive" and aspects["Notifications"] == "negative"
    assert review["mixed"] is True


def test_terms_match_whole_words_only():
    assert find_mentions("I added it to my cart", APP_ASPECTS) == []  # "ad" must not match "added"
    assert find_mentions("ads everywhere", APP_ASPECTS)[0]["aspect"] == "Ads"


# ---------- Keywords ----------

def test_product_name_and_generic_words_are_not_keywords():
    texts = ["WhatsApp is a good app, but the update broke backups"] * 3 + ["Good app, backups fail after update"] * 2
    terms = {k["term"] for k in extract_keywords(texts, extra_stopwords=name_stopwords("WhatsApp Messenger", "Meta"))}
    assert not terms & {"whatsapp", "app", "good"}
    assert {"update", "backups"} <= terms


# ---------- Engine selection and fallback ----------

def test_vader_preference_records_no_fallback():
    engine = one("Great")["engine"]
    assert engine["id"] == "vader" and engine["fallbackReason"] is None and engine["pipelineVersion"] == 2


def test_missing_model_falls_back_to_vader_with_a_reason(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "MODEL_DIR", tmp_path / "no-model-here")
    engines.reset_engines()
    try:
        analysis = one("Great app", engine_preference="transformer")
    finally:
        engines.reset_engines()
    assert analysis["engine"]["id"] == "vader"
    assert "VADER was used instead" in analysis["engine"]["fallbackReason"]
    assert analysis["reviews"][0]["sentiment"] == "positive"


def test_fallback_reason_does_not_reveal_local_paths(tmp_path, monkeypatch):
    broken = config.BACKEND_DIR / "models" / "test-broken-model"
    monkeypatch.setattr(config, "MODEL_DIR", broken)
    broken.mkdir(parents=True, exist_ok=True)
    (broken / "model_quantized.onnx").write_bytes(b"not a model")
    engines.reset_engines()
    try:
        reason = one("Great", engine_preference="transformer")["engine"]["fallbackReason"]
    finally:
        engines.reset_engines()
        for f in broken.iterdir():
            f.unlink()
        broken.rmdir()
    assert reason and str(config.BACKEND_DIR) not in reason


def test_engine_failure_during_analysis_redoes_the_run_with_vader(monkeypatch):
    class Broken:
        id, name = "transformer", "broken"

        def describe(self):
            return {"id": self.id}

        def predict(self, texts):
            raise RuntimeError("damaged model file")

    monkeypatch.setattr(engines, "get_engine", lambda preference=None: (Broken(), None))
    monkeypatch.setattr("app.nlp.pipeline.get_engine", lambda preference=None: (Broken(), None))
    analysis = analyze_reviews([{"id": "1", "text": "Great"}, {"id": "2", "text": "Awful battery"}])
    assert analysis["engine"]["id"] == "vader"
    assert "damaged model file" in analysis["engine"]["fallbackReason"]
    assert [r["sentiment"] for r in analysis["reviews"]] == ["positive", "negative"]


def test_engine_metadata_lists_the_features_used():
    engine = one("ok", domain="app", category="Food & Drink")["engine"]
    assert engine["domain"] == "app" and "Orders & delivery" in engine["features"]
