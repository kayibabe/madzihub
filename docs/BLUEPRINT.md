# MadziHub Product Blueprint

**MadziHub: Water Utility Performance & Intelligence Platform**
*Every drop, accounted for.*

Working specification, version 1.1, 24 September 2026.
Baseline: `kayibabe/opsapp` at `efa4a29`, imported into this repository with no utility data.
This document merges two independent reviews (the `MadziHub_Product_Blueprint.docx` draft and a code-level review), fills gaps in both, and records what the first implementation pass actually changed.

> **Status and scope update (24 September 2026):** MadziHub is a configurable platform, with water and wastewater utilities as the first product domain. It is not an SRWB-branded product and SRWB is no longer a reference tenant. SRWB-specific code, settings and tenant data were removed from this repository; the historical rights and licence question remains open. The existing code has useful generic tenant, fiscal calendar, metric and integration foundations, but arbitrary KPI catalogues, forms and organizational structures are not yet proven. See [RESEARCH_BENCHMARK.md](RESEARCH_BENCHMARK.md) for current external research and the revised implementation order. The working tree includes pending changes; this document does not claim they are committed or released.

---

## 1. Decision summary

| Decision | Choice | Why |
|---|---|---|
| Product | Build a configurable performance, planning and reporting platform for water and wastewater utilities first | Start with this domain's strategy, operations and regulatory reporting needs; do not claim support for arbitrary utilities until their metric models and workflows are validated. |
| Reference data | Synthetic demo and test tenants only | Never make a real utility's data the product demo or general regression fixture. |
| Deployment | **One isolated installation per utility** for the first release | Public-sector utilities generally require data on their own servers; per-install SQLite/PostgreSQL + a single process is simple to run, back up and support. |
| Multi-tenancy | Designed-for, **not built** | Clean config boundaries now; a shared hosted service needs its own architecture review, tenant-aware schema and isolation testing. An `org_id` column alone is not enough. |
| Refactor safety | Existing API **parity snapshots** on synthetic data | Preserve established endpoint behaviour unless a change is deliberate and documented. New strategy APIs use a separate namespace as specified in [RESEARCH_BENCHMARK.md](RESEARCH_BENCHMARK.md). |
| AI narratives | **Off by default**, explicit opt-in per install | Narratives send KPI data to an external provider; many utilities cannot allow that. |
| Demo | Synthetic **MadziHub** demo tenant identity | Demo identity may use the product brand, but utility records, activity, names and figures remain invented; it must not imply a real regulator or utility. |

### Where the two reviews differed, and how it was resolved

| Topic | Docx draft | Code review | Resolution |
|---|---|---|---|
| Database | Move to PostgreSQL with `tenant_id` everywhere | Keep SQLite per install | Support SQLite now; validate PostgreSQL in staging and prefer it for larger installs. No `tenant_id` until a hosted offer exists. |
| Hosting | Tenant-aware shared platform | One install per utility | One install per utility; keep boundaries clean so hosting is possible later. |
| Security baseline | "Auth needs testing" | README claimed auth was removed | Verified in code: data routers **do** require auth. Found and fixed a real hole instead (dev-preview login, §5). |
| Performance targets | Conflicting hard-coded targets found in the source review | Same | Use versioned targets with period, measure, organization scope, basis and source. Never elevate an old SRWB value into a MadziHub default. |

### Product plan update

The current benchmark adds a governed strategy/M&E cycle, explicit score completeness and versioning rules, frozen report instances, evidence and controlled-document lifecycles, shared actions, board resolutions, audit findings, risk, and source-verified regulator packs. The first internal five-band scoring scheme and each regulator's external ranking method are separate configurations. The sequence and acceptance gates are maintained in [RESEARCH_BENCHMARK.md](RESEARCH_BENCHMARK.md); it supersedes conflicting older sequence details in this document.

---

## 2. Name and positioning

**MadziHub.** *Madzi* means water in Chichewa; *Hub* leaves room for reporting, planning, integrations and collaboration. It is distinctive, regionally rooted, and not tied to one utility.

Tagline options (first is recommended):
1. **Every drop, accounted for.** Speaks to NRW, billing and governance at once.
2. From returns to decisions.
3. Clear data. Clean water. Confident decisions.
4. The performance heartbeat of your utility.
5. Know your network.

Each installation can present the customer's configured identity, with MadziHub shown as the platform provider where appropriate.

Before public launch: formal trademark, domain and regional-language clearance (other Malawian "Madzi" apps exist). Do not use IWA or IBNET in the name.

**Positioning.** Not "a dashboard". MadziHub is a configurable, standards-aligned performance, planning and reporting platform for water and wastewater utilities that works where data is imperfect and dispersed. It starts from spreadsheet returns and moves step by step to connected systems. It is **not** a billing, SCADA or asset work-order system; it sits above them.

---

## 3. What the code showed (verified at `efa4a29`)

| Finding | Evidence | Status after this pass |
|---|---|---|
| "SRWB" 111× in 25 files; "MWK" 197× | grep across app/ | Removed from all user-facing Python, HTML and JS; remaining hits are SRWB-format import adapters (by design, Stage 2). |
| `OrgProfile` existed but nothing read it | only `users.py` admin endpoints | Seeded from tenant YAML; overrides identity in `/api/config`, HTML and JS. |
| Five zones and colours hardcoded in 4 places (Python + JS, with **different** colours) | `panels.py`, `analytics.py`, `rawdata_builder.py`, `app-core.js` | Single source: `tenant.yaml → hierarchy.zones`. |
| April–March FY duplicated in ~10 places | `utils.py`, `budget.py`, `catalogue.py`, `upload.py`, `insights_engine.py`, `rawdata_builder.py`, JS month lists | Single fiscal calendar (`fy_start_month`), tested for Jan/Apr/Jul starts. |
| NRW target 25 in one place, 27 in others; Strategic Plan matrix hardcoded | `panels.py:1439`, `report_generator.py`, `insights_engine.py`, `strategic.py` | `targets.nrw_pct` + `strategic_plan` in tenant YAML. |
| Wide 222-column `records` table; column map duplicated (`COLUMN_MAP`, `HMAP`) | `database.py`, `excel_parser.py`, `main.py` | Unchanged (Stage 2: metric catalogue + mapping profiles). |
| SRWB data quirks inside calculations | Mangochi days-to-connect fix, supply hours monthly vs daily, stub-row guard | Unchanged (Stage 2: per-tenant validation rules at upload). |
| **Dev-preview login live on production installs** | env defaults to `development`, start scripts never set it; loopback check passes behind a same-host reverse proxy | **Fixed**: requires `MADZI_DEV_PREVIEW=true` *and* development env. |
| `reset_password.py` sets `Admin123` | repo root | **Fixed**: random/prompted password + forced change. |
| No forced password change | first-run admin printed once | **Fixed**: `must_change_password`, enforced server-side. |
| Stale SRWB budget snapshot baked into UI | fixed tariff `1,450/m³`, `1.057B` chemicals budget, dated source citation | Made generic; real values come from the fiscal-year tables. |
| Release bundle only excluded `srwb.secret` by name | `build_release_bundle.py` | Excludes data/, uploads/, secrets, keys, DBs, spreadsheets by pattern. |
| CI bundle validation required a `.env.example` that was never committed | `.gitignore` had `.env.*` | Added `.env.example`. |
| Front-end libraries from a CDN at runtime | Chart.js, DOMPurify, SheetJS via cdnjs; fonts from Google Fonts | **Fixed**: vendored in `app/static/vendor` with licences and a SHA-256 manifest; `scripts/update_vendor_assets.py` refreshes them. Verified with all external hosts blocked. |
| Public opsapp repo contains SRWB workbooks | `dataupdater/` | Not imported here. **Owner action** on opsapp (make private / history rewrite). |

---

## 4. Target architecture

```
tenants/<utility>/tenant.yaml ──► app/core/tenant.py (validated, cached per process)
                                      │
      ┌───────────────────────────────┼──────────────────────────────┐
      ▼                               ▼                              ▼
 app/utils.py                   routers & services             /api/config (+ /public, /logo)
 fiscal calendar                targets, thresholds,           index.html + app-core.js
 (start month)                  zones, plan KPIs, AI           placeholders filled server-side
```

Principles:
- **One process = one utility.** `MADZI_TENANT` selects the configuration; everything utility-specific lives in `tenants/<name>/`.
- **Config precedence:** tenant YAML → admin-edited organisation profile (identity only). Later: versioned DB tables for hierarchy and targets.
- **API supplies labels, currency and thresholds** to the UI; no business constants in browser code.
- **Keep the wide `records` table** as a compatibility layer while the metric catalogue arrives. Measure real query needs before any metric-row-store rewrite.
- **Migrations:** today `create_all` plus additive column checks at startup; adopt Alembic in Stage 2 before the first non-additive change.

### Tenant configuration (implemented)

| Section | Contents |
|---|---|
| `identity` | name, short name, product title, tagline, country, regulator, contacts, service area, population |
| `branding` | logo file, primary/accent colours |
| `currency` | ISO code, display symbol, decimals |
| `locale`, `timezone` | display locale and time zone |
| `fiscal_year` | `start_month` (1–12) |
| `hierarchy` | level labels (e.g. Zone/Scheme, Region/Service Area) and the zone list with colours |
| `targets` | e.g. `nrw_pct` |
| `thresholds` | insights alert thresholds |
| `strategic_plan` | title, years, KPI matrix (baseline, per-year targets, direction, capture state) |
| `modules` | on/off per module (UI enforcement: Stage 3) |
| `ai` | `enabled`, `provider`, `model` |

---

## 5. Security baseline

Implemented in this pass:
- Dev-preview passwordless login requires explicit opt-in and a development environment.
- `must_change_password` for the bootstrap admin, admin-created users and admin resets. Every API route except `/api/auth/me` and `/api/auth/change-password` returns `403 password_change_required` until changed, and the login screen shows a blocking dialog.
- New passwords must be ≥ 8 characters and differ from the current one.
- `scripts/reset_admin.py` replaces the fixed-password reset script.
- Environment variables are `MADZI_*` only (the legacy `SRWB_*` fallback was removed on 2026-09-24).

Still required before any second utility installs (Stage 3):
- Route-by-route authorization inventory, including exports and downloads. Add tests for denied access by role and, later, by organisational scope.
- Production defaults: refuse to start in production with the default secret (exists), and make `production` the default in shipped service scripts.
- Password policy and lockout, session revocation, audit of admin actions (partly exists).
- Vendor front-end libraries and add a Content-Security-Policy.
- Data protection: classify source files, set retention and deletion rules per client agreement, and redact data sent to AI providers.

---

## 6. Data and reporting workflow (target)

Submit → parse and map → validate → preview exceptions and duplicates → reviewer approval → publish a period → dashboards and reports → correction with version history.

- Every published value traces back to its upload, source row, correction and approving user.
- *Zero*, *missing*, *not applicable* and *pending* are distinct states.
- Each KPI shows its definition, formula, date coverage, data-quality status and calculation lineage (an in-app "KPI definition drawer").
- Never compare raw totals across different-sized utilities without normalisation.

---

## 7. Modules by release

| Release | Modules |
|---|---|
| **Core (adapt existing pages)** | Executive/board view, production & NRW, treatment & energy, customers & connections, billing & collections, operating cost, debtors, budgets, strategic scorecard, report centre, data approval |
| **Next vertical modules** | Water-quality compliance & corrective action; outages & service interruptions; customer complaints & service requests; assets & planned maintenance; GIS coverage & leak hotspots; capital projects |
| **Later extensions** | Offline field collection; regulator packs; billing/SCADA/ERP/LIMS connectors; forecasting & scenario planning; climate, energy & ESG indicators; optional AI narratives with redaction |

**Regulator packs** (a differentiator): dated indicator definitions, validation and export rules, jurisdiction and version. Candidates: MERA or the relevant water authority (Malawi), NWASCO (Zambia), WASREB (Kenya), EWURA (Tanzania). Confirm which body regulates **water** in each market before advertising a pack.

---

## 8. Additions beyond both reviews

These are the pieces that turn a configurable codebase into a supportable product:

1. **Units registry**: m³ vs ML, km vs m, with conversion at import, so KPIs stay comparable.
2. **Locale/i18n layer**: English first, with string keys ready for Portuguese, French and Swahili (SADC and East Africa markets).
3. **Data completeness score** per period and scope, shown next to every KPI and in board packs.
4. **Hierarchy labels in the UI**: the API already provides them; the UI still says "Zone/Scheme" everywhere (next Stage 1 item).
5. **Installation identity and version endpoint**: support can see version, tenant and schema level; this is a basis for licensing.
6. **`madzihub` CLI**: `init-tenant`, `import`, `backup`, `restore`, `reset-admin`, `check`.
7. **Upgrade policy**: semantic versions, Alembic migrations with rollback notes, and a tested upgrade path from the previous minor version.
8. **Vendored front-end assets**: no runtime CDN dependency; works offline.
9. **Backup/restore drill** as a release gate, not just a runbook.
10. **Synthetic dataset generator** (`tests/fixtures/synthetic_dataset.py`), reused for demos, training and performance tests.

---

## 9. Delivery stages and exit gates

Use [RESEARCH_BENCHMARK.md](RESEARCH_BENCHMARK.md) for the reviewed delivery sequence and module gates. The working order is migration foundation → shared scope/audit/workflow/actions → strategy and M&E → weighted scorecard → frozen reporting hub → document control → governance/risk → verified regulator packs and restricted HR extensions. Complete one reviewable slice at a time; do not treat this roadmap as authorization for a production migration or release.

### Acceptance scenarios
1. A new utility chooses a July–June year, a three-level branch hierarchy and a different currency. Every filter, KPI, chart, export and report follows, with no source edits. *(Calendar, currency and zones: done. Hierarchy depth and labels: Stage 1/2.)*
2. An administrator maps a new spreadsheet header to the platform's production measure. Invalid units and duplicate periods are flagged before commit, and corrections keep their source references.
3. Existing compatibility endpoints match their committed synthetic snapshots; any deliberate API change is separately documented and versioned.
4. A viewer cannot upload, configure targets, access restricted exports or see data outside their scope.
5. A clean demo instance contains only synthetic data, names and branding.

---

## 10. Decisions to record before distribution

- **Historical ownership and licence** for code, design, reporting definitions, prior Strategic Plan material, screenshots and branding associated with SRWB. Resolve this before public distribution; no SRWB deployment data belongs in the demo or product defaults.
- The first pilot utility's profile, the commercial support model, and whether clients need on-premises or managed private hosting.
- An accountable water-operations and finance reviewer to approve the initial common indicator catalogue and each local regulator pack against current primary sources.
- Exact default five-band labels, thresholds and scale direction for the internal score scheme; missing-data coverage gate and allowed overrides.
- Each first-market regulator's jurisdiction, current return format, code map, reporting cadence and scoring method. Do not infer a Malawi utility-provider league table from another country's regulator.
