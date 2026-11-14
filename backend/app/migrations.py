"""Database schema upgrades that keep existing data.

How it works
------------
SQLite has a built-in integer, `PRAGMA user_version`, stored inside the
database file. We use it as the schema version:

* New database      -> tables are created from models.py and the version is
                       set to the latest number. No migrations run.
* Older database    -> each pending migration runs in order, inside a
                       transaction, and bumps the version. Before the first
                       one runs, the database file is copied to
                       storage/backups/, so an upgrade can always be undone.
* Newer database    -> (made by a newer version of the app) startup stops
                       with a clear error instead of guessing.

Adding a schema change
----------------------
1. Change the model in models.py.
2. Append a function to MIGRATIONS below that makes the same change with SQL
   (ALTER TABLE ... ADD COLUMN, CREATE INDEX, data back-fill, ...). Never edit
   or reorder a migration that has already shipped.
3. Add a test in tests/test_migrations.py. The test checks that an upgraded
   database ends up with exactly the same tables and columns as a new one.

Why not Alembic? Alembic is the standard tool for larger projects and is the
natural next step if the app moves to PostgreSQL. For one SQLite file and a
handful of changes, this ~100-line runner is easier to read and has no extra
dependency.
"""
import json
import logging
import shutil
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import inspect, text
from sqlalchemy.engine import Connection, Engine

from .database import Base

log = logging.getLogger("reviews_dekho.migrations")


# ---------- Migrations (append only) ----------

def _v1_baseline(conn: Connection) -> None:
    """Phase 2 schema. Databases created before versioning already have it."""


def _v2_review_snapshots(conn: Connection) -> None:
    """Store per-review results on each analysis run instead of on the review rows.

    Before: reviews.sentiment/score/mixed/aspects held only the LATEST run, so
    older runs lost their review-level results. Now every run keeps its own
    copy. The latest run of each product is back-filled from the review rows,
    but only when they provably belong to that run (same number of reviews and
    the same sentiment counts). Phase 2 could leave them out of step (deleting
    the last reviews, or deleting the newest run), and a wrong snapshot is worse
    than none. Runs that can't be back-filled keep review_results = NULL: their
    stats stay visible and re-running the analysis rebuilds the details.
    """
    conn.exec_driver_sql("ALTER TABLE analysis_results ADD COLUMN review_results JSON")
    latest_runs = conn.exec_driver_sql(
        "SELECT id, product_id, total_reviews, stats FROM analysis_results "
        "WHERE id IN (SELECT MAX(id) FROM analysis_results GROUP BY product_id)").all()
    for analysis_id, product_id, total_reviews, stats in latest_runs:
        rows = conn.exec_driver_sql(
            "SELECT external_id, text, rating, review_date, title, reviewer, sentiment, score, mixed, aspects "
            "FROM reviews WHERE product_id = ? ORDER BY id", (product_id,)).all()
        counts = (json.loads(stats) if isinstance(stats, str) else stats or {}).get("sentimentCounts")
        row_counts = {label: sum(r.sentiment == label for r in rows) for label in ("positive", "neutral", "negative")}
        if (not rows or len(rows) != total_reviews or any(r.sentiment is None for r in rows)
                or (counts is not None and counts != row_counts)):
            continue  # the review rows don't match this run: leave it without a snapshot
        snapshot = [{
            "id": r.external_id, "text": r.text, "rating": r.rating, "date": r.review_date, "title": r.title,
            "reviewer": r.reviewer, "sentiment": r.sentiment, "score": r.score, "mixed": bool(r.mixed),
            "aspects": json.loads(r.aspects) if isinstance(r.aspects, str) else (r.aspects or []),
        } for r in rows]
        conn.exec_driver_sql("UPDATE analysis_results SET review_results = ? WHERE id = ?",
                             (json.dumps(snapshot), analysis_id))
    for column in ("sentiment", "score", "mixed", "aspects"):
        conn.exec_driver_sql(f"ALTER TABLE reviews DROP COLUMN {column}")


def _v3_collected_products(conn: Connection) -> None:
    """Remember where a collected product came from, so it can be refreshed instead of duplicated."""
    conn.exec_driver_sql("ALTER TABLE products ADD COLUMN source_site VARCHAR(40)")
    conn.exec_driver_sql("ALTER TABLE products ADD COLUMN external_product_id VARCHAR(100)")
    conn.exec_driver_sql("ALTER TABLE products ADD COLUMN source_region VARCHAR(10)")
    conn.exec_driver_sql("ALTER TABLE products ADD COLUMN collected_at DATETIME")
    conn.exec_driver_sql("CREATE UNIQUE INDEX uq_collected_product "
                         "ON products (source_site, external_product_id, source_region)")


VADER_BEFORE_PHASE_4 = {"id": "vader", "name": "VADER (rule-based)", "model": "vaderSentiment 3.3.2",
                        "pipelineVersion": 1, "fallbackReason": None, "domain": "product",
                        "recordedBy": "migration 4 (every run before Phase 4 used this pipeline)"}


def _v4_engine_and_domain(conn: Connection) -> None:
    """Record what was reviewed (product or app) and which sentiment engine produced each run.

    Every run made before Phase 4 used the same VADER pipeline with the physical-product feature list,
    so that is recorded for them. Snapshot contents are not touched.
    """
    conn.exec_driver_sql("ALTER TABLE products ADD COLUMN domain VARCHAR(20) NOT NULL DEFAULT 'product'")
    conn.exec_driver_sql("UPDATE products SET domain = 'app' WHERE source_site = 'apple_app_store'")
    conn.exec_driver_sql("ALTER TABLE analysis_results ADD COLUMN engine JSON")
    conn.exec_driver_sql("UPDATE analysis_results SET engine = ?", (json.dumps(VADER_BEFORE_PHASE_4),))


def _v5_ai_summaries(conn: Connection) -> None:
    """A separate table for optional AI-written overviews; existing tables are not changed."""
    conn.exec_driver_sql(
        "CREATE TABLE ai_summaries ("
        "id INTEGER NOT NULL PRIMARY KEY, "
        "analysis_id INTEGER NOT NULL REFERENCES analysis_results (id) ON DELETE CASCADE, "
        "created_at DATETIME NOT NULL, model VARCHAR(100) NOT NULL, prompt_version INTEGER NOT NULL, "
        "status VARCHAR(20) NOT NULL, attempts INTEGER NOT NULL, sentences JSON NOT NULL, problems JSON NOT NULL)")
    conn.exec_driver_sql("CREATE INDEX ix_ai_summaries_analysis_id ON ai_summaries (analysis_id)")


MIGRATIONS: list[tuple[str, Callable[[Connection], None]]] = [
    ("baseline (Phase 2 schema)", _v1_baseline),
    ("per-review results stored on each analysis run", _v2_review_snapshots),
    ("source details for products collected from links", _v3_collected_products),
    ("product domain and sentiment engine per analysis run", _v4_engine_and_domain),
    ("table for optional AI-written overviews", _v5_ai_summaries),
]
LATEST_VERSION = len(MIGRATIONS)


# ---------- Runner ----------

def get_version(conn: Connection) -> int:
    return conn.exec_driver_sql("PRAGMA user_version").scalar()


def _set_version(conn: Connection, version: int) -> None:
    conn.exec_driver_sql(f"PRAGMA user_version = {int(version)}")


def _backup(engine: Engine, version: int) -> Path | None:
    database = engine.url.database
    if not database or database == ":memory:":
        return None
    source = Path(database)
    backup_dir = source.parent / "backups"
    backup_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    target = backup_dir / f"{source.stem}-v{version}-{stamp}{source.suffix}"
    shutil.copy2(source, target)
    return target


def upgrade(engine: Engine) -> int:
    """Bring the database to LATEST_VERSION. Returns the number of migrations applied."""
    with engine.connect() as conn:
        version = get_version(conn)
        has_tables = bool(inspect(conn).get_table_names())

    if version > LATEST_VERSION:
        raise RuntimeError(f"The database is at schema version {version}, but this app only knows up to "
                           f"{LATEST_VERSION}. Update the app, or restore a backup from storage/backups/.")

    if not has_tables:  # brand-new database: create tables and record the version in ONE transaction,
        with engine.begin() as conn:  # so a crash can't leave tables without a version (read as Phase 2)
            Base.metadata.create_all(conn)
            _set_version(conn, LATEST_VERSION)
        return 0

    if version == 0:
        version = 1  # tables exist but no version: created by Phase 2, before versioning existed

    pending = MIGRATIONS[version:]
    if not pending:
        return 0
    backup = _backup(engine, version)
    log.info("Upgrading database from version %s to %s (backup: %s)", version, LATEST_VERSION, backup)
    for number, (description, migrate) in enumerate(pending, start=version + 1):
        # One transaction per migration: if it fails, that step is rolled back and the version is unchanged.
        with engine.begin() as conn:
            migrate(conn)
            _set_version(conn, number)
        log.info("Applied migration %s: %s", number, description)
    return len(pending)
