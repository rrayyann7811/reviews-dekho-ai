"""Database engine and session handling (SQLAlchemy 2.0 + SQLite)."""
from collections.abc import Iterator
from pathlib import Path

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker
from fastapi import Request

from . import config


class Base(DeclarativeBase):
    pass


def make_engine(url: str) -> Engine:
    if url.startswith("sqlite:///") and ":memory:" not in url:
        Path(url.removeprefix("sqlite:///")).parent.mkdir(parents=True, exist_ok=True)
    # check_same_thread=False: FastAPI may use a session from a different thread than the one that created it.
    engine = create_engine(url, connect_args={"check_same_thread": False} if url.startswith("sqlite") else {})

    if url.startswith("sqlite"):
        @event.listens_for(engine, "connect")
        def _on_connect(dbapi_connection, _record):
            # SQLite ignores foreign keys (and ON DELETE CASCADE) unless this is switched on.
            dbapi_connection.execute("PRAGMA foreign_keys=ON")
            # Let SQLAlchemy control transactions (see "begin" below) instead of the sqlite3 module.
            dbapi_connection.isolation_level = None

        @event.listens_for(engine, "begin")
        def _on_begin(connection):
            # Python's sqlite3 module does not put ALTER/CREATE inside a transaction by itself. Starting
            # every transaction explicitly makes schema migrations all-or-nothing too.
            connection.exec_driver_sql("BEGIN")

    return engine


engine = make_engine(config.DATABASE_URL)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def init_db(bind: Engine | None = None) -> None:
    """Create the tables, or upgrade an existing database without losing data."""
    from . import migrations, models  # noqa: F401  (models registers the tables on Base.metadata)

    migrations.upgrade(bind or engine)


def get_db(request: Request) -> Iterator[Session]:
    """FastAPI dependency: one session per request, always closed."""
    db = SessionLocal()
    principal = getattr(request.state, "principal", None)
    if principal is not None:
        db.info["principal"] = principal
    try:
        yield db
    finally:
        db.close()
