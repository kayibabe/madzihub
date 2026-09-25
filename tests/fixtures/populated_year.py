"""A populated fiscal year for review journeys: FY2025/26 of the demo tenant.

Every value is generated and every name is fictional. Unlike ``synthetic_dataset``
(stable but arbitrary numbers for API parity snapshots), this dataset keeps the
relationships a real water utility's returns have: billed volume + NRW = production,
connection and stuck-meter balances roll forward month to month, stuck and active
meters stay within metered connections, costs add up to operating cost, and debtors
move with billing and collections. Scale follows ``tenants/demo/budget.yaml``
(about 25,000 connections, 4 million m³ a year).

It also includes, on purpose, each data state the GUI/UX review must see
(docs/GUI_UX_REVIEW_2026-09-25.md, "Before Slice 2"). ``CASES`` names them:

  complete       Northgate, Hillside, Central Works, Riverside, Southport: every month,
                 every field. Southport performs poorly and Hillside has a main burst in
                 February 2026, so GOOD, WATCH and HIGH verdicts all occur.
  measured_zero  Ridgeway: pipe and pump breakdowns, disconnections, new connections,
                 new stuck meters and power-failure hours are entered as 0 every month.
  partial        Lakeshore: staffing and payroll never entered (NULL), so operating cost is
                 not totalled either; billing and collections not entered April-June 2026;
                 breakdowns not entered October-November 2025.
  stale          Valley: returns stop after December 2025 (nothing since).
  empty          no returns for September 2026 onwards, or for Valley from January 2026.

FY2026/27 (the demo tenant's current year) has July and August 2026 so far.
"""
from __future__ import annotations

import math
import random

from tests.fixtures.synthetic_dataset import MONTH_NAMES, _fy_label, _quarter

FY_START = 7                                   # tenants/demo: July - June
POPULATED_FY = 2026                            # FY-end year: July 2025 - June 2026
POPULATED_MONTHS = [(2025, m) for m in range(7, 13)] + [(2026, m) for m in range(1, 7)]
CURRENT_FY_MONTHS = [(2026, 7), (2026, 8)]     # FY2026/27 returns received so far

CATEGORIES = ("indiv", "inst", "comm", "cwp")  # individual, institutions, commercial, communal water points
CONN_SPLIT = {"indiv": 0.86, "inst": 0.03, "comm": 0.09, "cwp": 0.02}
USE_M3 = {"indiv": 5.6, "inst": 82.0, "comm": 24.0, "cwp": 70.0}          # per active connection per month
TARIFF = {"indiv": 1.20, "inst": 1.65, "comm": 1.95, "cwp": 0.70}          # USD per m³
SERVICE_CHARGE = {"indiv": 0.50, "inst": 4.00, "comm": 2.00, "cwp": 1.00}  # USD per active connection
METER_RENTAL = {"indiv": 0.30, "inst": 1.50, "comm": 1.00, "cwp": 0.50}
# Column-name spelling differs by field family.
_ACTIVE = {"indiv": "individual", "inst": "inst", "comm": "commercial", "cwp": "cwp"}
_SEGMENT = {"indiv": "indiv", "inst": "inst", "comm": "comm", "cwp": "cwp"}
_CHARGE = {"indiv": "individual", "inst": "institutions", "comm": "commercial", "cwp": "cwp"}

CHEMICALS = (  # column, dose per m³, USD per unit
    ("chlorine_kg", "chlorine_kg_per_m3", 0.0025, 3.2),
    ("alum_kg", "alum_kg_per_m3", 0.028, 0.95),
    ("soda_ash_kg", "soda_ash_kg_per_m3", 0.009, 0.80),
    ("algae_floc_litres", "algae_floc_per_m3", 0.0004, 6.0),
    ("sud_floc_litres", "sud_floc_per_m3", 0.0003, 7.5),
    ("kmno4_kg", "kmno4_per_m3", 0.0002, 9.0),
)
PVC_SIZES = ("pvc_20mm", "pvc_25mm", "pvc_32mm", "pvc_40mm", "pvc_50mm", "pvc_63mm", "pvc_75mm",
             "pvc_90mm", "pvc_110mm", "pvc_160mm")
OTHER_SIZES = {"pipe_gi": ("gi_15mm", "gi_20mm", "gi_25mm", "gi_50mm"),
               "pipe_di": ("di_150mm", "di_200mm"),
               "pipe_hdpe_ac": ("hdpe_32mm", "hdpe_50mm", "ac_75mm", "ac_100mm")}
DEV_LINE_SIZES = ("dev_lines_32mm", "dev_lines_50mm", "dev_lines_63mm", "dev_lines_90mm", "dev_lines_110mm")

# zone, scheme, connections at 1 July 2025, and the scheme's operating profile:
#   nrw %, collection %, kWh/m³, supply h/day, staff per 1,000 connections, stuck %,
#   active share of metered connections, pipe and pump breakdowns per month, overhead share of sales
SCHEMES = [
    ("North", "Northgate", 5200, dict(nrw=24, coll=94, kwh=0.45, supply=22.0, staff=11.0, stuck=4.0, active=0.93, pipe=3.0, pump=0.3, overhead=0.18)),
    ("North", "Hillside", 3100, dict(nrw=31, coll=86, kwh=0.62, supply=19.0, staff=13.5, stuck=6.5, active=0.88, pipe=3.0, pump=0.5, overhead=0.22)),
    ("North", "Ridgeway", 1900, dict(nrw=22, coll=97, kwh=0.38, supply=23.5, staff=12.0, stuck=3.0, active=1.00, pipe=0.0, pump=0.0, overhead=0.18)),
    ("Central", "Central Works", 5600, dict(nrw=29, coll=91, kwh=0.55, supply=21.0, staff=12.0, stuck=5.5, active=0.90, pipe=4.0, pump=0.4, overhead=0.20)),
    ("Central", "Riverside", 3300, dict(nrw=34, coll=79, kwh=0.72, supply=17.0, staff=15.0, stuck=7.5, active=0.84, pipe=3.0, pump=0.6, overhead=0.25)),
    ("South", "Southport", 3400, dict(nrw=39, coll=71, kwh=0.95, supply=14.5, staff=18.0, stuck=10.0, active=0.76, pipe=4.0, pump=0.8, overhead=0.30)),
    ("South", "Lakeshore", 1800, dict(nrw=33, coll=82, kwh=0.66, supply=18.0, staff=14.0, stuck=6.0, active=0.86, pipe=2.0, pump=0.4, overhead=0.24)),
    ("South", "Valley", 1200, dict(nrw=36, coll=74, kwh=0.85, supply=15.0, staff=16.0, stuck=9.0, active=0.80, pipe=2.0, pump=0.5, overhead=0.27)),
]

CASES = {
    "complete": ["Northgate", "Hillside", "Central Works", "Riverside", "Southport"],
    "measured_zero": ["Ridgeway"],
    "partial": ["Lakeshore"],
    "stale": ["Valley"],
}
MEASURED_ZERO_FIELDS = ("pipe_breakdowns", "pump_breakdowns", "total_disconnected", "new_connections",
                        "stuck_new", "power_fail_hours")
STALE_LAST_MONTH = (2025, 12)
PARTIAL_STAFF_FIELDS = ("perm_staff", "temp_staff", "staff_costs", "wages", "staff_per_1000m3_12h",
                        "op_cost", "op_cost_per_m3_produced", "op_cost_per_m3_billed", "op_cost_per_sales")
PARTIAL_BILLING_MONTHS = [(2026, 4), (2026, 5), (2026, 6)]
PARTIAL_BREAKDOWN_MONTHS = [(2025, 10), (2025, 11)]
BURST = ("Hillside", (2026, 2))                # a trunk-main burst: breakdowns, losses and outage hours spike


def _periods() -> list[tuple[int, int]]:
    return POPULATED_MONTHS + CURRENT_FY_MONTHS


def _season(month: int) -> float:
    """Demand peaks in the hot dry season (October) and dips in the rains (April)."""
    return 1 + 0.06 * math.cos(2 * math.pi * (month - 10) / 12)


def _split(total: int, shares: dict) -> dict:
    out = {c: int(total * shares[c]) for c in CATEGORIES if c != "indiv"}
    out["indiv"] = total - sum(out.values())
    return out


def _spread(rng: random.Random, total: int, columns) -> dict:
    """Distribute a whole-number count across columns."""
    out = {c: 0 for c in columns}
    for _ in range(total):
        out[rng.choice(columns)] += 1
    return out


def _scheme_rows(zone: str, scheme: str, conn0: int, p: dict) -> list[dict]:
    rng = random.Random(f"madzihub-populated-year:{scheme}")   # deterministic per scheme
    zero = scheme in CASES["measured_zero"]
    all_conn = conn0
    stuck = {c: round(conn0 * CONN_SPLIT[c] * p["stuck"] / 100) for c in CATEGORIES}
    monthly_sales = conn0 * 16.0
    debtors = monthly_sales * (1.0 + (95 - p["coll"]) / 15)    # opening arrears, worse where collection is weak
    rows = []
    for year, month in _periods():
        burst = (scheme, (year, month)) == BURST
        season = _season(month)
        r = {"zone": zone, "scheme": scheme, "year": year, "month_no": month, "month": MONTH_NAMES[month - 1],
             "quarter": _quarter(month, FY_START), "fiscal_year": _fy_label(year, month, FY_START)}

        # Connections: brought forward, applied, done, carried forward.
        applied = 0 if zero else round(all_conn * 0.075 / 12 * rng.uniform(0.8, 1.3))
        new = 0 if zero else round(applied * rng.uniform(0.65, 0.85))
        new_cat, applied_cat = _split(new, CONN_SPLIT), _split(applied, CONN_SPLIT)
        bfwd_cat = _split(all_conn, CONN_SPLIT)
        r.update(all_conn_bfwd=all_conn, all_conn_applied=applied, conn_applied=applied, new_connections=new,
                 prepaid_meters_installed=0)
        for c in CATEGORIES:
            r.update({f"conn_{c}_bfwd": bfwd_cat[c], f"conn_{c}_applied_pp": applied_cat[c],
                      f"conn_{c}_done_pp": new_cat[c], f"conn_{c}_done_prepaid": 0,
                      f"conn_{c}_total_done": new_cat[c], f"conn_{c}_cfwd": bfwd_cat[c] + new_cat[c]})
        all_conn += new
        r["all_conn_cfwd"] = all_conn

        # Metered, active and disconnected balances (every connection is metered).
        metered_cat = _split(all_conn, CONN_SPLIT)
        active_share = 1.0 if zero else min(0.99, p["active"] + rng.uniform(-0.015, 0.015))
        active_cat = {c: round(metered_cat[c] * active_share) for c in CATEGORIES}
        active = sum(active_cat.values())
        r.update(total_metered=all_conn, active_customers=active, active_postpaid=active, active_prepaid=0)
        for c in CATEGORIES:
            r[f"active_post_{_ACTIVE[c]}"] = active_cat[c]
            r[f"active_prep_{_ACTIVE[c]}"] = 0
            r[f"disconnected_{_ACTIVE[c]}"] = metered_cat[c] - active_cat[c]
        r["total_disconnected"] = all_conn - active
        pop_supplied = active_cat["indiv"] * 5.2 + active_cat["inst"] * 60 + active_cat["cwp"] * 150
        r.update(pop_supplied=round(pop_supplied), pop_supply_area=round(pop_supplied / 0.82),
                 pct_pop_supplied=82.0)

        # Stuck meters: brought forward + new - repaired - replaced = carried forward.
        for c in CATEGORIES:
            target = metered_cat[c] * p["stuck"] / 100
            s_new = 0 if zero else round(metered_cat[c] * p["stuck"] / 100 * rng.uniform(0.08, 0.16))
            fixable = stuck[c] + s_new
            fixed = min(fixable, max(0, round(fixable - target + rng.uniform(-1, 2))))
            repaired = round(fixed * 0.6)
            r.update({f"stuck_{c}_bfwd": stuck[c], f"stuck_{c}_new": s_new, f"stuck_{c}_repaired": repaired,
                      f"stuck_{c}_replaced": fixed - repaired, f"stuck_{c}_cfwd": fixable - fixed})
            stuck[c] = fixable - fixed
        r["stuck_meters"] = sum(r[f"stuck_{c}_bfwd"] for c in CATEGORIES)
        for part in ("new", "repaired", "replaced"):
            r[f"stuck_{part}"] = sum(r[f"stuck_{c}_{part}"] for c in CATEGORIES)
        r["all_stuck_cfwd"] = sum(stuck.values())

        # Water balance: billed consumption by category, then production from the loss rate.
        nrw_pct = p["nrw"] + rng.uniform(-1.5, 1.5) + (6.0 if burst else 0.0)
        billed_cat = {c: round(active_cat[c] * USE_M3[c] * season * rng.uniform(0.95, 1.05), 1) for c in CATEGORIES}
        billed = round(sum(billed_cat.values()), 1)
        produced = round(billed / (1 - nrw_pct / 100), 1)
        for c in CATEGORIES:
            r[f"vol_billed_{_SEGMENT[c]}_pp"] = billed_cat[c]
            r[f"vol_billed_{_SEGMENT[c]}_prepaid"] = 0.0
        r.update(vol_produced=produced, total_vol_billed_pp=billed, total_vol_billed_prepaid=0.0,
                 revenue_water=billed, nrw=round(produced - billed, 1),
                 pct_nrw=round((produced - billed) / produced * 100, 2))

        # Treatment chemicals and water quality sampling.
        chem_cost = 0.0
        for col, per_m3, dose, price in CHEMICALS:
            qty = round(produced * dose * rng.uniform(0.9, 1.1), 1)
            r[col], r[per_m3] = qty, round(qty / produced, 5)
            chem_cost += qty * price
        r.update(chem_cost=round(chem_cost, 2), chem_cost_per_m3=round(chem_cost / produced, 4))
        size = 1.0 if conn0 >= 3000 else 0.5
        wq_ok = 0.97 if p["nrw"] < 35 else 0.9
        samples = {"cl": round(30 * size), "turbidity": round(20 * size), "bact": round(12 * size), "ph": round(12 * size)}
        for key, n in samples.items():
            r[f"wq_{key}_samples"] = n
            r[f"wq_{key}_compliant"] = sum(rng.random() < wq_ok for _ in range(n))
        r.update(wq_samples_taken=sum(samples.values()), wq_residual_cl_mg_l=round(rng.uniform(0.4, 0.9), 2),
                 wq_turbidity_ntu=round(rng.uniform(1.0, 4.0 if p["nrw"] > 35 else 2.5), 2))

        # Power and continuity.
        kwh = round(produced * p["kwh"] * rng.uniform(0.95, 1.05), 1)
        power_cost = round(kwh * 0.24, 2)
        r.update(power_kwh=kwh, power_cost=power_cost, power_kwh_per_m3=round(kwh / produced, 4),
                 power_cost_per_m3=round(power_cost / produced, 4))
        supply = p["supply"] - (1.5 if month in (9, 10, 11) else 0) - (6.0 if burst else 0) + rng.uniform(-0.8, 0.8)
        r.update(supply_hours=round(min(24.0, supply), 1),
                 power_fail_hours=0.0 if zero else round(rng.uniform(4, 30 if p["kwh"] > 0.7 else 15), 1))

        # Network breakdowns by material and size.
        pipe = 0 if zero else max(0, round(p["pipe"] * rng.uniform(0.4, 1.6))) + (9 if burst else 0)
        pump = 0 if zero else int(rng.random() < p["pump"]) + int(rng.random() < p["pump"] / 3)
        pvc = round(pipe * 0.7)
        r.update(_spread(rng, pvc, PVC_SIZES))
        rest = _spread(rng, pipe - pvc, list(OTHER_SIZES))
        for total_col, sizes in OTHER_SIZES.items():
            r.update(_spread(rng, rest[total_col], sizes))
            r[total_col] = rest[total_col]
        r.update(pipe_pvc=pvc, pipe_breakdowns=pipe, pump_breakdowns=pump,
                 pump_hours_lost=round(pump * rng.uniform(6, 30), 1))
        dev = _spread(rng, round(new * rng.uniform(18, 30)), DEV_LINE_SIZES)   # metres of new distribution line
        r.update(dev, dev_lines_total=sum(dev.values()))

        # Billing, charges and collections.
        coll = p["coll"] + rng.uniform(-4, 4) - (6 if month == 12 else 0) + (8 if month == 6 else 0)
        amt = {c: round(billed_cat[c] * TARIFF[c], 2) for c in CATEGORIES}
        cash = {c: round(amt[c] * coll / 100, 2) for c in CATEGORIES}
        service = {c: round(active_cat[c] * SERVICE_CHARGE[c], 2) for c in CATEGORIES}
        rental = {c: round(active_cat[c] * METER_RENTAL[c], 2) for c in CATEGORIES}
        for c in CATEGORIES:
            s = _SEGMENT[c]
            r.update({f"amt_billed_{s}_pp": amt[c], f"amt_billed_{s}_prepaid": 0.0,
                      f"cash_coll_{s}_pp": cash[c], f"cash_coll_{s}_prepaid": 0.0,
                      f"service_charge_{_CHARGE[c]}": service[c], f"meter_rental_{_CHARGE[c]}": rental[c]})
        amt_billed, cash_collected = round(sum(amt.values()), 2), round(sum(cash.values()), 2)
        sales = round(amt_billed + sum(service.values()) + sum(rental.values()), 2)
        r.update(amt_billed_pp=amt_billed, amt_billed_prepaid=0.0, amt_billed=amt_billed,
                 cash_coll_pp=cash_collected, cash_coll_prepaid=0.0, cash_collected=cash_collected,
                 service_charge=round(sum(service.values()), 2), meter_rental=round(sum(rental.values()), 2),
                 total_sales=sales, collection_rate=round(cash_collected / amt_billed * 100, 2),
                 collection_per_sales=round(cash_collected / sales, 4))
        debtors = max(0.0, debtors + sales - cash_collected - (sales - amt_billed) * coll / 100)
        r.update(total_debtors=round(debtors, 2), private_debtors=round(debtors * 0.8, 2),
                 public_debtors=round(debtors - round(debtors * 0.8, 2), 2))

        # Staff, transport and operating cost.
        staff = all_conn / 1000 * p["staff"]
        perm, temp = round(staff * 0.88), round(staff * 0.12)
        km = round((1800 + all_conn * 0.6) * rng.uniform(0.9, 1.1), 1)
        fuel = round(km * rng.uniform(0.11, 0.15), 1)
        fuel_cost = round(fuel * 1.55, 2)
        maintenance = round(all_conn * 0.7 * (1 + (pipe + pump) * 0.08), 2)
        staff_costs, wages = round(perm * 420.0, 2), round(temp * 210.0, 2)
        overhead = round(sales * p["overhead"], 2)
        op_cost = round(chem_cost + power_cost + fuel_cost + maintenance + staff_costs + wages + overhead, 2)
        r.update(perm_staff=perm, temp_staff=temp, staff_per_1000m3_12h=round((perm + temp) / (produced / 1000), 4),
                 distances_km=km, fuel_used_litres=fuel, fuel_cost=fuel_cost, maintenance=maintenance,
                 staff_costs=staff_costs, wages=wages, other_overhead=overhead, op_cost=op_cost,
                 op_cost_per_m3_produced=round(op_cost / produced, 4), op_cost_per_m3_billed=round(op_cost / billed, 4),
                 op_cost_per_sales=round(op_cost / sales, 4))

        # Connection service levels and customer queries.
        fully_paid = new + (0 if zero else rng.randint(0, 4))
        days_to_connect = round(rng.uniform(14, 45 if p["coll"] < 80 else 28), 1)
        queries = round(active * rng.uniform(0.008, 0.016))
        r.update(days_to_quotation=round(rng.uniform(6, 21), 1), conn_fully_paid=fully_paid,
                 paid_up_applicants=fully_paid, days_to_connect=days_to_connect, connection_days=days_to_connect,
                 connectivity_rate=round(new / fully_paid * 100, 1) if fully_paid else 0.0,
                 queries_received=queries, time_to_resolve=round(rng.uniform(2, 9), 1),
                 response_time_avg=round(rng.uniform(4, 30), 1))

        _apply_case(scheme, (year, month), r)
        if not (scheme in CASES["stale"] and (year, month) > STALE_LAST_MONTH):
            rows.append(r)
    return rows


def _apply_case(scheme: str, period: tuple[int, int], r: dict) -> None:
    """Blank what a partial return did not enter (NULL means "not entered", never 0)."""
    if scheme not in CASES["partial"]:
        return
    for f in PARTIAL_STAFF_FIELDS:
        r[f] = None
    if period in PARTIAL_BILLING_MONTHS:
        for f in list(r):
            if f.startswith(("amt_billed", "cash_coll", "service_charge", "meter_rental")) or f in (
                    "cash_collected", "total_sales", "collection_rate", "collection_per_sales"):
                r[f] = None
    if period in PARTIAL_BREAKDOWN_MONTHS:
        for f in ("pipe_breakdowns", "pump_breakdowns", "pump_hours_lost", "pipe_pvc", *PVC_SIZES, *OTHER_SIZES,
                  *(s for sizes in OTHER_SIZES.values() for s in sizes)):
            r[f] = None


def build_rows() -> list[dict]:
    """Every return as a column -> value dict, in scheme then period order."""
    return [row for zone, scheme, conn0, profile in SCHEMES for row in _scheme_rows(zone, scheme, conn0, profile)]


def load(session, Record) -> int:
    """Insert every return, keeping "not entered" as NULL; the caller commits."""
    from sqlalchemy import update

    rows = build_rows()
    for row in rows:
        record = Record(**{k: v for k, v in row.items() if v is not None})
        session.add(record)
        session.flush()
        # The ORM substitutes column defaults for None; store a real NULL as the importer does.
        nulls = {k: None for k, v in row.items() if v is None}
        if nulls:
            session.execute(update(Record).where(Record.id == record.id).values(**nulls))
    return len(rows)


def manifest() -> dict:
    """What the dataset contains and which case each scheme represents, for review records."""
    rows = build_rows()
    return {
        "populated_fiscal_year": POPULATED_FY,
        "current_fiscal_year_months": [f"{y}-{m:02d}" for y, m in CURRENT_FY_MONTHS],
        "record_count": len(rows),
        "cases": CASES,
        "measured_zero_fields": list(MEASURED_ZERO_FIELDS),
        "partial": {"never_entered": list(PARTIAL_STAFF_FIELDS),
                    "billing_not_entered": [f"{y}-{m:02d}" for y, m in PARTIAL_BILLING_MONTHS],
                    "breakdowns_not_entered": [f"{y}-{m:02d}" for y, m in PARTIAL_BREAKDOWN_MONTHS]},
        "stale_last_return": "%d-%02d" % STALE_LAST_MONTH,
        "empty_scopes": ["September 2026 onwards (all schemes)", "Valley from January 2026"],
        "event": {"scheme": BURST[0], "month": "%d-%02d" % BURST[1],
                  "what": "trunk-main burst: breakdowns, losses and outage hours spike"},
    }
