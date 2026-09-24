# MadziHub

**Water Utility Performance & Intelligence Platform.** *Every drop, accounted for.*

MadziHub turns a water utility's monthly operational, commercial and financial returns into board-ready KPIs, reports and alerts: production and NRW, treatment and energy, customers and connections, billing and collections, costs, debtors, budgets and the strategic-plan scorecard. It is IWA/IBNET-aligned.

One installation serves one utility. Everything that differs between utilities lives in a tenant configuration file, not in the code: name, logo, currency, fiscal year, zones, targets, thresholds and the strategic plan.

> MadziHub began as the SRWB Corporate Performance Hub (Southern Region Water Board, Malawi). SRWB is the reference tenant (`tenants/srwb`). Ownership and licensing of the original code and of SRWB's content are being settled with SRWB, so no licence is granted yet.

- **Product plan:** [docs/BLUEPRINT.md](docs/BLUEPRINT.md)
- **Roadmap / checklist:** [docs/ROADMAP.md](docs/ROADMAP.md)

---

## Quick start

```bash
python -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt

export MADZI_TENANT=demo          # or srwb, or a path to your own tenant.yaml
export MADZI_ENV=development
uvicorn app.main:app --port 8000
```

On first start MadziHub creates an `admin` account, prints a one-time password to the console, and requires a new password at first login. Open http://localhost:8000 and upload a return from **Administration → Upload**.

Production installs: copy `.env.example`, then set `MADZI_ENV=production`, a strong `MADZI_SECRET_KEY` and `MADZI_ALLOWED_ORIGINS`. Production startup refuses insecure defaults. Existing SRWB installs keep working: `SRWB_*` variables, `data/srwb.db` and `data/srwb.secret` are still recognised.

Locked out of the admin account? Run `python scripts/reset_admin.py` (random one-time password, or `--prompt`).

## Configuring a utility

Create `tenants/<your-utility>/tenant.yaml` (copy `tenants/demo/tenant.yaml`) and set `MADZI_TENANT=<your-utility>`.

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

Administrators can override identity fields in **Administration → Organisation Profile**. The UI reads the effective configuration from `GET /api/config`.

## Architecture

- **Backend:** FastAPI + SQLAlchemy; SQLite by default, PostgreSQL supported through `DATABASE_URL`.
- **Frontend:** a single-page app (`app/static/index.html`, `app/static/assets/js/app-core.js`). Tenant values are filled in server-side when these files are served.
- **Tenant layer:** `app/core/tenant.py` (validated YAML) → `app/utils.py` (fiscal calendar) → routers and services.
- **Auth:** JWT bearer tokens, bcrypt, roles `admin` / `user` / `viewer`, and a forced password change for bootstrap and reset accounts.

```
app/            FastAPI app (core/, routers/, services/, static/)
tenants/        one folder per utility (srwb = reference, demo = fictional)
tests/          unit, security, tenant and API parity-snapshot tests
scripts/        admin, import, release-bundle tooling
docs/           blueprint, roadmap, runbooks; docs/reference = original opsapp README
```

## Tests

```bash
python -m unittest discover -s tests -p "test_*.py"
```

`tests/test_parity_snapshots.py` seeds a deterministic **synthetic** dataset and compares 58 read endpoints with committed JSON snapshots. Any refactor that changes output fails it. If a change is intentional, re-record with `MADZI_RECORD_SNAPSHOTS=1` and explain the diff in the PR.

CI (`.github/workflows/ci.yml`) runs a syntax check, the tests, and the release-bundle build and validation. The bundle excludes databases, secrets, uploads and spreadsheets.

## Data handling

Never commit utility data. `.gitignore` blocks spreadsheets, databases and secrets, and the release bundle excludes them again. Use the demo tenant and the synthetic dataset for demos, screenshots and tests.
