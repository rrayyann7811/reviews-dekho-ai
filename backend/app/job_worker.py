"""Explicit bounded worker; never imported to start a thread from the web application."""
import logging
import os
from pathlib import Path
import signal
from concurrent.futures import ThreadPoolExecutor
from threading import Event

from sqlalchemy import text, inspect
from sqlalchemy.orm import Session

from . import config, database
from .errors import AppError
from .services import jobs
from .services.retention import check_retention_schema

log = logging.getLogger('reviews_dekho')


def run_once(engine, *, slot=0, clock=jobs.utcnow, analyse=None):
    """One connection per worker thread, no prefetched jobs or in-memory work queue."""
    with engine.connect() as connection:
        postgres = engine.dialect.name == 'postgresql'
        locked = False
        try:
            if postgres:
                try:
                    locked = connection.execute(text('SELECT pg_try_advisory_lock(:namespace, :slot)'),
                        {'namespace': jobs.WORKER_LOCK, 'slot': slot}).scalar()
                    connection.commit()
                except BaseException:
                    # An acquisition with a lost acknowledgment may already hold a session lock.
                    connection.invalidate()
                    raise
                if not locked:
                    return False
            with Session(bind=connection, expire_on_commit=False, autoflush=False) as db:
                claimed = jobs.claim(db, now=clock())
                db.commit()
            if claimed is None:
                return False
            try:
                with Session(bind=connection, expire_on_commit=False, autoflush=False) as db:
                    jobs.execute(db, claimed, clock=clock, analyse=analyse)
                    db.commit()
            except Exception as error:
                # Session exit rolled back any snapshot before a separate failure-state transaction.
                # Expected validation/quota failures do not retry; transient/unexpected failures are bounded.
                with Session(bind=connection, expire_on_commit=False) as db:
                    jobs.failure(db, claimed, retryable=not isinstance(error, AppError) or error.status_code >= 500, now=clock())
                    db.commit()
                log.warning('Background analysis attempt failed')
            return True
        finally:
            if postgres and locked:
                try:
                    connection.rollback()
                    connection.execute(text('SELECT pg_advisory_unlock(:namespace, :slot)'),
                        {'namespace': jobs.WORKER_LOCK, 'slot': slot})
                    connection.commit()
                except BaseException:
                    # A connection with uncertain session-lock state must never return to the API pool.
                    connection.invalidate()
                    raise


def serve(engine, stop, *, concurrency=None):
    concurrency = config.JOB_CONCURRENCY if concurrency is None else concurrency
    if not 1 <= concurrency <= 4:
        raise ValueError('Worker concurrency must be between 1 and 4')
    # SQLite reserves one writer for the complete execution transaction, independent of thread count.
    if engine.dialect.name == 'sqlite':
        concurrency = 1
    def loop(slot):
        while not stop.is_set():
            try:
                run_once(engine, slot=slot)
            except Exception:
                log.error('Background worker database operation unavailable')
            # Always wait: limits database polling and gives shutdown a prompt interruptible boundary.
            stop.wait(config.JOB_POLL_SECONDS)
    with ThreadPoolExecutor(max_workers=concurrency, thread_name_prefix='analysis-job') as pool:
        futures = [pool.submit(loop, slot) for slot in range(concurrency)]
        for future in futures:
            future.result()


def check_schema(engine):
    if (engine.dialect.name == 'sqlite' and engine.url.database not in (None, '', ':memory:')
            and not Path(engine.url.database).is_file()):
        raise RuntimeError('Worker requires an existing explicitly migrated SQLite database')
    check_retention_schema(engine)
    # Retention's SQLite gate verifies version/cascades; also require the new operational columns/FK.
    from .models import ProcessingJob
    with engine.connect() as connection:
        reflection = inspect(connection)
        columns = {c['name'] for c in reflection.get_columns('processing_jobs')}
        if not set(ProcessingJob.__table__.columns.keys()).issubset(columns):
            raise RuntimeError('Worker schema is not current')
        if not any(f['constrained_columns'] == ['result_analysis_id']
                   and f['referred_table'] == 'analysis_results'
                   and (f.get('options', {}).get('ondelete') or '').upper() == 'SET NULL'
                   for f in reflection.get_foreign_keys('processing_jobs')):
            raise RuntimeError('Worker result-reference constraint is not current')


def main():
    # Read-only schema gate; never initialize or migrate an operator's existing application data.
    if not os.getenv('DATABASE_URL'):
        raise ValueError('Set an explicit DATABASE_URL before starting the worker')
    check_schema(database.engine)
    if (database.engine.dialect.name == 'postgresql' and config.DB_POOL_MODE == 'queue'
            and config.JOB_CONCURRENCY > config.DB_POOL_SIZE + config.DB_MAX_OVERFLOW):
        raise ValueError('Worker concurrency exceeds the configured connection pool')
    stop = Event()
    for name in (signal.SIGINT, signal.SIGTERM):
        signal.signal(name, lambda *_: stop.set())
    serve(database.engine, stop)


if __name__ == '__main__':
    try:
        main()
    except Exception:
        log.error('Background worker startup or shutdown failed')
        raise SystemExit(1) from None
