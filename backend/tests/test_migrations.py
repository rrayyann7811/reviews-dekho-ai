"""Upgrading an existing database keeps user data (docs/PLAN.md, "Schema changes")."""
import json
import sqlite3

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, inspect

from app import migrations
from app.database import Base, make_engine

from .conftest import BACKEND

PHASE2_SQL = (BACKEND / "tests/fixtures/phase2_schema.sql").read_text()


def make_phase2_database(path):
    """A database exactly as Phase 2 left it: two analysis runs of one product, results on the review rows."""
    con = sqlite3.connect(path)
    con.executescript(PHASE2_SQL)
    con.execute("INSERT INTO products VALUES (1, 'Old Phone', 'Acme', NULL, 'upload', NULL, 'old.csv', "
                "'2026-11-01 10:00:00')")
    run = ("INSERT INTO analysis_results VALUES (?, 1, ?, 2, 4.0, 50.0, 50.0, ?, '[]', '[]', '{}', ?)")
    con.execute(run, (1, "2026-11-01 10:00:01", json.dumps({"totalReviews": 2}), json.dumps({"fileName": "old.csv"})))
    con.execute(run, (2, "2026-11-02 10:00:01", json.dumps({"totalReviews": 2}), json.dumps({"fileName": "old.csv"})))
    aspects = json.dumps([{"aspect": "Battery", "sentiment": "positive", "score": 0.6, "snippet": "Great battery"}])
    con.execute("INSERT INTO reviews VALUES (1, 1, 'A1', 'Great battery', 5, '2026-10-01', 'Nice', 'Asha', "
                "'positive', 0.6249, 0, ?)", (aspects,))
    con.execute("INSERT INTO reviews VALUES (2, 1, 'A2', 'Awful screen', 1, NULL, NULL, NULL, "
                "'negative', -0.4588, 0, '[]')")
    con.commit()
    con.close()


def columns_by_table(engine):
    inspector = inspect(engine)
    return {t: sorted(c["name"] for c in inspector.get_columns(t)) for t in inspector.get_table_names()}


def indexes_by_table(engine):
    inspector = inspect(engine)
    return {t: sorted((i["name"], bool(i["unique"])) for i in inspector.get_indexes(t))
            for t in inspector.get_table_names()}


def test_new_database_starts_at_the_latest_version(tmp_path):
    engine = make_engine(f"sqlite:///{tmp_path / 'new.db'}")
    assert migrations.upgrade(engine) == 0
    with engine.connect() as conn:
        assert migrations.get_version(conn) == migrations.LATEST_VERSION
    assert not (tmp_path / "backups").exists()


def test_upgrade_from_phase2_keeps_every_record(tmp_path):
    path = tmp_path / "reviews_dekho.db"
    make_phase2_database(path)
    engine = make_engine(f"sqlite:///{path}")

    assert migrations.upgrade(engine) == migrations.LATEST_VERSION - 1

    con = sqlite3.connect(path)
    assert con.execute("PRAGMA user_version").fetchone()[0] == migrations.LATEST_VERSION
    assert con.execute("SELECT id, name, brand, file_name FROM products").fetchall() == [(1, "Old Phone", "Acme",
                                                                                          "old.csv")]
    assert con.execute("SELECT external_id, text, rating FROM reviews ORDER BY id").fetchall() == [
        ("A1", "Great battery", 5), ("A2", "Awful screen", 1)]
    runs = dict(con.execute("SELECT id, review_results FROM analysis_results").fetchall())
    con.close()
    # The latest run gets its per-review results from the review rows; the older run can't be recovered.
    assert runs[1] is None
    latest = json.loads(runs[2])
    assert [(r["id"], r["sentiment"], r["score"]) for r in latest] == [("A1", "positive", 0.6249),
                                                                        ("A2", "negative", -0.4588)]
    assert latest[0]["aspects"][0]["aspect"] == "Battery" and latest[0]["date"] == "2026-10-01"
    assert latest[0]["mixed"] is False


def test_upgraded_schema_equals_a_new_database(tmp_path):
    make_phase2_database(tmp_path / "old.db")
    upgraded = make_engine(f"sqlite:///{tmp_path / 'old.db'}")
    migrations.upgrade(upgraded)
    fresh = create_engine("sqlite://")
    Base.metadata.create_all(fresh)
    assert columns_by_table(upgraded) == columns_by_table(fresh)
    assert indexes_by_table(upgraded) == indexes_by_table(fresh)


def test_a_backup_is_made_before_upgrading(tmp_path):
    path = tmp_path / "reviews_dekho.db"
    make_phase2_database(path)
    migrations.upgrade(make_engine(f"sqlite:///{path}"))
    [backup] = (tmp_path / "backups").iterdir()
    assert backup.name.startswith("reviews_dekho-v1-")
    con = sqlite3.connect(backup)
    assert con.execute("PRAGMA user_version").fetchone()[0] == 0  # the untouched original
    assert "sentiment" in [row[1] for row in con.execute("PRAGMA table_info(reviews)")]
    con.close()


def test_upgrading_twice_does_nothing(tmp_path):
    make_phase2_database(tmp_path / "db.db")
    engine = make_engine(f"sqlite:///{tmp_path / 'db.db'}")
    migrations.upgrade(engine)
    assert migrations.upgrade(engine) == 0
    assert len(list((tmp_path / "backups").iterdir())) == 1


def test_a_failing_migration_is_rolled_back(tmp_path, monkeypatch):
    make_phase2_database(tmp_path / "db.db")
    engine = make_engine(f"sqlite:///{tmp_path / 'db.db'}")

    def broken(conn):
        conn.exec_driver_sql("ALTER TABLE products ADD COLUMN half_done TEXT")
        raise RuntimeError("simulated failure")

    monkeypatch.setattr(migrations, "MIGRATIONS", [*migrations.MIGRATIONS[:2], ("broken", broken)])
    with pytest.raises(RuntimeError):
        migrations.upgrade(engine)
    con = sqlite3.connect(tmp_path / "db.db")
    assert con.execute("PRAGMA user_version").fetchone()[0] == 2  # migration 2 completed, 3 did not
    assert "half_done" not in [row[1] for row in con.execute("PRAGMA table_info(products)")]
    con.close()


def test_a_database_from_a_newer_app_is_refused(tmp_path):
    path = tmp_path / "db.db"
    con = sqlite3.connect(path)
    con.execute("CREATE TABLE x (id INTEGER)")
    con.execute(f"PRAGMA user_version = {migrations.LATEST_VERSION + 1}")
    con.close()
    with pytest.raises(RuntimeError, match="only knows up to"):
        migrations.upgrade(make_engine(f"sqlite:///{path}"))


def test_the_app_serves_an_upgraded_database(tmp_path, monkeypatch):
    import app.database as database
    from app.main import create_app

    path = tmp_path / "db.db"
    make_phase2_database(path)
    engine = make_engine(f"sqlite:///{path}")
    monkeypatch.setattr(database, "engine", engine)
    monkeypatch.setattr(database, "SessionLocal", database.sessionmaker(bind=engine, expire_on_commit=False))
    # Startup no longer performs potentially destructive legacy upgrades automatically.
    # The stopped-app operator migration preserves the same historical data and snapshots.
    migrations.upgrade(engine)
    with TestClient(create_app()) as client:
        analysis = client.get("/api/products/1/analysis").json()
        assert [r["id"] for r in analysis["reviews"]] == ["A1", "A2"]
        old_run = client.get("/api/history/1").json()
        assert old_run["reviews"] is None and old_run["stats"] == {"totalReviews": 2}
        # Re-analysing works and produces a complete new snapshot.
        assert client.post("/api/products/1/analyze").status_code == 200
        assert client.get("/api/history").json()[0]["totalReviews"] == 2


# ---------- Found in the pre-commit review: never attach a snapshot that contradicts its run ----------

def _snapshot(path, run_id):
    con = sqlite3.connect(path)
    value = con.execute("SELECT review_results FROM analysis_results WHERE id = ?", (run_id,)).fetchone()[0]
    con.close()
    return value


def test_no_snapshot_when_reviews_were_deleted_after_the_run(tmp_path):
    # Phase 2: deleting a product's last review didn't re-run the analysis.
    path = tmp_path / "db.db"
    make_phase2_database(path)
    con = sqlite3.connect(path)
    con.execute("DELETE FROM reviews")
    con.commit()
    con.close()
    migrations.upgrade(make_engine(f"sqlite:///{path}"))
    assert _snapshot(path, 2) is None


def test_no_snapshot_when_the_newest_run_had_been_deleted(tmp_path):
    # Phase 2: deleting the newest run left review rows holding THAT run's results.
    path = tmp_path / "db.db"
    make_phase2_database(path)
    con = sqlite3.connect(path)
    con.execute("UPDATE analysis_results SET stats = ? WHERE id = 1", (json.dumps(
        {"totalReviews": 2, "sentimentCounts": {"positive": 2, "neutral": 0, "negative": 0}}),))
    con.execute("DELETE FROM analysis_results WHERE id = 2")
    con.commit()
    con.close()
    migrations.upgrade(make_engine(f"sqlite:///{path}"))
    assert _snapshot(path, 1) is None  # same count, different sentiment counts: not this run's results


def test_snapshot_is_kept_when_counts_match(tmp_path):
    path = tmp_path / "db.db"
    make_phase2_database(path)
    con = sqlite3.connect(path)
    con.execute("UPDATE analysis_results SET stats = ? WHERE id = 2", (json.dumps(
        {"totalReviews": 2, "sentimentCounts": {"positive": 1, "neutral": 0, "negative": 1}}),))
    con.commit()
    con.close()
    migrations.upgrade(make_engine(f"sqlite:///{path}"))
    assert len(json.loads(_snapshot(path, 2))) == 2


def test_a_new_database_is_created_in_one_transaction(tmp_path, monkeypatch):
    engine = make_engine(f"sqlite:///{tmp_path / 'new.db'}")

    def crash(conn, version):
        raise RuntimeError("power cut")

    monkeypatch.setattr(migrations, "_set_version", crash)
    with pytest.raises(RuntimeError):
        migrations.upgrade(engine)
    assert inspect(engine).get_table_names() == []  # nothing half-created, so the next start begins cleanly


# ---------- Migration 4: product type and engine per run ----------

def test_phase3_database_gets_domain_and_engine(tmp_path, monkeypatch):
    path = tmp_path / "db.db"
    make_phase2_database(path)
    engine = make_engine(f"sqlite:///{path}")
    phase3 = migrations.MIGRATIONS[:3]
    monkeypatch.setattr(migrations, "MIGRATIONS", phase3)
    monkeypatch.setattr(migrations, "LATEST_VERSION", 3)
    migrations.upgrade(engine)  # a database exactly as Phase 3 left it
    con = sqlite3.connect(path)
    con.execute("INSERT INTO products (id, name, source, created_at, source_site, external_product_id, source_region) "
                "VALUES (2, 'Some App', 'url', '2026-11-10 10:00:00', 'apple_app_store', '123456', 'in')")
    con.commit()
    con.close()
    monkeypatch.undo()

    assert migrations.upgrade(engine) == migrations.LATEST_VERSION - 3  # everything after Phase 3
    con = sqlite3.connect(path)
    assert con.execute("PRAGMA user_version").fetchone()[0] == migrations.LATEST_VERSION
    assert dict(con.execute("SELECT id, domain FROM products").fetchall()) == {1: "product", 2: "app"}
    engines = [json.loads(e) for (e,) in con.execute("SELECT engine FROM analysis_results")]
    con.close()
    assert len(engines) == 2 and all(e["id"] == "vader" and e["pipelineVersion"] == 1 for e in engines)
    assert len(list((tmp_path / "backups").iterdir())) == 2  # one backup per upgrade session


def test_upgraded_runs_keep_their_snapshots_untouched(tmp_path):
    path = tmp_path / "db.db"
    make_phase2_database(path)
    con = sqlite3.connect(path)
    con.execute("UPDATE analysis_results SET stats = ? WHERE id = 2", (json.dumps(
        {"totalReviews": 2, "sentimentCounts": {"positive": 1, "neutral": 0, "negative": 1}}),))
    con.commit()
    con.close()
    migrations.upgrade(make_engine(f"sqlite:///{path}"))
    snapshot = json.loads(_snapshot(path, 2))
    assert all("status" not in r for r in snapshot)  # not rewritten with fields the old run never had


# ---------- Migration 5: optional AI overviews in their own table ----------

def test_ai_summaries_table_is_added_without_touching_runs(tmp_path):
    path = tmp_path / "db.db"
    make_phase2_database(path)
    con = sqlite3.connect(path)
    before = con.execute("SELECT id, stats, summary FROM analysis_results ORDER BY id").fetchall()
    con.close()
    migrations.upgrade(make_engine(f"sqlite:///{path}"))
    con = sqlite3.connect(path)
    assert con.execute("SELECT id, stats, summary FROM analysis_results ORDER BY id").fetchall() == before
    columns = [row[1] for row in con.execute("PRAGMA table_info(ai_summaries)")]
    assert columns == ["id", "analysis_id", "created_at", "model", "prompt_version", "status", "attempts",
                       "sentences", "problems"]
    con.close()


# ---------- Migration 6: ownership is additive and legacy data remains local ----------

def test_ownership_upgrade_preserves_local_records_and_scopes_collector_index(tmp_path, monkeypatch):
    path = tmp_path / 'before-auth.db'
    make_phase2_database(path)
    engine = make_engine(f'sqlite:///{path}')
    with monkeypatch.context() as patch:
        patch.setattr(migrations, 'MIGRATIONS', migrations.MIGRATIONS[:5])
        patch.setattr(migrations, 'LATEST_VERSION', 5)
        migrations.upgrade(engine)
    with engine.connect() as conn:
        snapshots = conn.exec_driver_sql('SELECT id, review_results FROM analysis_results').all()
    assert migrations.upgrade(engine) == migrations.LATEST_VERSION - 5
    with engine.connect() as conn:
        assert conn.exec_driver_sql('SELECT id, owner_id, expires_at FROM products').all() == [(1, 'local', None)]
        assert conn.exec_driver_sql('SELECT id, review_results FROM analysis_results').all() == snapshots
    index = next(i for i in inspect(engine).get_indexes('products') if i['name'] == 'uq_collected_product')
    assert index['column_names'] == ['owner_id', 'source_site', 'external_product_id', 'source_region']
    assert index['unique']
    assert migrations.upgrade(engine) == 0
