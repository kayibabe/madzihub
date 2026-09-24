"""
scripts/seed_fiscal_years.py
============================
One-time (idempotent) migration that:

  1. Populates `fiscal_years` for FY2015/16 → FY2029/30
  2. Seeds `budget_lines` with the approved FY2025/26 figures
     (previously hardcoded in app/routers/budget.py)
  3. Seeds `budget_zone_shares` with the FY2025/26 IPSAS-18 allocation shares
  4. Seeds `spc_limits` with the FY2025/26 Shewhart ISO-7870-2 control limits

Safe to re-run: uses INSERT OR IGNORE (SQLite) so existing rows are untouched.

Usage
-----
    python scripts/seed_fiscal_years.py

To force a full refresh of FY2025/26 budget data:
    python scripts/seed_fiscal_years.py --refresh-fy 2026
"""
from __future__ import annotations
import argparse
import os
import sys
from datetime import datetime

# ── Make sure project root is on the path ──────────────────────
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from app.database import (
    Base, BudgetLine, BudgetZoneShare, FiscalYear, SpcLimit,
    SessionLocal, create_tables, engine,
)
from app.utils import fy_label

# ─────────────────────────────────────────────────────────────────────────────
# FY RANGE CONFIGURATION
# ─────────────────────────────────────────────────────────────────────────────
# All years here are the FY *end* year (e.g. 2026 = FY2025/26).
HISTORICAL_RANGE = range(2016, 2027)   # FY2015/16 → FY2025/26 (11 past years)
CURRENT_YEAR     = 2027                # FY2026/27
FUTURE_RANGE     = range(2028, 2031)   # FY2027/28 → FY2029/30

# The approved budget figures below belong to FY2025/26 (end-year 2026) and stay
# attached to that year regardless of which FY is "current". FY2026/27 onward have
# no approved budget yet (seed via the copy-year admin endpoint when available).
BUDGET_YEAR      = 2026                # FY2025/26 — owns the seeded budget data


def _fy_dates(year: int) -> tuple[str, str]:
    return (f"{year-1}-04-01", f"{year}-03-31")


# ─────────────────────────────────────────────────────────────────────────────
# FY2025/26 APPROVED BUDGET  (source: SRWB Draft Revenue & CapEx Budget)
# These are the exact values that were hardcoded in budget.py
# ─────────────────────────────────────────────────────────────────────────────
FY2026_BUDGET = [
    # category                   value              unit   notes
    ("tariff_per_m3",            1_450.0,           "MWK/m3", "Fixed tariff, no adjustment in FY"),
    # Revenue (Table 28)
    ("water_sales",              16_719_582_000,    "MWK",  "Table 28"),
    ("bottled_water",             8_881_488_000,    "MWK",  "Table 28 — no DB equivalent"),
    ("agency_reconnect",            158_494_000,    "MWK",  "Table 28"),
    ("meter_rental",                417_560_000,    "MWK",  "Table 28"),
    ("service_charges",             562_898_000,    "MWK",  "Table 28"),
    ("sundry",                      315_012_000,    "MWK",  "Table 28"),
    ("rental_income",                43_455_000,    "MWK",  "Table 28"),
    ("total_revenue",            27_198_591_000,    "MWK",  "Full P&L revenue"),
    # Plant & Vehicle Operating Costs (Table 29)
    ("mech_elec_spares",             93_429_000,    "MWK",  "Table 29"),
    ("plant_maint",                 265_363_000,    "MWK",  "Table 29"),
    ("electricity",               1_754_765_000,    "MWK",  "Table 29"),
    ("chemicals",                 1_057_349_000,    "MWK",  "Table 29"),
    ("bottled_prod",              3_539_978_000,    "MWK",  "Table 29 — no DB equiv"),
    ("fuel",                      1_317_750_000,    "MWK",  "Table 29"),
    ("office_equip",                 24_892_000,    "MWK",  "Table 29"),
    ("pipeline_maint",              879_633_000,    "MWK",  "Table 29"),
    ("mv_maint",                    379_475_000,    "MWK",  "Table 29"),
    ("water_purchases",              68_850_000,    "MWK",  "Table 29"),
    ("plant_veh_total",           9_381_484_000,    "MWK",  "Includes bottled water cost"),
    # Employee Costs (Table 29)
    ("salaries",                  5_112_490_000,    "MWK",  "Table 29"),
    ("wages",                       812_407_000,    "MWK",  "Table 29"),
    ("pension",                   1_042_202_000,    "MWK",  "Table 29"),
    ("life_cover",                  219_986_000,    "MWK",  "Table 29"),
    ("fbt",                         113_612_000,    "MWK",  "Table 29"),
    ("gratuity",                     21_593_000,    "MWK",  "Table 29"),
    ("overtime",                    414_317_000,    "MWK",  "Table 29"),
    ("medical",                     229_558_000,    "MWK",  "Table 29"),
    ("leave_grant",                  94_071_000,    "MWK",  "Table 29"),
    ("total_employee",            8_211_793_000,    "MWK",  "Table 29"),
    # Operating Costs (Table 29)
    ("security",                    651_398_000,    "MWK",  "Table 29"),
    ("subsistence",                 512_754_000,    "MWK",  "Table 29"),
    ("outsourced_mr",               329_982_000,    "MWK",  "Table 29"),
    ("printing_stat",               436_084_000,    "MWK",  "Table 29"),
    ("consulting",                  168_073_000,    "MWK",  "Table 29"),
    ("training",                    142_600_000,    "MWK",  "Table 29"),
    ("telephone",                   124_920_000,    "MWK",  "Table 29"),
    ("property_maint",              126_937_000,    "MWK",  "Table 29"),
    ("total_opex",                5_212_121_000,    "MWK",  "Table 29"),
    # Other Charges
    ("depreciation",              2_277_546_000,    "MWK",  "Table 29"),
    ("finance_costs",             2_066_088_000,    "MWK",  "Table 29"),
    ("total_other",               4_343_634_000,    "MWK",  "Table 29"),
    ("total_expenditure",        27_149_032_000,    "MWK",  "Table 29"),
    # Operational targets (Tables 31, 39)
    ("vol_produced",             15_883_399,        "m3",   "Table 31/39 annual target"),
    ("vol_sold",                 11_594_881,        "m3",   "Table 31/39 annual target"),
    ("nrw_pct",                          27.0,      "pct",  "Table 31/39 NRW target"),
    ("new_customers",                 8_588,        "count","Table 39"),
    ("active_customers",             89_824,        "count","Table 39 year-end target"),
    ("supply_hours",                     19.0,      "hrs",  "hrs/day target"),
    ("coverage_pct",                     86.0,      "pct",  "Table 39"),
    ("pipelines_km",                     85.63,     "km",   "Table 39 annual extension"),
]


FY2026_ZONE_SHARES = [
    # zone         rev_share   vol_share   conn_share
    ("Zomba",      0.5651,     0.5111,     0.3558),
    ("Mangochi",   0.2115,     0.2077,     0.2881),
    ("Liwonde",    0.0970,     0.1014,     0.1287),
    ("Ngabu",      0.0777,     0.0855,     0.0979),
    ("Mulanje",    0.0488,     0.0943,     0.1295),
]


FY2026_SPC = [
    # metric       mean          std         ucl2         lcl2         ucl3         lcl3
    ("nrw_pct",   31.28,        1.12,       33.52,       29.03,       34.65,       27.91),
    ("vol_prod",  1_205_597,    65_077,     1_335_751,   1_075_444,   1_400_827,   1_010_367),
    ("sales",     1_226_744_754,98_900_973, 1_424_547_700,1_028_942_809, None,     None),
    ("connections",669,         157,        983,         355,         1_140,       198),
    ("chems",     117_633_260,  14_907_267, 147_447_793, 87_818_726,  None,        None),
    ("power",     72_666_277,   3_983_747,  80_633_772,  64_698_783,  None,        None),
]


# ─────────────────────────────────────────────────────────────────────────────

def seed(refresh_fy: int | None = None):
    create_tables()
    db = SessionLocal()
    try:
        _seed_fiscal_years(db)
        _seed_fy2026_budget(db, refresh=refresh_fy == BUDGET_YEAR)
        _seed_fy2026_zone_shares(db, refresh=refresh_fy == BUDGET_YEAR)
        _seed_fy2026_spc(db, refresh=refresh_fy == BUDGET_YEAR)
        db.commit()
        print("[OK] Seed complete.")
    except Exception as e:
        db.rollback()
        print(f"[FAIL] Seed failed: {e}")
        raise
    finally:
        db.close()


def _seed_fiscal_years(db):
    """Insert fiscal year rows for all years in range (idempotent)."""
    years_to_add: list[dict] = []

    for y in HISTORICAL_RANGE:
        start, end = _fy_dates(y)
        years_to_add.append(dict(
            year=y, label=fy_label(y),
            start_date=start, end_date=end,
            status="historical", tariff_per_m3=None,
        ))

    start, end = _fy_dates(CURRENT_YEAR)
    years_to_add.append(dict(
        year=CURRENT_YEAR, label=fy_label(CURRENT_YEAR),
        start_date=start, end_date=end,
        status="current", tariff_per_m3=1_450.0,
        notes="Current FY — approved budget pending (seed via copy-year)",
    ))

    for y in FUTURE_RANGE:
        start, end = _fy_dates(y)
        years_to_add.append(dict(
            year=y, label=fy_label(y),
            start_date=start, end_date=end,
            status="future", tariff_per_m3=None,
            notes="Budget TBD — use copy-year to seed from prior FY",
        ))

    added = 0
    for row in years_to_add:
        existing = db.query(FiscalYear).filter(FiscalYear.year == row["year"]).first()
        if not existing:
            db.add(FiscalYear(**row))
            added += 1

    print(f"  fiscal_years: {added} rows inserted ({len(years_to_add)} configured).")


def _seed_fy2026_budget(db, refresh: bool = False):
    """Seed FY2025/26 budget lines (exact values from former hardcoded constants)."""
    if refresh:
        db.query(BudgetLine).filter(BudgetLine.year == BUDGET_YEAR).delete()
        print(f"  budget_lines: cleared FY{BUDGET_YEAR} for refresh.")

    added = 0
    for category, value, unit, notes in FY2026_BUDGET:
        existing = (db.query(BudgetLine)
                    .filter(BudgetLine.year == BUDGET_YEAR,
                            BudgetLine.category == category)
                    .first())
        if not existing:
            db.add(BudgetLine(year=BUDGET_YEAR, category=category,
                              value=value, unit=unit, notes=notes))
            added += 1

    print(f"  budget_lines (FY{BUDGET_YEAR}): {added} rows inserted.")


def _seed_fy2026_zone_shares(db, refresh: bool = False):
    if refresh:
        db.query(BudgetZoneShare).filter(BudgetZoneShare.year == BUDGET_YEAR).delete()

    added = 0
    for zone, rev, vol, conn in FY2026_ZONE_SHARES:
        existing = (db.query(BudgetZoneShare)
                    .filter(BudgetZoneShare.year == BUDGET_YEAR,
                            BudgetZoneShare.zone == zone)
                    .first())
        if not existing:
            db.add(BudgetZoneShare(year=BUDGET_YEAR, zone=zone,
                                   rev_share=rev, vol_share=vol, conn_share=conn))
            added += 1

    print(f"  budget_zone_shares (FY{BUDGET_YEAR}): {added} rows inserted.")


def _seed_fy2026_spc(db, refresh: bool = False):
    if refresh:
        db.query(SpcLimit).filter(SpcLimit.year == BUDGET_YEAR).delete()

    added = 0
    for metric, mean, std, ucl2, lcl2, ucl3, lcl3 in FY2026_SPC:
        existing = (db.query(SpcLimit)
                    .filter(SpcLimit.year == BUDGET_YEAR,
                            SpcLimit.metric == metric)
                    .first())
        if not existing:
            db.add(SpcLimit(year=BUDGET_YEAR, metric=metric,
                            mean=mean, std=std,
                            ucl2=ucl2, lcl2=lcl2, ucl3=ucl3, lcl3=lcl3))
            added += 1

    print(f"  spc_limits (FY{BUDGET_YEAR}): {added} rows inserted.")


# ─────────────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Seed multi-FY tables")
    parser.add_argument("--refresh-fy", type=int, default=None,
                        help="FY end-year to force-refresh budget data for (e.g. 2026)")
    args = parser.parse_args()
    seed(refresh_fy=args.refresh_fy)
