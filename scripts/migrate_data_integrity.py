"""
scripts/migrate_data_integrity.py
──────────────────────────────────
Applies the data-integrity changes from the Phase 1 audit to the
live SQLite database without requiring a full table rebuild.

What it does
────────────
1. Creates the composite index `ix_record_year_month` on (year, month_no)
   if it does not already exist. This is the main performance win — the
   FY-span OR filter can now use this index instead of a full-table scan.

2. Reports on the Numeric(15, 2) column-type declarations in the ORM model.
   SQLite does not enforce column type affinity after creation, so existing
   REAL columns continue to work correctly. The model change ensures:
     a) New databases are created with NUMERIC affinity from day one.
     b) The PostgreSQL migration path will use DECIMAL(15,2) correctly.
     c) The intent is documented in the schema for future Alembic migrations.

Usage
─────
    cd D:\\WebApps\\opsapp
    python scripts/migrate_data_integrity.py
"""
from __future__ import annotations

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.chdir(ROOT)

from sqlalchemy import inspect, text
from app.database import engine, Record, BudgetLine

NUMERIC_COLS = [
    c.name for c in Record.__table__.columns
    if hasattr(c.type, "precision")          # all Numeric(15,2) columns
]


def main() -> None:
    with engine.connect() as conn:
        inspector = inspect(engine)

        # ── 1. Composite index ────────────────────────────────────────────────
        existing_indexes = {
            idx["name"]
            for idx in inspector.get_indexes("records")
        }

        if "ix_record_year_month" in existing_indexes:
            print("✓  ix_record_year_month already exists — no action needed.")
        else:
            print("   Creating ix_record_year_month ON records(year, month_no)…")
            conn.execute(text(
                "CREATE INDEX ix_record_year_month ON records (year, month_no)"
            ))
            conn.commit()
            print("✓  ix_record_year_month created.")

        # ── 2. Numeric column report ──────────────────────────────────────────
        print()
        print(f"   ORM model declares {len(NUMERIC_COLS)} Numeric(15,2) columns on Record:")
        for col in NUMERIC_COLS:
            print(f"     • {col}")

        print()
        print("   Note: SQLite cannot ALTER COLUMN TYPE on existing tables.")
        print("   Existing REAL values are read and stored correctly by SQLAlchemy.")
        print("   Run Alembic (or pg_dump + restore) when migrating to PostgreSQL")
        print("   to materialise DECIMAL(15,2) affinity on those columns.")

        # Verify budget_lines.value
        bl_cols = {
            col["name"]: col
            for col in inspector.get_columns("budget_lines")
        }
        if "value" in bl_cols:
            print()
            print(f"   budget_lines.value affinity in SQLite: {bl_cols['value']['type']}")
            print("   (ORM model now declares Numeric(15,2) — applies to new DBs and PostgreSQL.)")


if __name__ == "__main__":
    main()
    print()
    print("Migration complete.")
