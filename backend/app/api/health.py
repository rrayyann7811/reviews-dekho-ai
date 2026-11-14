from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.orm import Session

from ..database import get_db
from ..schemas import Health

router = APIRouter(tags=["Health"])


@router.get("/health", response_model=Health, summary="Check that the API and database are working")
def health(db: Session = Depends(get_db)):
    db.execute(text("SELECT 1"))
    return {"status": "ok", "database": "ok", "version": "0.4.0"}
