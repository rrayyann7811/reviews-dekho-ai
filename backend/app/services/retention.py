"""Explicit physical cleanup. Expiry is also enforced on every account-data read/write."""
from datetime import datetime, timezone

from sqlalchemy import delete

from ..models import Product


def purge_expired_products(db, *, owner_id=None, now=None):
    query = delete(Product).where(Product.expires_at <= (now or datetime.now(timezone.utc)))
    if owner_id is not None:
        query = query.where(Product.owner_id == owner_id)
    # DB foreign-key cascades remove original reviews, snapshots and optional AI records together.
    # The caller owns the transaction. Local records have no expiry and are never selected.
    return db.execute(query.execution_options(synchronize_session=False)).rowcount
