"""Run every analysis step over a list of reviews and build one result.

Input reviews are plain dicts with keys: id, text, rating (1-5 or None),
date (ISO string or None), title, reviewer. Output is JSON-ready.
"""
from collections import Counter

from .aspects import ASPECT_TERMS, find_aspects, verdict
from .keywords import extract_keywords
from .preprocess import normalize_text
from .sentiment import score_text
from .summary import build_summary

SENTIMENTS = ("positive", "neutral", "negative")


def analyze_review(review: dict) -> dict:
    text = normalize_text(review.get("text"))
    sentiment = score_text(text)
    aspects = find_aspects(text)
    clause_labels = {a["sentiment"] for a in aspects}
    return {
        **review,
        "text": text,
        "sentiment": sentiment["label"],
        "score": sentiment["compound"],
        "aspects": aspects,
        # True when the review praises one aspect and criticises another.
        "mixed": {"positive", "negative"} <= clause_labels,
    }


def _percent(part: int, whole: int) -> float:
    return round(100 * part / whole, 1) if whole else 0.0


def _aspect_table(analyzed: list[dict]) -> list[dict]:
    rows = []
    for aspect in ASPECT_TERMS:
        mentions = [a | {"review_id": r["id"]} for r in analyzed for a in r["aspects"] if a["aspect"] == aspect]
        if not mentions:
            continue
        counts = Counter(m["sentiment"] for m in mentions)
        best = max(mentions, key=lambda m: m["score"])
        worst = min(mentions, key=lambda m: m["score"])
        rows.append({
            "aspect": aspect,
            "mentions": len(mentions),
            "positive": counts["positive"],
            "neutral": counts["neutral"],
            "negative": counts["negative"],
            "verdict": verdict(counts["positive"], counts["negative"], counts["neutral"]),
            "examplePositive": {"reviewId": best["review_id"], "text": best["snippet"]} if best["score"] > 0 else None,
            "exampleNegative": {"reviewId": worst["review_id"], "text": worst["snippet"]} if worst["score"] < 0 else None,
        })
    return sorted(rows, key=lambda r: -r["mentions"])


def analyze_reviews(reviews: list[dict]) -> dict:
    analyzed = [analyze_review(r) for r in reviews]
    total = len(analyzed)
    sentiment_counts = Counter(r["sentiment"] for r in analyzed)
    rated = [r["rating"] for r in analyzed if r.get("rating") is not None]
    dates = sorted(r["date"] for r in analyzed if r.get("date"))

    # Star rating and written sentiment are measured separately; where they
    # disagree strongly we flag the review instead of trusting either one.
    mismatched = [
        r["id"] for r in analyzed if r.get("rating") is not None and (
            (r["rating"] >= 4 and r["sentiment"] == "negative")
            or (r["rating"] <= 2 and r["sentiment"] == "positive"))
    ]

    stats = {
        "totalReviews": total,
        "ratedReviews": len(rated),
        "averageRating": round(sum(rated) / len(rated), 2) if rated else None,
        "sentimentCounts": {s: sentiment_counts[s] for s in SENTIMENTS},
        "sentimentPercent": {s: _percent(sentiment_counts[s], total) for s in SENTIMENTS},
        "ratingDistribution": [{"stars": s, "count": rated.count(s)} for s in (5, 4, 3, 2, 1)],
        "ratingSentimentMismatches": mismatched,
        "dateRange": {"from": dates[0], "to": dates[-1]} if dates else None,
    }
    aspects = _aspect_table(analyzed)
    keywords = extract_keywords([r["text"] for r in analyzed])
    return {
        "stats": stats,
        "aspects": aspects,
        "keywords": keywords,
        "summary": build_summary(stats, aspects),
        "reviews": analyzed,
    }
