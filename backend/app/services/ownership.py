"""Every child review, analysis and AI record inherits the product's owner and expiry."""
from datetime import datetime, timedelta, timezone

from sqlalchemy import and_

from ..models import Product

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
        scope = and_(scope, Product.expires_at > datetime.now(timezone.utc))
    return scope


def new_product_identity(db):
    identity = principal(db)
    return {"owner_id": identity.owner_id,
            "expires_at": None if identity.local else datetime.now(timezone.utc) + timedelta(days=RETENTION_DAYS)}
