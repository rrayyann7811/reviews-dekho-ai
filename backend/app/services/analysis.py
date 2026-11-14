"""Run the NLP pipeline on a product's stored reviews and save the result.

Every run is saved as a complete snapshot (AnalysisResult.review_results), so
the history always shows exactly what was analysed at the time.
"""
from datetime import timezone

from sqlalchemy.orm import Session

from ..collectors.registry import site_name
from ..errors import AppError
from ..models import AnalysisResult, Product, Review
from ..nlp.pipeline import analyze_reviews

REVIEW_FIELDS = ("id", "text", "rating", "date", "title", "reviewer", "sentiment", "score", "mixed", "aspects",
                 "status", "language", "usedTitle")


def as_utc(value):
    """SQLite returns naive datetimes; everything we store is UTC."""
    return value.replace(tzinfo=timezone.utc) if value and value.tzinfo is None else value


def review_input(review: Review) -> dict:
    return {
        "id": review.external_id,
        "text": review.text,
        "rating": review.rating,
        "date": review.review_date.isoformat() if review.review_date else None,
        "title": review.title,
        "reviewer": review.reviewer,
    }


def run_analysis(db: Session, product: Product, ingestion: dict | None = None) -> AnalysisResult:
    """Analyse every review of `product` and store a new AnalysisResult. The caller commits."""
    reviews = list(product.reviews)
    if not reviews:
        raise AppError("This product has no reviews to analyse. Add or upload reviews first.", 422)

    result = analyze_reviews([review_input(r) for r in reviews], domain=product.domain, category=product.category,
                             product_name=product.name, brand=product.brand)

    if ingestion is None and product.latest_analysis is not None:
        ingestion = product.latest_analysis.ingestion  # keep the upload/collection report on re-analysis

    stats = result["stats"]
    analysis = AnalysisResult(
        product=product,
        total_reviews=stats["totalReviews"],
        average_rating=stats["averageRating"],
        positive_percent=stats["sentimentPercent"]["positive"],
        negative_percent=stats["sentimentPercent"]["negative"],
        stats=stats,
        aspects=result["aspects"],
        keywords=result["keywords"],
        summary=result["summary"],
        ingestion=ingestion,
        review_results=[{key: r.get(key) for key in REVIEW_FIELDS} for r in result["reviews"]],
        engine=result["engine"],
    )
    db.add(analysis)
    db.flush()
    db.refresh(product)  # so product.analyses puts the new run first
    return analysis


def unanalysed_review(review: Review) -> dict:
    """A stored review that no analysis run has covered yet."""
    return review_input(review) | {"sentiment": None, "score": None, "mixed": False, "aspects": [],
                                   "status": "not_analysed_yet", "language": None, "usedTitle": False}


def current_reviews(product: Product) -> list[dict]:
    """Reviews with their results from the latest run (or without results if never analysed)."""
    latest = product.latest_analysis
    if latest is not None and latest.review_results is not None:
        return latest.review_results
    return [unanalysed_review(r) for r in product.reviews]


def source_out(product: Product) -> dict:
    """Where a product's reviews came from (link details are only set for collected products)."""
    return {
        "sourceUrl": product.source_url,
        "sourceSite": product.source_site,
        "sourceSiteName": site_name(product.source_site),
        "sourceRegion": product.source_region,
        "collectedAt": as_utc(product.collected_at),
    }


def analysis_out(product: Product) -> dict:
    """The full analysis for the product page: the latest run, exactly as it was stored."""
    analysis = product.latest_analysis
    if analysis is None:
        raise AppError("This product hasn’t been analysed yet.", 409)
    if analysis.review_results is None:
        raise AppError("This analysis was made by an older version of the app that didn’t keep per-review "
                       "results. Run the analysis again to see them.", 409)
    return {
        "analysisId": analysis.id,
        "product": {"id": product.id, "name": product.name, "brand": product.brand, "category": product.category,
                    "source": product.source, "domain": product.domain} | source_out(product),
        "engine": analysis.engine,
        "stats": analysis.stats,
        "aspects": analysis.aspects,
        "keywords": analysis.keywords,
        "summary": analysis.summary,
        "reviews": analysis.review_results,
        "ingestion": analysis.ingestion,
        "analyzedAt": as_utc(analysis.created_at),
    }
