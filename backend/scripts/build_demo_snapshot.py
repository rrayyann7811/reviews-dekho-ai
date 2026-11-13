"""Build the analysis snapshot the frontend uses for its demo product.

Temporary helper for Phase 1: once the API serves analyses (Phase 5) the
frontend reads live data and this script and the JSON file are removed.

Run from backend/:  .venv/bin/python scripts/build_demo_snapshot.py
"""
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.nlp.pipeline import analyze_reviews  # noqa: E402
from app.nlp.preprocess import normalize_text  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "backend/data/sample/demo_kestrel_orbit_5g.csv"
TARGET = ROOT / "frontend/src/demo/demoAnalysis.json"

df = pd.read_csv(SOURCE, dtype=str, keep_default_na=False)
rows_in_file = len(df)
df = df.drop_duplicates(subset="review_id")
duplicates = rows_in_file - len(df)
df["review_text"] = df["review_text"].map(normalize_text)
empty = int((df["review_text"] == "").sum())
df = df[df["review_text"] != ""]

reviews = [{
    "id": r.review_id,
    "reviewer": r.reviewer_name or None,
    "title": r.review_title or None,
    "rating": int(r.rating) if r.rating else None,
    "date": r.review_date or None,
    "text": r.review_text,
} for r in df.itertuples()]

result = analyze_reviews(reviews)
result["product"] = {
    "id": "demo",
    "name": df["product_name"].iloc[0],
    "brand": "Kestrel (fictional)",
    "category": "Smartphones",
    "source": "demo",
}
result["ingestion"] = {"rowsInFile": rows_in_file, "duplicatesRemoved": duplicates,
                       "emptyRemoved": empty, "fileName": SOURCE.name}
result["analyzedAt"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
TARGET.parent.mkdir(parents=True, exist_ok=True)
TARGET.write_text(json.dumps(result, indent=1, ensure_ascii=False))
print(f"Wrote {TARGET} ({len(reviews)} reviews)")
print(json.dumps({k: result[k] for k in ("stats", "keywords")}, indent=1)[:2500])
print(json.dumps([(a["aspect"], a["mentions"], a["positive"], a["neutral"], a["negative"], a["verdict"]) for a in result["aspects"]]))
print(json.dumps(result["summary"], indent=1)[:1500])
