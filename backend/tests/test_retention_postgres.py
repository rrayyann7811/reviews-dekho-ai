"""Live retention integration only when the guarded disposable PostgreSQL target is configured."""
from concurrent.futures import ThreadPoolExecutor

import pytest
from sqlalchemy import select, event
from sqlalchemy.orm import Session

from app.models import Product
from app.services import retention
from .test_postgres_integration import pg, upgrade
from .test_retention import seed, numbers, NOW


def test_postgres_retention_dry_run_owner_scope_cascades_and_repeated_cleanup(pg):
    upgrade(pg)
    seed(pg); seed(pg, owner='bob')
    local = seed(pg, owner='local')
    dry = retention.run_cleanup(pg, dry_run=True, batch_size=1, owner_id='alice', now=NOW)
    assert dry['matched'] == dict.fromkeys(retention.TABLES, 1)
    assert dry['deleted'] == dict.fromkeys(retention.TABLES, 0)
    report = retention.run_cleanup(pg, owner_id='alice', now=NOW)
    assert report['deleted'] == dry['matched']
    assert retention.run_cleanup(pg, owner_id='alice', now=NOW)['deleted']['products'] == 0
    assert retention.run_cleanup(pg, now=NOW)['deleted']['products'] == 1
    with Session(pg) as db:
        assert list(db.scalars(select(Product.id))) == [local]


def test_postgres_cleanup_skips_locked_roots_and_reports_pending_work(pg):
    upgrade(pg)
    locked, other = seed(pg), seed(pg)
    with Session(pg) as writer:
        writer.scalar(select(Product).where(Product.id == locked).with_for_update())
        report = retention.run_cleanup(pg, now=NOW)
        assert report['status'] == 'partial' and report['remaining']
        assert report['deleted']['products'] == 1
        # Dry-run reads do not wait for the write lock or delete its row.
        assert retention.run_cleanup(pg, dry_run=True, now=NOW)['matched']['products'] == 1
        writer.rollback()
    assert retention.run_cleanup(pg, now=NOW)['deleted']['products'] == 1
    assert numbers(pg) == dict.fromkeys(retention.TABLES, 0)


def test_postgres_parallel_cleaners_never_double_count_cascades(pg):
    upgrade(pg)
    for _ in range(6): seed(pg)
    with ThreadPoolExecutor(max_workers=2) as pool:
        reports = list(pool.map(lambda _: retention.run_cleanup(pg, batch_size=1, now=NOW), range(2)))
    assert sum(r['deleted']['products'] for r in reports) == 6
    assert sum(r['deleted']['reviews'] for r in reports) == 6
    assert numbers(pg) == dict.fromkeys(retention.TABLES, 0)


def test_postgres_interrupted_delete_rolls_back_every_cascade(pg):
    upgrade(pg); seed(pg)
    def fail(conn, cursor, statement, parameters, context, executemany):
        if statement.startswith('DELETE FROM products'): raise KeyboardInterrupt
    event.listen(pg, 'after_cursor_execute', fail)
    try:
        with pytest.raises(retention.RetentionFailure) as failed:
            retention.run_cleanup(pg, now=NOW)
    finally:
        event.remove(pg, 'after_cursor_execute', fail)
    assert failed.value.interrupted and failed.value.report['committed_batches'] == 0
    assert numbers(pg) == dict.fromkeys(retention.TABLES, 1)
    assert retention.run_cleanup(pg, now=NOW)['deleted']['products'] == 1


def test_postgres_dry_run_enforces_database_read_only(pg, monkeypatch):
    upgrade(pg); seed(pg)
    def writes(conn, ids): conn.exec_driver_sql("UPDATE products SET name='must not happen'")
    with monkeypatch.context() as patch:
        patch.setattr(retention, '_counts', writes)
        with pytest.raises(retention.RetentionFailure):
            retention.run_cleanup(pg, dry_run=True, now=NOW)
    assert numbers(pg)['products'] == 1
    assert retention.run_cleanup(pg, now=NOW)['deleted']['products'] == 1
