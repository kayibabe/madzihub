"""
services/benchmarking.py
────────────────────────
Builds the SRWB Benchmarking Tool (WUP001–WUP107) as a reported table that
mirrors the institutional benchmarking workbook, but sourced live from the
`records` table instead of manual data entry.

Design
------
The benchmarking workbook lists 107 "WUP" indicators down the rows and the
twelve fiscal-year months (Apr → Mar) across the columns. This module turns
each indicator into a value per FY month, aggregated across the *selected*
zones / schemes, so the existing frontend report engine (`renderTable`) can
render it with the same quarter/annual rollups used everywhere else.

Honesty about coverage
----------------------
Only part of the 107 indicators can be sourced from the current schema.
Each indicator declares an explicit derivation (`agg` + `fields`) or is
flagged `manual` (derivable=False) — those render blank in the table and are
clearly labelled as requiring a separate data source. We never fabricate a
value for an indicator the database cannot support.

Aggregation semantics (matches the rest of the app)
---------------------------------------------------
  • "flow"  indicators (volumes, costs, counts in a month) → SUM across the
            selected records for that month         → frontend annType "sum"
  • "stock" indicators (population, customers, connection/debtor balances) →
            latest data-bearing row per (zone, scheme), then SUM → "last"
  • "rate"  indicators (avg supply hours) → non-zero average → "avg"

Reuses the helpers already battle-tested in routers/panels.py so this stays
consistent with the production/commercial report pages.
"""
from __future__ import annotations

from collections import defaultdict
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from app.database import Record
from app.routers.panels import _filter, _latest, _nz_sum, _nz_avg, _dedupe_rows
from app.utils import MONTHS_ORDER, csv_list, fy_label


# ── Indicator registry ───────────────────────────────────────────────────────
# Each entry is one of:
#   {"section": "<group heading>"}                      → visual group header
#   {"code","label","agg","fields","fmt","note"}        → an indicator row
#
# agg ∈ {"sum","last","avg", None}
#   None  → manual indicator (no source column); renders blank.
# fields  → record column(s) summed together to form the indicator.
# fmt     → frontend number format: "num" | "mwk" | "dec1"
#
# Keys emitted into the monthly payload are the lower-cased code (e.g. wup035).
# ─────────────────────────────────────────────────────────────────────────────

INDICATORS: List[Dict[str, Any]] = [
    {"section": "1 · Water Quality & Compliance"},
    {"code": "WUP001", "label": "Required tests — residual chlorine (as per requirement)", "agg": None},
    {"code": "WUP002", "label": "Required tests — bacteriological (as per guideline)",      "agg": None},
    {"code": "WUP003", "label": "Tests conducted (bacteriological)",                          "agg": None},
    {"code": "WUP004", "label": "Tests meeting standards (bacteriological)",                  "agg": None},
    {"code": "WUP005", "label": "Total water samples tested",                                 "agg": None},
    {"code": "WUP006", "label": "Total compliant water samples",                              "agg": None},
    {"code": "WUP007", "label": "Samples with turbidity (≤5 NTU)",                            "agg": None},
    {"code": "WUP008", "label": "Samples with turbidity > 5 NTU",                             "agg": None},

    {"section": "2 · Customer Service"},
    {"code": "WUP009", "label": "Customers fully paid (new connection)",     "agg": "sum",  "fields": ["conn_fully_paid"],   "fmt": "num"},
    {"code": "WUP010", "label": "Days to connect fully-paid customers",      "agg": "sum",  "fields": ["days_to_connect"],   "fmt": "num", "note": "Aggregate days across schemes"},
    {"code": "WUP011", "label": "Customers applied for new connection",      "agg": "sum",  "fields": ["conn_applied"],      "fmt": "num"},
    {"code": "WUP012", "label": "Days taken to give a quotation",            "agg": "sum",  "fields": ["days_to_quotation"], "fmt": "num"},
    {"code": "WUP013", "label": "Total time taken to resolve queries",       "agg": "sum",  "fields": ["time_to_resolve"],   "fmt": "num"},
    {"code": "WUP014", "label": "Total queries received",                    "agg": "sum",  "fields": ["queries_received"],  "fmt": "num"},
    {"code": "WUP015", "label": "Hours of pumping failure",                  "agg": "sum",  "fields": ["pump_hours_lost"],   "fmt": "num"},
    {"code": "WUP016", "label": "Reported water interruptions",             "agg": None},
    {"code": "WUP017", "label": "Customer complaints resolved",             "agg": None},
    {"code": "WUP018", "label": "Customer satisfaction survey report",      "agg": None},
    {"code": "WUP019", "label": "Average daily supply (hours/day)",          "agg": "avg",  "fields": ["supply_hours"],      "fmt": "dec1", "note": "Non-zero scheme average, capped at 24h/day"},
    {"code": "WUP020", "label": "Customers supplied 24/7",                  "agg": None},

    {"section": "3 · Population, Sewerage & Sanitation"},
    {"code": "WUP021", "label": "Population served (water)",                 "agg": "last", "fields": ["pop_supplied"],     "fmt": "num"},
    {"code": "WUP022", "label": "Population in service area (water)",        "agg": "last", "fields": ["pop_supply_area"],  "fmt": "num"},
    {"code": "WUP023", "label": "Population served — sewerage",             "agg": None},
    {"code": "WUP024", "label": "Population in service area — sewerage",    "agg": None},
    {"code": "WUP025", "label": "Population served — sanitation (sewered + septic)", "agg": None},
    {"code": "WUP026", "label": "Population served — sewered sanitation",   "agg": None},
    {"code": "WUP027", "label": "Population served — non-sewered sanitation (NSS)",  "agg": None},
    {"code": "WUP028", "label": "NSS — population using septic tanks",      "agg": None},
    {"code": "WUP029", "label": "NSS — population using VIP",               "agg": None},
    {"code": "WUP030", "label": "NSS — population using pit latrines",      "agg": None},
    {"code": "WUP031", "label": "Number of sewage treatment plants",       "agg": None},
    {"code": "WUP032", "label": "Sewage treatment plant utilisation",      "agg": None},
    {"code": "WUP033", "label": "Number of faecal sludge treatment plants","agg": None},
    {"code": "WUP034", "label": "Faecal sludge treatment plant utilisation","agg": None},

    {"section": "4 · Water Production & Sales"},
    {"code": "WUP035", "label": "Volume of water produced",                 "agg": "sum", "fields": ["vol_produced"], "fmt": "num"},
    {"code": "WUP036", "label": "Volume of water sold",                     "agg": "sum", "fields": ["total_vol_billed_pp", "total_vol_billed_prepaid"], "fmt": "num"},
    {"code": "WUP037", "label": "Volume sold — residential direct connections", "agg": "sum", "fields": ["vol_billed_indiv_pp", "vol_billed_indiv_prepaid"], "fmt": "num"},
    {"code": "WUP038", "label": "Volume sold — public tap / standpipe",     "agg": "sum", "fields": ["vol_billed_cwp_pp", "vol_billed_cwp_prepaid"], "fmt": "num"},
    {"code": "WUP039", "label": "Volume sold — commercial / institutional", "agg": "sum", "fields": ["vol_billed_comm_pp", "vol_billed_comm_prepaid", "vol_billed_inst_pp", "vol_billed_inst_prepaid"], "fmt": "num"},
    {"code": "WUP040", "label": "Total number of pipe breaks",              "agg": "sum", "fields": ["pipe_breakdowns"], "fmt": "num"},
    {"code": "WUP041", "label": "Total length of water distribution network","agg": None},

    {"section": "5 · Operating Costs"},
    {"code": "WUP042", "label": "Total operating costs",                    "agg": "sum", "fields": ["op_cost"],      "fmt": "mwk"},
    {"code": "WUP043", "label": "Total staff cost",                         "agg": "sum", "fields": ["staff_costs"],  "fmt": "mwk"},
    {"code": "WUP044", "label": "Total energy costs",                       "agg": "sum", "fields": ["power_cost"],   "fmt": "mwk"},
    {"code": "WUP045", "label": "Total chemical costs",                     "agg": "sum", "fields": ["chem_cost"],    "fmt": "mwk"},
    {"code": "WUP058", "label": "Total maintenance of water works",         "agg": "sum", "fields": ["maintenance"],  "fmt": "mwk"},
    {"code": "WUP064", "label": "Cash operating expenses",                  "agg": None},
    {"code": "WUP073", "label": "Total costs",                              "agg": "sum", "fields": ["op_cost"],      "fmt": "mwk", "note": "Proxied by total operating cost"},
    {"code": "WUP085", "label": "Total W&WW operational expenses",          "agg": "sum", "fields": ["op_cost"],      "fmt": "mwk", "note": "Water-only; wastewater not yet tracked"},
    {"code": "WUP095", "label": "Total training cost",                      "agg": None},
    {"code": "WUP096", "label": "Total annual payroll",                     "agg": "sum", "fields": ["staff_costs", "wages"], "fmt": "mwk"},

    {"section": "6 · Connections"},
    {"code": "WUP046", "label": "New connections installed",                "agg": "sum",  "fields": ["new_connections"],   "fmt": "num"},
    {"code": "WUP047", "label": "Paid-up new water applicants",             "agg": "sum",  "fields": ["paid_up_applicants"],"fmt": "num"},
    {"code": "WUP077", "label": "Direct household water connections",       "agg": "last", "fields": ["conn_indiv_cfwd"],   "fmt": "num"},
    {"code": "WUP078", "label": "Public tap / standpipe connections",       "agg": "last", "fields": ["conn_cwp_cfwd"],     "fmt": "num"},
    {"code": "WUP079", "label": "Commercial / institutional connections",   "agg": "last", "fields": ["conn_comm_cfwd", "conn_inst_cfwd"], "fmt": "num"},
    {"code": "WUP080", "label": "Total metered connections",                "agg": "last", "fields": ["total_metered"],     "fmt": "num"},
    {"code": "WUP081", "label": "Total sewerage connections",               "agg": None},
    {"code": "WUP082", "label": "Total water & wastewater connections",     "agg": None},

    {"section": "7 · Revenue, Billing & Debtors"},
    {"code": "WUP048", "label": "Cash collected from Government",           "agg": None},
    {"code": "WUP049", "label": "Total amount billed to Government",        "agg": None},
    {"code": "WUP050", "label": "Opening Government debtors",               "agg": None},
    {"code": "WUP051", "label": "Cash collected from Private",              "agg": None},
    {"code": "WUP052", "label": "Total amount billed to Private",           "agg": None},
    {"code": "WUP053", "label": "Opening Private debtors",                  "agg": None},
    {"code": "WUP054", "label": "Total Government debtors",                 "agg": "last", "fields": ["public_debtors"],  "fmt": "mwk"},
    {"code": "WUP055", "label": "Total Government sales",                   "agg": None},
    {"code": "WUP056", "label": "Total Private debtors",                    "agg": "last", "fields": ["private_debtors"], "fmt": "mwk"},
    {"code": "WUP057", "label": "Total Private sales",                      "agg": None},
    {"code": "WUP059", "label": "Total sales (year 1)",                     "agg": "sum",  "fields": ["total_sales"],    "fmt": "mwk"},
    {"code": "WUP060", "label": "Total sales (year 0)",                     "agg": None},
    {"code": "WUP061", "label": "Total disconnected accounts",             "agg": "sum",  "fields": ["total_disconnected"], "fmt": "num"},
    {"code": "WUP062", "label": "Total number of customers",               "agg": "last", "fields": ["active_customers"], "fmt": "num"},
    {"code": "WUP063", "label": "Cash collected",                          "agg": "sum",  "fields": ["cash_collected"], "fmt": "mwk"},
    {"code": "WUP083", "label": "Total W&WW cash income / collections",    "agg": "sum",  "fields": ["cash_collected"], "fmt": "mwk", "note": "Water-only"},
    {"code": "WUP084", "label": "Total W&WW operating (billed) revenues",  "agg": "sum",  "fields": ["amt_billed"],     "fmt": "mwk", "note": "Water-only"},
    {"code": "WUP086", "label": "Cash collected (financial ratios)",       "agg": "sum",  "fields": ["cash_collected"], "fmt": "mwk"},
    {"code": "WUP087", "label": "Domestic billing",                        "agg": None},
    {"code": "WUP088", "label": "Average domestic bill ($/month)",         "agg": None},
    {"code": "WUP089", "label": "Average exchange rate ($)",               "agg": None},
    {"code": "WUP090", "label": "Domestic bill for 5 m³",                  "agg": None},
    {"code": "WUP091", "label": "Domestic bill for 30 m³",                 "agg": None},
    {"code": "WUP092", "label": "Earnings before interest and tax",        "agg": None},

    {"section": "8 · Balance Sheet & Financial Ratios"},
    {"code": "WUP065", "label": "Non-current assets",                       "agg": None},
    {"code": "WUP066", "label": "Current assets",                          "agg": None},
    {"code": "WUP067", "label": "Current liabilities",                     "agg": None},
    {"code": "WUP068", "label": "Total payable",                           "agg": None},
    {"code": "WUP069", "label": "Total purchases",                         "agg": None},
    {"code": "WUP070", "label": "Total current assets",                    "agg": None},
    {"code": "WUP071", "label": "Total current liabilities",              "agg": None},
    {"code": "WUP072", "label": "Acid test ratio",                         "agg": None},
    {"code": "WUP074", "label": "Tariff in year 0",                        "agg": None},
    {"code": "WUP075", "label": "Tariff in year 1",                        "agg": None},
    {"code": "WUP076", "label": "Inventory",                              "agg": None},

    {"section": "9 · Staffing & Human Resources"},
    {"code": "WUP093", "label": "Total number of staff",                   "agg": "last", "fields": ["perm_staff", "temp_staff"], "fmt": "num"},
    {"code": "WUP094", "label": "Total number of staff trained",           "agg": None},
    {"code": "WUP097", "label": "Full-time equivalent (FTE) employees",    "agg": None},
    {"code": "WUP098", "label": "Full-time employees who are women",       "agg": None},
    {"code": "WUP099", "label": "Full-time equivalent women employees",    "agg": None},
    {"code": "WUP100", "label": "Senior management (male)",                "agg": None},
    {"code": "WUP101", "label": "Senior management (female)",              "agg": None},
    {"code": "WUP102", "label": "Middle management (male)",                "agg": None},
    {"code": "WUP103", "label": "Middle management (female)",              "agg": None},
    {"code": "WUP104", "label": "Operations level (male)",                 "agg": None},
    {"code": "WUP105", "label": "Operations level (female)",               "agg": None},
    {"code": "WUP106", "label": "Staff who left within the year",          "agg": None},
    {"code": "WUP107", "label": "Total number of staff within the year",   "agg": None},
]


# Indicator rows only (no section markers) — convenience view.
def _indicator_rows() -> List[Dict[str, Any]]:
    return [i for i in INDICATORS if "code" in i]


# ── Per-month value computation ──────────────────────────────────────────────

def _value_for(ind: Dict[str, Any], month_rows: List[Record], latest_rows: List[Record]) -> Optional[float]:
    """Compute a single indicator's value for one month over the selection."""
    agg = ind.get("agg")
    if not agg:
        return None  # manual indicator → blank
    fields = ind["fields"]

    if agg == "sum":
        return round(sum(_nz_sum(month_rows, f) for f in fields), 2)

    if agg == "last":
        # Stock balance: latest data-bearing row per (zone, scheme), then sum.
        return round(sum(sum(getattr(r, f, 0) or 0 for f in fields) for r in latest_rows), 2)

    if agg == "avg":
        # Non-zero scheme average. supply_hours is stored as a monthly total
        # capped at 744h (31d×24h); convert to an average hours/day figure to
        # match the production/treatment report convention.
        if fields == ["supply_hours"]:
            return round(_nz_avg(month_rows, "supply_hours", cap=744) / 30.44, 1)
        vals = [_nz_avg(month_rows, f) for f in fields]
        vals = [v for v in vals if v]
        return round(sum(vals) / len(vals), 2) if vals else None

    return None


def build_monthly(rows: List[Record]) -> List[Dict[str, Any]]:
    """Return one payload dict per FY month: {month, has_data, wupNNN: value...}.

    Mirrors panels._monthly()'s has_data rule so empty stub months render blank
    consistently with the rest of the dashboard.
    """
    by_month: Dict[str, List[Record]] = defaultdict(list)
    for r in rows:
        by_month[r.month].append(r)

    inds = _indicator_rows()
    out: List[Dict[str, Any]] = []

    for month in MONTHS_ORDER:
        mr = by_month.get(month, [])
        if not mr:
            out.append({"month": month, "has_data": False})
            continue

        latest = _latest(mr)
        vol = _nz_sum(mr, "vol_produced")
        customers = sum((r.active_customers or 0) for r in latest)
        if vol == 0 and customers == 0:
            out.append({"month": month, "has_data": False})
            continue

        entry: Dict[str, Any] = {"month": month, "has_data": True}
        for ind in inds:
            v = _value_for(ind, mr, latest)
            if v is not None:
                entry[ind["code"].lower()] = v
        out.append(entry)

    return out


def build_benchmarking(
    zones: Optional[str],
    schemes: Optional[str],
    months: Optional[str],
    year: Optional[int],
    db: Session,
) -> Dict[str, Any]:
    """Full payload for the benchmarking report page."""
    rows = _filter(
        db.query(Record),
        csv_list(zones), csv_list(schemes), csv_list(months), year,
    ).all()
    rows = _dedupe_rows(rows)

    monthly = build_monthly(rows)
    derivable = sum(1 for i in _indicator_rows() if i.get("agg"))
    total = len(_indicator_rows())

    return {
        "fiscal_year": fy_label(year) if year else None,
        "filters": {
            "zones": csv_list(zones) or [],
            "schemes": csv_list(schemes) or [],
        },
        "coverage": {"derivable": derivable, "manual": total - derivable, "total": total},
        "indicators": indicator_metadata(),
        "monthly": monthly,
    }


def indicator_metadata() -> List[Dict[str, Any]]:
    """Ordered metadata for the frontend to build its report rows.

    Section markers are preserved as {"type":"section","label":...} so the
    table renders grouped headings exactly like the other report pages.
    """
    meta: List[Dict[str, Any]] = []
    for item in INDICATORS:
        if "section" in item:
            meta.append({"type": "section", "label": item["section"]})
            continue
        agg = item.get("agg")
        meta.append({
            "code": item["code"],
            "field": item["code"].lower(),
            "label": f'{item["code"]} · {item["label"]}',
            "derivable": bool(agg),
            "ann_type": {"sum": "sum", "last": "last", "avg": "avg"}.get(agg, "sum"),
            "fmt": item.get("fmt", "num"),
            "note": item.get("note"),
        })
    return meta
