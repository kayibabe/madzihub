# SRWB Operations Dashboard

**Southern Region Water Board — Internal Operations & Performance Dashboard**

A full-stack web application for monitoring and analysing monthly operational and financial KPIs across SRWB's five zones and their constituent schemes. Built on FastAPI + SQLite with a single-page HTML/JS frontend.

---

## Table of Contents

1. [Overview](#overview)
2. [Architecture](#architecture)
3. [Project Structure](#project-structure)
4. [Tech Stack](#tech-stack)
5. [Data Model](#data-model)
6. [Setup & Installation](#setup--installation)
7. [Running the Application](#running-the-application)
8. [API Reference](#api-reference)
9. [Data Ingestion](#data-ingestion)
10. [KPI Framework](#kpi-framework)
11. [Authentication & Roles](#authentication--roles)
12. [Known Issues & Tech Debt](#known-issues--tech-debt)
13. [Development Notes](#development-notes)

---

## Overview

The dashboard aggregates monthly operational data submitted from five zones — **Liwonde, Mangochi, Mulanje, Ngabu, and Zomba** — each containing multiple schemes. Data is organised by SRWB's **April–March financial year** with quarterly breakdowns.

Key capability areas:

- **Production & NRW** — volume produced, revenue water, non-revenue water (absolute and percentage)
- **Financial** — billing, cash collections, operating costs, debtors (private and public)
- **Customers** — active connections (postpaid and prepaid), new connections, disconnections, meter status
- **Infrastructure** — pipe breakdowns, pump failures, supply hours, pipeline development
- **IWA/IBNET Performance Indicators** — operating ratio (Fn25), days sales outstanding (Fn23), NRW financial cost, energy intensity (Ee01), population coverage, revenue per connection (Cu01), and more


---

## Architecture

```
Browser (SPA)
    │  HTTP/JSON
    ▼
FastAPI app  (app/main.py)
    ├── JWT auth middleware
    ├── Routers (analytics, panels, records, upload, reports, insights, …)
    ├── Services (excel_parser, kpi_engine, forecast_engine, narrative_engine, …)
    └── SQLAlchemy ORM
            │
            ▼
        SQLite  (data/srwb.db)
```

The frontend (`app/static/index.html`) is a self-contained single-page application served directly by FastAPI. It uses Chart.js for visualisation and communicates exclusively with the local API — there are no external service dependencies at runtime.

The API base URL is injected at request time by the server (`__API_BASE__` placeholder replacement), so the frontend works correctly whether accessed on localhost or a LAN address.

---

## Project Structure

```
D:\WebApps\opsapp\
├── app/
│   ├── main.py                  # FastAPI app entry point, lifespan, CORS, router registration
│   ├── auth.py                  # JWT generation/validation, role enforcement, default admin bootstrap
│   ├── database.py              # SQLAlchemy engine, Record model (222 columns), User model
│   ├── schemas.py               # Pydantic request/response schemas
│   ├── core/
│   │   ├── config.py            # Settings (env vars, secrets)
│   │   ├── logging.py           # Structured logging setup
│   │   └── security.py          # Password hashing (bcrypt)
│   ├── routers/
│   │   ├── analytics.py         # Aggregated KPI endpoints + IWA/IBNET indicators
│   │   ├── panels.py            # Zone/scheme panel data (latest-per-scheme logic)
│   │   ├── records.py           # Raw record CRUD + CSV export
│   │   ├── upload.py            # Excel ingestion pipeline (preview → commit)
│   │   ├── reports.py           # Formatted report endpoints
│   │   ├── catalogue.py         # Zone/scheme catalogue
│   │   ├── insights.py          # Narrative insights router
│   │   └── users.py             # User management + auth router
│   ├── services/
│   │   ├── excel_parser.py      # openpyxl-based parser; anomaly detection, conflict detection
│   │   ├── kpi_engine.py        # KPI computation logic
│   │   ├── forecast_engine.py   # Time-series forecasting
│   │   ├── insights_engine.py   # AI narrative generation
│   │   ├── narrative_engine.py  # Natural-language summary builder
│   │   ├── audit_log.py         # Upload and action audit trail
│   │   └── jobs.py              # Background task management
│   ├── ai/
│   │   └── anomaly.py           # Statistical anomaly detection
│   └── static/
│       └── index.html           # Single-page frontend (Chart.js, vanilla JS)
├── data/
│   └── srwb.db                  # SQLite database (gitignored)
├── uploads/
│   └── RawData.xlsx             # Source Excel file (gitignored)
├── scripts/
│   ├── import_data.py           # CLI bulk import from Excel
│   └── migrate_add_unique_constraint.py  # DB migration: adds UniqueConstraint on records
├── tests/
│   └── test_upload.py           # Upload pipeline test suite (40 tests)
├── run.bat                      # Windows startup script
├── start.sh                     # Linux/macOS startup script
├── requirements.txt             # Python dependencies
└── .gitignore
```


---

## Tech Stack

| Layer | Technology |
|---|---|
| API framework | FastAPI 0.100+ |
| ASGI server | Uvicorn |
| Database | SQLite (WAL mode) via SQLAlchemy ORM |
| Auth | JWT (python-jose) + bcrypt password hashing |
| Excel ingestion | openpyxl |
| Rate limiting | slowapi |
| Frontend | Vanilla JS, Chart.js |
| Forecasting | numpy-based time series |
| AI narratives | Groq API (key stored in `data/groq.key`) |
| Python version | CPython 3.14 |

---

## Data Model

### Record

The core `records` table has **222 columns** mapping directly to the DataEntry sheet of `RawData.xlsx`. Key column groups:

| Group | Key columns |
|---|---|
| Identity | `zone`, `scheme`, `fiscal_year`, `year`, `month_no`, `month`, `quarter` |
| Production | `vol_produced`, `revenue_water`, `nrw`, `pct_nrw` |
| Billing | `amt_billed`, `amt_billed_pp`, `amt_billed_prepaid`, `total_sales` |
| Collections | `cash_collected`, `cash_coll_pp`, `cash_coll_prepaid` |
| Operating costs | `op_cost`, `chem_cost`, `power_cost`, `fuel_cost`, `staff_costs`, `maintenance` |
| Customers | `active_customers`, `active_postpaid`, `active_prepaid`, `total_metered` |
| Connections | `new_connections`, `total_disconnected`, `prepaid_meters_installed` |
| Debtors | `total_debtors`, `private_debtors`, `public_debtors` |
| Infrastructure | `pipe_breakdowns`, `pump_breakdowns`, `supply_hours`, `dev_lines_total` |
| Staffing | `perm_staff`, `temp_staff` |
| Population | `pop_supply_area`, `pop_supplied`, `pct_pop_supplied` |

**Uniqueness constraint:** `(zone, scheme, month, year)` — enforced at the database level. The upload pipeline respects this with configurable conflict resolution (skip or replace per row).

**Financial year:** April = month 1, March = month 12. Do not rely on `month_no` alone for ordering across calendar years — always combine with `year`.

### User

| Column | Notes |
|---|---|
| `username` | Unique login identifier |
| `full_name` | Display name |
| `role` | `admin` \| `user` \| `viewer` |
| `hashed_password` | bcrypt |
| `is_active` | Boolean; inactive users cannot authenticate |

---

## Setup & Installation

### Prerequisites

- Python 3.10+
- Git
- Windows (primary target; Linux/macOS works via `start.sh`)

### Steps

```bash
# 1. Clone the repository
git clone <repo-url>
cd opsapp

# 2. Create and activate a virtual environment (recommended)
python -m venv venv
venv\Scripts\activate      # Windows
# source venv/bin/activate  # Linux/macOS

# 3. Install dependencies
pip install -r requirements.txt

# 4. Create the data directory
mkdir data

# 5. Run database migrations (only needed once, or after pulling schema changes)
python scripts/migrate_add_unique_constraint.py

# 6. (Optional) Seed from Excel
#    Place your RawData.xlsx in the uploads/ folder.
#    The app auto-imports on first startup if the records table is empty.
#    To import manually:
python scripts/import_data.py --excel uploads/RawData.xlsx --sheet DataEntry
```

> **Secrets:** The app reads `data/srwb.secret` for the JWT signing key and `data/groq.key` for AI narrative generation. These files are gitignored. Create them manually:
> ```
> echo "your-secret-key-min-32-chars" > data\srwb.secret
> echo "gsk_yourgroqapikey" > data\groq.key
> ```


---

## Running the Application

### Windows (recommended)

```bat
run.bat
```

This runs: `uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload`

### Manual

```bash
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

> **Port conflict:** If port 8000 is already in use, find the occupying PID and kill it before starting:
> ```bat
> netstat -ano | findstr :8000 | findstr LISTENING
> taskkill /PID <pid> /F
> ```
> Alternatively, start on a different port: `--port 8001`

Once running, open: **http://localhost:8000**

The interactive API docs are at: **http://localhost:8000/docs**

A quick health check: **http://localhost:8000/health**

A DB diagnostic (record counts by year/month): **http://localhost:8000/api/debug/db-status**

---

## API Reference

### Authentication

| Method | Path | Auth | Description |
|---|---|---|---|
| POST | `/api/auth/login` | Public | Returns a JWT Bearer token |

Include the token on all subsequent requests:
```
Authorization: Bearer <token>
```

### Core Data

| Method | Path | Auth | Description |
|---|---|---|---|
| GET | `/api/records` | user | Raw records with filters |
| GET | `/api/records/export/csv` | user/admin | Download records as CSV |
| GET | `/api/catalogue/zones` | user | List zones and schemes |

### Analytics

| Method | Path | Auth | Description |
|---|---|---|---|
| GET | `/api/analytics/kpi` | user | Aggregated KPIs + IWA indicators |
| GET | `/api/analytics/monthly` | user | Month-by-month trend data |
| GET | `/api/analytics/by-zone` | user | Per-zone breakdown |

### Panels

| Method | Path | Auth | Description |
|---|---|---|---|
| GET | `/api/panels/overview` | user | Latest-per-scheme summary for overview cards |
| GET | `/api/panels/zone/{zone}` | user | Scheme-level panel data for a zone |

### Upload Pipeline (admin only)

| Method | Path | Auth | Description |
|---|---|---|---|
| POST | `/api/upload/preview` | admin | Parse Excel, return preview with anomalies and conflicts |
| POST | `/api/upload/commit` | admin | Commit a previewed upload to the database |
| GET | `/api/upload/history` | admin | Last 20 upload log entries |

**Upload workflow:**

```bash
# Step 1 — Preview (dry run)
curl -X POST http://localhost:8000/api/upload/preview \
  -H "Authorization: Bearer <token>" \
  -F "file=@RawData_Jan2025.xlsx"
# Returns: preview_token, row statuses, conflicts, anomalies

# Step 2 — Commit
curl -X POST http://localhost:8000/api/upload/commit \
  -H "Authorization: Bearer <token>" \
  -H "Content-Type: application/json" \
  -d '{
    "preview_token": "<token from step 1>",
    "global_conflict_mode": "replace",
    "conflict_resolutions": {
      "Zomba__Zomba__1__2025": "skip"
    }
  }'
```

### Insights & Reports

| Method | Path | Auth | Description |
|---|---|---|---|
| GET | `/api/insights` | user | AI-generated narrative insights |
| GET | `/api/reports` | user | Formatted report data |
| GET | `/api/forecast` | user | Time-series forecasts |

### Admin

| Method | Path | Auth | Description |
|---|---|---|---|
| GET | `/api/admin/users` | admin | List all users |
| POST | `/api/admin/users` | admin | Create a user |
| PUT | `/api/admin/users/{id}` | admin | Update a user |
| DELETE | `/api/admin/users/{id}` | admin | Deactivate a user |

---

## Data Ingestion

### Source format

Data originates from `RawData.xlsx`, specifically the **DataEntry** sheet. Column headers in the sheet must match the mapping defined in `app/main.py` (`HMAP` dict) and `app/services/excel_parser.py`.

### Two ingestion paths

**1. Auto-import (startup):** If the `records` table is empty on startup and `uploads/RawData.xlsx` exists, the app imports it automatically. This is a one-time seed mechanism.

**2. Upload pipeline (preferred for ongoing updates):**
- Upload via the dashboard UI or the `/api/upload/preview` + `/api/upload/commit` endpoints
- The parser detects anomalies (statistical outliers vs. historical values) and conflicts (rows that already exist in the DB)
- Conflicts are resolved per-row or globally via `replace` or `skip` mode
- Every commit is logged to the audit trail

### Critical data hazards

> ⚠️ **Stub rows:** February and March rows exist as zero-value placeholders in the source Excel before real data arrives. Any aggregation logic must guard against them — do not assume data presence based on `month_no` alone. The filter is: skip rows where both `vol_produced = 0` AND `active_customers = 0`.

> ⚠️ **Fiscal year ordering:** The April–March year means December 2025 will beat March 2026 in a naive numeric `month_no` comparison. Always combine `year` and `month_no` when sorting.

> ⚠️ **`maintenance` column:** Currently zero across all records. Likely a column header mismatch in the source Excel — investigate the `HMAP` mapping.


---

## KPI Framework

The dashboard aligns with the **IWA/IBNET** water utility performance indicator framework. KPIs are computed in `app/routers/analytics.py` and `app/services/kpi_engine.py`.

| IWA Code | Indicator | Formula |
|---|---|---|
| Fn25 | Operating Ratio | `op_cost / total_sales` |
| Fn23 | Days Sales Outstanding | `(total_debtors / total_sales) × 365` |
| Cu01 | Revenue per Connection | `total_sales / active_customers` |
| Fn27 | Revenue Coverage | `cash_collected / op_cost` |
| Ee01 | Energy Intensity | `power_kwh / vol_produced` (kWh/m³) |
| — | NRW % | `nrw / vol_produced × 100` |
| — | NRW Financial Cost | `nrw × (op_cost / vol_produced)` |
| — | Meter Read Rate | `total_metered / active_customers` |
| — | Population Coverage | `pop_supplied / pop_supply_area` |
| — | Queries per 1K Connections | `queries_received / active_customers × 1000` |

The overview page renders these as 8 IWA-aligned KPI cards, four trend charts with benchmark reference lines, and a zone snapshot table with traffic-light colour coding.

---

## Authentication & Roles

| Role | Access |
|---|---|
| `viewer` | Read-only access to all dashboard views |
| `user` | Read access + CSV export |
| `admin` | Full access including upload, user management, and all admin endpoints |

Authentication uses **JWT Bearer tokens** with bcrypt password hashing. A default admin account is bootstrapped on first startup if no users exist (credentials defined in `app/auth.py`).

> **Note:** Authentication was temporarily stripped from FastAPI endpoint dependencies during a development phase to unblock dashboard work. The login system in `main.py` and `auth.py` is fully implemented and must be re-wired to all endpoints before any network-accessible deployment.

Password reset utility: `python reset_password.py` (also available at `app/reset_password.py`).

---

## Known Issues & Tech Debt

| Issue | Status | Notes |
|---|---|---|
| Auth not enforced on API endpoints | 🔴 Must fix before production | Dependencies were removed during dev; `main.py` includes auth on routers but individual endpoints should be verified |
| `maintenance` column always zero | 🟡 Investigate | Column header mismatch between Excel and `HMAP` in `app/main.py` |
| Stub rows (Feb/March placeholders) | 🟢 Mitigated | Guard clause in `latest_per_scheme()` skips zero-value rows; stays vigilant |
| GitHub remote not configured | 🟡 Incomplete | `.git` is initialised; remote push not yet set up (HTTPS token vs. SSH decision pending) |
| `requirements.txt` is incomplete | 🟡 Update needed | Only lists `fastapi`, `uvicorn`, `numpy`; missing `sqlalchemy`, `python-jose`, `bcrypt`, `openpyxl`, `python-multipart`, `slowapi`, etc. |
| Stale HTML backups in `app/static/` | 🟢 Low risk | `index - Copy.html` and `index - Copy (3).html` are gitignored; safe to delete |

---

## Development Notes

### Diagnostics

**JavaScript syntax errors in `index.html`** fail silently. The reliable diagnostic is:

```bash
# Extract the <script> block with Python and validate with Node
python scripts/extract_from_html.py > tmp_script.js
node --check tmp_script.js
```

**Port conflict detection (Windows):**

```bat
netstat -ano | findstr :8000 | findstr LISTENING
taskkill /PID <pid> /F
```

**Database record inspection:**

```
GET http://localhost:8000/api/debug/db-status
```

### Architecture decisions

- **Single HTML file frontend:** Keeps deployment trivial (no build step, no CDN dependency). Trade-off is that the file grows large and tooling support is limited.
- **SQLite:** Appropriate for a single-server internal utility at this data volume. If concurrent write load increases or multi-server deployment is needed, migrating to PostgreSQL is straightforward with SQLAlchemy.
- **Preview → Commit upload pattern:** Prevents partial imports and gives the operator a chance to review anomalies before data hits the database.
- **`latest_per_scheme` logic:** Panels show the most recent non-stub row per scheme, not a simple `ORDER BY month_no DESC`. This is intentional to avoid placeholder rows surfacing as current data.

### Shared aggregation utilities

Common logic lives in `app/aggregations.py` to avoid duplication:
- `MONTHS_ORDER` — canonical April-first month ordering
- `filter_records(records, zone, scheme, year)` — standard filter helper
- `latest_per_scheme(records)` — returns the most recent non-stub row per scheme

### Contact

Internal system — Southern Region Water Board, Malawi.
Maintainer: cmhango@gmail.com
