"""PostgreSQL migration configuration and a strictly read-only startup gate."""
from pathlib import Path

from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import inspect


def alembic_config():
    return Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"))


def check_schema(engine):
    from . import models  # noqa: F401
    from .database import Base
    expected = set(ScriptDirectory.from_config(alembic_config()).get_heads())
    with engine.connect() as connection:
        current = set(MigrationContext.configure(connection).get_current_heads())
        reflection = inspect(connection)
        valid = current == expected and set(Base.metadata.tables).issubset(reflection.get_table_names())
        if valid:
            for name, table in Base.metadata.tables.items():
                columns = {c['name'] for c in reflection.get_columns(name)}
                if not set(table.columns.keys()).issubset(columns):
                    valid = False
                    break
        if not valid:
            raise RuntimeError("PostgreSQL schema is not current. Stop the app, back up the database, "
                               "then run: alembic -c alembic.ini upgrade head")
