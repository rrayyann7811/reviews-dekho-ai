"""Product-root ordered durable jobs. No uploaded payloads or private error strings are stored."""
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import uuid

from sqlalchemy import select, func, or_, text

from .. import config
from ..auth import Principal, LOCAL_OWNER
from ..errors import AppError, NotFound
from ..models import Product, Review, AnalysisResult, ProcessingJob
from .ownership import principal, product_scope, RETENTION_DAYS
from .products import get_product
from .analysis import run_analysis

ACTIVE = ('queued', 'running')
QUEUE_LOCK = 782113
WORKER_LOCK = 782114


def utcnow():
    return datetime.now(timezone.utc)


def reserve_sqlite(db):
    if db.get_bind().dialect.name == 'sqlite' and not db.in_transaction():
        db.connection(execution_options={'sqlite_begin_mode': 'IMMEDIATE'})


def visible_product(now):
    return or_(Product.owner_id == LOCAL_OWNER,
               (Product.expires_at > now) & (Product.created_at > now - timedelta(days=RETENTION_DAYS)))


def create(db, product_id, request_key, *, now=None):
    reserve_sqlite(db)
    db.info["write_request"] = True
    product = get_product(db, product_id)
    if not _unexpired(product, now or utcnow()):
        raise NotFound("Processing product does not exist or has expired.")
    if db.get_bind().dialect.name == 'postgresql':
        # Serialize global/owner storage counts across queue creation transactions.
        db.execute(text('SELECT pg_advisory_xact_lock(:key)'), {'key': QUEUE_LOCK})
    existing = db.scalar(select(ProcessingJob).where(ProcessingJob.product_id == product_id,
                                                    ProcessingJob.request_key == request_key))
    if existing is not None:
        return existing
    count = lambda predicate: db.scalar(select(func.count()).select_from(ProcessingJob).where(predicate)) or 0
    total = count(True)
    owner_count = db.scalar(select(func.count()).select_from(ProcessingJob).join(Product).where(
        Product.owner_id == principal(db).owner_id)) or 0
    product_count = count(ProcessingJob.product_id == product_id)
    if total >= config.JOB_MAX_STORED or owner_count >= config.JOB_MAX_PER_OWNER or product_count >= config.JOB_MAX_PER_PRODUCT:
        raise AppError('The stored-job limit has been reached. Delete unneeded products or run retention cleanup.', 413)
    if count((ProcessingJob.product_id == product_id) & ProcessingJob.status.in_(ACTIVE)):
        raise AppError('This product already has an active processing job.', 409)
    runs = db.scalar(select(func.count()).select_from(AnalysisResult).where(AnalysisResult.product_id == product_id)) or 0
    rows = db.scalar(select(func.count()).select_from(Review).where(Review.product_id == product_id)) or 0
    if runs >= config.MAX_ANALYSIS_RUNS or rows > config.MAX_ROWS:
        raise AppError('This product exceeds the analysis limits.', 413)
    if rows == 0:
        raise AppError('This product has no stored reviews to analyse.', 422)
    now = now or utcnow()
    job = ProcessingJob(product_id=product.id, status='queued', kind='analysis', request_key=request_key,
                        attempts=0, max_attempts=config.JOB_MAX_ATTEMPTS, created_at=now, available_at=now)
    db.add(job)
    db.flush()
    return job


def get(db, job_id, *, write=False):
    if write:
        reserve_sqlite(db)
        db.info["write_request"] = True
    # First read is owner/expiry scoped. Never lock a foreign child before the product root.
    product_id = db.scalar(select(ProcessingJob.product_id).join(Product).where(
        ProcessingJob.id == job_id, product_scope(db)))
    if product_id is None:
        raise NotFound('Processing job does not exist or has expired.')
    get_product(db, product_id)
    query = select(ProcessingJob).where(ProcessingJob.id == job_id)
    if write and db.get_bind().dialect.name == 'postgresql':
        query = query.with_for_update()
    job = db.scalar(query.execution_options(populate_existing=True))
    if job is None:
        raise NotFound('Processing job does not exist or has expired.')
    return job


def cancel(db, job_id, *, now=None):
    job = get(db, job_id, write=True)
    if job.status == 'cancelled':
        return job
    if job.status != 'queued':
        raise AppError('Only queued jobs can be cancelled.', 409)
    job.status, job.finished_at, job.claim_token = 'cancelled', now or utcnow(), None
    return job


def out(job):
    analysis_id = job.result_analysis_id if job.status == 'succeeded' else None
    if type(analysis_id) is not int:
        analysis_id = None
    return {'id': job.id, 'productId': job.product_id, 'kind': job.kind,
            'status': job.status, 'attempts': job.attempts, 'maxAttempts': job.max_attempts,
            'createdAt': job.created_at, 'availableAt': job.available_at, 'claimedAt': job.claimed_at,
            'finishedAt': job.finished_at, 'error': job.error,
            'analysisId': analysis_id, 'resultUrl': f'/api/history/{analysis_id}' if analysis_id else None}


@dataclass(frozen=True)
class Claim:
    job_id: int
    product_id: int
    token: str


def claim(db, *, now=None):
    """Claim at most one eligible root; expired running leases are fenced with a new token."""
    reserve_sqlite(db)
    now = now or utcnow()
    ready = or_((ProcessingJob.status == 'queued') & (ProcessingJob.available_at <= now),
                (ProcessingJob.status == 'running') & (ProcessingJob.lease_until <= now))
    query = select(ProcessingJob).join(Product).where(ready, visible_product(now),
        ProcessingJob.kind == 'analysis', ProcessingJob.request_key.is_not(None)).order_by(ProcessingJob.id).limit(1)
    if db.get_bind().dialect.name == 'postgresql':
        query = query.with_for_update(of=Product, skip_locked=True)
    job = db.scalar(query)
    if job is None:
        return None
    if db.get_bind().dialect.name == 'postgresql':
        job = db.scalar(select(ProcessingJob).where(ProcessingJob.id == job.id).with_for_update()
                        .execution_options(populate_existing=True))
        if not ((job.status == "queued" and job.available_at is not None and job.available_at <= now) or
                (job.status == "running" and job.lease_until is not None and job.lease_until <= now)):
            return None
    if job.attempts >= job.max_attempts:
        job.status, job.finished_at = 'failed', now
        job.error, job.claim_token, job.lease_until = 'Processing attempts were exhausted.', None, None
        return None
    job.status, job.attempts = 'running', job.attempts + 1
    job.claimed_at, job.lease_until = now, now + timedelta(seconds=config.JOB_LEASE_SECONDS)
    job.claim_token = uuid.uuid4().hex
    job.error = None
    return Claim(job.id, job.product_id, job.claim_token)


def _lock_claim(db, claimed):
    reserve_sqlite(db)
    root = select(Product).where(Product.id == claimed.product_id)
    if db.get_bind().dialect.name == 'postgresql':
        root = root.with_for_update()
    product = db.scalar(root)
    if product is None:
        return None, None
    query = select(ProcessingJob).where(ProcessingJob.id == claimed.job_id)
    if db.get_bind().dialect.name == 'postgresql':
        query = query.with_for_update()
    job = db.scalar(query)
    if job is None or job.status != 'running' or job.claim_token != claimed.token:
        return None, None
    return product, job


def _unexpired(product, now):
    return (product.owner_id == LOCAL_OWNER or
            (product.expires_at is not None and product.expires_at > now and
             product.created_at > now - timedelta(days=RETENTION_DAYS)))


def execute(db, claimed, *, clock=utcnow, analyse=None):
    """Caller commits analysis and terminal job together; any exception rolls both back."""
    product, job = _lock_claim(db, claimed)
    if job is None:
        return False
    if not _unexpired(product, clock()):
        job.status, job.finished_at, job.claim_token, job.lease_until = 'cancelled', clock(), None, None
        job.error = 'The product retention deadline has passed.'
        return False
    db.info.update(principal=Principal(product.owner_id, local=product.owner_id == LOCAL_OWNER), write_request=True)
    analysis = (analyse or run_analysis)(db, product)
    if not _unexpired(product, clock()):
        raise AppError('The product retention deadline has passed.', 410)
    job.result = {'analysis_id': analysis.id}
    job.result_analysis_id = analysis.id
    job.status, job.finished_at, job.claim_token, job.lease_until = 'succeeded', clock(), None, None
    job.error = None
    return True


def failure(db, claimed, *, retryable, now=None):
    product, job = _lock_claim(db, claimed)
    if job is None:
        return
    now = now or utcnow()
    if not _unexpired(product, now):
        job.status, job.error = 'cancelled', 'The product retention deadline has passed.'
    elif retryable and job.attempts < job.max_attempts:
        job.status, job.error = 'queued', 'Processing was interrupted. A bounded retry is scheduled.'
        job.available_at = now + timedelta(seconds=config.JOB_RETRY_SECONDS * job.attempts)
    else:
        job.status, job.error = 'failed', 'Analysis could not be completed. Check stored review and history limits.'
    job.finished_at = None if job.status == 'queued' else now
    job.claim_token, job.lease_until = None, None
