"""Opt-in background analysis; synchronous product/ingestion APIs retain their contracts."""
from fastapi import APIRouter, Depends, Query
from pydantic import Field, ConfigDict
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import ProcessingJob
from ..schemas import ApiModel
from ..services import jobs
from ..services.products import get_product

router = APIRouter(tags=['Processing jobs'])


class JobCreate(ApiModel):
    model_config = ConfigDict(extra="forbid")
    request_key: str = Field(min_length=8, max_length=64, pattern=r'^[A-Za-z0-9_-]+$')
    # No arbitrary task names, user IDs, file paths or private payloads can enter the queue.


@router.post('/products/{product_id}/jobs', status_code=202)
def create_job(product_id: int, body: JobCreate, db: Session = Depends(get_db)):
    job = jobs.create(db, product_id, body.request_key)
    db.commit()
    return jobs.out(job)


@router.get('/products/{product_id}/jobs')
def list_jobs(product_id: int, limit: int = Query(20, ge=1, le=50),
              before_id: int | None = Query(None, ge=1), db: Session = Depends(get_db)):
    get_product(db, product_id)
    query = select(ProcessingJob).where(ProcessingJob.product_id == product_id).order_by(ProcessingJob.id.desc()).limit(limit)
    if before_id is not None:
        query = query.where(ProcessingJob.id < before_id)
    return [jobs.out(job) for job in db.scalars(query)]


@router.get('/jobs/{job_id}')
def job_status(job_id: int, db: Session = Depends(get_db)):
    return jobs.out(jobs.get(db, job_id))


@router.post('/jobs/{job_id}/cancel')
def cancel_job(job_id: int, db: Session = Depends(get_db)):
    job = jobs.cancel(db, job_id)
    db.commit()
    return jobs.out(job)
