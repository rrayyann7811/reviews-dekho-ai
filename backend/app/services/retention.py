"""Bounded, content-free physical retention. No identity-provider/account operations."""
from datetime import datetime, timezone, timedelta
from time import monotonic
import uuid
import traceback

from sqlalchemy import delete, select, func, or_, inspect

from ..models import Product, Review, AnalysisResult, AiSummary, ProcessingJob, ImportReceipt
from ..auth import LOCAL_OWNER
from .ownership import RETENTION_DAYS

TABLES = ("products", "reviews", "analyses", "ai_summaries", "jobs")


def expired_products(cutoff, owner_id=None):
    # A stored earlier expiry is honored; a later/missing expiry never extends the creation-time cap.
    query = (Product.owner_id != LOCAL_OWNER) & or_(Product.expires_at <= cutoff,
        Product.created_at <= cutoff - timedelta(days=RETENTION_DAYS))
    if owner_id is not None:
        query &= Product.owner_id == owner_id
    return query


def purge_expired_products(db, *, owner_id=None, now=None, batch_size=100):
    """One bounded helper batch. The caller owns the transaction (including the collection API)."""
    if not 1 <= batch_size <= 1000:
        raise ValueError("batch_size must be between 1 and 1000")
    predicate = expired_products(now or datetime.now(timezone.utc), owner_id)
    ids = select(Product.id).where(predicate).order_by(Product.expires_at, Product.id).limit(batch_size)
    if db.get_bind().dialect.name == "postgresql":
        ids = ids.with_for_update(skip_locked=True)
    query = delete(Product).where(Product.id.in_(ids), predicate)
    return db.execute(query.execution_options(synchronize_session=False)).rowcount


class RetentionSchemaError(Exception):
    pass


class RetentionFailure(Exception):
    def __init__(self, report, *, interrupted=False):
        super().__init__("Retention interrupted" if interrupted else "Retention failed")
        self.report, self.interrupted = report, interrupted


def _release_database_frames(error):
    """Sanitized reports must not retain cursor/connection locals through an exception chain."""
    pending, seen = [error], set()
    while pending:
        current = pending.pop()
        if current is None or id(current) in seen:
            continue
        seen.add(id(current))
        pending.extend([current.__cause__, current.__context__])
        if current.__traceback__ is not None:
            traceback.clear_frames(current.__traceback__)
        current.__traceback__ = None
        current.__cause__ = current.__context__ = None


def check_retention_schema(engine):
    """Read-only preflight: never create a SQLite file/schema or migrate the operator's target."""
    from ..database import Base
    if engine.dialect.name == "postgresql":
        from ..postgres_migrations import check_schema
        try:
            check_schema(engine)
        except RuntimeError as error:
            raise RetentionSchemaError("Schema is not current") from error
    with engine.connect() as connection:
        reflection = inspect(connection)
        if not set(Base.metadata.tables).issubset(reflection.get_table_names()):
            raise RetentionSchemaError("Missing application tables")
        if engine.dialect.name == "sqlite":
            from ..migrations import LATEST_VERSION
            if (connection.exec_driver_sql("PRAGMA user_version").scalar() != LATEST_VERSION
                    or connection.exec_driver_sql("PRAGMA foreign_keys").scalar() != 1):
                raise RetentionSchemaError("SQLite schema/foreign keys are not current")
        elif engine.dialect.name != "postgresql":
            raise RetentionSchemaError("Unsupported database")
        for child, parent, column in [("reviews", "products", "product_id"),
                ("analysis_results", "products", "product_id"), ("processing_jobs", "products", "product_id"),
                ("ai_summaries", "analysis_results", "analysis_id")]:
            if not any(f["referred_table"] == parent and f["constrained_columns"] == [column]
                       and (f.get("options", {}).get("ondelete") or "").upper() == "CASCADE"
                       for f in reflection.get_foreign_keys(child)):
                raise RetentionSchemaError("Required deletion cascade is missing")
        if not any(f["referred_table"] == "products" and f["constrained_columns"] == ["product_id"]
                   and (f.get("options", {}).get("ondelete") or "").upper() == "SET NULL"
                   for f in reflection.get_foreign_keys("import_receipts")):
            raise RetentionSchemaError("Required import receipt tombstone constraint is missing")


def _counts(connection, ids):
    def count(model, condition):
        with connection.execute(select(func.count()).select_from(model).where(condition)) as result:
            return result.scalar_one()
    return {"products": len(ids), "reviews": count(Review, Review.product_id.in_(ids)),
        "analyses": count(AnalysisResult, AnalysisResult.product_id.in_(ids)),
        "ai_summaries": count(AiSummary, AiSummary.analysis_id.in_(
            select(AnalysisResult.id).where(AnalysisResult.product_id.in_(ids)))),
        "jobs": count(ProcessingJob, ProcessingJob.product_id.in_(ids))}


def cleanup_batch(engine, *, cutoff, batch_size, owner_id=None, dry_run=False, after_id=None):
    """One transaction. No private text/JSON columns are selected, and no IDs leave this layer."""
    with engine.connect() as raw:
        connection = raw.execution_options(sqlite_begin_mode="DEFERRED" if dry_run else "IMMEDIATE")
        try:
            with connection.begin():
                if dry_run:
                    if engine.dialect.name == "sqlite":
                        connection.exec_driver_sql("PRAGMA query_only=ON")
                    else:
                        connection.exec_driver_sql("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
                predicate = expired_products(cutoff, owner_id)
                # Dry-run pagination uses IDs, so every product is counted at most once across batches.
                query = select(Product.id).where(predicate).order_by(Product.id).limit(batch_size)
                if after_id is not None:
                    query = query.where(Product.id > after_id)
                if not dry_run and engine.dialect.name == "postgresql":
                    query = query.with_for_update(skip_locked=True)
                with connection.execute(query) as result:
                    ids = list(result.scalars())
                if not ids:
                    return {key: 0 for key in TABLES}, after_id
                counts = _counts(connection, ids)
                if not dry_run:
                    # No RETURNING cursor: an interrupted SQLite fetch could otherwise retain a lock
                    # until the discarded cursor is finalized, even after transaction rollback.
                    with connection.execute(delete(Product).where(Product.id.in_(ids), predicate)) as result:
                        deleted = result.rowcount
                    if deleted != len(ids):
                        raise RuntimeError("Eligibility changed; roll back the batch")
            # Exiting the transaction commits before its counts become reportable.
            return counts, max(ids)
        finally:
            if dry_run and engine.dialect.name == "sqlite":
                # query_only is connection-local. Never return a read-only connection to an API pool.
                raw.invalidate()


def cleanup_receipts(engine, *, cutoff, owner_id, batch_size, max_batches, dry_run, report):
    predicate = ImportReceipt.expires_at <= cutoff
    if owner_id is not None:
        predicate &= ImportReceipt.owner_id == owner_id
    query = select(ImportReceipt.id).where(predicate).order_by(ImportReceipt.id)
    cursor = 0
    for _ in range(max_batches):
        with engine.connect() as raw, raw.execution_options(
            sqlite_begin_mode="DEFERRED" if dry_run else "IMMEDIATE"
        ).begin():
            connection = raw
            batch = query.where(ImportReceipt.id > cursor).limit(batch_size)
            if not dry_run and engine.dialect.name == "postgresql":
                batch = batch.with_for_update(skip_locked=True)
            ids = list(connection.scalars(batch))
            if not ids:
                break
            deleted = 0
            if not dry_run:
                with connection.execute(delete(ImportReceipt).where(ImportReceipt.id.in_(ids), predicate)) as result:
                    deleted = result.rowcount
        report["matched"] += len(ids)
        report["deleted"] += deleted
        if dry_run:
            cursor = ids[-1]
    with engine.connect() as connection:
        return connection.scalar(query.where(ImportReceipt.id > cursor).limit(1)) is not None


def run_cleanup(engine, *, batch_size=100, max_batches=10, dry_run=False, owner_id=None, now=None):
    if not 1 <= batch_size <= 1000 or not 1 <= max_batches <= 1000 or owner_id == LOCAL_OWNER:
        raise ValueError("Invalid retention limits/owner")
    cutoff = now or datetime.now(timezone.utc)
    if cutoff.tzinfo is None:
        raise ValueError("An aware UTC cutoff is required")
    cutoff = cutoff.astimezone(timezone.utc)
    started = monotonic()
    report = {"run_id": str(uuid.uuid4()), "status": "running", "dry_run": dry_run,
        "cutoff": cutoff.isoformat(), "batches": 0, "committed_batches": 0,
        "matched": {key: 0 for key in TABLES}, "deleted": {key: 0 for key in TABLES},
        "receipts": {"matched": 0, "deleted": 0}, "remaining": None, "error": None, "duration_ms": 0}
    cursor = None
    try:
        check_retention_schema(engine)
        for _ in range(max_batches):
            counts, last = cleanup_batch(engine, cutoff=cutoff, batch_size=batch_size,
                owner_id=owner_id, dry_run=dry_run, after_id=cursor if dry_run else None)
            if not counts["products"]:
                break
            report["batches"] += 1
            for key, value in counts.items():
                report["matched"][key] += value
                if not dry_run:
                    report["deleted"][key] += value
            if dry_run: cursor = last
            else: report["committed_batches"] += 1
        with engine.connect() as connection:
            query = select(Product.id).where(expired_products(cutoff, owner_id)).limit(1)
            if dry_run and cursor is not None:
                query = query.where(Product.id > cursor)
            with connection.execute(query) as result:
                report["remaining"] = result.scalar() is not None
        receipts_remaining = cleanup_receipts(engine, cutoff=cutoff, owner_id=owner_id,
            batch_size=batch_size, max_batches=max_batches, dry_run=dry_run, report=report["receipts"])
        report["remaining"] |= receipts_remaining
        report["status"] = "partial" if report["remaining"] else "complete"
        return report
    except RetentionSchemaError as error:
        _release_database_frames(error)
        report.update(status="configuration_error", error="schema_mismatch")
        raise RetentionFailure(report) from None
    except KeyboardInterrupt as error:
        _release_database_frames(error)
        report.update(status="interrupted", error="interrupted")
        raise RetentionFailure(report, interrupted=True) from None
    except Exception as error:
        _release_database_frames(error)
        report.update(status="failed", error="database_or_transaction_failure")
        raise RetentionFailure(report) from None
    finally:
        report["duration_ms"] = round((monotonic() - started) * 1000)
