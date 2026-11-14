"""Sentiment scoring with VADER (the rule-based engine and fallback).

VADER is a lexicon- and rule-based model (not deep learning). It scores text
from a dictionary of word polarities plus rules for negation, intensifiers
("very"), punctuation and capitalisation. The compound score ranges from
-1 (most negative) to +1 (most positive). Review-specific additions live in
rules.py.
"""
from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer

from .rules import DOMAIN_LEXICON, rewrite_for_vader

# Standard thresholds recommended by the VADER authors.
POSITIVE_THRESHOLD = 0.05
NEGATIVE_THRESHOLD = -0.05

_analyzer = SentimentIntensityAnalyzer()
_analyzer.lexicon.update(DOMAIN_LEXICON)
_KNOWN_WORDS = set(_analyzer.lexicon) | {"so", "too", "very", "soo"}


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
    compound = _analyzer.polarity_scores(rewrite_for_vader(text, _KNOWN_WORDS))["compound"]
    return {"compound": round(compound, 4), "label": label_for(compound)}
