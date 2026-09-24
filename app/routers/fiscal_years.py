"""
routers/fiscal_years.py  —  Multi-FY Configuration & Budget Admin
SRWB Southern Region Water Board

Public endpoints (any authenticated user):
  GET  /api/fiscal-years           — list all configured fiscal years
  GET  /api/fiscal-years/{year}    — single FY with full budget details

Admin endpoints (require admin role):
  POST /api/fiscal-years           — create a new FY
  PUT  /api/fiscal-years/{year}    — update FY metadata (status, tariff, notes)
  POST /api/fiscal-years/{year}/budget   — upsert budget lines for a FY
  POST /api/fiscal-years/{year}/zone-shares  — upsert zone shares for a FY
  POST /api/fiscal-years/{year}/spc          — upsert SPC limits for a FY
  POST /api/fiscal-years/{year}/copy-from/{source_year}
         — clone a prior year's budget as a planning baseline
         — accepts optional ?inflation_rate=0.08 to scale monetary values
"""
from __future__ import annotations
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Body, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.auth import require_admin
from app.utils import fy_label
from app.database import BudgetLine, BudgetZoneShare, FiscalYear, SpcLimit, get_db

router = APIRouter(prefix="/api/fiscal-years", tags=["Fiscal Years"])

# ── Helpers ────────────────────────────────────────────────────────────────────


def _fy_dates(year: int) -> tuple[str, str]:
    return (f"{year-1}-04-01", f"{year}-03-31")

def _fy_to_dict(fy: FiscalYear) -> dict:
    return {
        "year":         fy.year,
        "label":        fy.label,
        "start_date":   fy.start_date,
        "end_date":     fy.end_date,
        "status":       fy.status,
        "tariff_per_m3": fy.tariff_per_m3,
        "notes":        fy.notes,
        "created_at":   fy.created_at.isoformat() if fy.created_at else None,
        "updated_at":   fy.updated_at.isoformat() if fy.updated_at else None,
    }

# Monetary unit keywords — used by copy-from to decide what to inflate
_MONETARY_UNITS = {"MWK", "MWK/m3"}


# ── Public read endpoints ──────────────────────────────────────────────────────

@router.get("/", summary="List all configured fiscal years")
def list_fiscal_years(db: Session = Depends(get_db)):
    """
    Returns all configured fiscal years ordered by year (descending).
    Includes a `has_budget` flag and `budget_line_count` so the UI
    can indicate which future FYs still need budget data entered.
    """
    fys = db.query(FiscalYear).order_by(FiscalYear.year.desc()).all()

    # Count budget lines per year in one query
    from sqlalchemy import func
    counts = (db.query(BudgetLine.year, func.count().label("n"))
              .group_by(BudgetLine.year).all())
    count_map = {r.year: r.n for r in counts}

    zone_share_years = {r[0] for r in
                        db.query(BudgetZoneShare.year).distinct().all()}
    spc_years        = {r[0] for r in
                        db.query(SpcLimit.year).distinct().all()}

    result = []
    for fy in fys:
        d = _fy_to_dict(fy)
        d["budget_line_count"] = count_map.get(fy.year, 0)
        d["has_budget"]        = d["budget_line_count"] > 0
        d["has_zone_shares"]   = fy.year in zone_share_years
        d["has_spc_limits"]    = fy.year in spc_years
        result.append(d)

    return result


@router.get("/{year}", summary="Get a single fiscal year with full budget detail")
def get_fiscal_year(year: int, db: Session = Depends(get_db)):
    fy = db.query(FiscalYear).filter(FiscalYear.year == year).first()
    if not fy:
        raise HTTPException(status_code=404, detail=f"Fiscal year {year} not found")

    budget_lines = (db.query(BudgetLine)
                    .filter(BudgetLine.year == year)
                    .order_by(BudgetLine.category).all())

    zone_shares = (db.query(BudgetZoneShare)
                   .filter(BudgetZoneShare.year == year)
                   .order_by(BudgetZoneShare.zone).all())

    spc_limits  = (db.query(SpcLimit)
                   .filter(SpcLimit.year == year)
                   .order_by(SpcLimit.metric).all())

    return {
        **_fy_to_dict(fy),
        "budget_lines": [
            {"category": b.category, "value": b.value, "unit": b.unit, "notes": b.notes}
            for b in budget_lines
        ],
        "zone_shares": [
            {"zone": z.zone, "rev_share": z.rev_share,
             "vol_share": z.vol_share, "conn_share": z.conn_share}
            for z in zone_shares
        ],
        "spc_limits": [
            {"metric": s.metric, "mean": s.mean, "std": s.std,
             "ucl2": s.ucl2, "lcl2": s.lcl2, "ucl3": s.ucl3, "lcl3": s.lcl3}
            for s in spc_limits
        ],
    }


# ── Admin write endpoints ──────────────────────────────────────────────────────

@router.post("/", summary="Create a new fiscal year", dependencies=[Depends(require_admin)])
def create_fiscal_year(
    year: int          = Body(...),
    status: str        = Body(default="future"),
    tariff_per_m3: float | None = Body(default=None),
    notes: str | None  = Body(default=None),
    db: Session        = Depends(get_db),
):
    if db.query(FiscalYear).filter(FiscalYear.year == year).first():
        raise HTTPException(status_code=409, detail=f"Fiscal year {year} already exists")
    start, end = _fy_dates(year)
    fy = FiscalYear(
        year=year, label=fy_label(year),
        start_date=start, end_date=end,
        status=status, tariff_per_m3=tariff_per_m3, notes=notes,
    )
    db.add(fy)
    db.commit()
    db.refresh(fy)
    return _fy_to_dict(fy)


@router.put("/{year}", summary="Update FY metadata", dependencies=[Depends(require_admin)])
def update_fiscal_year(
    year: int,
    status: str | None        = Body(default=None),
    tariff_per_m3: float | None = Body(default=None),
    notes: str | None         = Body(default=None),
    db: Session               = Depends(get_db),
):
    fy = db.query(FiscalYear).filter(FiscalYear.year == year).first()
    if not fy:
        raise HTTPException(status_code=404, detail=f"Fiscal year {year} not found")
    if status is not None:
        fy.status = status
    if tariff_per_m3 is not None:
        fy.tariff_per_m3 = tariff_per_m3
    if notes is not None:
        fy.notes = notes
    fy.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(fy)
    return _fy_to_dict(fy)


@router.post("/{year}/budget",
             summary="Upsert budget lines for a fiscal year",
             dependencies=[Depends(require_admin)])
def upsert_budget_lines(
    year: int,
    lines: list[dict] = Body(..., examples=[[
        {"category": "water_sales", "value": 16_719_582_000, "unit": "MWK"},
        {"category": "vol_produced", "value": 15_883_399, "unit": "m3"},
    ]]),
    db: Session = Depends(get_db),
):
    """
    Upsert one or more budget line items for the given FY.
    Pass a list of `{category, value, unit?, notes?}` objects.
    Existing entries with the same category are updated; new ones are created.
    """
    if not db.query(FiscalYear).filter(FiscalYear.year == year).first():
        raise HTTPException(status_code=404, detail=f"Fiscal year {year} not found")

    upserted = 0
    for item in lines:
        cat = item.get("category")
        val = item.get("value")
        if not cat or val is None:
            continue
        existing = (db.query(BudgetLine)
                    .filter(BudgetLine.year == year, BudgetLine.category == cat)
                    .first())
        if existing:
            existing.value     = float(val)
            existing.unit      = item.get("unit", existing.unit)
            existing.notes     = item.get("notes", existing.notes)
            existing.updated_at = datetime.utcnow()
        else:
            db.add(BudgetLine(year=year, category=cat, value=float(val),
                              unit=item.get("unit"), notes=item.get("notes")))
        upserted += 1

    db.commit()
    return {"status": "ok", "upserted": upserted, "year": year}


@router.post("/{year}/zone-shares",
             summary="Upsert zone allocation shares",
             dependencies=[Depends(require_admin)])
def upsert_zone_shares(
    year: int,
    shares: list[dict] = Body(..., examples=[[
        {"zone": "Zomba",    "rev_share": 0.5651, "vol_share": 0.5111, "conn_share": 0.3558},
        {"zone": "Mangochi", "rev_share": 0.2115, "vol_share": 0.2077, "conn_share": 0.2881},
    ]]),
    db: Session = Depends(get_db),
):
    if not db.query(FiscalYear).filter(FiscalYear.year == year).first():
        raise HTTPException(status_code=404, detail=f"Fiscal year {year} not found")

    upserted = 0
    for item in shares:
        zone = item.get("zone")
        if not zone:
            continue
        existing = (db.query(BudgetZoneShare)
                    .filter(BudgetZoneShare.year == year,
                            BudgetZoneShare.zone == zone).first())
        if existing:
            existing.rev_share  = float(item.get("rev_share",  existing.rev_share))
            existing.vol_share  = float(item.get("vol_share",  existing.vol_share))
            existing.conn_share = float(item.get("conn_share", existing.conn_share))
            existing.updated_at = datetime.utcnow()
        else:
            db.add(BudgetZoneShare(
                year=year, zone=zone,
                rev_share=float(item.get("rev_share",  0)),
                vol_share=float(item.get("vol_share",  0)),
                conn_share=float(item.get("conn_share", 0)),
            ))
        upserted += 1

    db.commit()
    return {"status": "ok", "upserted": upserted, "year": year}


@router.post("/{year}/spc",
             summary="Upsert SPC limits for a fiscal year",
             dependencies=[Depends(require_admin)])
def upsert_spc_limits(
    year: int,
    limits: list[dict] = Body(..., examples=[[
        {"metric": "nrw_pct", "mean": 31.28, "std": 1.12,
         "ucl2": 33.52, "lcl2": 29.03, "ucl3": 34.65, "lcl3": 27.91},
    ]]),
    db: Session = Depends(get_db),
):
    if not db.query(FiscalYear).filter(FiscalYear.year == year).first():
        raise HTTPException(status_code=404, detail=f"Fiscal year {year} not found")

    upserted = 0
    for item in limits:
        metric = item.get("metric")
        if not metric:
            continue
        existing = (db.query(SpcLimit)
                    .filter(SpcLimit.year == year,
                            SpcLimit.metric == metric).first())
        fields = ["mean", "std", "ucl2", "lcl2", "ucl3", "lcl3"]
        if existing:
            for f in fields:
                if f in item:
                    setattr(existing, f, item[f])
            existing.updated_at = datetime.utcnow()
        else:
            db.add(SpcLimit(year=year, metric=metric,
                            **{f: item.get(f) for f in fields}))
        upserted += 1

    db.commit()
    return {"status": "ok", "upserted": upserted, "year": year}


@router.post("/{year}/copy-from/{source_year}",
             summary="Clone a prior year's budget as a planning baseline",
             dependencies=[Depends(require_admin)])
def copy_budget_from(
    year: int,
    source_year: int,
    inflation_rate: float = Query(
        default=0.0,
        description="Apply an inflation uplift to monetary MWK values (e.g. 0.08 = 8%). "
                    "Non-monetary values (m3, pct, hrs, km, count) are copied unchanged.",
    ),
    overwrite: bool = Query(
        default=False,
        description="If True, delete all existing budget data for target year first.",
    ),
    db: Session = Depends(get_db),
):
    """
    Copy budget lines, zone shares, and SPC limits from `source_year` into `year`.
    Ideal for setting up a new FY budget as an inflation-adjusted starting point.

    - `inflation_rate=0.08`  inflates all MWK budget lines by 8%
    - Non-monetary values (volumes, percentages, hours, km) are copied as-is
    - SPC limits and zone shares are always copied without adjustment
    - Use `overwrite=true` to replace existing target-year data
    """
    if not db.query(FiscalYear).filter(FiscalYear.year == year).first():
        raise HTTPException(status_code=404, detail=f"Target fiscal year {year} not found")
    if not db.query(FiscalYear).filter(FiscalYear.year == source_year).first():
        raise HTTPException(status_code=404, detail=f"Source fiscal year {source_year} not found")

    if overwrite:
        db.query(BudgetLine).filter(BudgetLine.year == year).delete()
        db.query(BudgetZoneShare).filter(BudgetZoneShare.year == year).delete()
        db.query(SpcLimit).filter(SpcLimit.year == year).delete()

    # Copy budget lines
    source_lines = db.query(BudgetLine).filter(BudgetLine.year == source_year).all()
    copied_lines = 0
    skipped_lines = 0
    for line in source_lines:
        existing = (db.query(BudgetLine)
                    .filter(BudgetLine.year == year,
                            BudgetLine.category == line.category).first())
        if existing and not overwrite:
            skipped_lines += 1
            continue
        multiplier = (1 + inflation_rate) if (
            line.unit in _MONETARY_UNITS or
            (line.unit and line.unit.startswith("MWK"))
        ) else 1.0
        db.add(BudgetLine(
            year=year, category=line.category,
            value=round(line.value * multiplier, 2),
            unit=line.unit, notes=line.notes,
        ))
        copied_lines += 1

    # Copy zone shares (unchanged)
    source_shares = db.query(BudgetZoneShare).filter(BudgetZoneShare.year == source_year).all()
    copied_shares = 0
    for share in source_shares:
        existing = (db.query(BudgetZoneShare)
                    .filter(BudgetZoneShare.year == year,
                            BudgetZoneShare.zone == share.zone).first())
        if existing and not overwrite:
            continue
        db.add(BudgetZoneShare(
            year=year, zone=share.zone,
            rev_share=share.rev_share, vol_share=share.vol_share,
            conn_share=share.conn_share,
        ))
        copied_shares += 1

    # Copy SPC limits (unchanged — FY-specific computation should replace these)
    source_spc = db.query(SpcLimit).filter(SpcLimit.year == source_year).all()
    copied_spc = 0
    for s in source_spc:
        existing = (db.query(SpcLimit)
                    .filter(SpcLimit.year == year,
                            SpcLimit.metric == s.metric).first())
        if existing and not overwrite:
            continue
        db.add(SpcLimit(
            year=year, metric=s.metric,
            mean=s.mean, std=s.std,
            ucl2=s.ucl2, lcl2=s.lcl2, ucl3=s.ucl3, lcl3=s.lcl3,
        ))
        copied_spc += 1

    db.commit()

    return {
        "status":        "ok",
        "target_year":   year,
        "source_year":   source_year,
        "inflation_rate": inflation_rate,
        "copied": {
            "budget_lines": copied_lines,
            "zone_shares":  copied_shares,
            "spc_limits":   copied_spc,
        },
        "skipped_budget_lines": skipped_lines,
    }
