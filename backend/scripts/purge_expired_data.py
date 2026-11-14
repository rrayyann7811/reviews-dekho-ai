"""Delete expired account review data, never identity-provider accounts or non-expiring local data.

Run from backend/: .venv/bin/python scripts/purge_expired_data.py
Uses DATABASE_URL. Scheduling and backup-retention integration are a later deployment checkpoint.
"""
import argparse
import sys
from pathlib import Path


def main():
    argparse.ArgumentParser(description=__doc__).parse_args()
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from app.database import SessionLocal
    from app.services.retention import purge_expired_products

    with SessionLocal.begin() as db:
        count = purge_expired_products(db)
    print(f"Deleted {count} expired product(s) with their reviews and analysis history.")


if __name__ == "__main__":
    main()
