# MadziHub vs. leading utility management software

Gap analysis and implementation plan, 24 September 2026.
Companion to [BLUEPRINT.md](BLUEPRINT.md) and [ROADMAP.md](ROADMAP.md). All work happens in this repository; `kayibabe/opsapp` is frozen (see §6).

> Vendor capabilities below are summarised from general market knowledge of each product category, not from a feature-by-feature audit or licensed demo. Verify any claim before putting it in a sales document.

---

## 1. The honest starting point

MadziHub today is a **performance reporting system**: about 83 API endpoints, and nearly all of them are read-only `GET`s over one wide `records` table (zone × scheme × month, ~220 measures). The only write paths are spreadsheet upload, fiscal-year and budget setup, and user administration.

The products utilities buy for strategy and performance are **management systems**. They record who owns an objective, which initiatives deliver it, what was done this quarter, why a KPI missed, who approved the numbers, and what risk threatens the plan. That, not charts, is the main gap.

Second structural gap: every measure is a **hardcoded database column**. So "take in as much information as possible" is currently impossible without code changes. Fixing that comes before adding modules; otherwise each new module adds another hardcoded wide table.

---

## 2. Who we are being compared against

No single product does everything listed in the brief. Utilities assemble a stack:

| Category | Representative products | What it owns |
|---|---|---|
| Strategy & balanced scorecard | Envisio, ClearPoint Strategy, Spider Impact, Cascade, QuickScore | Plans, objectives, KPIs, initiatives, owners, commentary, board reporting |
| Public-sector budgeting | Questica (Euna), OpenGov, Workday Adaptive Planning | Budget build, versions, approvals, capital plans, forecasts |
| Utility ERP / CIS | SAP S/4HANA Utilities, Oracle Utilities (CC&B, C2M) | Billing, customers, finance, procurement (system of record) |
| Enterprise asset management | IBM Maximo, HxGN EAM, Cityworks, Cartegraph | Asset register, work orders, maintenance, condition, risk-based renewal |
| Water operations analytics | Autodesk Info360, Aquasuite, Xylem digital products | SCADA/telemetry analytics, NRW and pressure management, energy |
| Compliance / LIMS | Aquatic Informatics (WIMS, WaterTrax), LIMS vendors | Sampling, lab results, regulatory limits, reporting |
| HR / HCM | Workday, SAP SuccessFactors, Sage | Payroll, positions, training, performance appraisal |
| GRC / risk | Riskonnect, LogicManager, Diligent | Risk register, controls, audit findings, board governance |
| GIS | Esri ArcGIS Utility Network | Network model, spatial assets, hotspots |
| Benchmarking | IBNET, AWWA Utility Benchmarking, national regulators | Standard indicator definitions and peer comparison |

**Positioning recommendation.** Do not rebuild ERP, EAM, CIS, SCADA or HCM. A utility in our market will not replace SAP or its billing system with MadziHub, and we cannot out-feature Maximo. The winning position is the **integrated performance and strategy layer above those systems**. It is Envisio/ClearPoint + Questica-lite + IBNET benchmarking, built for water utilities, and it runs on imperfect spreadsheet data as well as live feeds. For utilities with *no* EAM or HR system, offer lightweight registers (assets, staff, projects) that are good enough to report from, and do not market them as full EAM/HR replacements.

That is where we can credibly beat the big vendors: price, offline/on-premises deployment, water-specific KPIs out of the box, and starting from Excel returns on day one.

---

## 3. Capability matrix

Legend: ✅ have · 🟡 partial · ❌ missing. **Build** = implement in MadziHub; **Register** = lightweight in-app register; **Integrate** = import from the system of record.

### 3.1 Platform foundations (prerequisite for everything else)

| Capability | Leaders do | MadziHub | Gap / action | Approach |
|---|---|---|---|---|
| Configurable metric catalogue | KPIs defined as data: code, unit, formula, aggregation, polarity, owner | 🟡 KPI registry exists in `governance.py` but is Python constants; measures are DB columns | Metric catalogue tables; formulas evaluated over stored measures | Build |
| Flexible fact storage | Any measure at any org level and period | ❌ 222-column `records` table | `metric_value(metric, org_unit, period, dimension, value, status, source)` alongside `records`; migrate panels gradually | Build |
| N-level org hierarchy | Region → district → scheme → plant; departments as a parallel tree | 🟡 two fixed levels, configurable labels | `org_unit` table with parent, type, code, aliases, effective dates; department tree | Build |
| Periods | Monthly/quarterly/annual, custom fiscal year | 🟡 monthly, configurable FY start | `period` table; support quarterly and annual metrics | Build |
| Import mapping | Save a mapping per source file layout | 🟡 hardcoded `COLUMN_MAP` | Versioned mapping profiles to **metric codes** (not DB columns); single-row and grouped headers; unit conversion | Build |
| Data approval & lineage | Submit → review → publish, locks, audit | ❌ upload writes directly | Workflow states, period locks, correction history | Build |
| Zero / missing / N/A / pending | Distinct states | ❌ | `status` on every value | Build |
| Connectors / API ingest | REST, scheduled pulls, CSV drops | 🟡 SQL, REST/OData, file, push and legacy connectors built ([INTEGRATION_HUB.md](INTEGRATION_HUB.md)); vendor recipes untested | Validate against client sandboxes; admin UI | Integrate |
| Row-level access by org scope | Users see only their region/department | ❌ roles only | Scope on users; enforce in every query | Build |
| Multi-language | Common in regional products | ❌ | String keys (EN first; PT/FR/SW later) | Build |

### 3.2 Strategic planning & balanced scorecard

| Capability | Leaders do | MadziHub | Approach |
|---|---|---|---|
| Plan structure: vision, pillars/perspectives, objectives, strategies | Core feature | 🟡 flat KPI matrix in tenant YAML | Build: `plan → perspective → objective → KPI/initiative` in DB, editable in UI |
| BSC perspectives (Financial, Customer, Internal Process, Learning & Growth) | Standard template | ❌ (focus areas only) | Build: perspectives as configurable template |
| Cascading to departments / individuals | Core | ❌ | Build: objectives link to org units and parent objectives |
| Initiatives / projects with milestones, budget, % complete | Core | ❌ | Build |
| Owners and accountability | Every item has an owner | ❌ | Build |
| Periodic status updates & commentary ("why red, what next") | Core | ❌ | Build: commentary per KPI × period, with approval |
| Strategy map | Common | ❌ | Build (read-only visual from the plan tree) |
| Per-year and per-scope targets, tolerance bands | Core | 🟡 per-year targets in YAML, one scope | Build: `target(metric, period, org_unit, value, lower, upper, source)` |
| Scoring and roll-up (weighted objective scores) | Core | ❌ | Build |
| Action items / follow-ups from reviews | Common | ❌ | Build: action tracker linked to KPI, meeting and owner |
| Performance contracts (government/regulator contracts) | Common in African public utilities | ❌ | Build: contract = plan subset + targets + signed version |

### 3.3 Department operations (water-specific)

| Area | MadziHub | Gap | Approach |
|---|---|---|---|
| Production, NRW, water balance | ✅ panels + NRW analysis | IWA water-balance table (authorised/unauthorised, apparent/real losses) | Build |
| Treatment, chemicals, energy | ✅ wt-ei panel | Energy intensity by plant, chemical dosing vs. target | Build (with hierarchy) |
| Supply continuity / interruptions | 🟡 hours of supply | Outage events (start, end, customers affected, cause) | Register |
| Water quality compliance | 🟡 summary module | Sample schedule, results vs. limits, exceedances, corrective actions | Register + LIMS import |
| Customer service | ❌ | Complaints/requests, SLA times, resolution | Register + CIS import |
| Metering, connections, disconnections | ✅ | Meter age and accuracy profile | Build |
| Billing, collections, debtors | ✅ | Aged-debt buckets, collection by customer class | Build |
| Sanitation / wastewater | ❌ | Wastewater KPIs (coverage, treatment compliance) | Build via metric catalogue |

### 3.4 Finance & budgets

| Capability | Leaders do | MadziHub | Approach |
|---|---|---|---|
| Opex budget vs. actual | Core | ✅ variance by line and zone share | Keep |
| Budget build with versions (draft, approved, revised) and approval | Core (Questica, OpenGov) | ❌ entered, not built | Build |
| Capital budget and capital projects | Core | ❌ | Build: project register with budget, spend, milestones, funding source |
| Rolling forecast / scenarios | Core (Adaptive) | ❌ | Build later: driver-based forecast (tariff × volume × collection) |
| Tariff modelling and cost recovery | Specialist tools | 🟡 profitability panel | Build: cost-recovery ratio and tariff scenario |
| Financial statements KPIs (liquidity, debt service, working ratio) | Common | 🟡 | Build via metric catalogue; import GL trial balance |
| Donor / grant tracking | Relevant for our market | ❌ | Register |

### 3.5 Infrastructure & assets

| Capability | EAM leaders | MadziHub | Approach |
|---|---|---|---|
| Asset register (hierarchy, class, location, install date, value) | Core | ❌ (pipe-material summaries only) | Register |
| Condition and criticality → risk score | Core | ❌ | Register |
| Planned vs. reactive maintenance, work-order KPIs | Core | 🟡 breakdown counts | Integrate from EAM, or Register as simple work log |
| Renewal planning / capital needs | Core | ❌ | Build later on top of asset register |
| GIS map of assets, breakdowns and leaks | Core | ❌ | Build: map view from coordinates; Esri import later |
| SCADA / telemetry | Operations analytics tools | ❌ | Integrate (daily aggregates only, not real time) |

### 3.6 Human resources

| Capability | HCM leaders | MadziHub | Approach |
|---|---|---|---|
| Headcount, staff per 1,000 connections | Core | ✅ workforce and productivity panels | Keep |
| Establishment vs. filled positions, vacancies | Core | ❌ | Register or import |
| Turnover, absenteeism, overtime | Core | ❌ | Metric catalogue + import |
| Training hours and skills | Core | ❌ | Metric catalogue + import |
| Health & safety (incidents, LTIFR) | Core | ❌ | Register |
| Individual performance appraisal linked to objectives | Core | ❌ | Build later (cascading end point); do not replace payroll/HCM |

### 3.7 Governance, risk & reporting

| Capability | Leaders do | MadziHub | Approach |
|---|---|---|---|
| Board packs, scheduled reports | Core | ✅ board pack and report centre | Add scheduling and email distribution |
| KPI definitions and evidence | Core | ✅ governance bundle | Move into metric catalogue |
| Enterprise risk register (likelihood, impact, owner, controls, linked objectives) | Core (GRC) | ❌ | Build |
| Audit findings and management actions | Common | ❌ | Build (reuses action tracker) |
| Regulator submissions | Common | ❌ | Regulator packs (BLUEPRINT §7) |
| Benchmarking vs. peers | IBNET | ✅ indicators | Add peer datasets per regulator |
| Anomaly detection, narratives | Emerging | ✅ opt-in AI, anomaly service | Keep opt-in; add redaction |
| Mobile / offline data capture | Common | ❌ | Build later (PWA) |

---

## 4. Target data model

Everything above reduces to eleven core tables. Build these first and each module becomes configuration and screens, not new schema:

```
org_unit (id, parent_id, type[region|district|scheme|plant|department], code, name, aliases, valid_from, valid_to)
period (id, type[month|quarter|year], start_date, end_date, fiscal_year)
metric (code, name, unit, category, module, aggregation[sum|avg|last|formula], formula,
        direction[higher|lower|range], valid_min, valid_max, owner_role, definition, source)
metric_value (metric_code, org_unit_id, period_id, dimension_key, value, status[actual|missing|na|pending],
              upload_id, source_row, version, approved_by, approved_at)
target (metric_code, org_unit_id, period_id, value, lower, upper, source, plan_id)
import_profile (id, name, version, header_mode[single|grouped], mappings[json: column → metric_code, unit, org_unit rule])
plan / perspective / objective / initiative (tree with owners, weights, dates, budget, status)
update (entity_type, entity_id, period_id, status_colour, commentary, next_steps, author, approved_by)
action (source_entity, title, owner, due_date, status)
risk (title, category, likelihood, impact, owner, controls, linked_objective_ids, review_date)
register_item (register_type[asset|outage|complaint|incident|project|sample], org_unit_id, attributes[json], dates)
```

Design rules:
- **Keep `records` as a compatibility layer.** Existing panels keep working and parity snapshots stay green. Upload writes to both until each panel moves to `metric_value`.
- **Formulas reference metric codes**, e.g. `nrw_pct = (production - billed_volume) / production * 100`. Evaluate them with a safe parser, never with `eval`.
- **Aggregation is declared, not coded.** Ratios are recomputed from their components at each roll-up level, never averaged.
- **Typed registers use a JSON attribute schema per register type,** defined in tenant config. That gives flexibility without a table per register. Promote a register to real tables once its queries need it.
- Adopt **Alembic** before the first of these tables lands.

---

## 5. Implementation sequence

Every phase must keep the SRWB parity snapshots green, or document the diff.

| Phase | Deliverables | Exit test |
|---|---|---|
| **A. Foundations** (do first) | Alembic; `org_unit` (N levels + departments); `period`; `metric` catalogue seeded from the current 222 columns and the governance KPI registry; `metric_value` dual-write on upload; import profiles (single-row + grouped headers, unit conversion); value status | A fictional utility with a 3-level hierarchy uploads a differently shaped workbook through a saved profile, with no code change, and its values appear in the catalogue |
| **B. Data governance** | Submit → review → publish; period locks; correction history; org-scoped access | A viewer scoped to one region cannot see another region's data through any endpoint or export |
| **C. Strategy & BSC** | Plan tree in DB (migrate from YAML); perspectives; cascading objectives; initiatives; owners; targets table; scoring; quarterly updates with commentary; action tracker; strategy map | A quarterly performance review runs end to end in the app: owners submit updates, the executive approves, the board pack pulls commentary |
| **D. Budget & capital** | Budget versions and approval; capital project register; cost-recovery and financial ratios; GL trial-balance import | A capital project shows budget, spend, milestone and linked objective in one place |
| **E. Operational registers** | Outages, complaints, water-quality samples, H&S incidents, asset register (condition/criticality) using typed registers | Each register feeds at least one catalogue KPI automatically |
| **F. Risk & compliance** | Risk register linked to objectives; audit findings; regulator packs | Board pack includes top risks and overdue audit actions |
| **G. Integration & reach** | Ingest API; scheduled file drops; CIS/ERP/SCADA/LIMS adapters by demand; GIS map; PWA offline capture; i18n | A nightly feed replaces a monthly spreadsheet for one data domain |

Phases C–F can run in parallel once A and B are done. Doing C before A would hardcode the plan structure again.

---

## 6. Review of the Codex "reusable framework" change (opsapp)

The Codex change was made in a local `kayibabe/opsapp` checkout and never pushed; `opsapp` main is still `efa4a29`, the commit MadziHub was imported from. The review is therefore of its written summary, not its diff.

**Decision: opsapp is frozen. Do not continue the Codex branch.** Port only the two ideas below into MadziHub, with tests.

| Codex item | Assessment |
|---|---|
| Generic product/API identity, configurable name and currency | Already done in MadziHub (tenant YAML + org profile + `/api/config`). Duplicate. |
| Fiscal-year start month | Already done and tested (Jan/Apr/Jul). Duplicate. Caution for any implementation: changing the start month after data exists relabels historical periods, so lock it once data is loaded. |
| Two configurable hierarchy labels | MadziHub already has the labels. Still limited to two levels; the real fix is `org_unit` (Phase A). |
| Saved spreadsheet column mappings | **Worth porting.** However, the Codex version maps headings to existing storage fields, i.e. DB columns. Profiles should target **metric codes**, carry a version, and record unit conversions. Otherwise they need rewriting when the catalogue lands. |
| One-row headers as well as grouped headers | **Worth porting** into `excel_parser.py`, with tests against the synthetic dataset. |
| Removed `reset_password.py` (hardcoded admin password) | Already fixed in MadziHub (`scripts/reset_admin.py` + forced password change). The copy in public `opsapp` history is still exposed. If any live install still uses that password, rotate it. |
| Verification: compile, FY checks, `git diff --check`; app not run | Insufficient for production code. MadziHub requires unit tests plus the 58-endpoint parity snapshots. |
| Tracked workbooks and history left in place | **Open risk.** Utility spreadsheets remain in the public `opsapp` repo and its history. Owner action: make it private, or remove the files and rewrite history (ROADMAP Stage 0). |

Codex's own conclusion is right, and it matches this document: a file can only be mapped into fields the system already supports until there is a configurable metric catalogue, formulas, units and a flexible hierarchy. That is Phase A.
