"""Rule-based aspect sentiment.

How it works:
1. Split each review into clauses (see preprocess.split_clauses).
2. If a clause contains a term from ASPECT_TERMS, the clause is about that aspect.
3. Score that clause alone with VADER, so "great battery, but poor camera"
   gives battery = positive and camera = negative.

This is a transparent keyword method, not a learned model. It misses aspects
described without these words and can be confused by sarcasm.
"""
import re

from .preprocess import split_clauses
from .sentiment import score_text

ASPECT_TERMS = {
    "Battery": ["battery", "charge", "charging", "charger", "drains", "backup", "standby"],
    "Camera": ["camera", "photo", "photos", "selfie", "selfies", "portrait", "night mode", "lens", "video stabilisation"],
    "Display": ["display", "screen", "amoled", "brightness", "120hz", "dead pixels", "touch screen"],
    "Performance": ["performance", "lag", "lags", "lagging", "smooth", "gaming", "games", "heats", "overheating", "warm", "slows", "crashes", "software"],
    "Build quality": ["build", "built", "premium", "design", "weight", "heavy", "back panel", "matte back"],
    "Price": ["price", "value for money", "worth", "overpriced", "affordable", "budget", "rupee"],
    "Delivery": ["delivery", "delivered", "shipping", "received it"],
    "Packaging": ["packaging", "packed", "box"],
    "Customer service": ["customer service", "customer support", "support", "service centre", "replacement", "return process"],
}

_PATTERNS = {
    aspect: re.compile(r"\b(" + "|".join(re.escape(t) for t in terms) + r")\b", re.IGNORECASE)
    for aspect, terms in ASPECT_TERMS.items()
}

# An aspect needs at least this many mentions before we call it a strength/weakness.
MIN_MENTIONS_FOR_VERDICT = 3
# Share of positive (or negative) mentions needed to call it clearly positive (or negative).
CLEAR_MAJORITY = 0.65


def find_aspects(text: str) -> list[dict]:
    """Return one entry per aspect mentioned in the review."""
    found: dict[str, dict] = {}
    for clause in split_clauses(text):
        for aspect, pattern in _PATTERNS.items():
            if aspect in found or not pattern.search(clause):
                continue
            result = score_text(clause)
            found[aspect] = {"aspect": aspect, "sentiment": result["label"],
                             "score": result["compound"], "snippet": clause}
    return list(found.values())


def verdict(positive: int, negative: int, neutral: int) -> str:
    """Summarise one aspect's mentions as positive / negative / mixed."""
    total = positive + negative + neutral
    if total < MIN_MENTIONS_FOR_VERDICT:
        return "insufficient"
    if positive / total >= CLEAR_MAJORITY:
        return "positive"
    if negative / total >= CLEAR_MAJORITY:
        return "negative"
    return "mixed"
