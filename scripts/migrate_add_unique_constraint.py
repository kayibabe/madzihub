"""
migrate_add_unique_constraint.py
=================================
One-time migration: adds the DB-level unique constraint on
(zone, scheme, month, year) to an existing srwb.db.

Run from the project root:
    python scripts/migrate_add_unique_constraint.py

What this does
--------------
1. Scans for duplicate (zone, scheme, month, year) groups.
2. For each duplicate group, keeps the row with the highest `id`
   (most recently uploaded) and deletes the rest.
3. Creates a new `records` table with the UniqueConstraint baked in.
4. Copies the cleaned data across.
5. Drops the old table and renames the new one.

SQLite does not support ALTER TABLE ADD CONSTRAINT, so we use the
standard SQLite migration pattern: create-copy-drop-rename.

Safe to re-run — it checks whether the constraint already exists first.
"""
import os
import sys
import sqlite3

# ── Resolve DB path the same way the app does ────────────────
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH  = os.path.join(BASE_DIR, "data", "srwb.db")

if not os.path.exists(DB_PATH):
    print(f"Database not found: {DB_PATH}")
    print("Nothing to migrate — run the app once to create it first.")
    sys.exit(0)


def main():
    con = sqlite3.connect(DB_PATH)
    cur = con.cursor()

    # ── 1. Check if constraint already present ────────────────
    cur.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='records'")
    row = cur.fetchone()
    if row and "uq_zone_scheme_month_year" in (row[0] or ""):
        print("Unique constraint already present. Nothing to do.")
        con.close()
        return

    print("=== SRWB migration: adding unique constraint ===\n")

    # ── 2. Find and report duplicates ────────────────────────
    cur.execute("""
        SELECT zone, scheme, month, year, COUNT(*) AS cnt
        FROM   records
        GROUP  BY zone, scheme, month, year
        HAVING cnt > 1
    """)
    dupes = cur.fetchall()

    if dupes:
        print(f"Found {len(dupes)} duplicate group(s):")
        for z, s, m, y, c in dupes:
            print(f"  {z} / {s} / {m} / {y}  →  {c} rows (keeping newest)")
        print()

        # Keep the row with the highest id (last uploaded) per group
        cur.execute("""
            DELETE FROM records
            WHERE id NOT IN (
                SELECT MAX(id)
                FROM   records
                GROUP  BY zone, scheme, month, year
            )
        """)
        deleted = con.total_changes
        con.commit()
        print(f"Deleted {deleted} duplicate row(s).\n")
    else:
        print("No duplicate rows found.\n")

    # ── 3. Get current column definitions ────────────────────
    cur.execute("PRAGMA table_info(records)")
    cols = cur.fetchall()
    col_defs = []
    col_names = []
    for cid, name, typ, notnull, dflt, pk in cols:
        parts = [f'"{name}"', typ or "TEXT"]
        if pk:
            parts.append("PRIMARY KEY AUTOINCREMENT")
        if notnull and not pk:
            parts.append("NOT NULL")
        if dflt is not None:
            parts.append(f"DEFAULT {dflt}")
        col_defs.append(" ".join(parts))
        col_names.append(f'"{name}"')

    # ── 4. Rebuild table with the constraint ─────────────────
    col_block = ",\n    ".join(col_defs)
    create_sql = f"""
CREATE TABLE records_new (
    {col_block},
    CONSTRAINT uq_zone_scheme_month_year
        UNIQUE (zone, scheme, month, year)
)"""

    cur.execute(create_sql)

    col_list = ", ".join(col_names)
    cur.execute(f"""
        INSERT INTO records_new ({col_list})
        SELECT {col_list} FROM records
    """)

    cur.execute("DROP TABLE records")
    cur.execute("ALTER TABLE records_new RENAME TO records")

    # ── 5. Re-create index ────────────────────────────────────
    cur.execute("""
        CREATE INDEX IF NOT EXISTS ix_zone_scheme_month_year
        ON records (zone, scheme, month, year)
    """)

    con.commit()
    con.close()

    print("Migration complete.")
    print("The unique constraint uq_zone_scheme_month_year has been added.")
    print("\nNext step: restart the application.")


if __name__ == "__main__":
    main()
