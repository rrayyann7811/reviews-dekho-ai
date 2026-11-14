from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from ..database import get_db
from ..schemas import Comparison, ErrorResponse
from ..services import comparison
from ..services import products as product_service
from ..services.review_query import pick_run

router = APIRouter(tags=["Comparison"])
ERRORS = {404: {"model": ErrorResponse, "description": "Unknown product, or a run that belongs to another product"},
          409: {"model": ErrorResponse, "description": "A product hasn’t been analysed yet"}}


@router.get("/compare", response_model=Comparison, responses=ERRORS,
            summary="Two stored analysis runs side by side (two products, or two runs of one product)")
def compare(product_a: int = Query(..., description="Product on side A"),
            product_b: int = Query(..., description="Product on side B (may be the same product)"),
            analysis_a: int | None = Query(None, description="Run of product A; default: its latest run"),
            analysis_b: int | None = Query(None, description="Run of product B; default: its latest run"),
            db: Session = Depends(get_db)):
    a = product_service.get_product(db, product_a)
    b = product_service.get_product(db, product_b)
    run_a = pick_run(a, analysis_a, require_reviews=False)
    run_b = pick_run(b, analysis_b, require_reviews=False)
    return comparison.compare_runs(a, run_a, b, run_b)
