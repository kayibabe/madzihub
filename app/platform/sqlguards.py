"""Database-level guards used by migrations.

``append_only(table)`` adds triggers that reject UPDATE and DELETE on a table, so
audit events, submitted updates and document versions stay immutable even if a
bug or a manual SQL session tries to change them. Supported on SQLite and
PostgreSQL. A later batch (table-rebuild) migration on such a table must call
``append_only`` again, because rebuilding a SQLite table drops its triggers.
"""
from __future__ import annotations

from alembic import op


def append_only(table: str) -> None:
    dialect = op.get_bind().dialect.name
    if dialect == "sqlite":
        for verb in ("UPDATE", "DELETE"):
            op.execute(f"CREATE TRIGGER IF NOT EXISTS {table}_no_{verb.lower()} BEFORE {verb} ON {table} "
                       f"BEGIN SELECT RAISE(ABORT, '{table} is append-only'); END;")
    elif dialect == "postgresql":
        op.execute("CREATE OR REPLACE FUNCTION madzi_append_only() RETURNS trigger AS $$ "
                   "BEGIN RAISE EXCEPTION '% is append-only', TG_TABLE_NAME; END; $$ LANGUAGE plpgsql;")
        op.execute(f"DROP TRIGGER IF EXISTS {table}_append_only ON {table};")
        op.execute(f"CREATE TRIGGER {table}_append_only BEFORE UPDATE OR DELETE ON {table} "
                   "FOR EACH ROW EXECUTE FUNCTION madzi_append_only();")


def drop_append_only(table: str) -> None:
    dialect = op.get_bind().dialect.name
    if dialect == "sqlite":
        for verb in ("update", "delete"):
            op.execute(f"DROP TRIGGER IF EXISTS {table}_no_{verb}")
    elif dialect == "postgresql":
        op.execute(f"DROP TRIGGER IF EXISTS {table}_append_only ON {table};")
