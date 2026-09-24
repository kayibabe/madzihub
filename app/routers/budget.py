"""
routers/budget.py  —  Comprehensive Budget vs Actuals Variance Engine
Multi-FY  |  SRWB Southern Region Water Board

ANALYTICAL FRAMEWORK:
  Revenue Decomposition:  tariff is loaded per-FY from `fiscal_years` table,
    so 100% of revenue variance = volume variance × tariff (IWA Op23 / IBNET).
  Zone Budgets:  IPSAS 18 segment allocation from `budget_zone_shares` table
    (revenue share for revenue; volume share for costs/production).
  Statistical Process Control:  ISO 7870-2 Shewhart X-bar limits (2σ/3σ)
    loaded from `spc_limits` table per FY.
  Budget Performance Index:  adapted from EVM — Actual÷Budget (>1 favourable
    for revenue/volume; Budget÷Actual for costs).
  Scheme Scoring:  composite of NRW, collection rate, revenue/m³, connections.

All monetary values: MWK.
Budget figures are loaded dynamically from the database; add a new FY via the
  /api/fiscal-years  admin endpoints or the seed script.
"""
from __future__ import annotations
import statistics
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from sqlalchemy import func, and_, or_
from app.database import (
    BudgetLine, BudgetZoneShare, FiscalYear, Record, SpcLimit, get_db,
)
from app.utils import MONTHS_LBL

router = APIRouter(prefix="/api/budget", tags=["Budget"])


def safe_div(numerator, denominator, default=0.0):
    """
    Division with zero-denominator protection.
    Returns `default` (0.0 unless overridden) when denominator is falsy
    (zero, None, or any other falsy value), preventing ZeroDivisionError
    and NaN propagation through budget calculations.

    Examples:
        safe_div(120, 12)       → 10.0
        safe_div(120, 0)        → 0.0
        safe_div(120, 0, None)  → None   (use for "no data" semantics)
        safe_div(120, None)     → 0.0
    """
    return numerator / denominator if denominator else default

# ── Month helpers ─────────────────────────────────────────────────────────────
FY_MNO     = [4,5,6,7,8,9,10,11,12,1,2,3]
MONTH_NAME_TO_NO = {
    "april": 4, "apr": 4,
    "may": 5,
    "june": 6, "jun": 6,
    "july": 7, "jul": 7,
    "august": 8, "aug": 8,
    "september": 9, "sep": 9, "sept": 9,
    "october": 10, "oct": 10,
    "november": 11, "nov": 11,
    "december": 12, "dec": 12,
    "january": 1, "jan": 1,
    "february": 2, "feb": 2,
    "march": 3, "mar": 3,
}

def _fy_idx(yr, mno): return mno - 4 if mno >= 4 else mno + 8

def _csv_items(raw: str | None) -> list[str]:
    if not raw:
        return []
    return [item.strip() for item in raw.split(",") if item and item.strip()]

def _normalize_month_tokens(months_raw: str | None) -> list[int]:
    selected = []
    for token in _csv_items(months_raw):
        month_no = MONTH_NAME_TO_NO.get(token.lower())
        if month_no and month_no not in selected:
            selected.append(month_no)
    return selected

def _fy_scope_expr(year: int, selected_months: list[int] | None = None):
    months = selected_months or []
    if not months:
        return or_(
            and_(Record.year == year - 1, Record.month_no >= 4),
            and_(Record.year == year, Record.month_no <= 3),
        )
    parts = []
    for month_no in months:
        scope_year = year - 1 if month_no >= 4 else year
        parts.append(and_(Record.year == scope_year, Record.month_no == month_no))
    return or_(*parts)

def _var(metric, actual, budget, unit="MWK", invert=False, scope="full", note="", iwa_pi=""):
    v = actual - budget
    vpct = (v / budget * 100) if budget else None
    if abs(vpct or 0) < 2:   direction = "on_budget"
    elif invert:              direction = "favourable" if v < 0 else "adverse"
    else:                     direction = "favourable" if v > 0 else "adverse"
    return {
        "metric": metric, "actual": round(actual, 2),
        "budget_ytd": round(budget, 2),
        "variance": round(v, 2),
        "variance_pct": round(vpct, 1) if vpct is not None else None,
        "direction": direction, "unit": unit,
        "scope": scope, "note": note, "iwa_pi": iwa_pi,
    }


# ── Budget data loader ────────────────────────────────────────────────────────

def _load_budget(year: int, db: Session) -> dict:
    """
    Load all budget data for a given FY end-year from the database.
    Returns a dict with keys matching the old BUD_* Python constants.
    Falls back gracefully with zeros / None when data is absent.
    """
    rows = (db.query(BudgetLine)
            .filter(BudgetLine.year == year)
            .all())

    bud: dict[str, float] = {r.category: (r.value if r.value is not None else 0.0) for r in rows}

    # --- Derived composites (mirror the old constant relationships) ----------
    bud.setdefault("plant_veh_field",
                   bud.get("plant_veh_total", 0) - bud.get("bottled_prod", 0))

    return bud


def _load_zone_shares(year: int, db: Session) -> tuple[dict, dict, dict]:
    """Load ZONE_REV_SHARE, ZONE_VOL_SHARE, ZONE_CONN_SHARE for the given year."""
    rows = (db.query(BudgetZoneShare)
            .filter(BudgetZoneShare.year == year)
            .all())
    rev  = {r.zone: r.rev_share  for r in rows}
    vol  = {r.zone: r.vol_share  for r in rows}
    conn = {r.zone: r.conn_share for r in rows}
    return rev, vol, conn


def _load_spc(year: int, db: Session) -> dict:
    """Load SPC limits dict keyed by metric name."""
    rows = (db.query(SpcLimit)
            .filter(SpcLimit.year == year)
            .all())
    return {
        r.metric: {
            "mean": r.mean, "std": r.std,
            "ucl2": r.ucl2, "lcl2": r.lcl2,
            "ucl3": r.ucl3, "lcl3": r.lcl3,
        }
        for r in rows
    }


def _load_tariff(year: int, bud: dict, db: Session) -> float:
    """
    Tariff resolution order:
    1. budget_lines.category='tariff_per_m3' for this year
    2. fiscal_years.tariff_per_m3
    3. Hard fallback 1450 (base rate; log a warning)
    """
    if "tariff_per_m3" in bud:
        return bud["tariff_per_m3"]
    fy = db.query(FiscalYear).filter(FiscalYear.year == year).first()
    if fy and fy.tariff_per_m3:
        return fy.tariff_per_m3
    return 1_450.0   # last-resort fallback


# ── Main variance endpoint ─────────────────────────────────────────────────────

def _cs(col):
    """SUM(col) coalesced to 0, so a group whose values are all NULL yields 0
    instead of None (which would crash the downstream round() calls)."""
    return func.coalesce(func.sum(col), 0)


def _latest_active_customers(scope_filters, db, fy_filters=None):
    """Active customers is a stock snapshot recorded in only one month and
    left blank/zero afterwards. Sum each (zone, scheme)'s latest NON-ZERO
    value so the balance is not lost when the most recent month carries no
    fresh snapshot (which previously yielded 0 — or NULL, crashing round()).

    ``fy_filters`` (full fiscal-year scope, same zone/scheme but no month
    filter) lets a month-filtered window that excludes the snapshot month
    fall back to the latest non-zero balance from the whole FY, so e.g.
    filtering to March doesn't drop the customer base to 0.
    Returns (per_zone: dict, per_scheme: dict, total: float)."""
    def _scan(filters):
        rows = (db.query(Record.zone, Record.scheme, Record.year,
                         Record.month_no, Record.active_customers)
                .filter(*filters)
                .filter(Record.active_customers.isnot(None),
                        Record.active_customers > 0)
                .all())
        best = {}  # (zone, scheme) -> ((year, month_no), value)
        for r in rows:
            k = (r.zone, r.scheme)
            key = (r.year, r.month_no)
            if k not in best or key > best[k][0]:
                best[k] = (key, r.active_customers or 0)
        return best

    best = _scan(scope_filters)
    if fy_filters is not None:
        for k, v in _scan(fy_filters).items():
            best.setdefault(k, v)  # carry FY balance only where the window has none
    per_zone, per_scheme, total = {}, {}, 0.0
    for (zone, scheme), (_key, val) in best.items():
        per_zone[zone] = per_zone.get(zone, 0) + val
        per_scheme[scheme] = per_scheme.get(scheme, 0) + val
        total += val
    return per_zone, per_scheme, total


@router.get("/variance")
def get_variance(
    year: int = Query(default=2026, description="FY end year, e.g. 2026 = FY2025/26"),
    zones: str | None = Query(default=None),
    schemes: str | None = Query(default=None),
    months: str | None = Query(default=None),
    db: Session = Depends(get_db),
):
    """
    Full variance analysis: revenue · costs · operational KPIs · zone breakdown.
    Returns monthly trends with SPC limits, zone comparison, scheme rankings,
    and performance indices aligned with IWA/IBNET framework.

    Works for any configured fiscal year — budget figures are loaded from
    the database, not hardcoded.
    """
    # ── Load this FY's budget data from DB ───────────────────────────────────
    bud         = _load_budget(year, db)
    tariff      = _load_tariff(year, bud, db)
    zone_rev_s, zone_vol_s, zone_conn_s = _load_zone_shares(year, db)
    spc         = _load_spc(year, db)

    # has_budget: True only when real DB rows exist (the dict always has 1 derived key)
    has_budget  = db.query(BudgetLine).filter(BudgetLine.year == year).count() > 0

    # Convenience accessors with defaults
    def B(key, default=0.0) -> float:
        return float(bud.get(key, default))

    # ── Actuals by month ─────────────────────────────────────────────────────
    zone_items   = _csv_items(zones)
    scheme_items = _csv_items(schemes)
    selected_months = _normalize_month_tokens(months)
    scope_filters = [_fy_scope_expr(year, selected_months)]
    comparison_scope_filters = [_fy_scope_expr(year, selected_months)]
    if zone_items:
        scope_filters.append(Record.zone.in_(zone_items))
        comparison_scope_filters.append(Record.zone.in_(zone_items))
    if scheme_items:
        scope_filters.append(Record.scheme.in_(scheme_items))

    # Full fiscal-year scope (same zone/scheme, no month filter) — used to
    # carry stock-snapshot balances (active customers) into a month window
    # that excludes the month they were recorded. Only needed when months
    # are actually selected.
    fy_scope_filters = fy_comparison_filters = None
    if selected_months:
        fy_scope_filters = [_fy_scope_expr(year, None)]
        fy_comparison_filters = [_fy_scope_expr(year, None)]
        if zone_items:
            fy_scope_filters.append(Record.zone.in_(zone_items))
            fy_comparison_filters.append(Record.zone.in_(zone_items))
        if scheme_items:
            fy_scope_filters.append(Record.scheme.in_(scheme_items))

    q = (db.query(
            Record.year, Record.month_no,
            func.sum(Record.total_sales).label("sales"),
            func.sum(Record.amt_billed).label("billed"),
            func.sum(Record.cash_collected).label("collected"),
            func.sum(Record.service_charge).label("svc"),
            func.sum(Record.meter_rental).label("mtr"),
            func.sum(Record.op_cost).label("opex"),
            (func.sum(Record.staff_costs) + func.sum(Record.wages)).label("employee"),
            func.sum(Record.chem_cost).label("chems"),
            func.sum(Record.power_cost).label("power"),
            func.sum(Record.fuel_cost).label("fuel"),
            func.sum(Record.vol_produced).label("vp"),
            func.sum(Record.revenue_water).label("rw"),
            func.sum(Record.nrw).label("nrw_vol"),
            func.sum(Record.new_connections).label("conn"),
            func.sum(Record.dev_lines_total).label("pipelines"),
            func.sum(Record.pipe_breakdowns).label("pipe_bkdn"),
            func.avg(Record.supply_hours).label("sup_hrs"),
         )
         .filter(*scope_filters)
         .group_by(Record.year, Record.month_no)
         .order_by(Record.year, Record.month_no).all())

    by_idx  = {_fy_idx(r.year, r.month_no): r for r in q}
    complete = [i for i, r in by_idx.items() if r.vp and r.vp > 0]
    n = len(complete)
    if n == 0:
        return {
            "error": "No data",
            "meta": {
                "fiscal_year": f"{year-1}/{str(year)[-2:]}",
                "has_budget": has_budget,
            },
        }

    f = n / 12.0
    last_idx = max(complete)
    last_lbl = MONTHS_LBL[last_idx]
    last_yr  = year - 1 if FY_MNO[last_idx] >= 4 else year
    last_mno = FY_MNO[last_idx]

    def S(fld): return sum((getattr(by_idx[i], fld) or 0) for i in complete)

    act_sales    = S("sales");    act_billed   = S("billed");   act_collected = S("collected")
    act_svc      = S("svc");      act_mtr      = S("mtr");      act_opex      = S("opex")
    act_employee = S("employee"); act_chems    = S("chems");    act_power     = S("power")
    act_fuel     = S("fuel");     act_vp       = S("vp");       act_rw        = S("rw")
    act_nrw_vol  = S("nrw_vol");  act_conn     = int(S("conn"))
    act_pipes    = S("pipelines"); act_pipe_bkdn = S("pipe_bkdn")

    act_nrw_pct  = act_nrw_vol / act_vp * 100 if act_vp else 0
    act_coll_rt  = act_collected / act_billed * 100 if act_billed else 0
    act_rev_m3   = act_sales / act_rw if act_rw else 0

    latest_scope_filters = [Record.year == last_yr, Record.month_no == last_mno]
    latest_cmp_filters   = [Record.year == last_yr, Record.month_no == last_mno]
    if zone_items:
        latest_scope_filters.append(Record.zone.in_(zone_items))
        latest_cmp_filters.append(Record.zone.in_(zone_items))
    if scheme_items:
        latest_scope_filters.append(Record.scheme.in_(scheme_items))
        latest_cmp_filters.append(Record.scheme.in_(scheme_items))

    zone_active_map, scheme_active_map, act_active = _latest_active_customers(scope_filters, db, fy_scope_filters)
    act_sup_hrs = (db.query(func.avg(Record.supply_hours))
                   .filter(*latest_scope_filters).scalar() or 0)

    # ── Proportional share factors ────────────────────────────────────────────
    revenue_share_factor    = 1.0
    volume_share_factor     = 1.0
    connection_share_factor = 1.0
    customer_share_factor   = 1.0
    budget_scope_mode  = "board_budget"
    budget_scope_label = "Approved board budget comparator"
    budget_scope_note  = (
        "This page compares actuals with the approved board budget. "
        "Zone views use proportional allocation and scheme views "
        "should be treated as indicative."
    )

    if scheme_items:
        base_sales  = (db.query(func.sum(Record.total_sales))
                       .filter(*comparison_scope_filters).scalar() or 0)
        base_vp     = (db.query(func.sum(Record.vol_produced))
                       .filter(*comparison_scope_filters).scalar() or 0)
        base_conn   = (db.query(func.sum(Record.new_connections))
                       .filter(*comparison_scope_filters).scalar() or 0)
        _bz_active, _bs_active, base_active = _latest_active_customers(comparison_scope_filters, db, fy_comparison_filters)
        revenue_share_factor    = (act_sales  / base_sales)  if base_sales  else 0
        volume_share_factor     = (act_vp     / base_vp)     if base_vp     else 0
        connection_share_factor = (act_conn   / base_conn)   if base_conn   else 0
        customer_share_factor   = (act_active / base_active) if base_active else connection_share_factor
        budget_scope_mode  = "indicative_scheme_budget"
        budget_scope_label = "Indicative scheme budget slice"
        budget_scope_note  = (
            "Scheme filters do not have approved scheme budgets. The comparator "
            "shown here is an indicative budget slice derived from the selected "
            "schemes' share of the filtered parent scope."
        )
    elif zone_items:
        revenue_share_factor    = sum(zone_rev_s.get(z, 0)  for z in zone_items)
        volume_share_factor     = sum(zone_vol_s.get(z, 0)  for z in zone_items)
        connection_share_factor = sum(zone_conn_s.get(z, 0) for z in zone_items)
        customer_share_factor   = connection_share_factor
        budget_scope_mode  = "allocated_zone_budget"
        budget_scope_label = "Allocated zone budget"
        budget_scope_note  = (
            "Zone filters use the approved board budget allocated to the selected "
            "zones using the IPSAS 18 proportional allocation basis."
        )

    # ── Revenue decomposition ─────────────────────────────────────────────────
    bud_rw_ytd     = B("vol_sold")     * f * volume_share_factor
    vol_var_m3     = act_rw - bud_rw_ytd
    rev_vol_effect = vol_var_m3 * tariff

    bud_nrw_vol_ytd = B("vol_produced") * f * volume_share_factor * B("nrw_pct") / 100
    nrw_var_vol     = act_nrw_vol - bud_nrw_vol_ytd
    nrw_rev_impact  = nrw_var_vol * tariff

    # ── Revenue variance rows ─────────────────────────────────────────────────
    revenue_rows = [
        _var("Water Sales (Tariff Revenue)", act_sales,
             B("water_sales") * f * revenue_share_factor,
             note=f"Fixed tariff MK {tariff:,.0f}/m³. All variance = volume effect.",
             iwa_pi="Fi1/IBNET Revenue"),
        _var("Service Charges", act_svc,
             B("service_charges") * f * customer_share_factor,
             note="Fixed connection/standing charges.", iwa_pi="Fi2"),
        _var("Meter Rental", act_mtr,
             B("meter_rental") * f * customer_share_factor, iwa_pi="Fi2"),
        _var("Cash Collected", act_collected,
             B("water_sales") * f * revenue_share_factor * 0.90,
             note="Vs 90% IBNET collection rate benchmark applied to water budget.",
             iwa_pi="Fi9/IBNET Collection Rate"),
    ]

    decomposition = {
        "tariff_per_m3":            tariff,
        "budget_vol_sold_ytd_m3":   round(bud_rw_ytd),
        "actual_vol_sold_m3":       round(act_rw),
        "volume_variance_m3":       round(vol_var_m3),
        "revenue_volume_effect_mk": round(rev_vol_effect),
        "budget_nrw_vol_ytd_m3":    round(bud_nrw_vol_ytd),
        "actual_nrw_vol_m3":        round(act_nrw_vol),
        "nrw_vol_variance_m3":      round(nrw_var_vol),
        "nrw_revenue_impact_mk":    round(nrw_rev_impact),
        "interpretation": (
            f"At fixed tariff MK {tariff:,.0f}/m³, the {round(vol_var_m3/1e6, 2)}M m³ "
            f"volume shortfall accounts for MK {abs(rev_vol_effect)/1e9:.2f}B of revenue loss. "
            f"Excess NRW ({act_nrw_pct:.1f}% vs {B('nrw_pct')}% target) represents an additional "
            f"MK {abs(nrw_rev_impact)/1e9:.2f}B in unbilled production cost."
        ) if has_budget else "No approved budget loaded for this fiscal year.",
    }

    # ── Operational rows ──────────────────────────────────────────────────────
    operational_rows = [
        _var("Volume Produced",      act_vp,      B("vol_produced") * f * volume_share_factor,
             unit="m³", iwa_pi="Op23"),
        _var("Revenue Water Sold",   act_rw,      B("vol_sold") * f * volume_share_factor,
             unit="m³", iwa_pi="Op24"),
        _var("NRW %",                act_nrw_pct, B("nrw_pct"),
             unit="%", invert=True, scope="target",
             note=f"Vol-weighted. SRWB target {B('nrw_pct')}%, IWA <20%.", iwa_pi="Op23/Wn1"),
        _var("NRW Volume",           act_nrw_vol,
             B("vol_produced") * f * volume_share_factor * B("nrw_pct") / 100,
             unit="m³", invert=True, iwa_pi="Wn1"),
        _var("New Connections",      act_conn,
             B("new_customers") * f * connection_share_factor,
             unit="connections", iwa_pi="Cu1"),
        _var("Active Customer Base", act_active,
             B("active_customers") * customer_share_factor,
             unit="customers", scope="target",
             note=f"Latest: {last_lbl}; budget = year-end.", iwa_pi="Cu1"),
        _var("Pipeline Extensions",  act_pipes,
             B("pipelines_km") * 1000 * f * volume_share_factor, unit="m",
             note=f"Budget: {B('pipelines_km')} km annual. DB captures dev_lines_total.",
             iwa_pi="Qa2"),
        _var("Supply Hours/Day",     float(act_sup_hrs or 0), B("supply_hours"),
             unit="hrs/day", scope="target",
             note=f"Latest month ({last_lbl}).", iwa_pi="Op4"),
        _var("Collection Rate",      act_coll_rt, 90.0,
             unit="%", scope="target",
             note="Actual vs IBNET 90% benchmark.", iwa_pi="Fi9"),
    ]

    # ── Cost variance rows ────────────────────────────────────────────────────
    cost_rows = [
        _var("Electricity / Power",  act_power,
             B("electricity") * f * volume_share_factor, invert=True,
             note=f"Scheme power only. Budget MK {B('electricity')/1e9:.2f}B, excl. bottled water.",
             iwa_pi="Op39/Ee1", scope="field"),
        _var("Water Treatment Chemicals", act_chems,
             B("chemicals") * f * volume_share_factor, invert=True,
             note=f"Scheme chemicals only. Budget MK {B('chemicals')/1e9:.2f}B.",
             iwa_pi="Op34", scope="field"),
        _var("Fuel", act_fuel,
             B("fuel") * f * volume_share_factor, invert=True,
             note=f"Operating fuel only. Budget MK {B('fuel')/1e9:.2f}B. DB capture may be incomplete.",
             scope="field"),
        _var("Employee Costs", act_employee,
             (B("salaries") + B("wages")) * f * volume_share_factor, invert=True,
             note="Database covers scheme staff only. Corporate budget includes full establishment.",
             scope="field"),
        _var("Operating Expenditure", act_opex,
             (B("plant_veh_field") + B("salaries") + B("wages")) * f * volume_share_factor * 0.45,
             invert=True, scope="field",
             note="Operating-site portion estimated at 45% of the corporate plant, vehicle, and salaries budget."),
    ]

    # ── Efficiency KPIs ───────────────────────────────────────────────────────
    efficiency_kpis = {
        "operating_ratio":        round(act_opex / act_sales, 3) if act_sales else None,
        "opex_per_m3_produced":   round(act_opex / act_vp, 2)    if act_vp    else None,
        "revenue_per_connection": round(act_sales / act_active, 0) if act_active else None,
        "nrw_financial_cost_mk":  round(act_nrw_vol * tariff),
        "chemical_cost_per_m3":   round(act_chems / act_vp, 2)   if act_vp    else None,
        "power_cost_per_m3":      round(act_power / act_vp, 2)   if act_vp    else None,
        "collection_rate_pct":    round(act_coll_rt, 2),
        "revenue_tariff_eff":     round(act_rev_m3, 1),
        "connections_per_month":  round(safe_div(act_conn, n), 1),
        "budget_nrw_cost_mk":
            round(B("vol_produced") * f * volume_share_factor * B("nrw_pct") / 100 * tariff),
        "bpi_revenue":
            round(act_sales / (B("water_sales") * f * revenue_share_factor), 3)
            if B("water_sales") and revenue_share_factor else None,
        "bpi_volume":
            round(act_vp / (B("vol_produced") * f * volume_share_factor), 3)
            if B("vol_produced") and volume_share_factor else None,
        "bpi_nrw":   round(B("nrw_pct") / act_nrw_pct, 3) if act_nrw_pct else None,
        "bpi_connections":
            round(act_conn / (B("new_customers") * f * connection_share_factor), 3)
            if B("new_customers") and connection_share_factor else None,
    }

    # ── Zone-level actuals + proportional budgets ─────────────────────────────
    zone_q = (db.query(
            Record.zone,
            _cs(Record.total_sales).label("sales"),
            _cs(Record.amt_billed).label("billed"),
            _cs(Record.cash_collected).label("collected"),
            _cs(Record.service_charge).label("svc"),
            _cs(Record.op_cost).label("opex"),
            _cs(Record.chem_cost).label("chems"),
            _cs(Record.power_cost).label("power"),
            _cs(Record.vol_produced).label("vp"),
            _cs(Record.revenue_water).label("rw"),
            _cs(Record.nrw).label("nrw_vol"),
            _cs(Record.new_connections).label("conn"),
            _cs(Record.dev_lines_total).label("pipelines"),
            func.count(func.distinct(Record.scheme)).label("schemes"),
         )
         .filter(*scope_filters, or_(Record.vol_produced > 0))
         .group_by(Record.zone).all())

    cust_map = zone_active_map

    zone_rows = []
    for r in sorted(zone_q, key=lambda x: x.zone):
        z  = r.zone
        rs = zone_rev_s.get(z, 0)
        vs = zone_vol_s.get(z, 0)
        cs = zone_conn_s.get(z, 0)
        nrw_pct  = r.nrw_vol / r.vp * 100 if r.vp else 0
        coll_rt  = r.collected / r.billed * 100 if r.billed else 0
        rev_m3   = r.sales / r.rw if r.rw else 0
        cust     = cust_map.get(z, 0) or 0
        bud_sales_z = B("water_sales") * rs * f
        bud_vp_z    = B("vol_produced") * vs * f
        bud_conn_z  = B("new_customers") * cs * f
        zone_rows.append({
            "zone":                   z,
            "schemes":                r.schemes,
            "actual_sales":           round(r.sales),
            "actual_vol_produced":    round(r.vp),
            "actual_rev_water":       round(r.rw),
            "actual_nrw_vol":         round(r.nrw_vol),
            "actual_nrw_pct":         round(nrw_pct, 2),
            "actual_connections":     round(r.conn),
            "actual_opex":            round(r.opex),
            "actual_chems":           round(r.chems),
            "actual_power":           round(r.power),
            "actual_collected":       round(r.collected),
            "active_customers":       round(cust),
            "collection_rate":        round(coll_rt, 1),
            "revenue_per_m3":         round(rev_m3, 1),
            "budget_sales_ytd":       round(bud_sales_z),
            "budget_vol_ytd":         round(bud_vp_z),
            "budget_connections_ytd": round(bud_conn_z),
            "sales_variance":         round(r.sales - bud_sales_z),
            "sales_variance_pct":
                round((r.sales - bud_sales_z) / bud_sales_z * 100, 1) if bud_sales_z else None,
            "vol_variance":           round(r.vp - bud_vp_z),
            "conn_variance":          round(r.conn - bud_conn_z),
            "nrw_variance_pp":        round(nrw_pct - B("nrw_pct"), 2),
            "budget_share_pct":       round(rs * 100, 1),
            "allocation_basis":       "IPSAS 18 revenue-weighted proportional allocation",
        })

    # ── Zone monthly NRW for SPC visualisation ────────────────────────────────
    zone_monthly_q = (db.query(
            Record.zone, Record.year, Record.month_no,
            func.sum(Record.vol_produced).label("vp"),
            func.sum(Record.nrw).label("nrw_vol"),
            func.sum(Record.total_sales).label("sales"),
            func.sum(Record.new_connections).label("conn"),
         )
         .filter(*scope_filters, Record.vol_produced > 0)
         .group_by(Record.zone, Record.year, Record.month_no)
         .order_by(Record.zone, Record.year, Record.month_no).all())

    zone_monthly: dict = {}
    for r in zone_monthly_q:
        z = r.zone
        if z not in zone_monthly:
            zone_monthly[z] = {"nrw_pct": [None]*12, "sales": [None]*12,
                                "connections": [None]*12}
        idx = _fy_idx(r.year, r.month_no)
        if r.vp and r.vp > 0:
            zone_monthly[z]["nrw_pct"][idx] = round(r.nrw_vol / r.vp * 100, 2)
        zone_monthly[z]["sales"][idx]       = round(r.sales or 0)
        zone_monthly[z]["connections"][idx] = round(r.conn or 0)

    # ── Scheme league table ───────────────────────────────────────────────────
    scheme_q = (db.query(
            Record.zone, Record.scheme,
            func.count().label("n"),
            _cs(Record.vol_produced).label("vp"),
            _cs(Record.revenue_water).label("rw"),
            _cs(Record.nrw).label("nrw_vol"),
            _cs(Record.total_sales).label("sales"),
            _cs(Record.amt_billed).label("billed"),
            _cs(Record.cash_collected).label("collected"),
            _cs(Record.chem_cost).label("chems"),
            _cs(Record.power_cost).label("power"),
            _cs(Record.new_connections).label("conn"),
            func.avg(Record.supply_hours).label("sup_hrs"),
            _cs(Record.pipe_breakdowns).label("pipe_bkdn"),
         )
         .filter(*scope_filters, Record.vol_produced > 0)
         .group_by(Record.zone, Record.scheme).all())

    cust_sch_map = scheme_active_map

    nrw_target = B("nrw_pct") or 27.0   # fallback if no budget loaded
    scheme_rows = []
    for r in scheme_q:
        nrw_pct  = r.nrw_vol / r.vp * 100 if r.vp else 0
        coll_rt  = r.collected / r.billed * 100 if r.billed else 0
        rev_m3   = r.sales / r.rw if r.rw else 0
        chem_m3  = r.chems / r.vp if r.vp else 0
        pwr_m3   = r.power / r.vp if r.vp else 0
        cust     = cust_sch_map.get(r.scheme, 0) or 0
        nrw_score  = max(0, min(100, (45 - nrw_pct) / (45 - 10) * 100)) if nrw_pct else 50
        coll_score = min(100, coll_rt) if coll_rt else 0
        rev_score  = min(100, rev_m3 / tariff * 100) if rev_m3 else 0
        conn_score = min(100, r.conn / max(1, r.n) * 10) if r.conn else 0
        composite  = round(nrw_score * 0.35 + coll_score * 0.35 +
                           rev_score * 0.20 + conn_score * 0.10, 1)
        scheme_rows.append({
            "zone": r.zone, "scheme": r.scheme,
            "months":             r.n,
            "vol_produced_m3":    round(r.vp),
            "nrw_pct":            round(nrw_pct, 2),
            "nrw_variance_pp":    round(nrw_pct - nrw_target, 2),
            "revenue_mk":         round(r.sales),
            "revenue_per_m3":     round(rev_m3, 1),
            "collection_rate":    round(coll_rt, 1),
            "new_connections":    round(r.conn),
            "active_customers":   round(cust),
            "chem_per_m3":        round(chem_m3, 2),
            "power_per_m3":       round(pwr_m3, 2),
            "supply_hrs_avg":     round(r.sup_hrs or 0, 1),
            "pipe_breakdowns":    round(r.pipe_bkdn or 0),
            "performance_score":  composite,
            "nrw_score":          round(nrw_score, 1),
            "coll_score":         round(coll_score, 1),
            "rev_score":          round(rev_score, 1),
            "rag": "green" if composite >= 70 else "amber" if composite >= 50 else "red",
        })
    scheme_rows.sort(key=lambda x: x["performance_score"], reverse=True)

    # ── Monthly trend arrays ──────────────────────────────────────────────────
    trend = {"months": MONTHS_LBL, "complete": [i in complete for i in range(12)]}
    for attr, lbl in [
        ("sales",    "actual_sales"),    ("billed",   "actual_billed"),
        ("collected","actual_collected"),("opex",     "actual_opex"),
        ("employee", "actual_employee"), ("chems",    "actual_chems"),
        ("power",    "actual_power"),    ("fuel",     "actual_fuel"),
        ("vp",       "actual_vol_prod"), ("rw",       "actual_rev_water"),
        ("nrw_vol",  "actual_nrw_vol"),  ("conn",     "actual_connections"),
        ("pipelines","actual_pipelines"),("pipe_bkdn","actual_pipe_bkdn"),
    ]:
        trend[lbl] = [
            round(getattr(by_idx[i], attr) or 0, 2) if i in by_idx else None
            for i in range(12)
        ]

    trend["actual_nrw_pct"] = [
        round(by_idx[i].nrw_vol / by_idx[i].vp * 100, 2)
        if i in by_idx and by_idx[i].vp and by_idx[i].vp > 0 else None
        for i in range(12)
    ]

    trend["budget_sales"]       = [round(B("water_sales")    * revenue_share_factor / 12)] * 12
    trend["budget_vol_prod"]    = [round(B("vol_produced")   * volume_share_factor  / 12)] * 12
    trend["budget_rev_water"]   = [round(B("vol_sold")       * volume_share_factor  / 12)] * 12
    trend["budget_nrw_pct"]     = [B("nrw_pct")] * 12
    trend["budget_connections"] = [round(B("new_customers")  * connection_share_factor / 12)] * 12
    trend["budget_chems"]       = [round(B("chemicals")      * volume_share_factor  / 12)] * 12
    trend["budget_power"]       = [round(B("electricity")    * volume_share_factor  / 12)] * 12

    # SPC limits from DB (graceful absent)
    def _spc(metric, key, fallback=None):
        return spc.get(metric, {}).get(key, fallback)

    trend["spc_nrw_ucl2"] = [_spc("nrw_pct", "ucl2")] * 12
    trend["spc_nrw_lcl2"] = [_spc("nrw_pct", "lcl2")] * 12
    trend["spc_nrw_ucl3"] = [_spc("nrw_pct", "ucl3")] * 12
    trend["spc_nrw_mean"] = [_spc("nrw_pct", "mean")] * 12
    trend["spc_vp_ucl2"]  = [_spc("vol_prod", "ucl2")] * 12
    trend["spc_vp_lcl2"]  = [_spc("vol_prod", "lcl2")] * 12
    trend["spc_vp_mean"]  = [_spc("vol_prod", "mean")] * 12

    # ── Headline summary ──────────────────────────────────────────────────────
    all_rows = revenue_rows + operational_rows
    headline = {
        "n_adverse":         sum(1 for r in all_rows if r["direction"] == "adverse"),
        "n_favourable":      sum(1 for r in all_rows if r["direction"] == "favourable"),
        "n_on_budget":       sum(1 for r in all_rows if r["direction"] == "on_budget"),
        "revenue_variance_mk": round(act_sales - B("water_sales") * f * revenue_share_factor),
        "nrw_pp_variance":     round(act_nrw_pct - B("nrw_pct"), 2),
        "conn_variance":       round(act_conn - B("new_customers") * f * connection_share_factor),
        "cash_variance_mk":    round(act_collected - B("water_sales") * f * revenue_share_factor * 0.90),
        "chem_overrun_mk":     round(act_chems - B("chemicals") * f * volume_share_factor),
        "power_variance_mk":   round(act_power - B("electricity") * f * volume_share_factor),
        "nrw_financial_cost":  round(act_nrw_vol * tariff),
        "bpi_revenue":    efficiency_kpis["bpi_revenue"],
        "bpi_volume":     efficiency_kpis["bpi_volume"],
        "bpi_nrw":        efficiency_kpis["bpi_nrw"],
    }

    return {
        "meta": {
            "fiscal_year":       f"{year-1}/{str(year)[-2:]}",
            "data_months":       n,
            "period":            f"April {year-1} – {last_lbl} {last_yr}",
            "budget_factor":     round(f, 4),
            "has_budget":        has_budget,
            "framework":         "IWA/IBNET PI | IPSAS 18 | ISO 7870-2 SPC | EVM-adapted BPI",
            "tariff_mk_m3":      tariff,
            "zone_allocation":   "IPSAS 18 revenue-weighted proportional segment allocation",
            "budget_scope_mode":  budget_scope_mode,
            "budget_scope_label": budget_scope_label,
            "budget_scope_note":  budget_scope_note,
            "scope": {
                "zones":   zone_items,
                "schemes": scheme_items,
                "months":  _csv_items(months),
            },
        },
        "headline":        headline,
        "decomposition":   decomposition,
        "revenue":         revenue_rows,
        "operational":     operational_rows,
        "costs":           cost_rows,
        "efficiency_kpis": efficiency_kpis,
        "zones":           zone_rows,
        "zone_monthly":    zone_monthly,
        "schemes":         scheme_rows,
        "monthly":         trend,
        "spc_limits":      spc,
        "budget_ref": {
            "water_sales":           B("water_sales"),
            "total_revenue":         B("total_revenue"),
            "total_expenditure":    B("total_expenditure"),
            "vol_produced_target":   B("vol_produced"),
            "vol_sold_target":       B("vol_sold"),
            "nrw_target":            B("nrw_pct"),
            "electricity_budget":    B("electricity"),
            "chemicals_budget":      B("chemicals"),
            "fuel_budget":           B("fuel"),
            "pipeline_maint_budget": B("pipeline_maint"),
            "salaries_wages_budget": B("salaries") + B("wages"),
            "new_customer_target":   B("new_customers"),
            "pipelines_km_target":   B("pipelines_km"),
        },
    }
