"""Vercel's FastAPI entrypoint. Local development uses app.main:app."""

from urllib.parse import urlsplit

try:
    from app import config

    database = urlsplit(config.DATABASE_URL)
    if (not config.PUBLIC_DEMO or config.DB_POOL_MODE != "null"
            or not (database.hostname or "").endswith(".pooler.supabase.com")
            or database.port != 6543 or not database.username or not database.password
            or database.path in {"", "/"}):
        raise ValueError("Hosted profile or pooler configuration is invalid")

    from app.main import app  # noqa: F401
except Exception:
    raise RuntimeError("Hosted configuration could not initialize. Check the showcase environment and pooler settings.") from None
