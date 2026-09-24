"""
tools/backfill_from_source.py
=============================
Surgical, ADDITIVE backfill of the records table from verified source
workbooks, using the canonical ExcelParser COLUMN_MAP (the same mapping the
live upload flow uses).

Why: the DB was originally seeded through scripts/import_data.py, whose
FIELD_MAP is incomplete (missing per-class stuck meters, ALL StuckM
CarriedFwd, per-class connections/billing, service charge breakdowns, pipe
size breakdowns, etc.). Those columns sit at 0 in the DB even though the
source Excel carries real values. This script fills ONLY the columns that are
currently 0/NULL in the DB with the non-zero source value, matched on
(zone, scheme, year, month_no). It never overwrites a non-zero DB value and
never deletes rows, so existing good data cannot regress.

Usage:
    python tools/backfill_from_source.py            # dry run (no writes)
    python tools/backfill_from_source.py --commit   # apply
"""
from __future__ import annotations
import argparse
import os
import sqlite3
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from app.services.excel_parser import ExcelParser  # noqa: E402

DB_PATH = r"D:\WebApps\opsapp\data\srwb.db"

# (source workbook, expected fiscal_year label for sanity reporting)
SOURCES = [
    (r"D:\WebApps\opsapp\dataupdater\RawData.xlsx", "FY2025/26"),
    (r"D:\WebApps\opsapp\dataupdater\RawData_updated.xlsx", "FY2026/27"),
]

IDENTITY = {"id", "zone", "scheme", "fiscal_year", "year", "month_no", "month", "quarter"}


def db_columns(conn) -> set[str]:
    return {r[1] for r in conn.execute("PRAGMA table_info(records)")}


def backfill(commit: bool) -> None:
    conn = sqlite3.connect(DB_PATH)
    cols = db_columns(conn)
    metric_cols = cols - IDENTITY

    grand_rows_matched = 0
    grand_cells_filled = 0
    per_col_filled: dict[str, int] = {}

    for src, fy in SOURCES:
        if not os.path.exists(src):
            print(f"!! missing source {src}; skipping")
            continue
        with open(src, "rb") as f:
            res = ExcelParser().parse(f, conn)
        rows_matched = 0
        cells_filled = 0
        for r in res.importable_rows:
            db_row = conn.execute(
                "SELECT * FROM records WHERE zone=? AND scheme=? AND year=? AND month_no=?",
                (r.zone, r.scheme, r.year, r.month),
            ).fetchone()
            if db_row is None:
                continue
            rows_matched += 1
            colnames = [d[0] for d in conn.execute(
                "SELECT * FROM records WHERE zone=? AND scheme=? AND year=? AND month_no=? LIMIT 1",
                (r.zone, r.scheme, r.year, r.month)).description]
            current = dict(zip(colnames, db_row))
            sets, params = [], []
            for col in metric_cols:
                src_val = r.metrics.get(col)
                if not isinstance(src_val, (int, float)) or src_val == 0:
                    continue
                cur_val = current.get(col)
                if cur_val in (None, 0, 0.0):
                    sets.append(f'"{col}"=?')
                    params.append(float(src_val))
                    per_col_filled[col] = per_col_filled.get(col, 0) + 1
                    cells_filled += 1
            if sets and commit:
                params.extend([r.zone, r.scheme, r.year, r.month])
                conn.execute(
                    f"UPDATE records SET {', '.join(sets)} "
                    f"WHERE zone=? AND scheme=? AND year=? AND month_no=?",
                    params,
                )
        print(f"{fy}: parsed={len(res.importable_rows)} matched={rows_matched} cells_to_fill={cells_filled}")
        grand_rows_matched += rows_matched
        grand_cells_filled += cells_filled

    if commit:
        conn.commit()
        print("\nCOMMITTED.")
    else:
        print("\nDRY RUN (no writes). Re-run with --commit to apply.")
    print(f"Total rows matched: {grand_rows_matched}  cells filled: {grand_cells_filled}")
    print("\nTop columns backfilled:")
    for col, n in sorted(per_col_filled.items(), key=lambda kv: -kv[1])[:40]:
        print(f"  {col:28s} {n}")
    conn.close()


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--commit", action="store_true")
    args = ap.parse_args()
    backfill(commit=args.commit)
