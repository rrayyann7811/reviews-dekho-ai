"""Run every analysis step over a list of reviews and build one result.

Input reviews are plain dicts with keys: id, text, rating (1-5 or None),
date (ISO string or None), title, reviewer. Output is JSON-ready.

Steps for each review:
1. Language check (language.py). Reviews not in English are marked
   "language_not_supported" and get no sentiment, instead of a fake "neutral".
2. Text to analyse: the review text; for very short texts ("Trustworthy")
   the reviewer's own title is added, because it usually carries the opinion.
3. Whole-review sentiment: one batched call to the sentiment engine.
4. Features: each mention's own clause is scored, again in one batched call
   (aspects.py). A feature's sentiment never comes from the whole review.
"""
from collections import Counter

from .aspects import choose_vocabulary, find_mentions, verdict
from .engines import PIPELINE_VERSION, get_engine, vader_engine
from .keywords import extract_keywords, name_stopwords
from .language import NOT_SUPPORTED, SUPPORTED, detect_language
from .preprocess import normalize_text, tidy_for_analysis, word_count
from .summary import build_summary

SENTIMENTS = ("positive", "neutral", "negative")
SHORT_REVIEW_WORDS = 5  # texts this short are analysed together with their title


def _percent(part: int, whole: int) -> float:
    return round(100 * part / whole, 1) if whole else 0.0


def _prepare(review: dict) -> dict:
    text = normalize_text(review.get("text"))
    title = normalize_text(review.get("title"))
    use_title = bool(title) and word_count(text) <= SHORT_REVIEW_WORDS
    analysed_text = f"{title}. {text}" if use_title else text
    language = detect_language(analysed_text)
    return {**review, "text": text, "title": title or None, "_analysed_text": tidy_for_analysis(analysed_text),
            "usedTitle": use_title, "status": language["status"], "language": language["language"]}


def _predict(engine, texts: list[str]):
    """Run the engine; if it fails mid-run, redo everything with VADER so a run never mixes engines."""
    try:
        return engine, engine.predict(texts), None
    except Exception as exc:  # e.g. a damaged model file
        fallback = vader_engine()
        return fallback, fallback.predict(texts), f"The sentiment model failed during analysis ({exc}); VADER was used."


def _aspect_table(analysed: list[dict], vocabulary: dict) -> list[dict]:
    rows = []
    for aspect in vocabulary:
        mentions = [a | {"review_id": r["id"]} for r in analysed for a in r["aspects"] if a["aspect"] == aspect]
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
            "examplePositive": {"reviewId": best["review_id"], "text": best["snippet"]}
            if best["sentiment"] == "positive" else None,
            "exampleNegative": {"reviewId": worst["review_id"], "text": worst["snippet"]}
            if worst["sentiment"] == "negative" else None,
        })
    return sorted(rows, key=lambda r: -r["mentions"])


def analyze_reviews(reviews: list[dict], *, domain: str = "product", category: str | None = None,
                    product_name: str | None = None, brand: str | None = None,
                    engine_preference: str | None = None) -> dict:
    vocabulary = choose_vocabulary(domain, category)
    prepared = [_prepare(r) for r in reviews]
    supported = [r for r in prepared if r["status"] == SUPPORTED]

    # One batched call for whole reviews, one for every feature clause.
    engine, fallback_reason = get_engine(engine_preference)
    mentions = [(r, m) for r in supported for m in find_mentions(r["_analysed_text"], vocabulary)]
    texts = [r["_analysed_text"] for r in supported] + [m["snippet"] for _, m in mentions]
    engine, predictions, failure = _predict(engine, texts)
    fallback_reason = failure or fallback_reason
    review_predictions, mention_predictions = predictions[:len(supported)], predictions[len(supported):]

    for review in prepared:
        review["aspects"] = []
    for review, prediction in zip(supported, review_predictions):
        review["sentiment"], review["score"] = prediction["label"], prediction["score"]
    for (review, mention), prediction in zip(mentions, mention_predictions):
        review["aspects"].append({**mention, "sentiment": prediction["label"], "score": prediction["score"]})

    analysed = []
    for review in prepared:
        labels = {a["sentiment"] for a in review["aspects"]}
        not_supported = review["status"] == NOT_SUPPORTED
        analysed.append({
            "id": review["id"], "text": review["text"], "rating": review.get("rating"), "date": review.get("date"),
            "title": review["title"], "reviewer": review.get("reviewer"),
            "sentiment": None if not_supported else review["sentiment"],
            "score": None if not_supported else review["score"],
            "aspects": review["aspects"],
            # True when the review praises one feature and criticises another.
            "mixed": {"positive", "negative"} <= labels,
            "status": review["status"], "language": review["language"], "usedTitle": review["usedTitle"],
        })

    scored = [r for r in analysed if r["status"] == SUPPORTED]
    total, counted = len(analysed), len(scored)
    sentiment_counts = Counter(r["sentiment"] for r in scored)
    rated = [r["rating"] for r in analysed if r.get("rating") is not None]  # stars count in any language
    dates = sorted(r["date"] for r in analysed if r.get("date"))

    # Star rating and written sentiment are measured separately; where they
    # disagree strongly we flag the review instead of trusting either one.
    mismatched = [
        r["id"] for r in scored if r.get("rating") is not None and (
            (r["rating"] >= 4 and r["sentiment"] == "negative")
            or (r["rating"] <= 2 and r["sentiment"] == "positive"))
    ]

    stats = {
        "totalReviews": total,
        "analysedReviews": counted,
        "notAnalysed": {"languageNotSupported": total - counted},
        "ratedReviews": len(rated),
        "averageRating": round(sum(rated) / len(rated), 2) if rated else None,
        # Percentages are of the reviews whose sentiment could be analysed.
        "sentimentCounts": {s: sentiment_counts[s] for s in SENTIMENTS},
        "sentimentPercent": {s: _percent(sentiment_counts[s], counted) for s in SENTIMENTS},
        "ratingDistribution": [{"stars": s, "count": rated.count(s)} for s in (5, 4, 3, 2, 1)],
        "ratingSentimentMismatches": mismatched,
        "dateRange": {"from": dates[0], "to": dates[-1]} if dates else None,
    }
    aspects = _aspect_table(scored, vocabulary)
    keywords = extract_keywords([r["text"] for r in scored], extra_stopwords=name_stopwords(product_name, brand))
    return {
        "stats": stats,
        "aspects": aspects,
        "keywords": keywords,
        "summary": build_summary(stats, aspects),
        "reviews": analysed,
        "engine": engine.describe() | {"pipelineVersion": PIPELINE_VERSION, "fallbackReason": fallback_reason,
                                       "domain": "app" if domain == "app" else "product",
                                       "features": list(vocabulary)},
    }
