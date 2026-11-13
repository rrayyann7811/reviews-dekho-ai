"""Sentiment scoring with VADER.

VADER is a lexicon- and rule-based model (not deep learning). It scores text
from a dictionary of word polarities plus rules for negation, intensifiers
("very"), punctuation and capitalisation. The compound score ranges from
-1 (most negative) to +1 (most positive).
"""
from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer

# Standard thresholds recommended by the VADER authors.
POSITIVE_THRESHOLD = 0.05
NEGATIVE_THRESHOLD = -0.05

# Product-review words that VADER's general lexicon misses or scores as
# neutral. Kept small and visible so the effect is easy to explain.
DOMAIN_LEXICON = {
    "drains": -1.5, "drain": -1.2, "lag": -1.5, "lags": -1.5, "lagging": -1.8,
    "laggy": -1.8, "heats": -1.2, "overheating": -2.0, "grainy": -1.5,
    "blurry": -1.5, "bloatware": -1.5, "overpriced": -2.0, "defective": -2.5,
    "crashes": -2.0, "bugs": -1.5, "buggy": -1.8, "scratched": -1.5,
    "crushed": -1.5, "torn": -1.5, "stutter": -1.2, "sluggish": -1.5,
    "crisp": 1.5, "vibrant": 1.5, "smooth": 1.5, "sturdy": 1.3,
}

_analyzer = SentimentIntensityAnalyzer()
_analyzer.lexicon.update(DOMAIN_LEXICON)


def label_for(compound: float) -> str:
    if compound >= POSITIVE_THRESHOLD:
        return "positive"
    if compound <= NEGATIVE_THRESHOLD:
        return "negative"
    return "neutral"


def score_text(text: str) -> dict:
    """Return the compound score and its label for a piece of text."""
    if not text:
        return {"compound": 0.0, "label": "neutral"}
    compound = _analyzer.polarity_scores(text)["compound"]
    return {"compound": round(compound, 4), "label": label_for(compound)}
