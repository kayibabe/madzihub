# SRWB Dashboard — New-Data Schema & Migration Plan

Scaffolding plan to light up the four placeholder areas that currently lack
underlying data:

1. **Water-quality compliance** (Operations / Board governance)
2. **HR establishment, leave & training** (Human Resource & Administration)
3. **Asset register, maintenance & capital projects** (Infrastructure + Finance)
4. **Historical fiscal years** (unlocks trends / YoY / SPC — *no schema change*)

> This is a **review artifact**. The model code below is ready to paste into
> `app/database.py` once the design is approved — it is **not yet wired in**, so
> no empty tables are created until you say go.

---

## 0. How migrations work in this app (important)

- **ORM:** SQLAlchemy, `Base = declarative_base()` in `app/database.py`.
- **No Alembic.** Schema is applied at startup by `create_tables()`:
  - `Base.metadata.create_all(bind=engine)` → **creates any new table** automatically.
  - `_ensure_record_columns()` → inspects the `records` table and **auto-adds any
    missing columns** via `ALTER TABLE ... ADD COLUMN` (SQLite-safe, idempotent).
- **Implication for this plan:**
  - New **tables** (HR, assets, maintenance, capital projects) → appear automatically on next restart. Zero migration risk.
  - New **columns on `records`** (water quality) → auto-added by the existing
    `_ensure_record_columns()` helper. Zero migration risk.
  - The only generalisation needed: `_ensure_record_columns()` is hard-coded to
    the `records` table. If we later add columns to *other* existing tables we
    should rename it to a generic `_ensure_columns(model)` — not needed for this plan.
- **Backwards compatible:** every new column/table is nullable or defaults to 0,
  so existing queries and the current dataset are unaffected.

---

## 1. Water-quality compliance  → add columns to `records`

**Grain:** monthly, per (zone, scheme) — same as all operational data, so it
reuses `_base()`, the zone/period filters, `_by_zone`/`_monthly`, and the
`_backfill_stock_balances` machinery for free. Recommended over a separate
table precisely because the Compliance page can then compute **real** pass
rates with the existing helpers (today it shows only chemical-input proxies).

```python
# ── Water quality & treatment compliance (monthly, per scheme) ──────────────
# Sample counts + compliant counts per regulated parameter. Compliance % is
# derived (compliant / samples). Inputs (chlorine_kg etc.) already exist.
samples_taken        = Column(Integer, default=0)   # total samples analysed in month
# Residual (free) chlorine — WHO 0.2–0.5 mg/L at point of use
cl_samples           = Column(Integer, default=0)
cl_compliant         = Column(Integer, default=0)
residual_cl_mg_l     = Column(Float,   default=0.0) # avg measured residual
# Turbidity — < 5 NTU (ideally < 1)
turbidity_samples    = Column(Integer, default=0)
turbidity_compliant  = Column(Integer, default=0)
turbidity_ntu        = Column(Float,   default=0.0) # avg measured
# Bacteriological (E. coli / total coliform) — 0 CFU / 100 mL
bact_samples         = Column(Integer, default=0)
bact_compliant       = Column(Integer, default=0)
# pH (6.5–8.5)
ph_samples           = Column(Integer, default=0)
ph_compliant         = Column(Integer, default=0)
```

**KPIs unlocked** (all [MUST] gaps from the audit):
- Overall water-quality compliance % = Σ compliant ÷ Σ samples
- Per-parameter pass rate (chlorine, turbidity, bacteriological, pH)
- Sampling coverage (samples taken vs target)
- Avg residual chlorine, avg turbidity

**Surfaces:** the existing **Compliance & Data Quality** page (replace the proxy
narrative with real pass rates) **and** a new Operations **"Water Quality &
Compliance"** page (currently a placeholder) + a Board governance headline.

**Endpoint:** extend `app/routers/compliance.py` (`build_water_quality_module`
in `services/governance.py`) to read these columns instead of proxies; add a
`/api/panels/water-quality` panel if a dedicated page is wanted.

**Data entry:** add a `WaterQuality` block to the monthly RawData workbook
(columns above) → flows through the existing upload pipeline → `_ensure_record_columns`.

---

## 2. Human Resource & Administration  → new table `hr_monthly`

**Grain:** monthly, per organisational unit (zone *or* HQ division). Kept
separate from `records` because HR is org-grained, not (zone, scheme) water-grained.
One table covers establishment + leave + training to keep the monthly upload simple.

```python
class HrMonthly(Base):
    """Monthly HR establishment, attendance and training, per org unit."""
    __tablename__ = "hr_monthly"
    id             = Column(Integer, primary_key=True, autoincrement=True)
    year           = Column(Integer, ForeignKey("fiscal_years.year"), nullable=False, index=True)
    month_no       = Column(Integer, nullable=False)
    month          = Column(String(12), nullable=False)
    unit           = Column(String(80), nullable=False)   # zone or HQ division
    # Establishment
    approved_posts = Column(Integer, default=0)           # funded establishment
    filled_posts   = Column(Integer, default=0)
    perm_staff     = Column(Integer, default=0)
    temp_staff     = Column(Integer, default=0)
    new_hires      = Column(Integer, default=0)
    separations    = Column(Integer, default=0)
    female_staff   = Column(Integer, default=0)           # for gender ratio
    # Leave & attendance (staff-days)
    working_days   = Column(Float, default=0.0)           # available staff-days
    days_present   = Column(Float, default=0.0)
    leave_days     = Column(Float, default=0.0)
    sick_days      = Column(Float, default=0.0)
    # Training
    staff_trained  = Column(Integer, default=0)
    training_days  = Column(Float, default=0.0)
    training_spend = Column(Numeric(15, 2, asdecimal=False), default=0.0)
    created_at     = Column(DateTime, default=datetime.utcnow)
    updated_at     = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    __table_args__ = (UniqueConstraint("year", "month_no", "unit", name="uq_hr_year_month_unit"),)
```

**KPIs unlocked:** vacancy rate (1 − filled/approved), establishment fill %,
staff turnover (separations/headcount), absenteeism (1 − present/available),
leave liability, **% staff trained**, training days/spend per head, gender ratio.

**Surfaces:** the HR placeholder items go live — **Payroll Overview** (pairs with
existing `wages`/`staff_costs`), **Leave & Attendance**, **Recruitment Pipeline**
(hires/separations), **Training & Development**. Also enables the **Payroll Cost
Ratio** KPI that was pulled (once revenue + payroll reconcile).

**Endpoint:** new `app/routers/hr.py` (`/api/hr/monthly`, `/api/hr/summary`) or
extend `report_generator.report_hra` to left-join `hr_monthly`.

---

## 3. Infrastructure / Asset management → 3 new tables

### 3a. `assets` — the asset register (entity table, not time-series)

```python
class Asset(Base):
    """Fixed-asset / network register entry."""
    __tablename__ = "assets"
    id                = Column(Integer, primary_key=True, autoincrement=True)
    asset_code        = Column(String(40), unique=True, nullable=False)
    asset_type        = Column(String(30), index=True)   # pipe_main, pump, treatment_works,
                                                          # reservoir, borehole, meter, vehicle, building
    zone              = Column(String(60), index=True)
    scheme            = Column(String(60), nullable=True)
    name              = Column(String(120))
    material          = Column(String(20), nullable=True) # PVC, GI, DI, HDPE, AC (for mains)
    diameter_mm       = Column(Integer, nullable=True)
    length_m          = Column(Float, nullable=True)       # for mains → network length
    install_year      = Column(Integer, nullable=True)
    expected_life_yrs = Column(Integer, nullable=True)
    condition_score   = Column(Integer, nullable=True)     # 1 excellent … 5 failed
    criticality       = Column(String(10), nullable=True)  # high / medium / low
    replacement_value = Column(Numeric(15, 2, asdecimal=False), nullable=True)
    status            = Column(String(20), default="in_service")  # in_service/standby/decommissioned
    notes             = Column(String(300), nullable=True)
    created_at        = Column(DateTime, default=datetime.utcnow)
    updated_at        = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
```

**KPIs unlocked:** asset register & count by type/zone, **total network length
(km mains)**, asset condition profile, criticality mix, replacement value,
remaining useful life, age profile. → Infrastructure **"Asset Register"** &
**"Plant & Equipment Health"** placeholders go live.

### 3b. `maintenance_monthly` — planned vs reactive (monthly, per zone)

```python
class MaintenanceMonthly(Base):
    __tablename__ = "maintenance_monthly"
    id            = Column(Integer, primary_key=True, autoincrement=True)
    year          = Column(Integer, ForeignKey("fiscal_years.year"), nullable=False, index=True)
    month_no      = Column(Integer, nullable=False)
    month         = Column(String(12), nullable=False)
    zone          = Column(String(60), nullable=False)
    planned_jobs  = Column(Integer, default=0)
    planned_done  = Column(Integer, default=0)
    reactive_jobs = Column(Integer, default=0)
    reactive_done = Column(Integer, default=0)
    backlog_jobs  = Column(Integer, default=0)
    downtime_hrs  = Column(Float,   default=0.0)
    maint_cost    = Column(Numeric(15, 2, asdecimal=False), default=0.0)
    created_at    = Column(DateTime, default=datetime.utcnow)
    updated_at    = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    __table_args__ = (UniqueConstraint("year", "month_no", "zone", name="uq_maint_year_month_zone"),)
```

**KPIs unlocked:** planned-vs-reactive ratio (PM maturity), maintenance backlog,
completion rate, mean time to repair, maintenance cost (fixes the unreliable
`records.maintenance` column, 0% populated today). → **"Maintenance Schedule"**.

### 3c. `capital_projects` (+ optional progress snapshots)

```python
class CapitalProject(Base):
    __tablename__ = "capital_projects"
    id               = Column(Integer, primary_key=True, autoincrement=True)
    project_code     = Column(String(40), unique=True, nullable=False)
    name             = Column(String(160), nullable=False)
    zone             = Column(String(60), index=True, nullable=True)
    category         = Column(String(40), nullable=True)   # network, treatment, storage, metering, NRW
    funder           = Column(String(80), nullable=True)
    contractor       = Column(String(120), nullable=True)
    budget           = Column(Numeric(15, 2, asdecimal=False), default=0.0)
    spend_to_date    = Column(Numeric(15, 2, asdecimal=False), default=0.0)
    physical_pct     = Column(Float, default=0.0)          # % physical completion
    start_date       = Column(String(10), nullable=True)
    planned_end_date = Column(String(10), nullable=True)
    actual_end_date  = Column(String(10), nullable=True)
    status           = Column(String(20), default="planning")  # planning/active/complete/stalled
    created_at       = Column(DateTime, default=datetime.utcnow)
    updated_at       = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

class CapitalProjectProgress(Base):   # optional — for spend S-curves
    __tablename__ = "capital_project_progress"
    id           = Column(Integer, primary_key=True, autoincrement=True)
    project_id   = Column(Integer, ForeignKey("capital_projects.id"), nullable=False, index=True)
    year         = Column(Integer, nullable=False)
    month_no     = Column(Integer, nullable=False)
    cum_spend    = Column(Numeric(15, 2, asdecimal=False), default=0.0)
    physical_pct = Column(Float, default=0.0)
    __table_args__ = (UniqueConstraint("project_id", "year", "month_no", name="uq_capp_proj_period"),)
```

**KPIs unlocked:** CAPEX delivery (% physical vs % spend), budget utilisation,
on-time / on-budget %, schedule/cost variance, S-curve. → Infrastructure
**"Capital Projects"** + Finance **"Capital Expenditure"** placeholders.

**Endpoint:** new `app/routers/infrastructure.py` (`/api/infra/assets`,
`/api/infra/maintenance`, `/api/infra/capital-projects`).

---

## 4. Historical fiscal years — NO schema change (data import only)

The schema already supports many years: `records.year`/`fiscal_year`, and the
`FiscalYear` registry is seeded FY2005/06–FY2029/30. Only **one FY (2025/26) is
currently loaded**, so every trend / YoY / SPC feature renders empty.

**Runbook (per historical year):**
1. Confirm the `fiscal_years` row exists (status `historical`). Seeded already; verify via `GET /api/catalogue/fiscal-years`.
2. Import that year's `RawData.xlsx` through the existing pipeline:
   - UI: **Administration → Upload Data** (admin), or
   - CLI: `python scripts/import_data.py --excel uploads/RawData_FY2024-25.xlsx --sheet DataEntry`
   - Rows land in `records` with the correct `year`/`month_no`.
3. (Optional, per FY) compute comparators via existing admin endpoints:
   - `POST /api/fiscal-years/{year}/budget`, `/zone-shares`, `/spc`.
4. Once ≥ 2 years of `records` exist, **YoY** (`report_board_pack`) and the trend
   / SPC charts populate automatically — no code change.

**Effort:** data sourcing + cleaning per year; ~1 upload each. Start with the
last 2–3 years for immediate YoY value.

---

## 5. Rollout order, effort & decisions

| # | Workstream | New data needed | Effort | Unlocks |
|---|---|---|---|---|
| 1 | **Historical FYs** | Prior-year RawData workbooks | Low (import only) | Trends, YoY, SPC across the whole app |
| 2 | **Water quality** | Monthly lab results | Low (Record columns) | Real Compliance page + Ops Water Quality + Board governance |
| 3 | **HR `hr_monthly`** | Monthly HR returns | Medium (1 table + endpoint + 3 pages) | Vacancy, turnover, absenteeism, training, payroll ratio |
| 4 | **Infrastructure** | Asset register + maintenance + CAPEX | High (3 tables + endpoints + pages) | Asset register, network length, PM ratio, CAPEX delivery |

**Decisions needed before implementation:**
1. **Water quality grain** — confirm `records` columns (recommended) vs a separate `water_quality` table.
2. **HR `unit`** — report by **zone** (matches water data) or by **HQ division/department** (truer HR view)? Drives the `unit` dimension.
3. **Asset register source** — is there an existing asset/GIS inventory to import, or is this first-time capture?
4. **Capital projects** — does Finance already track these in a system we can import, or manual entry?
5. **Data entry** — extend the monthly RawData workbook with new sheets (Water Quality, HR), plus standalone Assets & Capital-Projects registers maintained via an admin screen.

**Migration safety:** all additions are nullable/zero-default and applied
idempotently at startup (`create_all` + `_ensure_record_columns`). No existing
query, the current FY2025/26 dataset, or the live pages are affected until data
is entered. Placeholder pages already exist and will simply swap their
"awaiting data feed" panel for live content once each feed is populated.
