"""Application settings, read from environment variables with safe defaults.

Override any of these when starting the server, e.g.
    DATABASE_URL=sqlite:///./other.db .venv/bin/uvicorn app.main:app
"""
import os
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
STORAGE_DIR = BACKEND_DIR / "storage"  # git-ignored

DATABASE_URL = os.getenv("DATABASE_URL", f"sqlite:///{STORAGE_DIR / 'reviews_dekho.db'}")
DB_POOL_MODE = os.getenv("DB_POOL_MODE", "queue")  # queue for a direct/session connection; null for external pooling
DB_POOL_SIZE = int(os.getenv("DB_POOL_SIZE", "2"))
DB_MAX_OVERFLOW = int(os.getenv("DB_MAX_OVERFLOW", "0"))
DB_POOL_TIMEOUT = int(os.getenv("DB_POOL_TIMEOUT", "5"))
DB_CONNECT_TIMEOUT = int(os.getenv("DB_CONNECT_TIMEOUT", "5"))
DB_STATEMENT_TIMEOUT_MS = int(os.getenv("DB_STATEMENT_TIMEOUT_MS", "30000"))
DB_LOCK_TIMEOUT_MS = int(os.getenv("DB_LOCK_TIMEOUT_MS", "5000"))

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
def _positive_limit(name, default):
    value = int(os.getenv(name, str(default)))
    if value < 1:
        raise ValueError(f"{name} must be positive")
    return value


MAX_UPLOAD_BYTES = _positive_limit("MAX_UPLOAD_BYTES", 10 * 1024 * 1024)
MAX_REQUEST_BYTES = _positive_limit("MAX_REQUEST_BYTES", 12 * 1024 * 1024)
MAX_ROWS = _positive_limit("MAX_ROWS", 20_000)
MAX_FORM_FIELD_BYTES = _positive_limit("MAX_FORM_FIELD_BYTES", 65536)
MAX_COLUMNS = _positive_limit("MAX_COLUMNS", 64)
MAX_REVIEW_CHARS = _positive_limit("MAX_REVIEW_CHARS", 5_000)
MAX_CSV_FIELD_CHARS = _positive_limit("MAX_CSV_FIELD_CHARS", 20_000)
MAX_XLSX_ENTRIES = _positive_limit("MAX_XLSX_ENTRIES", 256)
MAX_XLSX_EXPANDED_BYTES = _positive_limit("MAX_XLSX_EXPANDED_BYTES", 40 * 1024 * 1024)
MAX_XLSX_ENTRY_BYTES = _positive_limit("MAX_XLSX_ENTRY_BYTES", 20 * 1024 * 1024)
MAX_XLSX_RATIO = _positive_limit("MAX_XLSX_RATIO", 1000)
MAX_EXPENSIVE_REQUESTS = _positive_limit("MAX_EXPENSIVE_REQUESTS", 1)
MAX_PRODUCTS_PER_OWNER = _positive_limit("MAX_PRODUCTS_PER_OWNER", 100)
MAX_COLLECTION_BYTES = _positive_limit("MAX_COLLECTION_BYTES", 2 * 1024 * 1024)
MAX_ANALYSIS_RUNS = _positive_limit("MAX_ANALYSIS_RUNS", 20)
PREVIEW_ROWS = 5

# Single-process fixed-window request budgets. No background cleanup or shared service.
_rate_enabled = os.getenv("RATE_LIMIT_ENABLED", "true").strip().lower()
if _rate_enabled not in {"true", "false", "1", "0"}:
    raise ValueError("RATE_LIMIT_ENABLED must be true/false or 1/0")
RATE_LIMIT_ENABLED = _rate_enabled in {"true", "1"}
RATE_LIMIT_WINDOW_SECONDS = _positive_limit("RATE_LIMIT_WINDOW_SECONDS", 60)
RATE_LIMIT_MAX_IDENTITIES = _positive_limit("RATE_LIMIT_MAX_IDENTITIES", 4096)
RATE_LIMIT_GLOBAL_REQUESTS = _positive_limit("RATE_LIMIT_GLOBAL_REQUESTS", 3000)
RATE_LIMIT_PEER_REQUESTS = _positive_limit("RATE_LIMIT_PEER_REQUESTS", 600)
RATE_LIMIT_GENERAL_REQUESTS = _positive_limit("RATE_LIMIT_GENERAL_REQUESTS", 120)
RATE_LIMIT_INGESTION_REQUESTS = _positive_limit("RATE_LIMIT_INGESTION_REQUESTS", 10)
RATE_LIMIT_ANALYSIS_REQUESTS = _positive_limit("RATE_LIMIT_ANALYSIS_REQUESTS", 10)
RATE_LIMIT_COLLECTION_REQUESTS = _positive_limit("RATE_LIMIT_COLLECTION_REQUESTS", 5)
RATE_LIMIT_EXPORT_REQUESTS = _positive_limit("RATE_LIMIT_EXPORT_REQUESTS", 10)
RATE_LIMIT_AI_REQUESTS = _positive_limit("RATE_LIMIT_AI_REQUESTS", 5)

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

# Optional AI-written overview (app/services/ai_summary.py). OFF unless AI_SUMMARIES=on.
# Runs only through a local Ollama server; no cloud or paid API is ever called.
AI_SUMMARIES_ENABLED = os.getenv("AI_SUMMARIES", "off").strip().lower() in ("on", "1", "true", "yes")
OLLAMA_URL = os.getenv("OLLAMA_URL", "http://127.0.0.1:11434").rstrip("/")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "llama3.2:3b")
OLLAMA_TIMEOUT_SECONDS = float(os.getenv("OLLAMA_TIMEOUT_SECONDS", "120"))

# Explicitly select JWT mode before hosted use. Local mode is restricted to loopback clients.
AUTH_MODE = os.getenv("AUTH_MODE", "local")
AUTH_ISSUER = os.getenv("AUTH_ISSUER", "")
AUTH_AUDIENCE = os.getenv("AUTH_AUDIENCE", "")
AUTH_ALGORITHM = os.getenv("AUTH_ALGORITHM", "ES256")
AUTH_JWKS_URL = os.getenv("AUTH_JWKS_URL", "")
AUTH_JWKS_FILE = os.getenv("AUTH_JWKS_FILE", "")  # public keys only; supports offline verification/testing
