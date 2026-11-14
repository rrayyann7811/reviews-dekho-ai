from fastapi import APIRouter, Depends, Query, Response, status
from sqlalchemy.orm import Session

from ..database import get_db
from ..errors import NotFound
from ..schemas import ErrorResponse, ProductSummary, ReviewOut, ReviewPage, ReviewsCreate
from ..services import analysis as analysis_service
from ..services import products as product_service
from ..services import review_query
from ..services.review_query import RATING_FILTERS, SENTIMENT_FILTERS, SORTS

router = APIRouter(prefix="/products/{product_id}/reviews", tags=["Reviews"])
NOT_FOUND = {404: {"model": ErrorResponse, "description": "Product or review not found"}}


NOT_ANALYSED = {409: {"model": ErrorResponse, "description": "Not analysed yet, or a run without per-review results"}}


def _pattern(values):
    return "^(" + "|".join(values) + ")$"


@router.get("", response_model=ReviewPage, responses=NOT_FOUND | NOT_ANALYSED,
            summary="Search, filter, sort and page the reviews of an analysis run")
def list_reviews(
    product_id: int,
    analysis_id: int | None = Query(None, description="A specific run (default: the latest)"),
    sentiment: str = Query("all", pattern=_pattern(SENTIMENT_FILTERS)),
    rating: str = Query("all", pattern=_pattern(RATING_FILTERS)),
    search: str | None = Query(None, max_length=200),
    sort: str = Query("newest", pattern=_pattern(SORTS)),
    offset: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=500),
    db: Session = Depends(get_db),
):
    """Every value comes from the stored results of one run, so pages always agree with the dashboard."""
    run = review_query.pick_run(product_service.get_product(db, product_id), analysis_id)
    return review_query.query_reviews(run, sentiment=sentiment, rating=rating, search=search or "", sort=sort,
                                      offset=offset, limit=limit)


@router.get("/{review_id}", response_model=ReviewOut, responses=NOT_FOUND | NOT_ANALYSED,
            summary="One review as analysed in a run")
def get_review(product_id: int, review_id: str, analysis_id: int | None = Query(None),
               db: Session = Depends(get_db)):
    run = review_query.pick_run(product_service.get_product(db, product_id), analysis_id)
    return review_query.find_review(run, review_id)


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
