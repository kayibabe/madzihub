# Billing system pilot

The first live connection: MadziHub reads the utility's billing (customer information) system every night, and billed volume, billing, collections and accounts stop depending on monthly spreadsheet returns.

The files this guide refers to are in [`billing/`](billing/). The pilot configuration (`source.json`, `metrics.json`) is exercised by `tests/test_billing_pilot.py`, so this pack cannot drift from what the software accepts.

---

## 1. Why billing first

- **Biggest win for trust.** Billing and collections drive revenue, debtors, collection efficiency and non-revenue water. Today they arrive as hand-compiled returns.
- **Easiest system to reach.** Almost every billing system sits on a standard database (SQL Server, Oracle, PostgreSQL or MySQL). A read-only view is a routine request for a DBA; no vendor API or licence is needed.
- **Self-checking.** MadziHub already holds the monthly returns for the same measures, so the pilot can reconcile the two sources month by month. That comparison is itself valuable to management.

## 2. What we need from the utility

| # | Item | Who | Notes |
|---|---|---|---|
| 1 | Named **business owner** for billing data | Commercial Manager | Signs off the reconciliation and owns fixes when the feed goes red |
| 2 | Named **DBA / system administrator** | ICT | Creates the view and the read-only account |
| 3 | Database **engine and version** | ICT | SQL Server, Oracle, PostgreSQL or MySQL; decides the driver and view dialect |
| 4 | **Network path** from the MadziHub server to the database | ICT | Host and port reachable from the MadziHub server only; no internet exposure |
| 5 | **Read-only account** restricted to the view | DBA | `SELECT` on `v_madzi_monthly` only; no table access |
| 6 | The **view `v_madzi_monthly`**, per §3 | DBA | Start from `v_madzi_monthly.<engine>.sql`; map the placeholder tables to the real schema |
| 7 | **Branch list**: billing branch code → MadziHub unit | Commercial + MadziHub admin | Fill `branch_mapping_template.csv` |
| 8 | The billing system's **own reports for 3 recent closed months** (billed volume, billed amount, collections, active accounts per branch) | Commercial | The reference for reconciliation (§6) |
| 9 | A **test copy** of the billing database, if available | ICT | Lets the first runs happen away from production; not mandatory, because the account is read-only and reads are light |

Nothing personal leaves the billing system: the view is aggregated **per branch per month**. No names, account numbers or addresses.

## 3. The view contract: `v_madzi_monthly`

One row per **branch per month**, covering at least the last 24 months.

| Column | Type | Meaning |
|---|---|---|
| `branch_code` | text | The billing system's branch (or zone) code. Mapped to a MadziHub unit through key mappings. |
| `period_month` | date | First day of the month the figures belong to. |
| `billed_volume_m3` | number | Water volume billed in the month (m³), metered and estimated, excluding cancelled bills. Loads as **`revenue_water`**. |
| `billed_amount` | number | Amount billed in the month, in the reporting currency, excluding cancelled bills. Loads as **`amt_billed`**. |
| `cash_collected` | number | Receipts dated in the month, excluding reversals. Loads as **`cash_collected`**. |
| `active_accounts` | integer | Accounts connected at month end. Loads as **`active_customers`** (a latest value, not added across months). |
| `new_connections` | integer | Accounts connected during the month. Loads as **`new_connections`**. |
| `disconnections` | integer | Accounts disconnected during the month. Loads as **`disconnections`**. |
| `updated_at` | timestamp | Latest change to anything behind the row (bills, receipts, accounts). Drives incremental loading. |

Rules:
- A figure that is not known must be **NULL, not 0**. MadziHub treats blank as missing, not as a real zero.
- Months are **calendar months**. MadziHub builds quarters and fiscal years itself from the tenant's fiscal calendar.
- If the billing system corrects a past month, `updated_at` must move. MadziHub then re-reads that row and replaces the value (loads are idempotent).
- **If `updated_at` cannot be made reliable,** use a rolling window instead: change the query to `WHERE period_month >= <today minus 3 months>`, ignoring `:since`. Every night then re-reads the last three months in full, which is safe and cheap at monthly grain.

`v_madzi_monthly.postgresql.sql` and `v_madzi_monthly.sqlserver.sql` show one way to build it. **Table and column names in them are placeholders.** The DBA adapts them to the real schema, especially the definitions of "cancelled", "reversed" and "active".

## 4. MadziHub setup

1. **Driver** on the MadziHub server (only the one you need):

   | Engine | `pip install` | URL form for `MADZI_SRC_BILLING_DB_URL` |
   |---|---|---|
   | SQL Server | `pyodbc` (+ Microsoft ODBC Driver 18) | `mssql+pyodbc://user:pass@host:1433/db?driver=ODBC+Driver+18+for+SQL+Server&Encrypt=yes` |
   | PostgreSQL | `psycopg[binary]` | `postgresql+psycopg://user:pass@host:5432/db` |
   | Oracle | `oracledb` | `oracle+oracledb://user:pass@host:1521/?service_name=SVC` |
   | MySQL / MariaDB | `pymysql` | `mysql+pymysql://user:pass@host:3306/db` |

2. **Secret:** set `MADZI_SRC_BILLING_DB_URL` in the service environment, never in MadziHub's database or a file in the repository. Only `MADZI_SRC_*` variables can be used by sources.
3. **Catalogue:** in *Administration → Data Sources*, use *Set up from existing returns* if not done yet. It creates the organisation tree and the billing measures (`revenue_water`, `amt_billed`, `cash_collected`, `active_customers`, `new_connections`). Then add `disconnections` from `metrics.json` (*Measures & Targets → Add Measure*, or `POST /api/integration/metrics`).
4. **Source:** create it from `source.json` (*Add Source*, or `POST /api/integration/sources`). It is scheduled nightly (1440 min) with **priority 50**, so once reconciled it outranks the monthly returns (priority 500) on the Strategic Position page.
5. **Branch mapping:** add each row of the completed `branch_mapping_template.csv` as a key mapping (*Runs & mappings → Add mapping*, or `PUT /api/integration/sources/billing/key-mappings`). Codes that already equal a MadziHub unit code need no mapping.

## 5. Pilot plan

| Day | Step | Done when |
|---|---|---|
| 1 | **Connect and dry-run.** *Test* on the source (or `python -m app.integration.cli sync --source billing --dry-run`) reads a sample, maps it and reports what would load. **Nothing is written.** | Test shows `ok`, the expected columns, measures and periods; any rejects are only unmapped branches |
| 1–2 | **Map branches.** Each "unknown org unit" reject has a **Map** button; map every branch, then test again | Test shows zero rejects |
| 2 | **First load.** *Run*. The first run reads everything (no watermark yet) | Run is `success`; values appear on Strategic Position under source `billing` |
| 2–3 | **Reconcile** (§6) | All reference months within tolerance, or every difference explained and accepted by the business owner |
| 3 | **Go live.** Leave the nightly schedule on; schedule `python -m app.integration.cli sync --due` every 15 minutes (Task Scheduler / cron) | Freshness shows `billing` current the next morning |
| +30 days | **Review** with the business owner: missed nights, late corrections, differences | Decide whether monthly returns stop carrying these measures |

**Rollback** at any point: *Disable* the source. Values it loaded stay for audit, and the monthly returns remain the published figure for those measures, because they are the next source by priority.

## 6. Acceptance: reconciliation

For each of the three reference months, every branch and each measure (`revenue_water`, `amt_billed`, `cash_collected`, `active_customers`), compare three figures:
1. **The billing system's own report**, supplied in §2 item 8.
2. **MadziHub from `billing`**: the Strategic Position detail for the measure and unit, or `GET /api/position/{measure}?org_unit=<unit>`.
3. **MadziHub from the monthly returns:** `GET /api/position/{measure}/reconciliation?org_unit=<unit>` lists every month where `billing` and `legacy-returns` disagree, largest gap first.

Record the results in `reconciliation_template.csv`.

| Measure | Tolerance vs billing report | Typical reason for a difference |
|---|---|---|
| Billed volume, billed amount | exact, to rounding | View includes/excludes cancelled or adjusted bills differently from the report |
| Cash collected | exact, to rounding | Receipt date vs posting date; reversals |
| Active accounts | ±0.5% | Definition of "active" (month end vs any time in month; disconnected but billed) |
| vs monthly returns | none set: expect differences | The returns were compiled by hand; each large gap is a finding, not a defect |

**Accepted** when figures 1 and 2 agree within tolerance for all reference months, or the business owner has signed off every exception.

## 7. Risks and how the pilot handles them

| Risk | Handling |
|---|---|
| View definitions differ from how finance reports (cancelled bills, receipt dates) | Reconciliation against the billing system's own report in §6, not against the returns |
| `updated_at` unreliable, so late corrections are missed | Rolling 3-month re-read (§3) |
| Branch codes change or new branches appear | New codes show up as rejects with a **Map** button; nothing is guessed into the wrong unit |
| Database load | One aggregated query a night; the read-only account can only read the view |
| Credential exposure | URL only in the service environment (`MADZI_SRC_*`); errors never echo it |
| Feed silently stops | Freshness marks the source overdue after two missed schedules; the CLI exits non-zero so the scheduler can alert |
