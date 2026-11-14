"""Data is really stored in SQLite and survives a restart."""
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app import config
from app.database import make_engine
from app.main import create_app
from app.models import AnalysisResult, Product, Review


def test_imported_data_is_written_to_the_database(client, product):
    # A brand-new engine and session read the file directly, bypassing the API.
    engine = make_engine(config.DATABASE_URL)
    with Session(engine) as db:
        stored = db.get(Product, product["id"])
        assert stored.name == "Test Phone" and stored.source == "upload"
        assert db.scalar(select(func.count()).select_from(Review)) == 6
        [analysis] = db.scalars(select(AnalysisResult)).all()
        assert analysis.total_reviews == 6 and analysis.stats["totalReviews"] == 6
        assert [r["id"] for r in analysis.review_results] == [r.external_id for r in stored.reviews]
        assert all(r["sentiment"] in ("positive", "neutral", "negative") for r in analysis.review_results)
        assert stored.reviews[0].review_date.isoformat() == "2026-10-01"
    engine.dispose()


def test_data_survives_an_app_restart(client, product):
    before = client.get(f"/api/products/{product['id']}/analysis").json()
    with TestClient(create_app()) as restarted:
        after = restarted.get(f"/api/products/{product['id']}/analysis").json()
    assert after == before


def test_failed_import_leaves_no_partial_data(client):
    # Every review is empty, so the whole import is rejected.
    client.post("/api/uploads/import", files={"file": ("e.csv", b"review\n \n", "text/csv")},
                data={"product_name": "P", "columns": '{"text": "review"}'})
    engine = make_engine(config.DATABASE_URL)
    with Session(engine) as db:
        assert db.scalar(select(func.count()).select_from(Product)) == 0
        assert db.scalar(select(func.count()).select_from(Review)) == 0
    engine.dispose()


def test_foreign_keys_are_enforced(client, product):
    engine = make_engine(config.DATABASE_URL)
    with engine.connect() as conn:
        assert conn.exec_driver_sql("PRAGMA foreign_keys").scalar() == 1
    engine.dispose()
