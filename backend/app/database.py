"""SQLAlchemy sessions: SQLite locally, explicit migrations for PostgreSQL."""
from collections.abc import Iterator
from pathlib import Path

from sqlalchemy import create_engine, event, inspect
from sqlalchemy.engine import Engine
from sqlalchemy.engine import make_url
from sqlalchemy.pool import NullPool
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker
from fastapi import Request

from . import config


class Base(DeclarativeBase):
    pass


def make_engine(url: str) -> Engine:
    parsed = make_url(url)
    if parsed.drivername in {"postgres", "postgresql"}:
        parsed = parsed.set(drivername="postgresql+psycopg")
    if parsed.drivername not in {"sqlite", "sqlite+pysqlite", "postgresql+psycopg"}:
        raise ValueError("DATABASE_URL must use SQLite or postgresql+psycopg")
    sqlite = parsed.get_backend_name() == "sqlite"
    if sqlite and parsed.database and parsed.database != ":memory:":
        Path(parsed.database).parent.mkdir(parents=True, exist_ok=True)
    # check_same_thread=False: FastAPI may use a session from a different thread than the one that created it.
    options = {"hide_parameters": True, "pool_pre_ping": True}
    if sqlite:
        options["connect_args"] = {"check_same_thread": False}
    else:
        if set(parsed.query) - {"sslmode", "sslrootcert", "sslcert", "sslkey", "application_name", "channel_binding"}:
            raise ValueError("Unsupported PostgreSQL URL options; configure pooling/timeouts through DB_* settings")
        if (config.DB_POOL_MODE not in {"queue", "null"} or config.DB_POOL_SIZE < 1
                or config.DB_MAX_OVERFLOW < 0 or min(config.DB_POOL_TIMEOUT, config.DB_CONNECT_TIMEOUT,
                    config.DB_STATEMENT_TIMEOUT_MS, config.DB_LOCK_TIMEOUT_MS) < 1):
            raise ValueError("Invalid PostgreSQL connection/pool limits")
        args = {"connect_timeout": config.DB_CONNECT_TIMEOUT, "prepare_threshold": None}
        session_options = (f"-c timezone=UTC -c statement_timeout={config.DB_STATEMENT_TIMEOUT_MS} "
                           f"-c lock_timeout={config.DB_LOCK_TIMEOUT_MS}")
        if not config.PUBLIC_DEMO:
            args["options"] = session_options
        if parsed.host not in {None, "localhost", "127.0.0.1", "::1"}:
            if parsed.query.get("sslmode", "verify-full") != "verify-full":
                raise ValueError("Remote PostgreSQL requires sslmode=verify-full")
            args["sslmode"] = "verify-full"
        options["connect_args"] = args
        if config.DB_POOL_MODE == "null":
            options["poolclass"] = NullPool
        else:
            options.update(pool_size=config.DB_POOL_SIZE, max_overflow=config.DB_MAX_OVERFLOW,
                           pool_timeout=config.DB_POOL_TIMEOUT, pool_recycle=300)
    engine = create_engine(parsed, **options)

    if not sqlite and config.PUBLIC_DEMO:
        # Supavisor can assign a different server connection to each transaction.
        @event.listens_for(engine, "begin")
        def _hosted_transaction(connection):
            connection.exec_driver_sql(
                "SELECT set_config('timezone', 'UTC', true), "
                "set_config('statement_timeout', %s, true), set_config('lock_timeout', %s, true)",
                (str(config.DB_STATEMENT_TIMEOUT_MS), str(config.DB_LOCK_TIMEOUT_MS)),
            )

    if sqlite:
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
            mode = connection.get_execution_options().get("sqlite_begin_mode", "DEFERRED")
            if mode not in {"DEFERRED", "IMMEDIATE"}:
                raise ValueError("Unsupported SQLite transaction mode")
            connection.exec_driver_sql("BEGIN IMMEDIATE" if mode == "IMMEDIATE" else "BEGIN")

    return engine


engine = make_engine(config.DATABASE_URL)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def init_db(bind: Engine | None = None) -> None:
    """Initialize an empty SQLite file; existing schemas require an explicit operator migration."""
    from . import migrations, models  # noqa: F401  (models registers the tables on Base.metadata)

    target = bind or engine
    if target.dialect.name == "sqlite":
        with target.connect() as conn:
            tables = set(inspect(conn).get_table_names())
            version = migrations.get_version(conn)
        if tables and (version != migrations.LATEST_VERSION or not set(Base.metadata.tables).issubset(tables)):
            raise RuntimeError("SQLite schema is not current. Stop the app, back up the file, then run "
                               "scripts/migrate_sqlite.py with the intended DATABASE_URL.")
        migrations.upgrade(target)
    else:
        from .postgres_migrations import check_schema
        check_schema(target)  # read-only; PostgreSQL migrations are never run at startup


def get_db(request: Request) -> Iterator[Session]:
    """FastAPI dependency: one session per request, always closed."""
    db = SessionLocal()
    principal = getattr(request.state, "principal", None)
    if principal is not None:
        db.info["principal"] = principal
    db.info["write_request"] = request.method in {"POST", "PATCH", "DELETE", "PUT"}
    try:
        yield db
    finally:
        db.close()
