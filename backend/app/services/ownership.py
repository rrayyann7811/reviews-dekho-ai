"""Every child review, analysis and AI record inherits the product's owner and expiry."""
from datetime import datetime, timedelta, timezone

from sqlalchemy import and_
from sqlalchemy import select

from ..models import Product, ProcessingJob

RETENTION_DAYS = 7


def principal(db):
    identity = db.info.get("principal")
    if identity is None:
        raise RuntimeError("Data access requires an authenticated request context")
    return identity


def product_scope(db):
    identity = principal(db)
    scope = Product.owner_id == identity.owner_id
    if not identity.local:
        # Expired/null-expiry account data is invisible even if physical cleanup has not run.
        now = datetime.now(timezone.utc)
        scope = and_(scope, Product.expires_at > now,
                     Product.created_at > now - timedelta(days=RETENTION_DAYS))
    return scope


def new_product_identity(db):
    identity = principal(db)
    created = datetime.now(timezone.utc)
    return {"owner_id": identity.owner_id, "created_at": created,
            "expires_at": None if identity.local else created + timedelta(days=RETENTION_DAYS)}


def lock_owned_product(db, statement):
    """Recheck owner/expiry and lock the root in the same PostgreSQL write transaction."""
    if db.info.get("write_request") and db.get_bind().dialect.name == "postgresql":
        return statement.with_for_update(of=Product)
    return statement


def job_query(db):
    """Future job APIs/workers must use the same product ownership/expiry boundary."""
    return lock_owned_product(db, select(ProcessingJob).join(Product).where(product_scope(db)))
