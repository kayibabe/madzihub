# MadziHub Roadmap

Checklist view of [BLUEPRINT.md §9](BLUEPRINT.md#9-delivery-stages-and-exit-gates). Tick items in the PR that completes them.

All development happens in this repository; `kayibabe/opsapp` is frozen. For the researched product direction, source-linked benchmarks, scoring rules, reporting/document controls, and revised delivery order, see [RESEARCH_BENCHMARK.md](RESEARCH_BENCHMARK.md). The earlier market gap analysis remains useful background: [COMPETITIVE_GAP_ANALYSIS.md](COMPETITIVE_GAP_ANALYSIS.md).

## Stage 0: Protect and baseline
- [x] Clean import of opsapp code without utility data or git history
- [x] `.gitattributes`; `.gitignore` blocks spreadsheets, DBs and secrets
- [x] Synthetic dataset + API parity snapshots (58 endpoints)
- [x] Synthetic demo tenant (MadziHub identity; all utility records and figures fictional)
- [ ] **Owner:** written code/data ownership and licence position with SRWB
- [ ] **Owner:** opsapp public repo: make private, or remove `dataupdater/` and rewrite history
- [x] Remove SRWB from the product: `tenants/srwb`, SRWB import tools and legacy `SRWB_*` settings removed (2026-09-24); last SRWB version preserved at tag `srwb-reference`

## Stage 1: Extract configuration
- [x] Tenant YAML + validated loader (`app/core/tenant.py`)
- [x] Fiscal calendar from `fiscal_year.start_month` (tested Jan/Apr/Jul)
- [x] Zone list and colours from tenant (Python + JS)
- [x] Single NRW target (`targets.nrw_pct`); insights thresholds from tenant
- [x] Strategic plan KPI matrix from tenant
- [x] `/api/config`, `/api/config/public`, `/api/config/logo`; org profile overrides identity
- [x] HTML and `app-core.js` branded server-side (name, currency, targets, months)
- [x] AI narratives behind `ai.enabled`; model configurable
- [x] Security: dev-preview opt-in, forced password change, safe admin reset, `MADZI_*` env
- [ ] UI uses hierarchy labels (`Zone/Scheme` → tenant labels) in filters, tables, charts, exports
- [x] Currency-neutral money headers in `excel_parser.COLUMN_MAP` / `main.HMAP` (tenant currency suffix accepted)
- [ ] Currency formatting via one `fmtMoney()` using `currency.decimals` and locale
- [x] API key `srwb_target_pct` renamed `nrw_target_pct`; `*_mk` budget keys renamed (no frontend used the old names)
- [x] Budget seed reads `tenants/<tenant>/budget.yaml` (fictional demo budget included)
- [ ] Rewrite `docs/DEPLOYMENT_RUNBOOK.md` for MadziHub (tenant selection, production env)

## Integration hub ([INTEGRATION_HUB.md](INTEGRATION_HUB.md))
- [x] Org-unit tree of any depth; metric catalogue; `metric_values` with source lineage; targets by period and basis
- [x] Connectors: SQL, REST/OData (paging, incremental), file drop/upload (CSV/Excel), push with per-source token, legacy records bridge
- [x] Key mappings (cost centres, sites, tags → our codes); rejects with reasons; idempotent loads; watermarks
- [x] Source priority for the published value; reconciliation between sources; freshness/overdue per source
- [x] Position API: where we were / are / are going, gap to target, trend; organisation-level roll-up of additive measures
- [x] CLI for scheduled pulls (`python -m app.integration.cli sync --due`)
- [x] Formula measures (ratios computed from components at every level); fiscal quarter/year roll-up with year-to-date flag; plan targets seeded
- [x] Admin UI: sources, runs, rejects, key mappings, push tokens, freshness (Administration → Data Sources)
- [x] Measures & Targets admin screen: catalogue editor with live formula check and preview; targets by measure, unit and fiscal period
- [x] Strategic Position page on `metric_values`: unit/period picker, status vs target, trend, lineage chart (Board → Strategic Position)
- [x] Dry-run **Test** for sources (UI, API, CLI): connect, sample, map, report; writes nothing
- [x] Billing pilot pack (docs/pilots): view contract + SQL (PostgreSQL, SQL Server), client checklist, day-by-day plan, reconciliation acceptance; configuration tested end to end
- [ ] Run the billing pilot with a utility (needs their read-only account and branch list)
- [ ] Validate recipes against client sandboxes: SAP OData, Maximo, historian/PI, HR export
- [ ] Unit registry and conversion at mapping time
- [ ] Move existing panels from `records` to `metric_values` (parity-guarded)

## Stage 2: Generalise data entry
- [x] Alembic migrations: baseline `0001` = schema at 8de1ef9; startup builds only empty databases; `python -m app.migrate status|upgrade|adopt` with automatic SQLite backups; pre-Alembic databases checked against a baseline fingerprint before stamping; SQLite foreign keys and WAL on ([DEPLOYMENT_RUNBOOK.md](DEPLOYMENT_RUNBOOK.md#database-migrations))
- [ ] Hierarchy table: N levels, parent/child, codes ✅ (`org_units`); aliases via key mappings ✅; effective dates ⏳
- [ ] Versioned targets: KPI × fiscal year × org scope, with benchmark provenance (fixes per-year SP NRW targets)
- [ ] Metric catalogue: code, unit, aggregation, direction, formula ✅ (`metrics`); valid range ⏳
- [ ] Import mapping profiles: upload sample → map columns → validate → save a versioned profile (per-source mappings ✅; versioning and UI ⏳) (targets metric codes, not DB columns; single-row and grouped headers; unit conversion)
- [x] SRWB zone-workbook builder (`rawdata_builder.py`) removed; source-specific formats belong in the integration hub as adapters
- [ ] Per-tenant validation rules replace calculation-time data quirks (days-to-connect outliers, supply-hours units, stub rows)
- [x] Approval workflow: submit → verify → approve; period locks; reasoned reopen; correction history and lineage (strategy module, revision 0003)
- [x] Distinct zero / missing / not-applicable / pending states (progress updates)

- [x] Org-scoped access, deny-by-default (revision 0002; route sweep test)

## Stage 2b: Strategy & balanced scorecard (sequence and design in [RESEARCH_BENCHMARK.md](RESEARCH_BENCHMARK.md); guide in [PERFORMANCE_GOVERNANCE.md](PERFORMANCE_GOVERNANCE.md))
- [x] Plan → configurable levels → results and delivery trees in DB; importer from tenant YAML (0003)
- [x] Owners, weights (100 per level), scoring and roll-up with coverage gate (0004)
- [x] Quarterly updates with commentary, DQA and approval; action tracker (0002–0003)
- [x] Strategy map (0004); performance contracts and staff appraisal behind policy/privacy gates (0009)
- [ ] Budget versions and approval; capital project register
- [x] Risk register linked to objectives; audit findings; meetings and resolutions (0007)
- [x] Internal plan score schemes separate from versioned regulator packs; explicit rating order and missing-data policy (0004, 0008)
- [x] Frozen score inputs, scheme and engine versions, inputs hash and approval for every approved score (0004)
- [x] Reporting hub: frozen instances, approval, HTML/PDF/XLSX outputs, access log (0005)
- [x] Document control: evidence versions, controlled documents, search, backup/restore (0006)
- [ ] Regulator packs: fill and verify WASREB IMPACT 17 / EWURA FY2023/24 figures from the cited tables; add the EWURA four-component KPI scoring; second-officer approval
- [ ] NWASCO / IBNET packs after primary-source verification
- [ ] Kenya performance-contract adapter only if it reproduces the exact current rules
- [ ] Scheduled/e-mail report distribution (needs explicit configuration and authorisation)
- [ ] Records retention, legal holds, disposal (needs each utility's approved schedule); OCR

## Research-led module order

Use [RESEARCH_BENCHMARK.md](RESEARCH_BENCHMARK.md) as the working plan for the real system: migration foundation → shared scope/audit/workflow/actions → strategy and M&E → weighted scorecard → frozen reporting hub → evidence and controlled documents → governance/risk → locally verified regulator packs and restricted HR extensions. This sequence supersedes the older broad grouping below where they conflict.

## Stage 3: Package and harden
- [x] Vendor Chart.js, DOMPurify, SheetJS and the Inter / IBM Plex Mono fonts (no runtime CDN; offline installs); checksum manifest enforced by tests and the release-bundle validator
- [ ] Content-Security-Policy header (needs the remaining inline scripts in `index.html` moved to files first)
- [ ] Decide on SheetJS beyond 0.18.5 (later versions are not on npm; current use is write-only exports)
- [ ] Module toggles enforced in UI and API; hide pages without data
- [ ] Setup wizard: identity → hierarchy → calendar → currency/units → mapping → targets → users
- [ ] Docker image and compose file; `production` default in service scripts
- [x] Replace python-jose with PyJWT (removes ecdsa, which has an unpatched timing advisory)
- [x] Route-by-route authorization inventory and tests (every /api route must be admin, org-wide or scope-guarded)
- [x] Backup/restore runbook + restore round-trip test (`python -m app.platform.backup`)
- [ ] PostgreSQL validated in staging; documented migration from SQLite
- [ ] `madzihub` CLI (`init-tenant`, `import`, `backup`, `restore`, `reset-admin`, `check`)
- [ ] Version/installation endpoint; upgrade policy
- [ ] Accessibility pass: keyboard access, colour-independent status, missing-data states

## Stage 4: Extend (by funded demand)
- [ ] Water-quality compliance and corrective actions
- [ ] Outages and service interruptions
- [ ] Customer complaints and service requests
- [ ] Assets and planned maintenance; capital projects
- [ ] GIS coverage and leak hotspots
- [ ] Regulator packs (confirm the water regulator per market)
- [ ] Connectors: billing, SCADA, LIMS, ERP/payroll
- [ ] Forecasting and scenarios; climate/energy/ESG indicators
- [ ] Offline field collection
