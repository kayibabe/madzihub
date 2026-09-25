# MadziHub GUI and UX review

Date: 25 September 2026. Status: consolidated working review; implementation pending. The fiscal-filter policy below remains recommended, pending product confirmation.

## Scope and evidence

This consolidates the initial source review with an interactive browser review of the current checkout. Browser observations used an isolated SQLite database, `data/ux-review-20260925.db`, created with the repository's fictional demo seed. The existing application database was not used or changed. The account was the seeded planner, not an administrator.

Reviewed: sign-in; Board Summary without operational returns; My Work with an assigned action; Progress Updates queues and an approved record; Reporting Hub and its new-report dialog; Scorecard; Strategic Position without data and with North's quarterly figure and its drill-down. Desktop viewport: 1440 x 1000. Responsive spot check: 390 x 844, plus the browser's initial narrow viewport. Screenshots and accessibility snapshots were inspected during the session.

The seeded 31.4% NRW value is fictional. No reports, approvals, comments or operational returns were submitted. The new-report form was cancelled with Escape.

Not covered: production, populated legacy operational dashboards, administrator setup/import journeys, other roles, large datasets, full keyboard traversal, measured colour contrast, assistive-technology testing, exports, or every responsive breakpoint. Browser-rendered demo observations are Verified for this local setup, not proof of production behaviour. Design proposals below are recommendations.

Version under review: HEAD recorded during the browser review was `8647c52` ("Correct KPI missing-data assessment and set NRW target to 27 percent"). Working-tree changes were limited to this review document; the application code matched HEAD. Follow-up source verification of UX-01, UX-02, UX-03, UX-09 and UX-11 used the same commit. Future reviews must record both the commit and any application-code changes.

Earlier version: the first draft of this review, with its source anchors, comparative analysis and six-group navigation proposal, is in git at `8647c52:docs/GUI_UX_REVIEW_2026-09-25.md`. This document supersedes its ordering. The correctness exit gate from that draft has been carried into Slice 1a below.

## Overall direction

Keep the teal identity, restrained cards, text status badges, and existing evidence/approval history. The main need is a coherent application shell and clearer task flows. Correct misleading states and reporting context before expanding visual styling.

## Verified findings and recommended treatment

| ID | Priority | Observation | Recommended treatment |
| --- | --- | --- | --- |
| UX-01 | P1 | Board Summary says Awaiting Data and NO RETURNS. Operations and Finance show Not assessed, but HR shows GOOD for staff per 1,000 connections and payroll; Infrastructure shows GOOD for reliability/stuck meters and CRITICAL for active connection ratio, all against zero values. **Source cause (verified at `8647c52`):** `app/routers/report_generator.py:548-662` returns `0` rather than `null` for zero-denominator ratios (`staff_per_1000_conn`, `payroll_cost_ratio`, `stuck_pct`, `active_conn_ratio`). Line 641 uses `active = ... or 1`, so an empty scope yields 0 breakdowns per 1k customers. The Board cards at `app/static/assets/js/app-core.js:2488-2503` already guard on `null`, but receive `0`. Lines 2501 and 2739 also coerce missing values with `(x\|\|0)` before assigning a badge. Commit `8647c52` did not cover these HR and Infrastructure paths. | Apply one missing-data contract to every card: no performance verdict without sufficient inputs. Keep real zero distinct from missing, pending and not applicable. Fix at the API (return `null` or an explicit assessment state), then remove the client-side coercions. |
| UX-02 | P1 | After selecting FY 2025/26 in the top bar, Progress Updates still lists Q1 FY2026/27. Reporting Hub lists that period, its New report dialog defaults to FY2026/27, and Scorecard's local period remains Q1 FY2026/27. Strategic Position also displays a quarter starting July 2026 under the FY 2025/26 header. **Demo artefact vs defect:** `app/demo_seed.py:122-124` seeds the strategy cycle into the quarter containing today's date (Q1 FY2026/27 on the review date), while operational screens default to FY2025/26. The mismatch in record years is therefore partly seed timing. The product defect is independent of the seed: the global year control has no effect on the strategy and reporting pages, yet appears to govern them. | Make each control's scope explicit. Either bind applicable pages to the selected year or remove the unrelated global year control and show authoritative page-local scope. Cross-year work queues can remain cross-year if labelled clearly. Do not silently reset drafts or reinterpret historical reports. |
| UX-03 | P1 | Strategic Position displays All sources current alongside strategy-updates: never, including its no-data state. **Source cause:** `app/static/assets/js/integration-hub.js:444-446` flags only sources that are enabled and overdue or failed. A source that has never run therefore counts as current. | Separate freshness from connector scheduling and ingestion history. Show Not assessed / No ingestion recorded when appropriate; distinguish manually approved updates from polled sources. Do not imply healthy coverage from the absence of overdue sources. |
| UX-04 | P2 | At 390 x 844, menu, year, zone, period, clear, advanced-filter and refresh controls stack above the department tabs. The page title begins roughly halfway down the screen. The attribution footer occupies the bottom area alongside the mobile action bar. | Use a compact mobile header and a filter sheet with a selection summary. Reserve non-overlapping space for bottom actions; move attribution out of the fixed working area. |
| UX-05 | P2 | Navigation combines horizontal department tabs with a changing sidebar. The planner initially lands on Board Summary; My Work requires opening Performance & Governance. Board has several similar summary/strategy destinations and Soon items; the governance sidebar is long and some group labels truncate. | Provide a persistent My Work entry and role-appropriate landing. Clarify summary vs analysis vs governed scorecard destinations. Group setup separately and remove Soon entries from primary task navigation. Preserve useful departmental views and existing permissions. |
| UX-06 | P2 | Progress Updates gives the list most of the width while the selected record's definition, evidence, revisions, decisions and comments occupy a narrow column. With two rows, much of the list area is empty while the detail requires scrolling. | Allow expanded record detail, with a clear back-to-list route, selected-row state and preserved queue filters. Use tabs/sections for overview, evidence and history; retain the existing audit information. |
| UX-07 | P2 | Reporting Hub and Scorecard open with long descriptions of implementation and governance mechanics. New report embeds long template descriptions inside a narrow select, truncating the selected text. Its action is simply Save. | Use short task-oriented introductions and contextual help. Put template descriptions below the selection or in a template chooser. Label the final action Create draft report and summarise the selected unit and period before submission. |
| UX-08 | P2 | My Work already has action counts, overdue counts, verification, notices and record links. The populated planner example repeats the same action in its table and notice list, while an empty verification panel has equal visual weight. | Enhance this existing workspace: prioritise actionable/overdue queues, make counts useful navigation, and visually subordinate empty/completed sections. Verify all role-specific module queues before adding new ones. |
| UX-09 | P2 | Strategic Position shows actual 31.4%, target 28%, and gap 3.4%. It has a working trend/source drill-down. Missing measures precede the one reporting measure. | Label this absolute difference 3.4 percentage points (pp). Lead with reporting measures and exceptions; group missing measures with a coverage summary. Preserve drill-down and distinguish target, benchmark and approval status. |
| UX-10 | P2 | Both legacy Zone/Scheme filters and newer organisational-unit selectors appear in the reviewed journeys. Strategic Position additionally has both global Period and local Period controls with different meanings. | Use configured hierarchy labels and name local aggregation explicitly, e.g. View by: Month / Quarter / Fiscal year. Avoid duplicate controls that appear to govern the same data. |
| UX-11 | P1 | **Unclear comparator context.** The demo has a 27% corporate NRW target (`tenants/demo/tenant.yaml`, `targets.nrw_pct`); strategic-plan targets of 30% for 2026 and 28% for 2027; North/South quarterly targets of 28%/30% (`app/demo_seed.py:125-127`); and warning/critical thresholds of 35%. These can legitimately differ. Missing comparator provenance makes verdicts difficult to interpret and creates a risk of inconsistent assessment for equivalent contexts. Different numbers alone do not establish an incorrect target. (Source-verified; a rendered side-by-side comparison of equivalent contexts is Untested.) | Show comparator type, source, unit, period and version with each assessment. Use a shared governed resolver that preserves measure definition, comparator type, organisational scope, period and version. Keep corporate/plan targets, operational warning bands and regulatory benchmarks distinct. Equivalent contexts must resolve consistently; missing rules mean Not assessed against that rule, without silent fallback. |

## Existing strengths to preserve

- Teal branding and restrained card styling already provide a usable visual foundation.
- My Work is implemented; this is an improvement task, not a new module.
- Progress Updates distinguishes approved, not submitted, and missing submissions; its detail retains narrative, evidence, data-quality checks and decisions.
- Scorecard explicitly separates achievement, completeness and data quality, and shows Incomplete rather than zero for insufficient coverage.
- Strategic Position already offers actual/target comparison and a chart/source drill-down.
- The new-report dialog has an initial focused control and dismisses with Escape. A complete focus-trap/return-focus audit remains outstanding.

## Consolidated delivery sequence

### Slice 1a: Missing-data correctness (small, independently shippable)

Implement UX-01 through the affected calculations and their consumers. This slice fixes data handling and its presentation; navigation and design-system changes remain outside its scope.

Scope:

- **Before editing application code**, inventory each affected calculation and every consumer: APIs, cards, charts, Excel/PDF exports, live reports, narratives, alerts and snapshot tests. Record current behaviour, intended missing/zero semantics, affected files and regression coverage. Check frozen-report paths separately.
- Return `null` (or an explicit assessment state) for zero-denominator ratios in `report_generator.py` and the equivalent paths in `panels.py`, `insights_engine.py` and `narrative_engine.py`. Remove the `active = ... or 1` substitution.
- Preserve zero defaults only where zero is semantically valid. Correct any default that misrepresents missing or unassessed data, including totals, charts, exports, narratives and badge assignments; do not blanket-replace `(x||0)`. Missing assessed values render `—` with Not assessed.
- Update affected consumers to handle the resulting contract without crashes, misleading chart points or unsupported performance narratives.

Correctness exit gate:

- Changed status labels remain understandable without colour and accessible to assistive technology; retain keyboard access to affected controls.
- Tests cover absent keys, explicit nulls, genuine zeros, zero denominators, partial scope, stale data and complete data, including unit and fiscal roll-ups. Python `get(key, 0)` does not replace an existing `None`, so explicit nulls need their own test.
- For the same measure, rule, scope and period, dashboard and report statuses agree.
- An empty return scope never produces GOOD, WATCH, HIGH or CRITICAL badges. A legitimate measured zero still displays as zero.
- An empty alert list does not imply that all indicators were assessed.
- Existing approved or frozen reports are not silently regenerated. Audit the frozen reporting hub separately: a defect in the live Report Centre does not by itself prove that approved snapshots contain it.
- API snapshot changes in `tests/snapshots/` are reviewed individually. Each `0` → `null` change must be explained, not bulk-accepted.

### Slice 1b: Reporting scope, freshness and comparators

Implement UX-02, UX-03, UX-11 and the percentage-point correction from UX-09. Establish shared display states and an explicit page-by-page filter contract before standardising the header.

**Fiscal-filter policy — accepted as written by the product owner on 25 September 2026.** Inventory every page and map it to the agreed policy before changing the shared header.

| Page type | Recommended scope behaviour |
| --- | --- |
| Performance dashboards | Apply the selected global fiscal year and applicable unit/period filters. |
| My Work and approval queues | Permit cross-year work and label that scope explicitly; do not imply that the global fiscal year filters the queue. |
| Strategy and scorecards | Use explicit local plan, unit and period selectors; hide unrelated global fiscal controls. |
| Governed reports | Use explicit scope when creating/listing reports. An existing report's period is fixed by its record; opening an approved FY2025/26 report never changes its period or content to match the top bar. |
| Setup screens | Hide fiscal controls that do not affect the task. |

Acceptance:

- Changed filters have accessible names, keyboard operation and visible focus; scope/status meaning does not depend on colour.
- No page presents an apparently active fiscal filter that does not govern its content without an explicit explanation. Cross-year work queues say that they are cross-year.
- A never-ingested or unassessed source does not receive an unconditional current/healthy label.
- Every assessment identifies its comparator (type, source, unit, period and version). Screens and newly generated reports resolve consistently for the same measure definition, comparator type, scope, period and version. Preserve the rules and values frozen into historical approved reports.
- The fictional 31.4% versus 28% example reads 3.4 pp above target.
- Demo seed timing is controlled in tests (fixed date or explicit period), so filter-scope tests do not depend on the calendar.

Validation: browser checks of year changes, cross-year work queues, source states, comparator labels and historical report context.

### Before Slice 2: close coverage gaps

The current rendered review covers the planner; the earlier review recorded an administrator session separately. Neither establishes complete role coverage or populated operational behaviour. Before committing to Slice 2 designs, repeat the key journeys with at least one department-level contributor and one approver, against twelve fiscal months of synthetic data with complete cases and deliberately empty, measured-zero, partial and stale cases. Keep this data in an isolated database; the working application database must not be used.

### Slice 2: Navigation, page headers and My Work

Implement UX-05, UX-08 and UX-10, with the shared header informed by the Slice 1b filter-scope decision. Use My Work, Progress Updates and Strategic Position as the first reference screens. Keep existing routes and authorisation intact.

Acceptance:
- My Work is directly reachable from every main workspace.
- Each screen clearly communicates its purpose and effective scope.
- Users can distinguish executive overview, measure analysis and governed scorecard.
- Applicable selections survive navigation; incompatible selections are explained.
- Empty queues do not overshadow work requiring action.
- Changed navigation and headers support keyboard access, visible focus, meaningful accessible names and status indicators that do not rely on colour.

### Slice 3: Records, forms and visual consistency

Implement UX-06 and UX-07, then standardise table density, buttons, spacing, empty/error/loading states and currency formatting. Keep approval reasons and immutable evidence intact.

Acceptance:
- A selected update can be read comfortably without a permanently cramped detail pane.
- Returning to a list retains its position and filters.
- Forms show readable choices, clear field errors and task-specific submit labels.
- Saving/submitting communicates pending, success and recoverable failure states without losing input.
- Changed forms and details support keyboard use, labelled fields and errors, dialog focus containment and focus return; verify contrast and narrow-screen readability for changed components.

### Slice 4: Responsive and accessibility completion

Implement UX-04 and validate the shared components throughout the first three slices, rather than deferring all accessibility work to the end.

Acceptance:
- At 390 x 844, useful page content appears without a half-screen stack of global controls.
- Fixed headers/footers do not cover controls or the final content row.
- Keyboard users can navigate, open a record, use dialogs and return to their starting control.
- Tables remain usable at narrow widths; labels and statuses remain meaningful without colour.
- Contrast, zoom, focus order, touch targets and screen-reader names receive measured checks.

## Decision

The first implementation should be Slice 1a (missing-data correctness with regression tests), then Slice 1b, then the navigation + My Work + shared-header slice once the coverage gaps are closed. The rendered review raises data-state honesty and scope clarity above cosmetic work. A broad rebrand or wholesale dashboard rewrite is not justified by this review.

## Slice 1a implementation record

Base commit `2ff9c41`. Contract: a ratio whose denominator is zero or missing, or whose flow inputs are incomplete, returns `null` (displayed `—`, Not assessed). A measured zero numerator remains `0`. Stock balances (connections, staff, meters) are backfilled across months, so row completeness is not applied to them. For those balances, only a zero denominator yields Not assessed. The shared helper is `assessment.divide`.

### Inventory

| Calculation | Previous behaviour | Now | Consumers updated |
| --- | --- | --- | --- |
| HRA `staff_per_1000_conn`, `payroll_cost_ratio`, `m3_per_staff`, `wages_per_staff`, `fuel_per_km`, zone `m3_per_staff` (`report_generator.py`) | `0` on zero denominator. Staff count used `or 1`, so empty staffing reported volume ÷ 1. | `null`; flow inputs must be complete | Board HR card, HR page, Report Centre HRA and Staff Productivity narratives/tables/chart |
| Infra `breakdowns_per_1k_customers`, `stuck_pct`, `active_conn_ratio` | `active ... or 1`; `0` on zero denominator (Board: GOOD/CRITICAL on empty scope) | `null`. Breakdowns must be complete because NULL means "not entered" for them. | Board Infra card, Infrastructure page, Report Centre Infrastructure narrative |
| HRA/Infra responses | no record count; Board passed the summary, so the empty-scope guard never fired | `record_count` added; Board passes the full response | Board `kpis()` empty-scope guard |
| Executive panel `rev_per_conn` (total/zone), `avg_tariff`, `nrw_cost`, `nrw_per_conn_yr`, `energy_intensity`, `meter_read_rate`, `complaints_1000`/`complaints_flag`, `stuck_pct` (`panels.py`) | `0`; `complaints_flag` "LOW" for no data | `null`; flag `NOT ASSESSED` | Board NRW Cost card; Executive Dashboard exception strip, zone ranking, action list, zone table |
| Panels `stuck.per_1k_customers`, `stuck.repair_rate`, `breakdowns.per_1k_customers`, `disconnections.disconnection_rate`, `staff-productivity.staff_per_1000conn` | `or 1` / `0` | `null` | Staff-productivity and workforce cards (`null<=13` was true in JS); breakdowns card now accepts a measured 0 |
| NRW analysis `avg_tariff`, `nrw_cost_estimate` | `0` | `null` | Report Centre NRW narrative |
| Alert engine stuck-meter rate, company and zone (`insights_engine.py`) | stuck ÷ active accounts with `or 1`; `0` on no data | stuck ÷ metered connections, matching the Board, Infrastructure report and panels; `null` on zero | Alert text, `kpi_snapshot` |
| Alert engine output | empty list could imply all assessed | `not_assessed` lists indicators without inputs | Alert drawer |
| Narrative context (`narrative_engine.py`) | `vol or 1`; crashed on `None` zone NRW; zero defaults sent to the LLM | assessed ratios; prompt says "not assessed" and instructs the model not to infer | AI narrative (only when `ai.enabled`) |

Frozen reports: `app/modules/reporting` does not read these endpoints or fields, so approved snapshots are unaffected and are not regenerated. Scorecard (`/api/reports/scorecard`) already refused to grade on zero denominators and was left unchanged.

### Snapshot review (`tests/snapshots/`)

- `api_insights_summary`, `api_reports_recommendations`: `stuck_pct` 137.3 → 127.8, because the denominator changed from active accounts (8,340) to metered connections (8,962). It now equals Infrastructure and Executive (127.8). Alert wording changed accordingly. New `not_assessed: ["Collection rate"]`, because synthetic `amt_billed` is 0.
- `api_reports_hra`: `payroll_cost_ratio` 0 → null, because `total_revenue` is 0 (a zero denominator). `record_count` added.
- `api_reports_infrastructure`: `record_count` added.
- No other snapshot changed.

### Evidence

- Implemented in `53c554b`.
- New `tests/test_missing_data_contract.py` covers absent keys, explicit NULLs, measured zeros, zero denominators, partial scope, zone roll-up, month-window stock carry-forward, complete data, cross-screen agreement and the narrative prompt. It passes together with `tests/test_assessment.py` (17 tests).
- Full suite: the baseline at `2ff9c41` ran 213 tests with 1 failure. The changed tree ran 225 tests with the same single failure. That failure, `test_platform_foundation.test_scoped_user_is_refused_on_every_org_wide_get` ("0 not greater than 40"), predates this slice and is unrelated.
- `node --check app/static/assets/js/app-core.js` passes. The script version was bumped to `20260925-2`.
- Browser check (isolated copy of the review DB, 1440 × 1000). With no returns, all 16 Board cards show `— / NOT ASSESSED`, and Executive Dashboard actions read "4 of 4 main indicators could not be assessed". With the synthetic FY2024/25 dataset, unassessed exceptions show "Not assessed" in neutral tone, and the zone ranking is withheld where inputs are incomplete. No console errors.

### Open findings

- Synthetic data has stuck meters above metered connections (127.8%), which produces a negative meter-read rate. Impossible-input validation belongs to data-quality checks and is not in this slice.
- Report Centre text cites IBNET <5 staff/1k while the Board cites ≤13. This is a comparator inconsistency for UX-11 (Slice 1b). Resolved in Slice 1b.

## Slice 1b implementation record

Base commit `8846326`. The fiscal-filter policy was accepted as written on 25 September 2026.

### UX-02: page scope inventory

The top bar's `api()` calls send the global fiscal year, zones and months. Module pages (`MZ.api`) and Strategic Position (`ihApi`) send none of them. Before this slice, module pages hid zone and period but still showed a fiscal-year selector that had no effect. Strategic Position, Administration and the placeholder page showed every filter while ignoring them. Compliance endpoints take no filter parameters, and the Strategic Plan Scorecard takes the year only.

| Policy class | Pages | Year | Zone / period / advanced | Scope note |
| --- | --- | --- | --- | --- |
| Performance dashboard | board, overview, finance, hra, infrastructure, operations, commercial, production, wt-ei, customers, connections, stuck, connectivity, breakdowns, pipelines, billed, collections, charges, expenses, debtors, segment-revenue, workforce, class-connections, pipe-materials, nrw, supply-continuity, disconnections, profitability, staff-productivity, benchmarking, budget, report-centre | shown | shown | none |
| Scorecard, year only | strategic | shown | hidden | "Fiscal year applies. Zone and period filters do not apply to this page." |
| Latest dataset | compliance, water-quality | hidden | hidden | "Latest assessed dataset. Not filtered by fiscal year, zone or period." |
| Work queue (cross-year) | my-work, updates, actions, risks, audit-findings, meetings | hidden | hidden | "Cross-year work queue: items from every fiscal year." |
| Strategy and scorecards | strategy, strategy-map, scorecard, position, cycles, evaluations | hidden | hidden | "Plan, unit and period are chosen on this page." |
| Governed reports | reports-hub, regulatory | hidden | hidden | "Each report keeps the period and unit fixed in its record." |
| Setup | admin, access, people, periods, schemes, documents, audit-trail, soon | hidden | hidden | none |

Decision: the Strategic Plan Scorecard keeps the global year, because that is its only period control. Its zone and period filters are hidden and the note says so. `PAGE_SCOPE` in `app-core.js` is the single source. Page meta lines and export headers use `pageScopeSummary()`. `tests/test_page_scope.py` fails when a page is unclassified or a module page is presented as globally filtered. The Report Centre re-runs saved reports with their stored scope (`scopeOverride`), so reopening a report never adopts the top-bar year.

### UX-03: freshness

`/api/position/sources/freshness` now returns `feed`, `last_value_at` and an explicit `freshness` state: `current`, `overdue`, `failed`, `disabled`, `no_ingestion` or `not_scheduled`. "Current" applies only to a scheduled source that has succeeded within twice its interval. Approved progress updates (`strategy-updates`) are shown as "approved updates · last published …", never as current or never-run. The Strategic Position banner says "All scheduled sources current" only when every enabled source qualifies; otherwise it reads "Freshness not fully assessed" with the reason. Newly frozen Exceptions reports carry `sources_contract: 2` and list sources that are not confirmed current. Reports frozen earlier render exactly as approved.

### UX-09 (pp) and UX-11: comparators

- Strategic Position states a gap as "3.4 pp above target" for percentage measures.
- Targets resolve by exact period and by basis. The strategic-plan target is primary, and other bases (regulator, budget, internal) are listed separately and never promoted. An earlier period's target is no longer carried forward. Instead, `target_note` says there is no target for the period and cites the latest one. Each comparator carries its type, source (plan or entry route), unit, organisational unit, period and version (`target #id, updated date`).
- Dashboard KPIs use one governed registry, `app/services/comparators.py`. Its values come from tenant `targets`/`thresholds` where configured, and each boundary records its type and origin. The registry is injected into `app-core.js` as `CMP` and used by API flags, the report scorecard, Board, department cards and Report Centre text. Card tooltips carry the comparator and registry version.

| Measure | Inconsistency found | Now |
| --- | --- | --- |
| Staff per 1,000 connections | Board "IBNET ≤13" (watch 20), panels "target 13", report scorecard "IBNET <5" (watch 10) | staffing target ≤13, watch ≤20 everywhere; IBNET 5 shown as unverified context only |
| Breakdowns per 1,000 connections | Board/pages ≤5 / 10 ("IBNET"), report scorecard <10 / 20 ("IBNET") | band ≤5 / ≤10 (product default, not attributed to IBNET) |
| Collection rate (company) | cards watch at 80, API watch at 75 (`coll_warn`) | tenant `coll_warn` 75; zone views keep `zone_coll_warn` 80 |
| Supply hours | Board 20 / 16, supply-continuity panel 21 | 20 / 16 |
| Active connection ratio | Board ≥90 GOOD, report text ">85%" | ≥90 / ≥75 |
| Energy intensity | tile watch 0.7, Report Centre watch 0.8 | 0.5 / 0.8 |
| NRW panel card | "Within 25% target" while the target is 27 | corporate target from configuration |
| DSO | "<90d (IBNET)" in the scorecard vs "IBNET <60" on cards | ≤60 reference, ≤90 alert band |

Also fixed while touching these paths, all missing-data defects of the UX-01 kind: board-pack `active_customers` reported 1 with no connections (`or 1`); board-pack energy intensity and chemical cost per m³ defaulted to 0; the supply-continuity panel returned a server error on an empty scope; the NRW panel card called a missing rate GOOD (`null<=27`); Report Centre zone supply tables labelled missing data "High risk".

### Snapshot review

- `api_panels_staff_productivity`: `target_per_1000conn` 13 → 13.0 (the same value, now from the registry).
- `api_panels_supply_continuity`: `target_hours` 21 → 20 and `gap_to_target` 2.3 → 3.3, aligned with the Board band. New `supply_flag: GOOD`.
- No other snapshot changed. The report scorecard grades the synthetic data as Not assessed, so its flags do not appear.

### Evidence

- Implemented in `51e5692`. Full suite: 243 tests, with the single failure that predates Slice 1a (`test_scoped_user_is_refused_on_every_org_wide_get`) and no new failures.
- `tests/test_scope_freshness_comparators.py` (13 tests) covers freshness states, legacy and new report rendering, comparator provenance, no carry-forward, basis separation, registry boundaries and origins, report/dashboard agreement and the empty-scope supply panel. `tests/test_page_scope.py` has 5 tests. All 18 pass. `tests/test_tenant_config.py` now checks the injected registry.
- Browser check (isolated review DB copy, 1440 × 1000 and 390 × 844). The ten representative pages show exactly the controls and note in the table above. Strategic Position for North, quarter view, reads "Strategic plan target 28% · 3.4 pp above target", followed by the plan, North and the quarter, with the version in the tooltip. The freshness banner reads "Freshness not fully assessed (1 without a schedule)", with "strategy-updates: approved updates · last published 3 h ago". The Board staff card reads "Staffing target ≤13 / 1k conn". No console errors. No horizontal overflow at 390 px.

### Open findings (Slice 1b)

- ~~Product confirmation needed for the values marked "product default" in the registry.~~ Accepted by the product owner on 25 September 2026 as the shipped defaults, unchanged: stuck meters ≤5 / ≤8 %, staffing alert ≤20 per 1,000, breakdowns ≤5 / ≤10 per 1,000, active connections ≥90 / ≥75 %, payroll ≤35 / ≤50 % of revenue, supply ≥20 / ≥16 h/day, energy alert ≤0.8 kWh/m³. Screens keep "(default)" and origin "product default" because the value is the product's, not the tenant's. External benchmark attributions that screens previously disagreed on are no longer asserted: staff <5 IBNET, breakdowns 5 or 10 IBNET. Tenants can override each value through `thresholds`/`targets` keys named in the registry.
- Comparator details appear in visible card text (source and boundary) and in tooltips (types, origin, version). Card tooltips are not keyboard-reachable. That is an existing pattern, left for Slice 3/4.
- Strategic Position "View by" wording and leading with reporting measures (the rest of UX-09 and UX-10) remain in Slice 2.

## Coverage gaps: populated-year dataset

The first half of "Before Slice 2" is in place: an isolated database with twelve populated fiscal months. The role journeys themselves are still to be done.

### What it contains

`tests/fixtures/populated_year.py` generates FY2025/26 (July 2025 – June 2026) for the demo tenant's 8 schemes, plus July–August 2026 of the current year. That is 104 returns. Values are fictional but consistent with each other: billed volume + NRW = production, and connection and stuck-meter balances roll forward. Stuck and active meters stay within metered connections, costs add up to operating cost, and debtors move with billing and collection. Scale follows `tenants/demo/budget.yaml` (4.2 M m³, USD 4.0 M water sales).

| Case | Where | Expected on screen |
| --- | --- | --- |
| Complete | Northgate, Hillside, Central Works, Riverside, Southport | Assessed. North reads GOOD, South HIGH, and Hillside has a trunk-main burst in February 2026 |
| Measured zero | Ridgeway: breakdowns, disconnections, new connections, new stuck meters, power failures entered as 0 | Assessed as 0 (breakdowns 0.0 per 1,000, GOOD), never "—" |
| Partial (not entered) | Lakeshore: staffing and payroll never; billing April–June 2026; breakdowns October–November 2025 | Not assessed wherever those inputs are needed (South and company collection, operating ratio, DSO, payroll, breakdowns) |
| Stale | Valley: no returns after December 2025 | Latest period December 2025 |
| Empty | September 2026 onwards; Valley from January 2026; FY2027/28 | Nothing assessed |

`scripts/build_review_dataset.py --out <new folder>` builds the database. It adds the demo people and grants (`app.demo_seed`: contributor `north.ops`, reviewer `north.mgr`, approvers `planner` and `south.mgr`, viewers `auditor` and `board`), fiscal years and budget, and the returns. It publishes the returns to the measure catalogue through the existing legacy-returns bridge, and adds three sources whose freshness is current, overdue and failed. It refuses the project's `data/` folder and any non-empty folder it did not build (a marker file). `--replace` rebuilds only its own folders. It writes `manifest.json` and `accounts.txt` (one-time random passwords for the fictional accounts) next to the database. Freshness is relative to build time, so rebuild before a journey.

### Evidence

- `tests/test_populated_year.py` (15 tests, pass) covers: shape, determinism and scale; the relationships above in every entered return; measured zeros are 0 and not NULL; NULLs only where declared; the cases through the real report and panel API; builder refusals and the rebuild of read-only evidence files; and an end-to-end build in a subprocess. The end-to-end build checks record, user and NULL counts, that the legacy bridge published exactly the entered values, and that freshness is computed as current, overdue and failed.
- Built and served locally (`madzihub-review-year` launch configuration, 1440 × 1000). Board, FY2025/26: "3 Zones · 8 Schemes · 12 Months", "2/3 fully assessed", Production 4.21 M m³, NRW 30.3 % WATCH, Finance Net margin and Collection rate Not assessed ("Required data unavailable"). No console errors. Strategic Position: "2 sources need attention", with billing-export current, lims-results failed and scada-daily overdue.
- API check on a copy, FY2025/26. North: NRW 25.9 GOOD, collection 92.4 GOOD, operating ratio 0.78 GOOD, DSO 69.2 WATCH, breakdowns 9.3 per 1,000. South: NRW 36.9 HIGH; collection, operating ratio, DSO, payroll and breakdowns Not assessed. South January–March: collection 76.8 WATCH.

### Findings the dataset exposed (not fixed here)

1. `/api/catalogue/data-quality` returns a server error once any return has a NULL amount (`catalogue.py:200`, `None > 0`). The same check reads `pct_nrw` as a fraction and reports NRW "2293 %". The importer rollup, the compliance overview and the parity fixture all store it as a percentage.
2. Staff per 1,000 connections stays assessed when a scheme's staffing is not entered. South reads 15.8 with Lakeshore's staff counted as 0 but its connections still counted. Stock NULLs are coerced to 0 before `divide`.
3. The breakdowns panel for Lakeshore reads 15.4 per 1,000 with two months not entered, while the Infrastructure report says Not assessed for the same scope. The panel does not apply the completeness rule.
4. Staleness is not surfaced. The Board status reads "Latest: June · Returns through June" although Valley stopped in December. Strategic Position shows Valley's December value with `data_age_days` 0, because age counts from load time, not from the period.
5. One partial scheme (Lakeshore, 7 % of connections) makes company-wide collection, operating ratio and DSO Not assessed for the year. That is correct under the contract, but the screens do not say which unit is missing. This feeds Slice 2's scope and coverage messaging.
6. The demo seed's service areas (Hilltop, north Riverside, Market Town, Bay Area) differ from the demo returns' schemes, so Strategic Position expects 12 units where 8 report returns.

Next: run the contributor (`north.ops`), reviewer (`north.mgr`) and approver (`planner`, `south.mgr`) journeys on this database, then choose the Slice 2 design.

## Working checklist

- [x] Consolidate browser findings, source causes and agreed review corrections.
- [ ] Preview the final Markdown and commit this document separately from application changes. (Committed separately as `2ff9c41`; rendered preview not yet done.)
- [x] Slice 1a: complete the calculation/consumer inventory before editing code.
- [x] Slice 1a: implement, pass the correctness exit gate and review snapshot changes individually; commit independently (`53c554b`).
- [x] Confirm the page-by-page fiscal-filter policy before the relevant Slice 1b changes (accepted as written, 25 September 2026).
- [x] Slice 1b: verify scope, freshness, comparator provenance and percentage-point presentation (`51e5692`).
- [x] Confirm the registry's product-default comparator values (accepted as shipped, 25 September 2026).
- [x] Build the isolated populated-year dataset with complete, measured-zero, partial, stale and empty cases.
- [ ] Complete the additional-role journeys on that dataset before selecting the Slice 2 design.
- [ ] Deliver Slices 2 and 3 with accessibility checks within each slice.
- [ ] Complete Slice 4's responsive and accessibility checks across the affected journeys.

For each slice, record the tested commit, cases, results, remaining limitations and affected paths. Preserve unrelated work, access restrictions and approved historical artifacts. Mark completion only when that slice's acceptance criteria are met.
