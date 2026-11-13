from fastapi import APIRouter, Depends, Query, Response, status
from sqlalchemy.orm import Session

from ..database import get_db
from ..errors import NotFound
from ..models import AnalysisResult
from ..schemas import ErrorResponse, HistoryDetail, HistoryEntry
from ..services import products as product_service

router = APIRouter(prefix="/history", tags=["History"])
NOT_FOUND = {404: {"model": ErrorResponse, "description": "Analysis not found"}}


@router.get("", response_model=list[HistoryEntry], summary="Every analysis run, newest first")
def list_history(
    product_id: int | None = Query(None, description="Only runs for this product"),
    limit: int = Query(100, ge=1, le=500),
    db: Session = Depends(get_db),
):
    query = product_service.history_query()
    if product_id is not None:
        query = query.where(AnalysisResult.product_id == product_id)
    return [product_service.history_out(a, name, source) for a, name, source in db.execute(query.limit(limit))]


@router.get("/{analysis_id}", response_model=HistoryDetail, responses=NOT_FOUND,
            summary="One past analysis run with its stored results")
def get_history_entry(analysis_id: int, db: Session = Depends(get_db)):
    row = db.execute(product_service.history_query().where(AnalysisResult.id == analysis_id)).first()
    if row is None:
        raise NotFound(f"Analysis {analysis_id} doesn’t exist.")
    return product_service.history_out(*row, detail=True)


@router.delete("/{analysis_id}", status_code=status.HTTP_204_NO_CONTENT, responses=NOT_FOUND,
               summary="Delete one past analysis run (the product and reviews are kept)")
def delete_history_entry(analysis_id: int, db: Session = Depends(get_db)):
    analysis = db.get(AnalysisResult, analysis_id)
    if analysis is None:
        raise NotFound(f"Analysis {analysis_id} doesn’t exist.")
    db.delete(analysis)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
