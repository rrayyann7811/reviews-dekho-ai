"""Search, filter, sort and page the reviews of ONE analysis run.

The dashboard's review list asks the server for one page at a time instead of
downloading every review. The rules match the offline demo's filtering in
frontend/src/lib/reviewFilters.js, so both behave the same way:

  sentiment  all | positive | neutral | negative
             mixed       (praises one feature, criticises another)
             mismatch    (star rating disagrees with the wording)
             unanalysed  (not analysed, e.g. not English)
  rating     all | 1-5 | none (no star rating)
  search     case-insensitive, in the title, text and reviewer name
  sort       newest | oldest | positive | negative  (missing dates/scores always last)
"""
from ..errors import AppError, NotFound
from ..models import AnalysisResult, Product

SENTIMENT_FILTERS = ("all", "positive", "neutral", "negative", "mixed", "mismatch", "unanalysed")
RATING_FILTERS = ("all", "1", "2", "3", "4", "5", "none")
SORTS = ("newest", "oldest", "positive", "negative")


def pick_run(product: Product, analysis_id: int | None) -> AnalysisResult:
    """The latest run, or a specific one (so paging stays consistent if a new run is added meanwhile)."""
    if analysis_id is None:
        run = product.latest_analysis
        if run is None:
            raise AppError("This product hasn’t been analysed yet.", 409)
    else:
        run = next((a for a in product.analyses if a.id == analysis_id), None)
        if run is None:
            raise NotFound(f"Analysis {analysis_id} doesn’t belong to this product.")
    if run.review_results is None:
        raise AppError("This analysis was made by an older version of the app that didn’t keep per-review "
                       "results. Run the analysis again to see them.", 409)
    return run


def _matches(review: dict, sentiment: str, rating: str, needle: str, mismatches: set) -> bool:
    if sentiment == "mixed" and not review.get("mixed"):
        return False
    if sentiment == "mismatch" and review["id"] not in mismatches:
        return False
    if sentiment == "unanalysed" and review.get("sentiment") is not None:
        return False
    if sentiment in ("positive", "neutral", "negative") and review.get("sentiment") != sentiment:
        return False
    if rating == "none" and review.get("rating") is not None:
        return False
    if rating not in ("all", "none") and review.get("rating") != int(rating):
        return False
    if needle:
        haystack = f"{review.get('title') or ''} {review.get('text') or ''} {review.get('reviewer') or ''}".casefold()
        if needle not in haystack:
            return False
    return True


def _sorted(reviews: list[dict], sort: str) -> list[dict]:
    # Python's sort is stable, so equal items keep their stored order — like the demo's sorting.
    if sort in ("newest", "oldest"):
        dated = [r for r in reviews if r.get("date")]
        dated.sort(key=lambda r: r["date"], reverse=sort == "newest")
        return dated + [r for r in reviews if not r.get("date")]
    scored = [r for r in reviews if r.get("score") is not None]
    scored.sort(key=lambda r: r["score"], reverse=sort == "positive")
    return scored + [r for r in reviews if r.get("score") is None]


def query_reviews(run: AnalysisResult, *, sentiment="all", rating="all", search="", sort="newest",
                  offset=0, limit=20) -> dict:
    mismatches = set(run.stats.get("ratingSentimentMismatches", []))
    needle = (search or "").strip().casefold()
    rows = [r for r in run.review_results if _matches(r, sentiment, rating, needle, mismatches)]
    rows = _sorted(rows, sort)
    return {"analysisId": run.id, "total": len(rows), "offset": offset, "limit": limit,
            "items": rows[offset:offset + limit]}


def find_review(run: AnalysisResult, review_id: str) -> dict:
    review = next((r for r in run.review_results if r["id"] == review_id), None)
    if review is None:
        raise NotFound(f"Review {review_id} isn’t part of this analysis.")
    return review


def tone_by_rating(reviews: list[dict]) -> list[dict]:
    """For each star rating: how many reviews read positive / neutral / negative, and how many weren't analysed.

    Derived from the stored per-review results, so it is available for every run that has them.
    """
    rows = []
    for stars in (5, 4, 3, 2, 1):
        group = [r for r in reviews if r.get("rating") == stars]
        rows.append({"stars": stars, "reviews": len(group),
                     **{s: sum(r.get("sentiment") == s for r in group) for s in ("positive", "neutral", "negative")},
                     "notAnalysed": sum(r.get("sentiment") is None for r in group)})
    return rows
