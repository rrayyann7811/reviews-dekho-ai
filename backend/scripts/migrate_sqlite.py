"""Explicit legacy SQLite upgrade. Stop the app first; the runner creates a file backup before upgrades."""
import os
import sys
from pathlib import Path


def main():
    url = os.getenv("DATABASE_URL", "")
    if not url.startswith(("sqlite:///", "sqlite+pysqlite:///")):
        raise SystemExit("Set an explicit SQLite DATABASE_URL before running this upgrade.")
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from app.database import make_engine
    from app import migrations, models  # noqa: F401
    engine = make_engine(url)
    try:
        count = migrations.upgrade(engine)
        print(f"Applied {count} SQLite migration(s).")
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
