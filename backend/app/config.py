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

# Collecting reviews from product links (see app/collectors/).
COLLECT_TIMEOUT_SECONDS = float(os.getenv("COLLECT_TIMEOUT_SECONDS", "15"))
APPLE_MAX_PAGES = 10              # Apple's feed serves at most 10 pages of 50 reviews
APPLE_PAGE_DELAY_SECONDS = 0.3    # pause between pages, to be polite to Apple's servers
APPLE_DEFAULT_COUNTRY = "us"      # used when a link has no country code (Apple shows the US store then)

# Sentiment engine (see app/nlp/engines.py):
#   "auto"        use the pretrained transformer if its files are installed, otherwise VADER
#   "transformer" same as auto, but the analysis records a warning when it had to fall back
#   "vader"       always use the rule-based VADER engine
SENTIMENT_ENGINE = os.getenv("SENTIMENT_ENGINE", "auto").strip().lower()
MODEL_DIR = Path(os.getenv("MODEL_DIR", str(BACKEND_DIR / "models" / "twitter-roberta-sentiment")))
# Texts per model call. 1 on purpose: the int8 model quantizes each call's activations using the range of the
# whole batch, so with larger batches a review's result changed with its batch-mates (measured: 3.5% of labels
# flipped). One text per call is deterministic and only ~15% slower (219 vs 257 texts/s on an M3).
# A full-precision model could use larger batches safely.
MODEL_BATCH_SIZE = 1
MODEL_MAX_TOKENS = 256
