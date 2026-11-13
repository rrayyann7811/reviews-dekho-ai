from fastapi import APIRouter, Depends, Query, Response, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..database import get_db
from ..errors import NotFound
from ..models import Review
from ..schemas import ErrorResponse, ProductSummary, ReviewPage, ReviewsCreate
from ..services import analysis as analysis_service
from ..services import products as product_service

router = APIRouter(prefix="/products/{product_id}/reviews", tags=["Reviews"])
NOT_FOUND = {404: {"model": ErrorResponse, "description": "Product or review not found"}}


@router.get("", response_model=ReviewPage, responses=NOT_FOUND, summary="List a product's reviews")
def list_reviews(
    product_id: int,
    sentiment: str | None = Query(None, pattern="^(positive|neutral|negative)$"),
    rating: int | None = Query(None, ge=1, le=5),
    search: str | None = Query(None, max_length=200),
    offset: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=500),
    db: Session = Depends(get_db),
):
    product_service.get_product(db, product_id)
    query = select(Review).where(Review.product_id == product_id)
    if sentiment:
        query = query.where(Review.sentiment == sentiment)
    if rating:
        query = query.where(Review.rating == rating)
    if search:
        query = query.where(Review.text.icontains(search.strip(), autoescape=True))
    rows = list(db.scalars(query.order_by(Review.id)))
    return {"total": len(rows), "items": [analysis_service.review_out(r) for r in rows[offset:offset + limit]]}


@router.post("", response_model=ProductSummary, status_code=status.HTTP_201_CREATED,
             responses=NOT_FOUND | {409: {"model": ErrorResponse, "description": "Duplicate review ID"}},
             summary="Add reviews to a product and re-run its analysis")
def add_reviews(product_id: int, body: ReviewsCreate, db: Session = Depends(get_db)):
    product = product_service.get_product(db, product_id)
    product_service.add_reviews(db, product, [r.model_dump() for r in body.reviews])
    analysis_service.run_analysis(db, product)
    db.commit()
    return product_service.summary_out(product)


@router.delete("/{review_id}", status_code=status.HTTP_204_NO_CONTENT, responses=NOT_FOUND,
               summary="Delete one review and re-run the analysis")
def delete_review(product_id: int, review_id: str, db: Session = Depends(get_db)):
    product = product_service.get_product(db, product_id)
    review = next((r for r in product.reviews if r.external_id == review_id), None)
    if review is None:
        raise NotFound(f"Review {review_id} doesn’t exist for this product.")
    product.reviews.remove(review)
    db.flush()
    if product.reviews:
        analysis_service.run_analysis(db, product)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
