"""Explicit PostgreSQL migrations only; never point this runner at an existing SQLite database."""
import os
from contextlib import nullcontext

from alembic import context
from sqlalchemy.engine import make_url

from app.database import make_engine

cfg = context.config
connection = cfg.attributes.get("connection")
url = os.getenv("DATABASE_URL", "")
if connection is None and (not url or make_url(url).get_backend_name() not in {"postgres", "postgresql"}):
    raise RuntimeError("Alembic requires an explicit PostgreSQL DATABASE_URL; SQLite uses app.migrations")


def run(connection):
    if connection.dialect.name != "postgresql":
        raise RuntimeError("This Alembic history targets PostgreSQL only")
    # A single migration transaction; failed DDL must not advance alembic_version.
    with (nullcontext() if connection.in_transaction() else connection.begin()):
        context.configure(connection=connection, on_version_apply=cfg.attributes.get("on_version_apply"))
        # Serialize explicit operators; not a scheduler or an application-startup migration.
        connection.exec_driver_sql("SELECT pg_advisory_xact_lock(829314201)")
        context.run_migrations()


if context.is_offline_mode():
    context.configure(dialect_name="postgresql", literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()
elif connection is not None:
    run(connection)
else:
    engine = make_engine(url)
    try:
        with engine.connect() as conn:
            run(conn)
    finally:
        engine.dispose()
