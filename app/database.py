"""
database.py — Full schema matching RawData.xlsx DataEntry sheet (222 cols),
              plus the User model for role-based authentication,
              and multi-FY support tables (FiscalYear, BudgetLine,
              BudgetZoneShare, SpcLimit).
"""
import os
from datetime import datetime
from sqlalchemy import (
    create_engine, Column, Integer, Float, Numeric, String,
    Boolean, DateTime, Index, UniqueConstraint, inspect, text, ForeignKey,
)
from sqlalchemy.orm import declarative_base, sessionmaker

from app.core.config import settings

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATABASE_URL = settings.database_url

_engine_kwargs = {"echo": False}
if DATABASE_URL.startswith("sqlite"):
    _engine_kwargs["connect_args"] = {"check_same_thread": False}

engine = create_engine(DATABASE_URL, **_engine_kwargs)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

class Record(Base):
    __tablename__ = "records"
    id                       = Column(Integer, primary_key=True, autoincrement=True)
    # Identity
    zone                     = Column(String(60), nullable=False, index=True)
    scheme                   = Column(String(80), nullable=False, index=True)
    fiscal_year              = Column(String(12), nullable=True)
    year                     = Column(Integer,    nullable=False)
    month_no                 = Column(Integer,    nullable=False)
    month                    = Column(String(20), nullable=False, index=True)
    quarter                  = Column(String(4),  nullable=False)
    # Water production & NRW  (volumes in m³ — Float is appropriate)
    vol_produced             = Column(Float, default=0.0)
    vol_billed_indiv_pp      = Column(Float, default=0.0)
    vol_billed_cwp_pp        = Column(Float, default=0.0)
    vol_billed_inst_pp       = Column(Float, default=0.0)
    vol_billed_comm_pp       = Column(Float, default=0.0)
    total_vol_billed_pp      = Column(Float, default=0.0)
    vol_billed_indiv_prepaid = Column(Float, default=0.0)
    vol_billed_cwp_prepaid   = Column(Float, default=0.0)
    vol_billed_inst_prepaid  = Column(Float, default=0.0)
    vol_billed_comm_prepaid  = Column(Float, default=0.0)
    total_vol_billed_prepaid = Column(Float, default=0.0)
    revenue_water            = Column(Numeric(15, 2, asdecimal=False), default=0.0)  # MWK
    nrw                      = Column(Float, default=0.0)
    pct_nrw                  = Column(Float, default=0.0)
    # Chemicals  (physical units — Float)
    chlorine_kg              = Column(Float, default=0.0)
    alum_kg                  = Column(Float, default=0.0)
    soda_ash_kg              = Column(Float, default=0.0)
    algae_floc_litres        = Column(Float, default=0.0)
    sud_floc_litres          = Column(Float, default=0.0)
    kmno4_kg                 = Column(Float, default=0.0)
    chem_cost                = Column(Numeric(15, 2, asdecimal=False), default=0.0)  # MWK
    chem_cost_per_m3         = Column(Float, default=0.0)   # MWK/m³ rate — Float ok
    chlorine_kg_per_m3       = Column(Float, default=0.0)
    alum_kg_per_m3           = Column(Float, default=0.0)
    soda_ash_kg_per_m3       = Column(Float, default=0.0)
    algae_floc_per_m3        = Column(Float, default=0.0)
    sud_floc_per_m3          = Column(Float, default=0.0)
    kmno4_per_m3             = Column(Float, default=0.0)
    # Water-quality compliance (monthly sampling — samples vs compliant counts).
    # Compliance % is derived (compliant / samples). All default 0 = "no samples
    # entered", which the Compliance page treats as N/A (falls back to proxies).
    wq_samples_taken         = Column(Integer, default=0)   # total samples analysed
    wq_cl_samples            = Column(Integer, default=0)   # free/residual chlorine
    wq_cl_compliant          = Column(Integer, default=0)
    wq_residual_cl_mg_l      = Column(Float,   default=0.0) # avg measured residual
    wq_turbidity_samples     = Column(Integer, default=0)   # turbidity < 5 NTU
    wq_turbidity_compliant   = Column(Integer, default=0)
    wq_turbidity_ntu         = Column(Float,   default=0.0) # avg measured
    wq_bact_samples          = Column(Integer, default=0)   # E. coli / coliform (0 CFU/100mL)
    wq_bact_compliant        = Column(Integer, default=0)
    wq_ph_samples            = Column(Integer, default=0)   # pH 6.5–8.5
    wq_ph_compliant          = Column(Integer, default=0)
    # Power
    power_kwh                = Column(Float, default=0.0)
    power_cost               = Column(Numeric(15, 2, asdecimal=False), default=0.0)  # MWK
    power_cost_per_m3        = Column(Float, default=0.0)   # MWK/m³ rate — Float ok
    power_kwh_per_m3         = Column(Float, default=0.0)
    # Transport & ops
    distances_km             = Column(Float, default=0.0)
    fuel_used_litres         = Column(Float, default=0.0)
    fuel_cost                = Column(Numeric(15, 2, asdecimal=False), default=0.0)  # MWK
    maintenance              = Column(Numeric(15, 2, asdecimal=False), default=0.0)  # MWK
    staff_costs              = Column(Numeric(15, 2, asdecimal=False), default=0.0)  # MWK
    wages                    = Column(Numeric(15, 2, asdecimal=False), default=0.0)  # MWK
    other_overhead           = Column(Numeric(15, 2, asdecimal=False), default=0.0)  # MWK
    op_cost                  = Column(Numeric(15, 2, asdecimal=False), default=0.0)  # MWK
    op_cost_per_m3_produced  = Column(Float, default=0.0)   # MWK/m³ rate — Float ok
    op_cost_per_m3_billed    = Column(Float, default=0.0)   # MWK/m³ rate — Float ok
    # Staffing
    perm_staff               = Column(Float, default=0.0)
    temp_staff               = Column(Float, default=0.0)
    staff_per_1000m3_12h     = Column(Float, default=0.0)
    # Connections aggregated
    all_conn_bfwd            = Column(Float, default=0.0)
    all_conn_applied         = Column(Float, default=0.0)
    new_connections          = Column(Float, default=0.0)
    all_conn_cfwd            = Column(Float, default=0.0)
    prepaid_meters_installed = Column(Float, default=0.0)
    conn_indiv_bfwd          = Column(Float, default=0.0)
    conn_indiv_applied_pp    = Column(Float, default=0.0)
    conn_indiv_done_pp       = Column(Float, default=0.0)
    conn_indiv_done_prepaid  = Column(Float, default=0.0)
    conn_indiv_total_done    = Column(Float, default=0.0)
    conn_indiv_cfwd          = Column(Float, default=0.0)
    conn_inst_bfwd           = Column(Float, default=0.0)
    conn_inst_applied_pp     = Column(Float, default=0.0)
    conn_inst_done_pp        = Column(Float, default=0.0)
    conn_inst_done_prepaid   = Column(Float, default=0.0)
    conn_inst_total_done     = Column(Float, default=0.0)
    conn_inst_cfwd           = Column(Float, default=0.0)
    conn_comm_bfwd           = Column(Float, default=0.0)
    conn_comm_applied_pp     = Column(Float, default=0.0)
    conn_comm_done_pp        = Column(Float, default=0.0)
    conn_comm_done_prepaid   = Column(Float, default=0.0)
    conn_comm_total_done     = Column(Float, default=0.0)
    conn_comm_cfwd           = Column(Float, default=0.0)
    conn_cwp_bfwd            = Column(Float, default=0.0)
    conn_cwp_applied_pp      = Column(Float, default=0.0)
    conn_cwp_done_pp         = Column(Float, default=0.0)
    conn_cwp_done_prepaid    = Column(Float, default=0.0)
    conn_cwp_total_done      = Column(Float, default=0.0)
    conn_cwp_cfwd            = Column(Float, default=0.0)
    # Disconnections
    disconnected_individual  = Column(Float, default=0.0)
    disconnected_inst        = Column(Float, default=0.0)
    disconnected_commercial  = Column(Float, default=0.0)
    disconnected_cwp         = Column(Float, default=0.0)
    total_disconnected       = Column(Float, default=0.0)
    # Active consumers — postpaid
    active_post_individual   = Column(Float, default=0.0)
    active_post_inst         = Column(Float, default=0.0)
    active_post_commercial   = Column(Float, default=0.0)
    active_post_cwp          = Column(Float, default=0.0)
    active_postpaid          = Column(Float, default=0.0)
    # Active consumers — prepaid
    active_prep_individual   = Column(Float, default=0.0)
    active_prep_inst         = Column(Float, default=0.0)
    active_prep_commercial   = Column(Float, default=0.0)
    active_prep_cwp          = Column(Float, default=0.0)
    active_prepaid           = Column(Float, default=0.0)
    # Active totals
    active_customers         = Column(Float, default=0.0)
    total_metered            = Column(Float, default=0.0)
    # Population
    pop_supply_area          = Column(Float, default=0.0)
    pop_supplied             = Column(Float, default=0.0)
    pct_pop_supplied         = Column(Float, default=0.0)
    # Stuck meters aggregated
    stuck_meters             = Column(Float, default=0.0)
    stuck_new                = Column(Float, default=0.0)
    stuck_repaired           = Column(Float, default=0.0)
    stuck_replaced           = Column(Float, default=0.0)
    all_stuck_cfwd           = Column(Float, default=0.0)
    stuck_indiv_bfwd         = Column(Float, default=0.0)
    stuck_indiv_new          = Column(Float, default=0.0)
    stuck_indiv_repaired     = Column(Float, default=0.0)
    stuck_indiv_replaced     = Column(Float, default=0.0)
    stuck_indiv_cfwd         = Column(Float, default=0.0)
    stuck_inst_bfwd          = Column(Float, default=0.0)
    stuck_inst_new           = Column(Float, default=0.0)
    stuck_inst_repaired      = Column(Float, default=0.0)
    stuck_inst_replaced      = Column(Float, default=0.0)
    stuck_inst_cfwd          = Column(Float, default=0.0)
    stuck_comm_bfwd          = Column(Float, default=0.0)
    stuck_comm_new           = Column(Float, default=0.0)
    stuck_comm_repaired      = Column(Float, default=0.0)
    stuck_comm_replaced      = Column(Float, default=0.0)
    stuck_comm_cfwd          = Column(Float, default=0.0)
    stuck_cwp_bfwd           = Column(Float, default=0.0)
    stuck_cwp_new            = Column(Float, default=0.0)
    stuck_cwp_repaired       = Column(Float, default=0.0)
    stuck_cwp_replaced       = Column(Float, default=0.0)
    stuck_cwp_cfwd           = Column(Float, default=0.0)
    # Pipe breakdowns — material totals
    pipe_pvc                 = Column(Float, default=0.0)
    pipe_gi                  = Column(Float, default=0.0)
    pipe_di                  = Column(Float, default=0.0)
    pipe_hdpe_ac             = Column(Float, default=0.0)
    pipe_breakdowns          = Column(Float, default=0.0)
    # PVC breakdowns by pipe size
    pvc_20mm                 = Column(Float, default=0.0)
    pvc_25mm                 = Column(Float, default=0.0)
    pvc_32mm                 = Column(Float, default=0.0)
    pvc_40mm                 = Column(Float, default=0.0)
    pvc_50mm                 = Column(Float, default=0.0)
    pvc_63mm                 = Column(Float, default=0.0)
    pvc_75mm                 = Column(Float, default=0.0)
    pvc_90mm                 = Column(Float, default=0.0)
    pvc_110mm                = Column(Float, default=0.0)
    pvc_160mm                = Column(Float, default=0.0)
    pvc_200mm                = Column(Float, default=0.0)
    pvc_250mm                = Column(Float, default=0.0)
    pvc_315mm                = Column(Float, default=0.0)
    gi_15mm                  = Column(Float, default=0.0)
    gi_20mm                  = Column(Float, default=0.0)
    gi_25mm                  = Column(Float, default=0.0)
    gi_40mm                  = Column(Float, default=0.0)
    gi_50mm                  = Column(Float, default=0.0)
    gi_75mm                  = Column(Float, default=0.0)
    gi_100mm                 = Column(Float, default=0.0)
    gi_150mm                 = Column(Float, default=0.0)
    gi_200mm                 = Column(Float, default=0.0)
    di_150mm                 = Column(Float, default=0.0)
    di_200mm                 = Column(Float, default=0.0)
    di_250mm                 = Column(Float, default=0.0)
    di_300mm                 = Column(Float, default=0.0)
    di_350mm                 = Column(Float, default=0.0)
    di_525mm                 = Column(Float, default=0.0)
    hdpe_20mm                = Column(Float, default=0.0)
    hdpe_25mm                = Column(Float, default=0.0)
    hdpe_32mm                = Column(Float, default=0.0)
    hdpe_50mm                = Column(Float, default=0.0)
    ac_50mm                  = Column(Float, default=0.0)
    ac_75mm                  = Column(Float, default=0.0)
    ac_100mm                 = Column(Float, default=0.0)
    ac_150mm                 = Column(Float, default=0.0)
    # Pumps & supply hours
    pump_breakdowns          = Column(Float, default=0.0)
    pump_hours_lost          = Column(Float, default=0.0)
    supply_hours             = Column(Float, default=0.0)
    power_fail_hours         = Column(Float, default=0.0)
    # Development lines
    dev_lines_32mm           = Column(Float, default=0.0)
    dev_lines_50mm           = Column(Float, default=0.0)
    dev_lines_63mm           = Column(Float, default=0.0)
    dev_lines_90mm           = Column(Float, default=0.0)
    dev_lines_110mm          = Column(Float, default=0.0)
    dev_lines_total          = Column(Float, default=0.0)
    # Cash collected  (MWK — Numeric)
    cash_coll_pp             = Column(Numeric(15, 2, asdecimal=False), default=0.0)
    cash_coll_prepaid        = Column(Numeric(15, 2, asdecimal=False), default=0.0)
    cash_collected           = Column(Numeric(15, 2, asdecimal=False), default=0.0)
    cash_coll_indiv_pp       = Column(Numeric(15, 2, asdecimal=False), default=0.0)
    cash_coll_cwp_pp         = Column(Numeric(15, 2, asdecimal=False), default=0.0)
    cash_coll_comm_pp        = Column(Numeric(15, 2, asdecimal=False), default=0.0)
    cash_coll_inst_pp        = Column(Numeric(15, 2, asdecimal=False), default=0.0)
    cash_coll_indiv_prepaid  = Column(Numeric(15, 2, asdecimal=False), default=0.0)
    cash_coll_cwp_prepaid    = Column(Numeric(15, 2, asdecimal=False), default=0.0)
    cash_coll_comm_prepaid   = Column(Numeric(15, 2, asdecimal=False), default=0.0)
    cash_coll_inst_prepaid   = Column(Numeric(15, 2, asdecimal=False), default=0.0)
    # Amounts billed  (MWK — Numeric)
    amt_billed_pp            = Column(Numeric(15, 2, asdecimal=False), default=0.0)
    amt_billed_prepaid       = Column(Numeric(15, 2, asdecimal=False), default=0.0)
    amt_billed               = Column(Numeric(15, 2, asdecimal=False), default=0.0)
    amt_billed_indiv_pp      = Column(Numeric(15, 2, asdecimal=False), default=0.0)
    amt_billed_cwp_pp        = Column(Numeric(15, 2, asdecimal=False), default=0.0)
    amt_billed_inst_pp       = Column(Numeric(15, 2, asdecimal=False), default=0.0)
    amt_billed_comm_pp       = Column(Numeric(15, 2, asdecimal=False), default=0.0)
    amt_billed_indiv_prepaid = Column(Numeric(15, 2, asdecimal=False), default=0.0)
    amt_billed_cwp_prepaid   = Column(Numeric(15, 2, asdecimal=False), default=0.0)
    amt_billed_inst_prepaid  = Column(Numeric(15, 2, asdecimal=False), default=0.0)
    amt_billed_comm_prepaid  = Column(Numeric(15, 2, asdecimal=False), default=0.0)
    # Charges  (MWK — Numeric)
    service_charge              = Column(Numeric(15, 2, asdecimal=False), default=0.0)
    meter_rental                = Column(Numeric(15, 2, asdecimal=False), default=0.0)
    total_sales                 = Column(Numeric(15, 2, asdecimal=False), default=0.0)
    service_charge_individual   = Column(Numeric(15, 2, asdecimal=False), default=0.0)
    service_charge_cwp          = Column(Numeric(15, 2, asdecimal=False), default=0.0)
    service_charge_institutions = Column(Numeric(15, 2, asdecimal=False), default=0.0)
    service_charge_commercial   = Column(Numeric(15, 2, asdecimal=False), default=0.0)
    meter_rental_individual     = Column(Numeric(15, 2, asdecimal=False), default=0.0)
    meter_rental_cwp            = Column(Numeric(15, 2, asdecimal=False), default=0.0)
    meter_rental_institutions   = Column(Numeric(15, 2, asdecimal=False), default=0.0)
    meter_rental_commercial     = Column(Numeric(15, 2, asdecimal=False), default=0.0)
    # Debtors  (MWK — Numeric)
    private_debtors          = Column(Numeric(15, 2, asdecimal=False), default=0.0)
    public_debtors           = Column(Numeric(15, 2, asdecimal=False), default=0.0)
    total_debtors            = Column(Numeric(15, 2, asdecimal=False), default=0.0)
    # Financial KPIs  (ratios/rates — Float ok)
    op_cost_per_sales        = Column(Float, default=0.0)
    collection_rate          = Column(Float, default=0.0)
    collection_per_sales     = Column(Float, default=0.0)
    # Connection performance
    conn_applied             = Column(Float, default=0.0)
    days_to_quotation        = Column(Float, default=0.0)
    conn_fully_paid          = Column(Float, default=0.0)
    paid_up_applicants       = Column(Float, default=0.0)
    days_to_connect          = Column(Float, default=0.0)
    connection_days          = Column(Float, default=0.0)
    connectivity_rate        = Column(Float, default=0.0)
    # Query performance
    queries_received         = Column(Float, default=0.0)
    time_to_resolve          = Column(Float, default=0.0)
    response_time_avg        = Column(Float, default=0.0)

    __table_args__ = (
        # Canonical business key for one reporting period.
        # Use month_no (INTEGER) instead of month (TEXT) so legacy rows like
        # month="4" and canonical rows like month="April" cannot coexist.
        UniqueConstraint(
            "zone", "scheme", "year", "month_no",
            name="uq_zone_scheme_year_monthno",
        ),
        # Full business-key covering index — used when zone+scheme are filtered.
        Index(
            "ix_zone_scheme_year_monthno",
            "zone", "scheme", "year", "month_no",
        ),
        # Dedicated FY-span index — used by the OR(year==FY-1 AND month_no>=4,
        # year==FY AND month_no<=3) filter when zone/scheme are NOT constrained
        # (e.g. dashboard overview, budget variance, analytics aggregations).
        Index(
            "ix_record_year_month",
            "year", "month_no",
        ),
    )

# ── Multi-FY support tables ────────────────────────────────────────────────

class FiscalYear(Base):
    """
    Registry of all fiscal years the system knows about.
    Populated at startup with historical (FY2005/06–FY2024/25),
    current (FY2025/26), and future (FY2026/27–FY2029/30) years.

    `year`  = FY end year  (e.g. 2026 = FY2025/26, Apr-2025 → Mar-2026)
    `status` = "historical" | "current" | "future"
    """
    __tablename__ = "fiscal_years"

    year           = Column(Integer, primary_key=True)      # e.g. 2026
    label          = Column(String(12), nullable=False)     # "FY2025/26"
    start_date     = Column(String(10), nullable=False)     # "2025-04-01"
    end_date       = Column(String(10), nullable=False)     # "2026-03-31"
    status         = Column(String(12), nullable=False, default="historical")
    tariff_per_m3  = Column(Float, nullable=True)           # MK/m³ (None = TBD)
    notes          = Column(String(500), nullable=True)
    created_at     = Column(DateTime, default=datetime.utcnow)
    updated_at     = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class BudgetLine(Base):
    """
    One row per approved budget line item per fiscal year.
    Replaces the 87 hardcoded constants that previously lived in budget.py.

    `category` keys (snake_case) match the old Python constant names minus
    the BUD_ prefix, e.g. "water_sales", "electricity", "vol_produced".
    """
    __tablename__ = "budget_lines"

    id         = Column(Integer, primary_key=True, autoincrement=True)
    year       = Column(Integer, ForeignKey("fiscal_years.year"), nullable=False, index=True)
    category   = Column(String(60), nullable=False)
    value      = Column(Numeric(15, 2, asdecimal=False), nullable=False, default=0.0)
    unit       = Column(String(20), nullable=True)   # "MWK", "m3", "pct", "count", "hrs", "km"
    notes      = Column(String(300), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (
        UniqueConstraint("year", "category", name="uq_budget_year_category"),
    )


class BudgetZoneShare(Base):
    """
    IPSAS 18 proportional allocation shares per zone per fiscal year.
    Derived from each FY's actual revenue/volume/connection data and
    stored here once calculated, so the budget engine uses the correct
    vintage of shares for each year.
    """
    __tablename__ = "budget_zone_shares"

    id          = Column(Integer, primary_key=True, autoincrement=True)
    year        = Column(Integer, ForeignKey("fiscal_years.year"), nullable=False, index=True)
    zone        = Column(String(60), nullable=False)
    rev_share   = Column(Float, nullable=False, default=0.0)
    vol_share   = Column(Float, nullable=False, default=0.0)
    conn_share  = Column(Float, nullable=False, default=0.0)
    created_at  = Column(DateTime, default=datetime.utcnow)
    updated_at  = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (
        UniqueConstraint("year", "zone", name="uq_zone_share_year_zone"),
    )


class SpcLimit(Base):
    """
    ISO 7870-2 Shewhart SPC control limits per metric per fiscal year.
    Computed from that year's actuals and stored here so the budget
    variance page can display historically accurate control charts.
    """
    __tablename__ = "spc_limits"

    id     = Column(Integer, primary_key=True, autoincrement=True)
    year   = Column(Integer, ForeignKey("fiscal_years.year"), nullable=False, index=True)
    metric = Column(String(40), nullable=False)   # e.g. "nrw_pct", "vol_prod"
    mean   = Column(Float, nullable=True)
    std    = Column(Float, nullable=True)
    ucl2   = Column(Float, nullable=True)
    lcl2   = Column(Float, nullable=True)
    ucl3   = Column(Float, nullable=True)
    lcl3   = Column(Float, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (
        UniqueConstraint("year", "metric", name="uq_spc_year_metric"),
    )


# ── Organisation profile (singleton row, id always = 1) ──────
class OrgProfile(Base):
    __tablename__ = "org_profile"

    id                 = Column(Integer, primary_key=True, default=1)
    org_name           = Column(String(120),  default="Southern Region Water Board")
    short_name         = Column(String(20),   default="SRWB")
    registration_no    = Column(String(60),   nullable=True)
    regulator          = Column(String(120),  nullable=True)
    country            = Column(String(60),   default="Malawi")
    reporting_currency = Column(String(10),   default="MWK")
    service_area_km2   = Column(Float,        nullable=True)
    population_served  = Column(Integer,      nullable=True)
    contact_email      = Column(String(120),  nullable=True)
    contact_phone      = Column(String(40),   nullable=True)
    website            = Column(String(200),  nullable=True)
    updated_at         = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


# ── Activity log ──────────────────────────────────────────────
class ActivityLog(Base):
    __tablename__ = "activity_log"

    id         = Column(Integer, primary_key=True, autoincrement=True)
    username   = Column(String(60),  nullable=False, index=True)
    action     = Column(String(60),  nullable=False)
    detail     = Column(String(500), nullable=True)
    ip_address = Column(String(60),  nullable=True)
    logged_at  = Column(DateTime, default=datetime.utcnow, index=True)


# ── Upload history log ────────────────────────────────────────
class UploadLog(Base):
    __tablename__ = "upload_log"

    id            = Column(Integer, primary_key=True, autoincrement=True)
    uploaded_by   = Column(String(60),  nullable=False)
    filename      = Column(String(200), nullable=True)
    period        = Column(String(30),  nullable=True)   # e.g. "Apr 2026 – Mar 2027"
    rows_inserted = Column(Integer, default=0)
    rows_updated  = Column(Integer, default=0)
    rows_skipped  = Column(Integer, default=0)
    rows_errored  = Column(Integer, default=0)
    logged_at     = Column(DateTime, default=datetime.utcnow, index=True)


# ── User model (authentication & RBAC) ───────────────────────
class User(Base):
    """
    Application user for role-based access control.

    Roles:
      admin   — full access: view, export, upload Excel, manage users
      user    — view + export CSV; no upload; no user management
      viewer  — read-only; no export; no upload; no user management
    """
    __tablename__ = "users"

    id            = Column(Integer, primary_key=True, autoincrement=True)
    username      = Column(String(60), unique=True, nullable=False, index=True)
    full_name     = Column(String(120), nullable=True)
    password_hash = Column(String(128), nullable=False)
    role          = Column(String(20), nullable=False, default="user")
    is_active     = Column(Boolean, nullable=False, default=True)
    created_at    = Column(DateTime, default=datetime.utcnow)
    created_by    = Column(String(60), nullable=True)
    last_login    = Column(DateTime, nullable=True)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

def create_tables():
    Base.metadata.create_all(bind=engine)
    _ensure_record_columns()
    _ensure_table_columns(UploadLog)
    _ensure_table_columns(ActivityLog)
    _ensure_table_columns(OrgProfile)

def recreate_tables():
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)


def _default_sql(column):
    default = getattr(column.default, "arg", None)
    if default is None or callable(default):
        return ""
    if isinstance(default, str):
        return f" DEFAULT '{default}'"
    if isinstance(default, bool):
        return f" DEFAULT {1 if default else 0}"
    return f" DEFAULT {default}"


def _ensure_table_columns(model):
    """Add any columns present in `model` that are missing from the live DB table."""
    table_name = model.__tablename__
    inspector = inspect(engine)
    if table_name not in inspector.get_table_names():
        return
    existing = {col["name"] for col in inspector.get_columns(table_name)}
    with engine.begin() as conn:
        for column in model.__table__.columns:
            if column.name in existing or column.primary_key:
                continue
            col_type = column.type.compile(dialect=engine.dialect)
            nullable = "" if column.nullable else " NOT NULL"
            default_sql = _default_sql(column)
            conn.execute(text(
                f"ALTER TABLE {table_name} ADD COLUMN {column.name} {col_type}{nullable}{default_sql}"
            ))


def _ensure_record_columns():
    inspector = inspect(engine)
    if "records" not in inspector.get_table_names():
        return
    existing = {col["name"] for col in inspector.get_columns("records")}
    with engine.begin() as conn:
        for column in Record.__table__.columns:
            if column.name in existing or column.primary_key:
                continue
            col_type = column.type.compile(dialect=engine.dialect)
            nullable = "" if column.nullable else " NOT NULL"
            default_sql = _default_sql(column)
            conn.execute(text(
                f"ALTER TABLE records ADD COLUMN {column.name} {col_type}{nullable}{default_sql}"
            ))

# ── Multi-FY support tables ────────────────────────────────────────────────
