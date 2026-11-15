import io
import json
import os
import tempfile
from pathlib import Path

# Point the app at a throwaway database BEFORE it is imported, so tests never touch real data.
_TMP = Path(tempfile.mkdtemp(prefix="reviews-dekho-tests-"))
os.environ["DATABASE_URL"] = f"sqlite:///{_TMP / 'test.db'}"
# The default suite uses VADER so results are exact and the model files aren't needed.
# tests/test_transformer_engine.py covers the pretrained model (skipped if it isn't installed).
os.environ["SENTIMENT_ENGINE"] = "vader"

import pandas as pd  # noqa: E402
import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.database import Base, engine, init_db  # noqa: E402
from app.main import create_app  # noqa: E402

BACKEND = Path(__file__).resolve().parents[1]
DEMO_CSV = BACKEND / "data/sample/demo_kestrel_orbit_5g.csv"
FRONTEND_DEMO_JSON = BACKEND.parent / "frontend/src/demo/demoAnalysis.json"

SAMPLE_CSV = """review_id,product_name,rating,review_date,review_title,review_text,reviewer_name
A1,Test Phone,5,2026-10-01,Love it,"The battery life is amazing and the camera is excellent.",Asha
A2,Test Phone,1,2026-10-02,Awful,"Terrible phone. The battery drains fast and the screen cracked.",Ravi
A3,Test Phone,4,2026-10-03,Good value,"Great value for the price, delivery was quick.",Meera
A4,Test Phone,2,2026-10-04,Meh,"The camera is poor in low light but the display is good.",Karan
A5,Test Phone,3,2026-10-05,Okay,"It is a phone. Does calls.",Zoya
A6,Test Phone,5,2026-10-06,Superb,"Excellent performance, very fast and smooth. Battery is great.",Imran
"""


@pytest.fixture
def client():
    Base.metadata.drop_all(engine)
    init_db(engine)  # the same path the app uses at startup
    # Admission and frequency state belong to one app lifetime, not the whole test session.
    with TestClient(create_app()) as test_client:
        yield test_client


def csv_file(text: str = SAMPLE_CSV, name: str = "reviews.csv", encoding: str = "utf-8"):
    return {"file": (name, text.encode(encoding), "text/csv")}


def xlsx_bytes(rows: list[dict]) -> bytes:
    buffer = io.BytesIO()
    pd.DataFrame(rows).to_excel(buffer, index=False, engine="openpyxl")
    return buffer.getvalue()


DEFAULT_COLUMNS = {"text": "review_text", "rating": "rating", "date": "review_date", "title": "review_title",
                   "reviewer": "reviewer_name", "productName": "product_name", "id": "review_id"}


def import_file(client, files=None, product_name="Test Phone", columns=None, **extra):
    data = {"product_name": product_name, "columns": json.dumps(columns or DEFAULT_COLUMNS), **extra}
    return client.post("/api/uploads/import", files=files or csv_file(), data=data)


@pytest.fixture
def product(client):
    """A product imported from SAMPLE_CSV."""
    response = import_file(client)
    assert response.status_code == 201, response.text
    return response.json()
