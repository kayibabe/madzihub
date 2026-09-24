"""
tools/backfill_historical.py
============================
Reverse-engineered, LABEL-ANCHORED backfill for the older fiscal years
(FY2023/24, FY2024/25) whose per-zone workbooks use a different row layout
than the FY2025/26 master the importer was built for.

Instead of fixed row indices (fragile across files), it locates each metric
by walking the sheet's label column and tracking the current section header
(STUCK METERS / SERVICE CHARGES / METER RENTAL / connection blocks). Within a
section the ordered sub-rows (New / Repaired / Replaced / Carried Forward /
Total Done) map to the four customer classes then the aggregate, in the order
they appear in the source template.

Writes are ADDITIVE: a DB cell is only filled when it is currently 0/NULL and
the source has a non-zero value, matched on (zone, scheme, year, month_no).
Existing non-zero data is never overwritten and no rows are deleted.

    python tools/backfill_historical.py                 # dry run + spot check
    python tools/backfill_historical.py --commit        # apply
"""
from __future__ import annotations
import argparse
import os
import sqlite3
import pandas as pd

DB_PATH = r"D:\WebApps\opsapp\data\srwb.db"
BASE = r"D:\WebApps\opsapp\dataupdater"
ZONES = ["Liwonde", "Mangochi", "Mulanje", "Ngabu", "Zomba"]
NON_DATA = {"Zone Monthly", "1st QTR", "2nd QTR ", "Midyear Summary", "3rd QTR", "4th QTR",
            "Zone Annual Summary", "Targets", "Budget", "ZA TH JA CALCULATION",
            "COST OF POWER", "WATER TARIFF"}
MONTH_NO = {"APRIL": 4, "MAY": 5, "JUNE": 6, "JULY": 7, "AUGUST": 8, "SEPTEMBER": 9,
            "OCTOBER": 10, "NOVEMBER": 11, "DECEMBER": 12, "JANUARY": 1, "FEBRUARY": 2, "MARCH": 3}
MONTH_NAME = {4: "April", 5: "May", 6: "June", 7: "July", 8: "August", 9: "September",
              10: "October", 11: "November", 12: "December", 1: "January", 2: "February", 3: "March"}

# Customer-class order as the rows appear within each section of the template.
CONN_CLASS_ORDER = ["indiv", "inst", "comm", "cwp", "all"]      # Total Done / Carried Fwd blocks
STUCK_CLASS_ORDER = ["inst", "comm", "cwp", "indiv", "all"]     # New/Repaired/Replaced/CF + header bfwd
CHARGE_CLASS_ORDER = ["individual", "cwp", "institutions", "commercial", "total"]


def norm(s):
    return str(s).strip().lower() if isinstance(s, str) and str(s).strip() else ""


def label_of(df, r):
    for c in range(min(3, df.shape[1])):
        v = df.iloc[r, c]
        if isinstance(v, str) and v.strip():
            return v.strip()
    return ""


def month_columns(df):
    """Return {col_index: month_no} by scanning the header row for month names."""
    cols = {}
    for r in range(min(12, df.shape[0])):
        for c in range(df.shape[1]):
            v = df.iloc[r, c]
            key = norm(v).upper()
            if key in MONTH_NO and c not in cols:
                cols[c] = MONTH_NO[key]
        if len(cols) >= 12:
            break
    return cols


def num(v):
    try:
        if pd.isna(v):
            return 0.0
    except Exception:
        pass
    if isinstance(v, str):
        v = v.strip().replace(",", "")
        if v == "":
            return 0.0
    try:
        return float(v)
    except Exception:
        return 0.0


def extract_sheet(df):
    """Return {month_no: {db_col: value}} for one scheme sheet."""
    mcols = month_columns(df)
    if not mcols:
        return {}
    out = {mn: {} for mn in mcols.values()}

    # Walk rows, tracking the active section.
    section = None
    conn_done_seen = 0       # count of "total done" rows within connections
    conn_cf_seen = 0
    stuck_blocks = {"new": 0, "repaired": 0, "replaced": 0, "carried forward": 0, "header": 0}

    def put(db_col, r):
        for c, mn in mcols.items():
            out[mn][db_col] = num(df.iloc[r, c])

    for r in range(df.shape[0]):
        lab = norm(label_of(df, r))
        if not lab:
            continue
        # Section transitions
        if "water connections and disconnections" in lab:
            section = "conn"; conn_done_seen = 0; conn_cf_seen = 0; continue
        if lab.startswith("prepaid metering") or "active and disconnected" in lab:
            if section == "conn":
                section = None
        if lab == "stuck meters":
            section = "stuck"; stuck_blocks = {k: 0 for k in stuck_blocks}; continue
        if lab.startswith("breakdown"):
            if section == "stuck":
                section = None
        if lab == "service charges":
            section = "svc"; continue
        if lab == "meter rental":
            section = "rental"; continue
        if lab in ("amount billed postpaid", "cash collected postpaid", "pipeline extensions"):
            section = None

        # Connections: ordered Total Done / Carried Forward rows = indiv,inst,comm,cwp,all
        if section == "conn":
            if lab == "total done" and conn_done_seen < len(CONN_CLASS_ORDER):
                cls = CONN_CLASS_ORDER[conn_done_seen]; conn_done_seen += 1
                col = "new_connections" if cls == "all" else f"conn_{cls}_total_done"
                put(col, r)
            elif lab == "carried forward" and conn_cf_seen < len(CONN_CLASS_ORDER):
                cls = CONN_CLASS_ORDER[conn_cf_seen]; conn_cf_seen += 1
                col = "all_conn_cfwd" if cls == "all" else f"conn_{cls}_cfwd"
                put(col, r)

        # Stuck meters: class header (brought-fwd) then New/Repaired/Replaced/Carried Forward
        elif section == "stuck":
            if lab.startswith("stuck master") or lab.startswith("stuck meters cwp") \
               or lab.startswith("stuck individual") or lab.startswith("aggregated stuck"):
                i = stuck_blocks["header"]
                if i < len(STUCK_CLASS_ORDER):
                    cls = STUCK_CLASS_ORDER[i]
                    col = "stuck_meters" if cls == "all" else f"stuck_{cls}_bfwd"
                    put(col, r)
                stuck_blocks["header"] += 1
            elif lab in ("new", "repaired", "replaced", "carried forward"):
                i = stuck_blocks[lab]
                if i < len(STUCK_CLASS_ORDER):
                    cls = STUCK_CLASS_ORDER[i]
                    suffix = {"new": "new", "repaired": "repaired", "replaced": "replaced", "carried forward": "cfwd"}[lab]
                    if cls == "all":
                        col = {"new": "stuck_new", "repaired": "stuck_repaired",
                               "replaced": "stuck_replaced", "cfwd": "all_stuck_cfwd"}[suffix]
                    else:
                        col = f"stuck_{cls}_{suffix}"
                    put(col, r)
                stuck_blocks[lab] += 1

        # Service charge / meter rental: labelled per class + total
        elif section == "svc":
            for cls in CHARGE_CLASS_ORDER:
                key = "total service charge" if cls == "total" else f"service charge {cls}"
                # commercial label has /industrial suffix
                if cls == "commercial" and lab.startswith("service charge commercial"):
                    put("service_charge_commercial", r)
                elif lab == key:
                    put("service_charge" if cls == "total" else f"service_charge_{cls}", r)
        elif section == "rental":
            if lab.startswith("total meter rental"):
                put("meter_rental", r)
            elif lab.startswith("meter rental commercial"):
                put("meter_rental_commercial", r)
            else:
                for cls in ("individual", "cwp", "institutions"):
                    if lab == f"meter rental {cls}":
                        put(f"meter_rental_{cls}", r)
    return out


IDENTITY_OK = {"new_connections", "all_conn_cfwd", "service_charge", "meter_rental"}


def run(commit: bool):
    fys = [
        (os.path.join(BASE, "FY2324"), 2024, "FY2023/24"),
        (os.path.join(BASE, "FY2425"), 2025, "FY2024/25"),
    ]
    conn = sqlite3.connect(DB_PATH)
    db_cols = {r[1] for r in conn.execute("PRAGMA table_info(records)")}

    total_rows = total_cells = 0
    spot = []
    for folder, end_year, fy in fys:
        fy_rows = fy_cells = 0
        for zone in ZONES:
            zpath = os.path.join(folder, f"{zone}.xlsx")
            if not os.path.exists(zpath):
                print("  missing", zpath); continue
            xl = pd.ExcelFile(zpath)
            for sheet in xl.sheet_names:
                if sheet in NON_DATA:
                    continue
                df = pd.read_excel(zpath, sheet_name=sheet, header=None)
                per_month = extract_sheet(df)
                for mn, metrics in per_month.items():
                    metrics = {k: v for k, v in metrics.items() if k in db_cols and isinstance(v, (int, float)) and v != 0}
                    if not metrics:
                        continue
                    year = end_year - 1 if mn >= 4 else end_year
                    row = conn.execute(
                        "SELECT * FROM records WHERE zone=? AND scheme=? AND year=? AND month_no=?",
                        (zone, sheet, year, mn)).fetchone()
                    if row is None:
                        continue
                    colnames = [d[0] for d in conn.execute(
                        "SELECT * FROM records WHERE zone=? AND scheme=? AND year=? AND month_no=? LIMIT 1",
                        (zone, sheet, year, mn)).description]
                    current = dict(zip(colnames, row))
                    sets, params = [], []
                    for col, val in metrics.items():
                        if current.get(col) in (None, 0, 0.0):
                            sets.append(f'"{col}"=?'); params.append(float(val))
                    if not sets:
                        continue
                    fy_rows += 1; fy_cells += len(sets)
                    if len(spot) < 6 and zone == "Liwonde":
                        spot.append((fy, zone, sheet, MONTH_NAME[mn],
                                     {c: metrics.get(c) for c in ("all_stuck_cfwd", "service_charge", "new_connections", "conn_indiv_total_done") if c in metrics}))
                    if commit:
                        params += [zone, sheet, year, mn]
                        conn.execute(f"UPDATE records SET {', '.join(sets)} WHERE zone=? AND scheme=? AND year=? AND month_no=?", params)
        print(f"{fy}: rows touched={fy_rows} cells filled={fy_cells}")
        total_rows += fy_rows; total_cells += fy_cells

    print("\nSpot check (Liwonde):")
    for s in spot:
        print("  ", s)
    if commit:
        conn.commit(); print("\nCOMMITTED.")
    else:
        print("\nDRY RUN — re-run with --commit to apply.")
    print(f"Total rows touched={total_rows} cells filled={total_cells}")
    conn.close()


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--commit", action="store_true")
    run(ap.parse_args().commit)
