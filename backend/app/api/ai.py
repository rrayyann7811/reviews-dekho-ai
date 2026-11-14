from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from ..database import get_db
from ..schemas import ErrorResponse
from ..services import ai_summary
from ..services import products as product_service
from ..services.review_query import pick_run

router = APIRouter(tags=["AI overview (optional)"])
ERRORS = {404: {"model": ErrorResponse}, 409: {"model": ErrorResponse, "description": "Turned off, or no evidence"},
          503: {"model": ErrorResponse, "description": "Ollama or the model isn’t available"},
          504: {"model": ErrorResponse, "description": "The model took too long"}}


@router.get("/ai/status", summary="Whether optional AI overviews are on and the local model is available")
def status():
    return ai_summary.availability()


@router.get("/products/{product_id}/ai-summary", responses=ERRORS,
            summary="The latest AI overview attempt for an analysis run (null if there is none)")
def latest(product_id: int, analysis_id: int | None = Query(None), db: Session = Depends(get_db)):
    run = pick_run(product_service.get_product(db, product_id), analysis_id, require_reviews=False)
    return ai_summary.out(run.ai_summaries[0] if run.ai_summaries else None)


@router.post("/products/{product_id}/ai-summary", responses=ERRORS,
             summary="Write an AI overview of an analysis run with the local model, then check it")
def create(product_id: int, analysis_id: int | None = Query(None), db: Session = Depends(get_db)):
    product = product_service.get_product(db, product_id)
    run = pick_run(product, analysis_id, require_reviews=False)
    return ai_summary.out(ai_summary.generate(db, run, product.name))
