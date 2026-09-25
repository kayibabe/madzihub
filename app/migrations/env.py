"""Alembic environment: migrate the database the app itself is configured for.

The engine comes from app.database, so migrations always act on the same
DATABASE_URL (and the same SQLite pragmas) as the running app.
"""
from __future__ import annotations

from logging.config import fileConfig

from alembic import context
from sqlalchemy import text

from app.database import Base, engine
from app import model_registry as _models  # noqa: F401  (registers every table on Base)
from app.migrate import include_object

target_metadata = Base.metadata

# Developer CLI (`python -m alembic ...`) reads alembic.ini for logging; the app's
# programmatic runs (app.migrate) have no config file and keep the app's logging.
if context.config.config_file_name:
    fileConfig(context.config.config_file_name, disable_existing_loggers=False)


def _run(connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        render_as_batch=connection.dialect.name == "sqlite",  # SQLite ALTERs need table rebuilds
        compare_type=True,
        include_object=include_object,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connection = context.config.attributes.get("connection")
    if connection is not None:
        _run(connection)
        return
    with engine.connect() as connection:
        sqlite = connection.dialect.name == "sqlite"
        if sqlite:
            # Batch migrations drop and recreate tables; enforcing FKs mid-rebuild would fail or cascade.
            connection.execute(text("PRAGMA foreign_keys=OFF"))
            connection.commit()
        try:
            _run(connection)
        finally:
            if sqlite:
                connection.execute(text("PRAGMA foreign_keys=ON"))
                connection.commit()


if context.is_offline_mode():
    raise SystemExit("Offline (--sql) migrations are not supported; run against a database.")
run_migrations_online()
