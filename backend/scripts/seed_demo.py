"""Creates a separate demo database from the synthetic review files — never touches your real data.

Run from backend/:
    .venv/bin/python scripts/seed_demo.py                       # creates storage/demo.db
    .venv/bin/python scripts/seed_demo.py --reset               # re-creates it (only if this script made it)
    .venv/bin/python scripts/seed_demo.py --engine vader        # fast and lightweight (no sentiment model needed)
Then start the backend on it:
    DATABASE_URL=sqlite:///storage/demo.db .venv/bin/uvicorn app.main:app --reload

What it creates (all reviews, products and reviewer names are synthetic — see data/demo/README.md):
  * Kestrel Orbit 5G (demo)  — the bundled 63-review sample
  * Aurora X5 (demo)         — a second phone, to compare with Kestrel
  * QuickCart (demo app)     — an app with two runs: October reviews, then November reviews after an update
  * Saffron Buds (demo)      — earphones with 12 Hinglish reviews, which are marked "not analysed"

Safety rules (checked before anything is opened or created):
  * the file name must end in .db and contain "demo";
  * it must not be the real database (storage/reviews_dekho.db) or the one DATABASE_URL points to, nor a symlink;
  * it must be inside backend/storage/ or outside this repository (no stray databases in the source tree);
  * an existing file is never overwritten, unless --reset is given AND the file carries this script's marker.
Every run prints a content digest of all stored analysis results (timestamps and database IDs excluded); the same
files and engine give the same digest.
"""
import argparse
import datetime as dt
import hashlib
import json
import os
import sqlite3
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
REPO = BACKEND.parent
STORAGE = BACKEND / "storage"
REAL_DB = STORAGE / "reviews_dekho.db"
DEMO_DATA = BACKEND / "data" / "demo"
SAMPLE = BACKEND / "data" / "sample" / "demo_kestrel_orbit_5g.csv"
MARKER_TABLE = "demo_seed_info"
MARKER_APP = "reviews-dekho-ai demo seed"


class Refused(Exception):
    pass


def _sqlite_path(url: str | None) -> Path | None:
    if url and url.startswith("sqlite:///"):
        return Path(url.removeprefix("sqlite:///")).expanduser()
    return None


def has_marker(path: Path) -> bool:
    try:
        con = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        try:
            row = con.execute(f"SELECT app FROM {MARKER_TABLE} LIMIT 1").fetchone()
        finally:
            con.close()
    except sqlite3.Error:
        return False
    return bool(row) and row[0] == MARKER_APP


def check_target(raw: str, reset: bool) -> Path:
    """The resolved, safe target path, or Refused with the reason. Never creates, opens for writing or deletes."""
    given = Path(raw).expanduser()
    if not given.is_absolute():
        given = Path.cwd() / given
    if given.is_symlink():
        raise Refused(f"{given} is a symbolic link; give the real path of a demo database.")
    path = given.resolve()
    protected = {REAL_DB.resolve()}
    env_db = _sqlite_path(os.environ.get("DATABASE_URL"))
    if env_db is not None and "demo" not in env_db.name.lower():
        protected.add((env_db if env_db.is_absolute() else Path.cwd() / env_db).resolve())
    if path in protected or path.name.lower().startswith("reviews_dekho"):
        raise Refused(f"{path} is (or looks like) the real database. The demo must use its own file.")
    if path.suffix != ".db" or "demo" not in path.name.lower():
        raise Refused(f"“{path.name}” isn't a demo database name: it must end in .db and contain “demo”.")
    inside_repo = path.is_relative_to(REPO.resolve())
    if inside_repo and not path.is_relative_to(STORAGE.resolve()):
        raise Refused(f"{path} is inside the source tree. Use backend/storage/ (git-ignored) or a folder outside "
                      "the repository.")
    if path.is_dir():
        raise Refused(f"{path} is a folder.")
    if path.exists():
        if not reset:
            raise Refused(f"{path} already exists, so nothing was changed. Add --reset to re-create it "
                          "(only allowed for a database this script made).")
        if not has_marker(path):
            raise Refused(f"{path} exists but wasn't made by this script (no demo marker), so it won't be deleted.")
    return path


def remove_demo(path: Path) -> None:
    for extra in ("", "-wal", "-shm", "-journal"):
        Path(f"{path}{extra}").unlink(missing_ok=True)


def content_digest(db_path: Path) -> tuple[str, list[dict]]:
    """SHA-256 of every stored analysis result, in a canonical order, without timestamps or database IDs."""
    con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    rows = con.execute(
        "SELECT p.name, p.domain, p.category, a.total_reviews, a.stats, a.aspects, a.keywords, a.summary, "
        "a.review_results, a.engine FROM analysis_results a JOIN products p ON p.id = a.product_id "
        "ORDER BY p.name, a.id").fetchall()
    con.close()
    canonical, overview = [], []
    for name, domain, category, total, *blobs in rows:
        stats, aspects, keywords, summary, reviews, engine = (json.loads(b) if b else None for b in blobs)
        canonical.append([name, domain, category, total, stats, aspects, keywords, summary, reviews, engine])
        overview.append({"product": name, "reviews": total, "analysed": stats.get("analysedReviews"),
                         "engine": (engine or {}).get("id")})
    blob = json.dumps(canonical, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(blob.encode()).hexdigest(), overview


def seed(path: Path, engine: str) -> dict:
    # The app reads its settings when imported, so they are set here, after every safety check passed.
    os.environ["DATABASE_URL"] = f"sqlite:///{path}"
    os.environ["SENTIMENT_ENGINE"] = engine
    os.environ["AI_SUMMARIES"] = "off"
    sys.path.insert(0, str(BACKEND))
    from fastapi.testclient import TestClient
    from app.main import app

    def upload(client, file: Path, name: str, columns: dict, **form) -> dict:
        response = client.post("/api/uploads/import", files={"file": (file.name, file.read_bytes(), "text/csv")},
                               data={"product_name": name, "columns": json.dumps(columns), **form})
        if response.status_code != 201:
            raise RuntimeError(f"Importing {file.name} failed: {response.text}")
        return response.json()

    columns = {"text": "review_text", "rating": "rating", "date": "review_date", "reviewer": "reviewer_name",
               "id": "review_id"}
    with TestClient(app) as client:
        upload(client, SAMPLE, "Kestrel Orbit 5G (demo)", columns | {"title": "review_title"}, brand="Kestrel",
               category="Smartphones", domain="product")
        upload(client, DEMO_DATA / "aurora_x5_phone.csv", "Aurora X5 (demo)", columns, brand="Aurora",
               category="Smartphones", domain="product")
        app_product = upload(client, DEMO_DATA / "quickcart_app_october.csv", "QuickCart (demo app)", columns,
                             category="Shopping", domain="app")
        import csv
        with open(DEMO_DATA / "quickcart_app_november_update.csv", encoding="utf-8") as f:
            november = [{"id": r["review_id"], "reviewer": r["reviewer_name"], "rating": int(r["rating"]),
                         "date": r["review_date"], "text": r["review_text"]} for r in csv.DictReader(f)]
        response = client.post(f"/api/products/{app_product['id']}/reviews", json={"reviews": november})
        if response.status_code != 201:
            raise RuntimeError(f"Adding the November reviews failed: {response.text}")
        upload(client, DEMO_DATA / "saffron_buds_earphones_mixed_language.csv", "Saffron Buds (demo)", columns,
               brand="Saffron", category="Audio", domain="product")

    digest, overview = content_digest(path)
    con = sqlite3.connect(path)
    con.execute(f"CREATE TABLE {MARKER_TABLE} (app TEXT NOT NULL, created_at TEXT NOT NULL, engine TEXT NOT NULL, "
                "content_digest TEXT NOT NULL)")
    con.execute(f"INSERT INTO {MARKER_TABLE} VALUES (?, ?, ?, ?)",
                (MARKER_APP, dt.datetime.now(dt.timezone.utc).isoformat(), engine, digest))
    con.commit()
    con.close()
    return {"database": str(path), "engine": engine, "contentDigest": digest, "runs": overview}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Create the synthetic demo database (never your real one).")
    parser.add_argument("--db", default=str(STORAGE / "demo.db"), help="Demo database file (default storage/demo.db)")
    parser.add_argument("--reset", action="store_true", help="Re-create the demo database if this script made it")
    parser.add_argument("--engine", choices=("auto", "vader"), default="auto",
                        help="auto: the sentiment model if installed, else VADER (default); vader: always VADER")
    parser.add_argument("--json", action="store_true", help="Print the result as JSON")
    args = parser.parse_args(argv)
    try:
        path = check_target(args.db, args.reset)
    except Refused as exc:
        print(f"Refused: {exc}", file=sys.stderr)
        return 2
    if path.exists():
        remove_demo(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    result = seed(path, args.engine)
    if args.json:
        print(json.dumps(result))
    else:
        print(f"Demo database: {result['database']}")
        for run in result["runs"]:
            print(f"  {run['product']:<26} {run['reviews']:>4} reviews, {run['analysed']:>4} analysed ({run['engine']})")
        print(f"Content digest: {result['contentDigest']}")
        rel = os.path.relpath(path, BACKEND)
        print(f"Start the backend on it:\n  DATABASE_URL=sqlite:///{rel if not rel.startswith('..') else path} "
              ".venv/bin/uvicorn app.main:app --reload")
    return 0


if __name__ == "__main__":
    sys.exit(main())
