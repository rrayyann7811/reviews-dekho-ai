"""Transactional, owner-scoped replay of authenticated file imports."""

import re
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as postgres_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from ..errors import AppError
from ..models import ImportReceipt, Product
from .ownership import RETENTION_DAYS, principal, product_scope

KEY_PATTERN = re.compile(r"[A-Za-z0-9_-]{16,64}")


def validate_key(key):
    if not KEY_PATTERN.fullmatch(key):
        raise AppError("The import key must contain 16–64 letters, digits, dashes or underscores.", 422)


def receipt_query(db, key):
    return select(ImportReceipt).where(
        ImportReceipt.owner_id == principal(db).owner_id, ImportReceipt.request_key == key,
    )


def claim(db, key, fingerprint):
    """The unique index arbitrates across instances; a rollback releases the claim."""
    now = datetime.now(timezone.utc)
    sqlite = db.get_bind().dialect.name == "sqlite"
    if sqlite:
        db.connection(execution_options={"sqlite_begin_mode": "IMMEDIATE"})
    insert = sqlite_insert if sqlite else postgres_insert
    statement = insert(ImportReceipt).values(
        owner_id=principal(db).owner_id, request_key=key, fingerprint=fingerprint,
        expires_at=now + timedelta(days=RETENTION_DAYS),
    )
    statement = statement.on_conflict_do_update(
        index_elements=[ImportReceipt.owner_id, ImportReceipt.request_key],
        set_={"fingerprint": statement.excluded.fingerprint, "expires_at": statement.excluded.expires_at,
              "product_id": None, "result": None},
        where=ImportReceipt.expires_at <= now,
    ).returning(ImportReceipt)
    receipt = db.scalars(statement).first()
    if receipt is not None:
        return receipt, None

    receipt = db.scalars(receipt_query(db, key)).one_or_none()
    if receipt is None:
        raise AppError("Import status changed. Check status before retrying.", 503)
    if receipt.fingerprint != fingerprint:
        raise AppError("This import key was already used for a different file or options.", 409)
    return None, completed_result(db, receipt)


def completed_result(db, receipt):
    if receipt.product_id is None or db.scalar(
        select(Product.id).where(Product.id == receipt.product_id, product_scope(db))
    ) is None:
        raise AppError("This import is no longer available. Start a new import if needed.", 410)
    return receipt.result


def status_result(db, key):
    validate_key(key)
    receipt = db.scalars(receipt_query(db, key).where(
        ImportReceipt.expires_at > datetime.now(timezone.utc)
    )).one_or_none()
    if receipt is None:
        raise AppError("No completed import is recorded for this key yet.", 404)
    return completed_result(db, receipt)
