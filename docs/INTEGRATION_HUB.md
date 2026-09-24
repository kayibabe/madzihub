# Integration hub

**Purpose.** A utility's picture is scattered across SAP, Maximo, the billing system, SCADA historians, HR systems, spreadsheets and board reports, and management cannot see it whole. The integration hub pulls all of them into one governed repository. Every KPI then answers three questions from the same trusted data:

| Question | What the platform returns | Endpoint |
|---|---|---|
| **Where were we?** | Published history for each period, with the source and the row it came from | `GET /api/position/{metric}` → `where_we_were` |
| **Where are we?** | Latest published value, its source, and how old the data is | `where_we_are` (+ `data_age_days`), `GET /api/position/sources/freshness` |
| **Where are we going?** | Targets by period and basis (strategic plan, budget, regulator), gap to target, trend | `where_we_are_going`, `gap_to_target`, `trend` |

`GET /api/position?org_unit=org` returns that for every active measure: the organisation-level scorecard.

---

## 1. What "single source of truth" means here

MadziHub is the source of truth for **performance**: measures, targets and the published position. It is **not** the system of record for transactions. Invoices stay in SAP, work orders in Maximo, meter reads in billing and telemetry in the historian. MadziHub keeps what management needs, with a link back to where it came from.

That distinction matters. Copying every transaction would create a second, unsupported ERP and a reconciliation problem with no end. The hub instead stores **period values per measure per organisational unit**, plus the lineage to drill back into the source system.

When two systems report the same measure (billing and a finance spreadsheet both report cash collected), both are kept:
- `DataSource.priority` decides the **published** figure (lower wins).
- `GET /api/position/{metric}/reconciliation` lists periods where the sources disagree, largest gap first. That report is often the first thing management has never seen before.

---

## 2. How it works

```
 SAP / ERP ─┐   REST/OData     ┌───────────────────────────────────────────────┐
 Maximo ────┤   REST / SQL     │ connector → map & validate → load (idempotent)  │
 Billing ───┤   SQL view       │     │             │               │             │
 Historian ─┤   SQL / REST     │  watermark     rejects with     metric_values    │──► /api/position
 SCADA gw ──┤   push (token)   │  (incremental)  reasons          + lineage       │    scorecards, reports
 HR ────────┤   REST / file    │                                  + targets       │
 Excel/CSV ─┘   drop / upload  └───────────────────────────────────────────────┘
                                   SyncRun per run: rows read / loaded / rejected, errors
```

| Table | Role |
|---|---|
| `org_units` | Organisation tree of any depth: organisation → region → zone → scheme → plant; departments too |
| `metrics` | Catalogue: code, unit, category, aggregation (`sum/avg/last/max/min`), direction (`higher/lower/range`) |
| `data_sources` | One per system or feed: connector, config (no secrets), mapping, priority, schedule, watermark |
| `key_mappings` | Crosswalk from a source's keys (SAP cost centre, Maximo site, SCADA tag) to our codes |
| `sync_runs` | Audit of every run, including the first 200 rejected rows and why |
| `metric_values` | One value per measure × unit × period × source, with `source_ref` lineage |
| `metric_targets` | Targets per measure × unit × period × basis, with tolerance bands |

Rules the pipeline enforces:
- **Blank is not zero.** Empty cells are skipped, so a missing return shows as missing, not as a collapse to zero.
- **Unknown keys are rejected, not guessed.** An unmapped cost centre or tag is listed with its reason, never loaded to the wrong place. Use `ignore_unmapped_metrics` for feeds that send far more tags than you track.
- **Finer data is aggregated to the stored grain** using each measure's aggregation (hourly SCADA → daily or monthly).
- **Roll-up only for additive measures.** A unit without its own value gets the sum of its leaf units for `sum` measures. Averages and ratios are never added up. They return as missing until formula measures arrive (see §6).
- **Idempotent loads.** Re-running a source or re-dropping a file updates rows in place.
- **The watermark only advances after a successful load.** A failed run retries from the same point.

---

## 3. Connectors

| Connector | Use for | Key config |
|---|---|---|
| `sql` | Billing/CIS databases, historian SQL interfaces, SAP HANA views, Maximo reporting views, HR databases | `url_env`, `query` (use `:since`), `watermark_field` |
| `rest` | SAP OData, Maximo REST/OSLC, Workday reports-as-a-service, OSIsoft/AVEVA PI Web API, any JSON API | `base_url`, `path`, `auth`, `params` (`{since}` placeholder), `records_path`, `next_link_path`, `watermark_field` |
| `file` | Monthly returns, management reports, exports that systems email or save to a share | `path` (glob inside the drop folder), `sheet`, `header_row` |
| `push` | SCADA gateways, scripts and systems that can send but cannot be reached | Token from `POST /api/integration/sources/{code}/token`; send `POST /api/ingest/{code}` with header `X-Madzi-Ingest-Token` |
| `legacy_records` | MadziHub's existing monthly returns table | Created by `bootstrap-legacy` |

Any file source also accepts a one-off upload: `POST /api/integration/sources/{code}/upload`.

**Secrets are never stored in the database.** Config names environment variables (`url_env`, `username_env`, `password_env`, `token_env`) and the values are read at run time. Those variables must be named `MADZI_SRC_*`, so a source can never be configured to read the application's own secrets and send them elsewhere. Give every source a **read-only** account restricted to the views it needs.

**Deployment.** MadziHub runs inside the utility's network and **pulls**. No inbound firewall openings are needed except for push feeds, which only need to reach the MadziHub server itself.

---

## 4. System recipes

These are starting configurations. **None has been tested against a live SAP, Maximo, PI or Workday instance.** Each needs the client's sandbox, a service account and a day of field-mapping work with the system owner. Entity and field names vary by version and customisation; confirm them with the client's administrators.

### SAP (S/4HANA or ECC): finance, procurement, plant maintenance
Preferred: a released OData service or a CDS view exposed as OData, read with a technical user.
```json
{"code": "sap-fi", "system_type": "erp", "connector": "rest", "schedule_minutes": 1440,
 "config": {"base_url": "https://sap.example/sap/opu/odata/sap/<SERVICE>", "path": "<EntitySet>",
            "auth": {"type": "basic", "username_env": "MADZI_SRC_SAP_USER", "password_env": "MADZI_SRC_SAP_PASSWORD"},
            "params": {"$format": "json", "$filter": "LastChangeDateTime gt datetime'{since}'"},
            "records_path": "d.results", "next_link_path": "d.__next", "watermark_field": "LastChangeDateTime"},
 "mapping": {"layout": "wide", "metrics": {"opex_actual": "AmountInCompanyCodeCurrency"},
             "period": {"field": "PostingDate"}, "org_unit": {"field": "CostCenter"}}}
```
Then map cost centres to org units with `PUT /api/integration/sources/sap-fi/key-mappings`. Alternatives: `sql` against a HANA reporting view, or a scheduled SAP report saved as CSV to the drop folder. For OData v4 use `records_path: "value"` and `next_link_path: "@odata.nextLink"`.

### IBM Maximo: assets, work orders, maintenance
```json
{"code": "maximo", "system_type": "eam", "connector": "rest", "schedule_minutes": 360,
 "config": {"base_url": "https://maximo.example/maximo/api", "path": "os/<object structure>",
            "auth": {"type": "header", "header_name": "apikey", "token_env": "MADZI_SRC_MAXIMO_APIKEY"},
            "params": {"lean": "1", "oslc.select": "wonum,siteid,worktype,status,actfinish",
                       "oslc.where": "changedate>\"{since}\""},
            "records_path": "member", "next_link_path": "responseInfo.nextPage.href", "watermark_field": "changedate"}}
```
Work-order KPIs such as planned-maintenance ratio and completed work orders are usually easier to take from a Maximo **reporting view** through `sql`, pre-aggregated by site and month, than to count from the API.

### Billing / customer information system
Nearly always best through `sql` on a read-only reporting view that already groups by branch and month (billed volume, billed amount, collections, active and new connections, disconnections):
```json
{"code": "billing", "system_type": "billing", "connector": "sql", "schedule_minutes": 1440,
 "config": {"url_env": "MADZI_SRC_BILLING_DB_URL", "watermark_field": "updated_at",
            "query": "SELECT branch_code, period_month, billed_m3, billed_amount, collected, updated_at FROM v_madzi_monthly WHERE updated_at > :since"},
 "mapping": {"layout": "wide", "period": {"field": "period_month"}, "org_unit": {"field": "branch_code"},
             "metrics": {"revenue_water": "billed_m3", "amt_billed": "billed_amount", "cash_collected": "collected"}}}
```
Database drivers are installed per site (for example `psycopg` for PostgreSQL, `pyodbc` for SQL Server, `oracledb` for Oracle) and are not in the base requirements.

### SCADA / telemetry
Do **not** stream raw telemetry into MadziHub; management needs daily or monthly totals. Two options:
- **Historian pull** (preferred): the historian's SQL interface or PI Web API, returning interpolated or summary values per tag per day. Use `layout: "long"`, map tags to measures with key mappings, `period_type: "day"`, `ignore_unmapped_metrics: true`.
- **Gateway push**: the SCADA gateway or an edge script posts daily totals to `/api/ingest/{code}` with its token.

Typical measures: water produced per works, energy kWh, pump hours, reservoir levels (`last`), pressure (`avg`), hours of supply.

### HR / payroll
Workday: a custom report exposed as a JSON web service (`rest`, `records_path: "Report_Entry"`). SuccessFactors: OData (`rest`). Sage and local payroll systems usually work best as a monthly CSV export to the drop folder. Measures: headcount, vacancies, overtime hours, absenteeism days, training hours, leavers. Load **aggregates by department, not personal records**; the hub does not need names or salaries.

### Reports and spreadsheets
Create a `file` source per report layout, then drop files in `data/dropzone/<folder>/` or upload them. For wide monthly returns, map each column to a measure. Management reports that only exist as PDF must first be turned into a tabular export at the source. PDF parsing is deliberately out of scope because it is not reliable enough to govern.

---

## 5. Running it

```bash
# seed the organisation tree, core measures and a source from existing records (safe to repeat)
python -m app.integration.cli bootstrap-legacy
python -m app.integration.cli sync --source legacy-returns

# scheduled pulls: run every 15 minutes from cron or Windows Task Scheduler
python -m app.integration.cli sync --due        # exit code 1 if any run failed
python -m app.integration.cli status            # freshness JSON
```
Pulls run outside the web server on purpose. Several web workers can never start the same pull twice, a slow extract never blocks dashboards, and the scheduler's exit code gives alerting for free.

### Onboarding a new system (playbook)
1. Agree the measures, grain and owner with the business: what question does this system answer?
2. Get a read-only service account and, ideally, a reporting view pre-aggregated by unit and month.
3. Register the measures (`POST /api/integration/metrics`) and any missing org units.
4. Create the source with a mapping, then run it once against a small date range.
5. Work through the rejects in `GET /api/integration/runs?source=<code>&include_rejects=true`, adding key mappings until they are empty.
6. Reconcile a few months against the system's own report, and against other sources through `/reconciliation`.
7. Set `priority` and `schedule_minutes`, and name the `owner` who fixes it when freshness goes red.

---

## 6. Honest limits and what comes next

| Limit today | Next step |
|---|---|
| Ratios (NRW %, collection efficiency, cost per m³) cannot roll up | **Formula measures** (`nrw_pct = nrw / vol_produced × 100`), evaluated per unit and period from their components with a safe expression parser |
| Existing dashboards still read the wide `records` table | Move panels to `metric_values` one at a time, with the parity snapshots guarding each move |
| No approval step: loaded values publish immediately | Submit → review → publish states, period locks, correction history (ROADMAP Stage 2) |
| No admin UI for sources and mappings; API only | Sources screen: create, test, run, view rejects, edit key mappings |
| No unit conversion registry | Units table (m³/ML, kWh/MWh) with conversion at mapping time; `scale` covers simple cases now |
| Scheduling relies on OS cron/Task Scheduler | Acceptable for on-premises installs; revisit only for a hosted offer |
| New tables are created by `create_all` | Adopt Alembic before the first non-additive change to these tables |
| SQLite is fine for monthly data; daily telemetry for many sites will grow quickly | Use PostgreSQL for installs with daily feeds |
| Vendor recipes are untested | Validate each against a client sandbox before it is sold as supported |
