"""Run the NLP pipeline on a product's stored reviews and save the result."""
from datetime import timezone

from sqlalchemy.orm import Session

from ..errors import AppError
from ..models import AnalysisResult, Product, Review
from ..nlp.pipeline import analyze_reviews


def as_utc(value):
    """SQLite returns naive datetimes; everything we store is UTC."""
    return value.replace(tzinfo=timezone.utc) if value and value.tzinfo is None else value


def _review_input(review: Review) -> dict:
    return {
        "id": review.external_id,
        "text": review.text,
        "rating": review.rating,
        "date": review.review_date.isoformat() if review.review_date else None,
        "title": review.title,
        "reviewer": review.reviewer,
    }


def run_analysis(db: Session, product: Product, ingestion: dict | None = None) -> AnalysisResult:
    """Analyse every review of `product`, update the reviews and store a new AnalysisResult.

    The caller commits the session.
    """
    reviews = list(product.reviews)
    if not reviews:
        raise AppError("This product has no reviews to analyse. Add or upload reviews first.", 422)

    result = analyze_reviews([_review_input(r) for r in reviews])

    by_id = {r.external_id: r for r in reviews}
    for analysed in result["reviews"]:
        row = by_id[analysed["id"]]
        row.sentiment = analysed["sentiment"]
        row.score = analysed["score"]
        row.mixed = analysed["mixed"]
        row.aspects = analysed["aspects"]

    if ingestion is None and product.latest_analysis is not None:
        ingestion = product.latest_analysis.ingestion  # keep the upload's cleaning report on re-analysis

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
    )
    db.add(analysis)
    db.flush()
    db.refresh(product)  # so product.analyses puts the new run first
    return analysis


def review_out(review: Review) -> dict:
    return {
        "id": review.external_id,
        "text": review.text,
        "rating": review.rating,
        "date": review.review_date,
        "title": review.title,
        "reviewer": review.reviewer,
        "sentiment": review.sentiment,
        "score": review.score,
        "mixed": review.mixed,
        "aspects": review.aspects or [],
    }


def analysis_out(product: Product) -> dict:
    """The full analysis for the product page (latest run + current reviews)."""
    analysis = product.latest_analysis
    if analysis is None:
        raise AppError("This product hasn’t been analysed yet.", 409)
    return {
        "analysisId": analysis.id,
        "product": {"id": product.id, "name": product.name, "brand": product.brand,
                    "category": product.category, "source": product.source},
        "stats": analysis.stats,
        "aspects": analysis.aspects,
        "keywords": analysis.keywords,
        "summary": analysis.summary,
        "reviews": [review_out(r) for r in product.reviews],
        "ingestion": analysis.ingestion,
        "analyzedAt": as_utc(analysis.created_at),
    }
