"""Product and review helpers shared by several routes."""
from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from ..errors import AppError, NotFound
from ..models import AnalysisResult, Product, Review
from .analysis import as_utc, source_out


def get_product(db: Session, product_id: int) -> Product:
    product = db.get(Product, product_id)
    if product is None:
        raise NotFound(f"Product {product_id} doesn’t exist. It may have been deleted.")
    return product


def summary_out(product: Product) -> dict:
    latest = product.latest_analysis
    return {
        "id": product.id,
        "name": product.name,
        "brand": product.brand,
        "category": product.category,
        "source": product.source,
        "fileName": product.file_name,
        "createdAt": as_utc(product.created_at),
        # The number the latest analysis covered, so the list always agrees with the analysis page.
        "totalReviews": latest.total_reviews if latest else len(product.reviews),
        "averageRating": latest.average_rating if latest else None,
        "positivePercent": latest.positive_percent if latest else None,
        "analyzedAt": as_utc(latest.created_at) if latest else None,
    } | source_out(product)


def list_products(db: Session) -> list[Product]:
    query = (select(Product)
             .options(selectinload(Product.reviews).load_only(Review.id), selectinload(Product.analyses))
             .order_by(Product.created_at.desc(), Product.id.desc()))
    return list(db.scalars(query))


def add_reviews(db: Session, product: Product, reviews: list[dict], skip_existing: bool = False) -> tuple[int, int]:
    """Add review dicts (id, text, rating, date, title, reviewer) to a product. Returns (added, skipped).

    A review whose ID already exists for this product is rejected (409), so the
    same reviews can't silently be counted twice — or, with skip_existing=True
    (used when refreshing collected reviews), quietly skipped.
    """
    existing = set(db.scalars(select(Review.external_id).where(Review.product_id == product.id))) if product.id else set()
    next_number = (db.scalar(select(func.count()).select_from(Review).where(Review.product_id == product.id)) or 0) + 1 \
        if product.id else 1

    duplicates, added = [], 0
    for item in reviews:
        external_id = item.get("id")
        if not external_id:
            while f"R-{next_number}" in existing:
                next_number += 1
            external_id = f"R-{next_number}"
        if external_id in existing:
            duplicates.append(external_id)
            continue
        existing.add(external_id)
        added += 1
        product.reviews.append(Review(
            external_id=external_id, text=item["text"], rating=item.get("rating"), review_date=item.get("date"),
            title=item.get("title"), reviewer=item.get("reviewer")))
    if duplicates and not skip_existing:
        shown = ", ".join(duplicates[:5]) + ("…" if len(duplicates) > 5 else "")
        raise AppError(f"These review IDs already exist for this product: {shown}.", 409)
    return added, len(duplicates)


def history_query():
    return (select(AnalysisResult, Product.name, Product.source)
            .join(Product, AnalysisResult.product_id == Product.id)
            .order_by(AnalysisResult.created_at.desc(), AnalysisResult.id.desc()))


def history_out(analysis: AnalysisResult, product_name: str, source: str, detail: bool = False) -> dict:
    out = {
        "id": analysis.id,
        "productId": analysis.product_id,
        "productName": product_name,
        "source": source,
        "createdAt": as_utc(analysis.created_at),
        "totalReviews": analysis.total_reviews,
        "averageRating": analysis.average_rating,
        "positivePercent": analysis.positive_percent,
        "negativePercent": analysis.negative_percent,
    }
    if detail:
        out |= {"stats": analysis.stats, "aspects": analysis.aspects, "keywords": analysis.keywords,
                "summary": analysis.summary, "ingestion": analysis.ingestion,
                "reviews": analysis.review_results}  # None for runs made before Phase 3
    return out
