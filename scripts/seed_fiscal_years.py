"""
scripts/seed_fiscal_years.py
============================
Idempotent seed for the multi-FY tables, driven by the tenant's
``tenants/<tenant>/budget.yaml``:

  1. Registers fiscal years (``fiscal_years``) for the configured range
  2. Seeds ``budget_lines`` for each fiscal year listed under ``budgets``
  3. Seeds ``budget_zone_shares`` (IPSAS-18 allocation shares)
  4. Seeds ``spc_limits`` (Shewhart ISO-7870-2 control limits)

Existing rows are left untouched unless ``--refresh-fy`` names that year.
A tenant without budget.yaml gets no fiscal years; add them in
Administration → Fiscal Years instead.

Usage
-----
    python scripts/seed_fiscal_years.py
    python scripts/seed_fiscal_years.py --refresh-fy 2026

budget.yaml layout (all years are FY *end* years)
-------------------------------------------------
    fiscal_years: {first: 2022, current: 2027, last: 2030}
    budgets:
      2026:
        tariff_per_m3: 1.15
        lines:       [{category: water_sales, value: 4800000, notes: "..."}]
        zone_shares: [{zone: North, rev_share: 0.45, vol_share: 0.42, conn_share: 0.40}]
        spc:         [{metric: nrw_pct, mean: 30.1, std: 1.2, ucl2: 32.5, lcl2: 27.7}]

Budget-line ``unit`` defaults to the tenant currency code, so monetary lines
need no unit; give volumes, percentages and counts an explicit one.
"""
from __future__ import annotations

import argparse
import os
import sys

# ── Make sure project root is on the path ──────────────────────
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import yaml  # noqa: E402

from app.core.tenant import tenant  # noqa: E402
from app.database import (  # noqa: E402
    BudgetLine, BudgetZoneShare, FiscalYear, SessionLocal, SpcLimit, create_tables,
)
from app.utils import fy_dates, fy_label  # noqa: E402

SPC_FIELDS = ("mean", "std", "ucl2", "lcl2", "ucl3", "lcl3")


def load_budget_config() -> dict:
    path = tenant.folder / "budget.yaml" if tenant.folder else None
    if not path or not path.exists():
        return {}
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def seed(refresh_fy: int | None = None):
    cfg = load_budget_config()
    if not cfg:
        print(f"[SKIP] No budget.yaml for tenant '{tenant.key}'; nothing to seed.")
        return
    create_tables()
    db = SessionLocal()
    try:
        budgets = {int(y): b or {} for y, b in (cfg.get("budgets") or {}).items()}
        _seed_fiscal_years(db, cfg.get("fiscal_years") or {}, budgets)
        # Budget rows reference fiscal_years.year; without an ORM relationship the flush
        # order is not guaranteed, so write the parent rows first (foreign keys are enforced).
        db.flush()
        for year, budget in sorted(budgets.items()):
            refresh = refresh_fy == year
            lines = list(budget.get("lines") or [])
            if budget.get("tariff_per_m3") is not None:
                # Also a budget line, so copy-from carries (and inflates) it into new years.
                lines.append({"category": "tariff_per_m3", "value": budget["tariff_per_m3"],
                              "unit": f"{tenant.currency.code}/m3", "notes": "Tariff per m³"})
            _seed_budget_lines(db, year, lines, refresh)
            _seed_zone_shares(db, year, budget.get("zone_shares") or [], refresh)
            _seed_spc(db, year, budget.get("spc") or [], refresh)
        db.commit()
        print("[OK] Seed complete.")
    except Exception as e:
        db.rollback()
        print(f"[FAIL] Seed failed: {e}")
        raise
    finally:
        db.close()


def _seed_fiscal_years(db, fy_cfg: dict, budgets: dict[int, dict]):
    """Insert fiscal year rows for the configured range (idempotent)."""
    years = set(budgets)
    if fy_cfg.get("first") and fy_cfg.get("last"):
        years |= set(range(int(fy_cfg["first"]), int(fy_cfg["last"]) + 1))
    current = int(fy_cfg["current"]) if fy_cfg.get("current") else None

    added = 0
    for y in sorted(years):
        if db.query(FiscalYear).filter(FiscalYear.year == y).first():
            continue
        start, end = fy_dates(y)
        status = ("current" if y == current else
                  "future" if current is not None and y > current else "historical")
        db.add(FiscalYear(
            year=y, label=fy_label(y), start_date=start, end_date=end, status=status,
            tariff_per_m3=(budgets.get(y) or {}).get("tariff_per_m3"),
            notes=None if y in budgets else "Budget not loaded yet",
        ))
        added += 1
    print(f"  fiscal_years: {added} rows inserted ({len(years)} configured).")


def _seed_budget_lines(db, year: int, lines: list[dict], refresh: bool):
    if refresh:
        db.query(BudgetLine).filter(BudgetLine.year == year).delete()
        print(f"  budget_lines: cleared FY{year} for refresh.")
    added = 0
    for line in lines:
        cat = line["category"]
        if db.query(BudgetLine).filter(BudgetLine.year == year, BudgetLine.category == cat).first():
            continue
        db.add(BudgetLine(year=year, category=cat, value=float(line["value"]),
                          unit=line.get("unit", tenant.currency.code), notes=line.get("notes")))
        added += 1
    print(f"  budget_lines (FY{year}): {added} rows inserted.")


def _seed_zone_shares(db, year: int, shares: list[dict], refresh: bool):
    if refresh:
        db.query(BudgetZoneShare).filter(BudgetZoneShare.year == year).delete()
    added = 0
    for s in shares:
        if db.query(BudgetZoneShare).filter(BudgetZoneShare.year == year,
                                            BudgetZoneShare.zone == s["zone"]).first():
            continue
        db.add(BudgetZoneShare(year=year, zone=s["zone"], rev_share=s["rev_share"],
                               vol_share=s["vol_share"], conn_share=s["conn_share"]))
        added += 1
    print(f"  budget_zone_shares (FY{year}): {added} rows inserted.")


def _seed_spc(db, year: int, limits: list[dict], refresh: bool):
    if refresh:
        db.query(SpcLimit).filter(SpcLimit.year == year).delete()
    added = 0
    for s in limits:
        if db.query(SpcLimit).filter(SpcLimit.year == year, SpcLimit.metric == s["metric"]).first():
            continue
        db.add(SpcLimit(year=year, metric=s["metric"], **{f: s.get(f) for f in SPC_FIELDS}))
        added += 1
    print(f"  spc_limits (FY{year}): {added} rows inserted.")


# ─────────────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Seed multi-FY tables from the tenant budget.yaml")
    parser.add_argument("--refresh-fy", type=int, default=None,
                        help="FY end-year whose budget data is replaced from budget.yaml (e.g. 2026)")
    args = parser.parse_args()
    seed(refresh_fy=args.refresh_fy)
