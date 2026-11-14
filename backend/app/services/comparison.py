"""Side-by-side comparison of two stored analysis runs (Phase 7).

Everything is computed from the two immutable snapshots (stats, features, engine record); nothing is re-analysed,
stored or written, so the same pair of runs always gives the same comparison. The two runs can belong to two
products or to the same product (for example before and after new reviews were collected).

How differences are described
* Every share is shown with its count and base (n) and a 95% Wilson interval.
* A difference is called "clear separation in these samples" only when both bases are at least
  MIN_SAMPLE_FOR_SEPARATION and the two intervals don't overlap. That is a description of these two samples,
  not a significance test: reviews are written by people who chose to write them, not a random sample of
  customers, and the interval reflects sample size only.
* Otherwise the difference is "overlapping" (the intervals overlap), "too few" (a base under the threshold) or
  "not measurable" (a base of zero; never shown as 0%).
* There is no overall winner and no generated text.

Features
A feature on one side is "compared" (>= MIN_FEATURE_MENTIONS mentions), "few mentions", "not mentioned" (searched
for, no mention), "not looked for" (not in that run's feature list, e.g. app features for a phone) or "unknown"
(older runs didn't record which features were searched for). Missing features are never treated as negative.
"""
import math

from ..models import AnalysisResult, Product
from ..nlp.aspects import MIN_MENTIONS_FOR_VERDICT
from .analysis import as_utc, source_out

MIN_SAMPLE_FOR_SEPARATION = 30   # per side, for the base of a share (analysed reviews, or a feature's mentions)
SIZE_GAP_WARNING = 5             # warn when one side has this many times the analysed reviews of the other
NOT_ANALYSED_WARNING = 0.10      # warn when more than this share of a side's reviews wasn't analysed
MIN_FEATURE_MENTIONS = MIN_MENTIONS_FOR_VERDICT  # the dashboard's own threshold for a feature verdict (3)
Z_95 = 1.959964

SENTIMENTS = ("positive", "neutral", "negative")
CLEAR, OVERLAPPING, TOO_FEW, NOT_MEASURABLE = "clear", "overlapping", "too-few", "not-measurable"
SEPARATION_TEXT = "clear separation in these samples"
SELF_SELECTED_NOTE = ("Reviews come from people who chose to write them, so neither side is a random or "
                      "representative sample of all customers. The intervals reflect sample size only.")


# ---------- Shares and intervals ----------

def wilson_interval(count: int, n: int) -> tuple[float, float] | None:
    """95% Wilson score interval for count/n, as fractions; None when n is 0."""
    if n <= 0:
        return None
    p = count / n
    denominator = 1 + Z_95 ** 2 / n
    centre = (p + Z_95 ** 2 / (2 * n)) / denominator
    half = Z_95 * math.sqrt(p * (1 - p) / n + Z_95 ** 2 / (4 * n ** 2)) / denominator
    return max(0.0, centre - half), min(1.0, centre + half)


def share(count: int, n: int) -> dict:
    """{count, n, percent, interval} with percentages rounded to 1 decimal; percent is None when n is 0."""
    interval = wilson_interval(count, n)
    return {"count": count, "n": n,
            "percent": round(100 * count / n, 1) if n else None,
            "interval": [round(100 * interval[0], 1), round(100 * interval[1], 1)] if interval else None}


def separation(a_count: int, a_n: int, b_count: int, b_n: int) -> str:
    if a_n == 0 or b_n == 0:
        return NOT_MEASURABLE
    if min(a_n, b_n) < MIN_SAMPLE_FOR_SEPARATION:
        return TOO_FEW
    a_low, a_high = wilson_interval(a_count, a_n)
    b_low, b_high = wilson_interval(b_count, b_n)
    return CLEAR if a_low > b_high or b_low > a_high else OVERLAPPING   # touching intervals count as overlapping


def compare_share(a_count: int, a_n: int, b_count: int, b_n: int) -> dict:
    a, b = share(a_count, a_n), share(b_count, b_n)
    difference = round(a["percent"] - b["percent"], 1) if a["percent"] is not None and b["percent"] is not None else None
    return {"a": a, "b": b, "difference": difference, "separation": separation(a_count, a_n, b_count, b_n)}


# ---------- One side ----------

def _engine(run: AnalysisResult) -> dict:
    engine = run.engine or {}
    # Runs made before Phase 4 have no engine record: they used the original VADER pipeline (version 1).
    return {"id": engine.get("id", "vader"), "name": engine.get("name", "VADER (rule-based)"),
            "model": engine.get("model"), "pipelineVersion": engine.get("pipelineVersion", 1),
            "fallbackReason": engine.get("fallbackReason")}


def _counts(run: AnalysisResult) -> dict:
    stats = run.stats or {}
    total = stats.get("totalReviews", run.total_reviews)
    analysed = stats.get("analysedReviews", total)   # before Phase 4 every review was analysed
    reasons = {k: v for k, v in (stats.get("notAnalysed") or {}).items() if v}
    return {"total": total, "analysed": analysed, "notAnalysed": total - analysed, "notAnalysedReasons": reasons,
            "rated": stats.get("ratedReviews", 0)}


def _side(product: Product, run: AnalysisResult) -> dict:
    stats, counts, ingestion = run.stats or {}, _counts(run), run.ingestion or {}
    latest = product.latest_analysis
    sentiment_counts = stats.get("sentimentCounts")
    sentiment = None
    if sentiment_counts and counts["analysed"]:
        sentiment = {s: share(sentiment_counts.get(s, 0), counts["analysed"]) for s in SENTIMENTS}
    distribution = {row["stars"]: row["count"] for row in stats.get("ratingDistribution") or []}
    rated = counts["rated"] or sum(distribution.values())
    store_rating = ingestion.get("storeRating") if isinstance(ingestion.get("storeRating"), (int, float)) else None
    return {
        "product": {"id": product.id, "name": product.name, "brand": product.brand, "category": product.category,
                    "source": product.source, "domain": product.domain, "fileName": product.file_name}
                   | source_out(product),
        "run": {"id": run.id, "createdAt": as_utc(run.created_at),
                "isLatest": latest is not None and latest.id == run.id,
                "latestRunId": latest.id if latest is not None else None,
                "summaryVersion": (run.summary or {}).get("version", 1)},
        "engine": _engine(run),
        "counts": counts | {"rated": rated},
        "dateRange": stats.get("dateRange"),
        # None = not measurable (nothing analysed, or an old run that didn't store counts) — never 0%.
        "sentiment": sentiment,
        "ratings": {
            "rated": rated,
            "average": stats.get("averageRating") if rated else None,
            "distribution": [{"stars": s, "count": distribution.get(s, 0),
                              "percent": round(100 * distribution.get(s, 0) / rated, 1) if rated else None}
                             for s in (5, 4, 3, 2, 1)],
            # Apple's own rating of the app, for context only: it isn't part of this analysis.
            "storeRating": store_rating,
            "storeRatingCount": ingestion.get("storeRatingCount") if store_rating is not None else None,
        },
    }


def _feature_list(run: AnalysisResult) -> list[str] | None:
    """The features this run searched for, or None if the run didn't record it (made before Phase 4)."""
    features = (run.engine or {}).get("features")
    return list(features) if features else None


# ---------- Features ----------

def _feature_side(row: dict | None, aspect: str, searched: list[str] | None, analysed: int) -> dict:
    mentions = row["mentions"] if row else 0
    if mentions >= MIN_FEATURE_MENTIONS:
        status = "compared"
    elif mentions:
        status = "few-mentions"
    elif searched is None:
        status = "unknown"
    elif aspect in searched:
        status = "not-mentioned"
    else:
        status = "not-looked-for"
    counts = {s: (row or {}).get(s, 0) for s in SENTIMENTS}
    return {"status": status, "mentions": mentions, **counts,
            "verdict": row.get("verdict") if row else None,
            # No rate when the feature wasn't (or may not have been) looked for: that's missing information, not 0%.
            "mentionRate": share(mentions, analysed) if status not in ("not-looked-for", "unknown") else None}


def _features(run_a: AnalysisResult, run_b: AnalysisResult, analysed_a: int, analysed_b: int) -> list[dict]:
    rows_a = {r["aspect"]: r for r in run_a.aspects or [] if r.get("mentions")}
    rows_b = {r["aspect"]: r for r in run_b.aspects or [] if r.get("mentions")}
    searched_a, searched_b = _feature_list(run_a), _feature_list(run_b)
    out = []
    for aspect in dict.fromkeys([*rows_a, *rows_b]):   # every feature mentioned on at least one side
        a = _feature_side(rows_a.get(aspect), aspect, searched_a, analysed_a)
        b = _feature_side(rows_b.get(aspect), aspect, searched_b, analysed_b)
        both = a["status"] == b["status"] == "compared"
        row = {"aspect": aspect, "a": a, "b": b, "comparable": both, "mentionRate": None, "tone": None}
        if a["mentionRate"] and b["mentionRate"]:
            row["mentionRate"] = compare_share(a["mentions"], analysed_a, b["mentions"], analysed_b)
        if both:  # tone within the feature: shares of its mentions
            row["tone"] = {s: compare_share(a[s], a["mentions"], b[s], b["mentions"]) for s in ("positive", "negative")}
        out.append(row)
    rank = lambda r: max(r["a"]["mentions"] / analysed_a if analysed_a else 0,
                         r["b"]["mentions"] / analysed_b if analysed_b else 0)
    return sorted(out, key=lambda r: (not r["comparable"], -rank(r), r["aspect"]))


# ---------- Caveats ----------

def _caveat(code: str, severity: str, message: str) -> dict:
    return {"code": code, "severity": severity, "message": message}


def _periods_overlap(a: dict | None, b: dict | None) -> bool | None:
    if not (a and b and a.get("from") and a.get("to") and b.get("from") and b.get("to")):
        return None
    return a["from"] <= b["to"] and b["from"] <= a["to"]


def _caveats(a: dict, b: dict, same_product: bool, same_run: bool, runs: tuple) -> list[dict]:
    out = []
    sides = (("A", a), ("B", b))
    if same_run:
        out.append(_caveat("same-run", "info", "Both sides are the same analysis run, so every figure is identical."))
    elif same_product:
        out.append(_caveat("same-product", "info",
                           "Both sides are runs of the same product. If reviews were added or re-collected between "
                           "the runs, the two samples share many reviews, so they aren't independent."))
    for label, side in sides:
        n = side["counts"]["analysed"]
        if n == 0:
            out.append(_caveat("nothing-analysed", "warning",
                               f"Side {label}: none of its {side['counts']['total']} reviews could be analysed "
                               "(for example, not in English), so its sentiment can't be measured."))
        elif side["sentiment"] is None:
            out.append(_caveat("sentiment-not-stored", "warning",
                               f"Side {label}: this older run didn't store sentiment counts, so its sentiment can't "
                               "be compared. Re-analyse the product for a comparable run."))
        elif n < MIN_SAMPLE_FOR_SEPARATION:
            out.append(_caveat("small-sample", "warning",
                               f"Side {label} has only {n} analysed reviews. Differences are only called clear when "
                               f"both sides have at least {MIN_SAMPLE_FOR_SEPARATION}."))
    sizes = sorted((a["counts"]["analysed"], b["counts"]["analysed"]))
    if sizes[0] and sizes[1] >= SIZE_GAP_WARNING * sizes[0] and not same_run:
        big, small = ("A", "B") if a["counts"]["analysed"] > b["counts"]["analysed"] else ("B", "A")
        out.append(_caveat("size-gap", "warning",
                           f"The samples differ a lot in size (A: {a['counts']['analysed']:,}, B: "
                           f"{b['counts']['analysed']:,} analysed reviews), so side {small}'s figures are much less "
                           f"certain than side {big}'s. Compare shares and their intervals, not counts."))
    for label, side in sides:
        total, missing = side["counts"]["total"], side["counts"]["notAnalysed"]
        if total and missing / total > NOT_ANALYSED_WARNING and side["counts"]["analysed"]:
            out.append(_caveat("not-analysed", "warning",
                               f"Side {label}: {missing:,} of {total:,} reviews ({round(100 * missing / total)}%) "
                               "weren't analysed (for example, not in English) and are left out of the sentiment "
                               "and feature figures. Their star ratings still count."))
    ea, eb = a["engine"], b["engine"]
    if ea["id"] != eb["id"] or ea["pipelineVersion"] != eb["pipelineVersion"]:
        out.append(_caveat("engine-differs", "warning",
                           f"The runs used different sentiment methods ({_engine_label(ea)} vs {_engine_label(eb)}). "
                           "The same review can be labelled differently by each, so sentiment differences may come "
                           "from the method rather than the reviews."))
    if a["product"]["domain"] != b["product"]["domain"]:
        out.append(_caveat("domain-differs", "info",
                           "One side is an app and the other a physical product, so they were checked for different "
                           "features. Only features both were checked for can be compared."))
    elif None not in (lists := (_feature_list(runs[0]), _feature_list(runs[1]))) and set(lists[0]) != set(lists[1]):
        out.append(_caveat("feature-lists-differ", "info",
                           "The two runs looked for slightly different features (for example, app categories add "
                           "their own). A feature looked for on one side only is marked “not looked for”, not "
                           "counted as zero."))
    if None in (_feature_list(runs[0]), _feature_list(runs[1])):
        out.append(_caveat("feature-list-unknown", "info",
                           "An older run didn't record which features it looked for, so a feature it doesn't mention "
                           "is shown as “unknown” rather than “not mentioned”."))
    if a["product"]["source"] != b["product"]["source"] or a["product"]["sourceSite"] != b["product"]["sourceSite"]:
        out.append(_caveat("source-differs", "info",
                           f"The reviews come from different sources ({_source_label(a)} vs {_source_label(b)}), "
                           "which can attract different kinds of reviewers."))
    if any(side["product"]["sourceSite"] == "apple_app_store" for _, side in sides):
        out.append(_caveat("app-store-recent", "info",
                           "App Store data covers only the most recent reviews Apple publishes (up to 500 per "
                           "country store), not every review ever written."))
    overlap = _periods_overlap(a["dateRange"], b["dateRange"])
    if overlap is False:
        out.append(_caveat("periods-differ", "info",
                           f"The review periods don't overlap ({_period(a)} vs {_period(b)}); opinions may have "
                           "changed over time."))
    elif overlap is None and not same_run:
        out.append(_caveat("period-unknown", "info",
                           "At least one side has no review dates, so the review periods can't be compared."))
    for label, side in sides:
        if side["ratings"]["rated"] == 0:
            out.append(_caveat("no-ratings", "info", f"Side {label} has no star ratings, so ratings can't be compared."))
    return out


def _engine_label(engine: dict) -> str:
    return engine["name"] if engine["pipelineVersion"] >= 2 else f"{engine['name']}, earlier pipeline"


def _source_label(side: dict) -> str:
    product = side["product"]
    if product["sourceSiteName"]:
        return product["sourceSiteName"]
    return {"upload": "uploaded file", "manual": "added by hand"}.get(product["source"], product["source"])


def _period(side: dict) -> str:
    r = side["dateRange"]
    return f"{r['from']} to {r['to']}"


# ---------- Statements ----------

def _pct(value: float | None) -> str:
    return "—" if value is None else f"{value:g}%"


def _share_sentence(subject: str, c: dict, base: str) -> str:
    return (f"{subject}: A {_pct(c['a']['percent'])} of {c['a']['n']:,} {base} vs B {_pct(c['b']['percent'])} of "
            f"{c['b']['n']:,} — {SEPARATION_TEXT}.")


def _statements(a: dict, b: dict, sentiment: dict | None, features: list[dict], same_run: bool) -> list[str]:
    if same_run:
        return ["Both sides are the same analysis run, so there are no differences to describe."]
    out = []
    if sentiment:
        for s in ("positive", "negative"):
            if sentiment[s]["separation"] == CLEAR:
                out.append(_share_sentence(f"{s.capitalize()} share of analysed reviews", sentiment[s],
                                           "analysed reviews"))
    for row in features:
        if row["tone"]:
            for s in ("positive", "negative"):
                if row["tone"][s]["separation"] == CLEAR:
                    out.append(_share_sentence(f"{row['aspect']}, {s} share of its mentions", row["tone"][s],
                                               "mentions"))
        if row["mentionRate"] and row["mentionRate"]["separation"] == CLEAR and row["comparable"]:
            out.append(_share_sentence(f"{row['aspect']}, share of analysed reviews mentioning it",
                                       row["mentionRate"], "analysed reviews"))
    ra, rb = a["ratings"], b["ratings"]
    if ra["average"] is not None and rb["average"] is not None:
        out.append(f"Average star rating: A {ra['average']:.1f} from {ra['rated']:,} rated reviews vs B "
                   f"{rb['average']:.1f} from {rb['rated']:,} (shown for reference; no separation test).")
    if not any(SEPARATION_TEXT in s for s in out):
        if min(a["counts"]["analysed"], b["counts"]["analysed"]) < MIN_SAMPLE_FOR_SEPARATION:
            out.insert(0, f"No difference is described as clear: at least one side has fewer than "
                          f"{MIN_SAMPLE_FOR_SEPARATION} analysed reviews.")
        else:
            out.insert(0, "No sentiment or feature figure shows clear separation in these samples; the intervals "
                          "overlap.")
    return out


# ---------- Public ----------

def compare_runs(product_a: Product, run_a: AnalysisResult, product_b: Product, run_b: AnalysisResult) -> dict:
    a, b = _side(product_a, run_a), _side(product_b, run_b)
    same_run, same_product = run_a.id == run_b.id, product_a.id == product_b.id
    sentiment = None
    if a["sentiment"] and b["sentiment"]:
        na, nb = a["counts"]["analysed"], b["counts"]["analysed"]
        sentiment = {s: compare_share(a["sentiment"][s]["count"], na, b["sentiment"][s]["count"], nb)
                     for s in SENTIMENTS}
    features = _features(run_a, run_b, a["counts"]["analysed"], b["counts"]["analysed"])
    return {
        "a": a,
        "b": b,
        "sameProduct": same_product,
        "sameRun": same_run,
        "sentiment": sentiment,
        "features": features,
        "caveats": _caveats(a, b, same_product, same_run, (run_a, run_b)),
        "statements": _statements(a, b, sentiment, features, same_run),
        "notes": [SELF_SELECTED_NOTE,
                  f"“Clear separation” means both sides have at least {MIN_SAMPLE_FOR_SEPARATION} in the base and "
                  "the 95% intervals don't overlap. It describes these samples; it isn't proof of a real difference "
                  "between the products.",
                  "Feature figures count each review once per feature it mentions, as shares of analysed reviews "
                  "or of the feature's mentions."],
        "thresholds": {"minSampleForSeparation": MIN_SAMPLE_FOR_SEPARATION, "sizeGapWarning": SIZE_GAP_WARNING,
                       "notAnalysedWarning": NOT_ANALYSED_WARNING, "minFeatureMentions": MIN_FEATURE_MENTIONS},
    }
