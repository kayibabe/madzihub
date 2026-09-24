"""
schemas.py — Pydantic v2 models for API request/response validation.

RecordOut   : full row returned to client (camelCase for JS compatibility)
RecordIn    : shape expected when creating/updating a record
SummaryOut  : aggregated KPI response
FilterParams: query-param model shared across analytic endpoints
"""
from __future__ import annotations
from typing import Optional, List
from pydantic import BaseModel, ConfigDict, field_validator


# ── Serialisation helper ──────────────────────────────────────
class CamelBase(BaseModel):
    """Convert snake_case fields to camelCase for the JS frontend."""
    model_config = ConfigDict(
        populate_by_name=True,
        alias_generator=lambda s: "".join(
            w.capitalize() if i else w for i, w in enumerate(s.split("_"))
        ),
    )


# ── Full record (read) ────────────────────────────────────────
class RecordOut(CamelBase):
    id: int
    zone: str
    scheme: str
    month: str
    month_no: int
    year: int
    quarter: str

    vol_produced: float
    revenue_water: float
    nrw: float
    pct_nrw: float

    chem_cost: float
    power_cost: float
    power_kwh: float
    fuel_cost: float
    staff_costs: float
    op_cost: float

    new_connections: float
    active_customers: float
    active_postpaid: float
    active_prepaid: float
    pop_supplied: float
    pop_supply_area: float

    stuck_meters: float
    stuck_new: float
    stuck_repaired: float
    pipe_breakdowns: float
    pump_breakdowns: float

    supply_hours: float
    power_fail_hours: float

    cash_collected: float
    amt_billed: float
    service_charge: float
    meter_rental: float
    total_sales: float
    private_debtors: float
    public_debtors: float
    total_debtors: float
    collection_rate: float

    perm_staff: float
    temp_staff: float


# ── Create/update record ──────────────────────────────────────
class RecordIn(CamelBase):
    zone: str
    scheme: str
    month: str
    month_no: int
    year: int
    quarter: str

    vol_produced: float = 0.0
    revenue_water: float = 0.0
    nrw: float = 0.0
    pct_nrw: float = 0.0

    chem_cost: float = 0.0
    power_cost: float = 0.0
    power_kwh: float = 0.0
    fuel_cost: float = 0.0
    staff_costs: float = 0.0
    op_cost: float = 0.0

    new_connections: float = 0.0
    active_customers: float = 0.0
    active_postpaid: float = 0.0
    active_prepaid: float = 0.0
    pop_supplied: float = 0.0
    pop_supply_area: float = 0.0

    stuck_meters: float = 0.0
    stuck_new: float = 0.0
    stuck_repaired: float = 0.0
    pipe_breakdowns: float = 0.0
    pump_breakdowns: float = 0.0

    supply_hours: float = 0.0
    power_fail_hours: float = 0.0

    cash_collected: float = 0.0
    amt_billed: float = 0.0
    service_charge: float = 0.0
    meter_rental: float = 0.0
    total_sales: float = 0.0
    private_debtors: float = 0.0
    public_debtors: float = 0.0
    total_debtors: float = 0.0
    collection_rate: float = 0.0

    perm_staff: float = 0.0
    temp_staff: float = 0.0


# ── KPI summary ───────────────────────────────────────────────
class KPISummary(BaseModel):
    total_records: int
    vol_produced: float
    revenue_water: float
    nrw_pct: float
    active_customers: float
    new_connections: float
    cash_collected: float
    amt_billed: float
    collection_rate: float
    op_cost: float
    total_debtors: float


# ── Zone / scheme catalogue ───────────────────────────────────
class ZoneSchemes(BaseModel):
    zones: List[str]
    zone_schemes: dict[str, List[str]]


# ── Monthly pivot row ─────────────────────────────────────────
class PivotRow(BaseModel):
    month: str
    month_no: int
    zone: Optional[str] = None
    scheme: Optional[str] = None
    vol_produced: float = 0.0
    revenue_water: float = 0.0
    nrw: float = 0.0
    pct_nrw: float = 0.0
    active_customers: float = 0.0
    active_postpaid: float = 0.0
    active_prepaid: float = 0.0
    new_connections: float = 0.0
    cash_collected: float = 0.0
    amt_billed: float = 0.0
    op_cost: float = 0.0
    total_debtors: float = 0.0
    pipe_breakdowns: float = 0.0


# ── Import result ─────────────────────────────────────────────
class ImportResult(BaseModel):
    inserted: int
    skipped: int
    errors: List[str] = []
