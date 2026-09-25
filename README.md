# MadziHub

**Water Utility Performance & Intelligence Platform.** *Every drop, accounted for.*

MadziHub turns a water utility's monthly operational, commercial and financial returns into board-ready KPIs, reports and alerts: production and NRW, treatment and energy, customers and connections, billing and collections, costs, debtors, budgets and the strategic-plan scorecard. It is IWA/IBNET-aligned.

MadziHub pulls a utility's scattered systems, files and reports (ERP, asset management, billing, SCADA historians, HR, spreadsheets) into one governed repository. Management gets one trusted picture of **where we were, where we are and where we are going**: history with lineage, the current position with data freshness, and targets with the gap to them. See [docs/INTEGRATION_HUB.md](docs/INTEGRATION_HUB.md).

One installation serves one utility. Everything that differs between utilities lives in a tenant configuration file, not in the code: name, logo, currency, fiscal year, zones, targets, thresholds and the strategic plan.

> MadziHub began as the SRWB Corporate Performance Hub (Southern Region Water Board, Malawi). This repository is now a utility-neutral template: every SRWB name, figure, file format and configuration has been removed, and the demo tenant is the default. The last SRWB-specific version is preserved at the git tag `srwb-reference`. Ownership and licensing of the original code are still being settled with SRWB, so no licence is granted yet.

- **Product plan:** [docs/BLUEPRINT.md](docs/BLUEPRINT.md)
- **Roadmap / checklist:** [docs/ROADMAP.md](docs/ROADMAP.md)
- **Market gap analysis:** [docs/COMPETITIVE_GAP_ANALYSIS.md](docs/COMPETITIVE_GAP_ANALYSIS.md)
- **Performance & Governance (strategy and M&E, scorecard, reporting hub, documents, governance and risk, regulator packs, contracts and appraisals):** [docs/PERFORMANCE_GOVERNANCE.md](docs/PERFORMANCE_GOVERNANCE.md)
- **Integration hub (SAP, Maximo, billing, SCADA, HR, spreadsheets):** [docs/INTEGRATION_HUB.md](docs/INTEGRATION_HUB.md)
- **First live connection, the billing pilot:** [docs/pilots/BILLING_PILOT.md](docs/pilots/BILLING_PILOT.md)

---

## Quick start

```bash
python -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt

export MADZI_TENANT=demo          # the default; or your tenant folder, or a path to a tenant.yaml
export MADZI_ENV=development
uvicorn app.main:app --port 8000
```

On first start MadziHub creates an `admin` account, prints a one-time password to the console, and requires a new password at first login. Open http://localhost:8000 and upload a return from **Administration → Upload**.

Access is **deny-by-default**: other users see nothing until an administrator grants them units and duties in **Performance & Governance → Access & Scope**. To explore every module with fictional data, run `python -m app.demo_seed` (demo tenant only; it prints the demo passwords once).

Existing databases are never migrated at start-up: run `python -m app.migrate status`, then `python -m app.migrate upgrade` (it backs up first). Back up the database and file store together with `python -m app.platform.backup create`; schedule `python -m app.platform.cli reminders` daily for due and overdue notices.

Production installs: copy `.env.example`, then set `MADZI_ENV=production`, a strong `MADZI_SECRET_KEY` and `MADZI_ALLOWED_ORIGINS`. Production startup refuses insecure defaults. Only `MADZI_*` variables are read; the database defaults to `data/madzihub.db`.

Locked out of the admin account? Run `python scripts/reset_admin.py` (random one-time password, or `--prompt`).

## Configuring a utility

Create `tenants/<your-utility>/tenant.yaml` (copy `tenants/demo/tenant.yaml`) and set `MADZI_TENANT=<your-utility>`. Optionally add `budget.yaml` beside it (copy `tenants/demo/budget.yaml`) to register fiscal years and load approved budgets with `python scripts/seed_fiscal_years.py`.

| Section | What it controls |
|---|---|
| `identity` | Organisation name and short name, product title, country, regulator, contacts |
| `branding` | Logo file (inside the tenant folder) and colours |
| `currency` | ISO code and display symbol used across the UI, reports and narratives |
| `fiscal_year.start_month` | Fiscal calendar: month order, quarters, FY labels, period filters |
| `hierarchy` | Level labels and the zone list with chart colours |
| `targets`, `thresholds` | NRW target and insight alert thresholds |
| `strategic_plan` | Strategic plan title, years and KPI matrix for the scorecard |
| `modules` | Modules offered to this utility |
| `ai` | AI narratives (**off by default**: they send KPI data to an external provider) |

Monthly returns are uploaded as a RawData workbook (DataEntry sheet). Money columns are currency-neutral (`Cost of Chemicals`, `TOTAL Sales`); a header may also carry the tenant's own currency code (`Wages USD`), but a different currency is rejected rather than imported.

Administrators can override identity fields in **Administration → Organisation Profile**. The UI reads the effective configuration from `GET /api/config`.

## Architecture

- **Backend:** FastAPI + SQLAlchemy; SQLite by default, PostgreSQL supported through `DATABASE_URL`.
- **Frontend:** a single-page app (`app/static/index.html`, `app/static/assets/js/app-core.js`). Tenant values are filled in server-side when these files are served. Governance modules are separate `mod-*.js` files built on a shared toolkit (`mod-platform.js`).
- **Tenant layer:** `app/core/tenant.py` (validated YAML) → `app/utils.py` (fiscal calendar) → routers and services.
- **Auth:** JWT bearer tokens, bcrypt, roles `admin` / `user` / `viewer`, and a forced password change for bootstrap and reset accounts. Data access is resolved per request from unit grants and duties (`app/platform/scope.py`).
- **Schema:** Alembic revisions `0001`–`0009` in `app/migrations/versions`.

```
app/            FastAPI app (core/, routers/, services/, static/)
app/platform/   shared governance: scope, periods, audit, workflow, actions, links, file store, backup
app/modules/    strategy, scorecard, reporting, documents, governance, regulatory, people
tenants/        one folder per utility (demo = fictional default); _packs/regulators = regulator packs
tests/          unit, security, tenant and API parity-snapshot tests
scripts/        admin, import, release-bundle tooling
docs/           blueprint, roadmap, runbooks
```

## Tests

```bash
python -m unittest discover -s tests -p "test_*.py"
```

`tests/test_parity_snapshots.py` seeds a deterministic **synthetic** dataset into the demo tenant and compares 58 read endpoints with committed JSON snapshots. Any refactor that changes output fails it. If a change is intentional, re-record with `MADZI_RECORD_SNAPSHOTS=1` and explain the diff in the PR.

CI (`.github/workflows/ci.yml`) runs a syntax check, the tests, and the release-bundle build and validation. The bundle contains committed files only and excludes databases, secrets, uploads and spreadsheets.

## Offline installs and third-party front-end files

The browser loads nothing from the internet. Chart.js, DOMPurify, SheetJS and the Inter and IBM Plex Mono fonts are vendored in `app/static/vendor`, with their licences and a `manifest.json` of SHA-256 checksums. Tests and the release-bundle validator fail if a file is missing or changed. To upgrade one, change its version in `scripts/update_vendor_assets.py`, run the script (it downloads the npm package, verifies the registry's integrity hash and rewrites the manifest), then run the tests.

## Data handling

Never commit utility data. `.gitignore` blocks spreadsheets, databases and secrets, and the release bundle excludes them again. Use the demo tenant and the synthetic dataset for demos, screenshots and tests.
