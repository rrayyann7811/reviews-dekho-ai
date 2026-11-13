"""Application settings, read from environment variables with safe defaults.

Override any of these when starting the server, e.g.
    DATABASE_URL=sqlite:///./other.db .venv/bin/uvicorn app.main:app
"""
import os
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
STORAGE_DIR = BACKEND_DIR / "storage"  # git-ignored

DATABASE_URL = os.getenv("DATABASE_URL", f"sqlite:///{STORAGE_DIR / 'reviews_dekho.db'}")

# Frontend origins allowed to call the API (comma-separated).
CORS_ORIGINS = [
    o.strip()
    for o in os.getenv(
        "CORS_ORIGINS",
        "http://localhost:5173,http://127.0.0.1:5173,http://localhost:4173,http://127.0.0.1:4173",
    ).split(",")
    if o.strip()
]

# Upload limits. The frontend checks the same size limit before uploading.
MAX_UPLOAD_BYTES = 10 * 1024 * 1024
MAX_ROWS = 20_000
MAX_REVIEW_CHARS = 5_000
PREVIEW_ROWS = 5
