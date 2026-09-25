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

The role journeys are recorded in the next section.

## Role journeys on the populated-year dataset

Commit under test: `eeb472a`, with no application-code changes. The dataset was rebuilt immediately beforehand (`scripts/build_review_dataset.py --replace`) and served through the `madzihub-review-year` launch configuration at 1440 × 1000. Each role was signed in with an 8-hour session token minted from that database's own secret, so no password was typed. The helper script was not committed; the passwords in `accounts.txt` work equally well. Accounts: contributor `north.ops`, reviewer `north.mgr`, approvers `planner` (organisation-wide, strategy and report manager) and `south.mgr` (South).

### Journey run

1. **Planner sets up the work.** The New cycle list offered only FY2026/27 periods. The planner first used Setup → Reporting periods → Add fiscal year (2026) to create the FY2025/26 periods. The planner then created "Q4 FY2025/26 progress" (due 15 October 2026, verification required), generated assignments and opened the cycle.
2. **Contributor submits.** `north.ops` landed on My Work, which listed Q-NRW North under "Progress updates to submit". An empty save was refused with a readable alert. A save of 150 % with no evidence was **accepted** and sent for review; the range and evidence checks failed only on the saved revision. Revision 2 corrected it to 25.9 %, the North value computed from the returns for April–June 2026 (411,972 m³ produced).
3. **Reviewer returns.** `north.mgr` found the update on My Work and returned it. The reason was required: an empty confirm was refused and focus stayed on the field. The contributor received a notice that included the reason. Revision 3 added a variance reason, and the reviewer verified it.
4. **Approver approves.** `planner` found it under "Updates to approve" and approved it. The record keeps all three revisions, each with its checks and the full decision trail. The approved value appears in the Strategic Position trend for North (source `strategy-updates`).
5. **Scope and segregation.** `south.mgr` could not see or approve North's update: the API returned 404. The server refuses verification or approval of one's own submission (`app/modules/strategy/service.py:786`).
6. **Governed report.** `planner` created "Submissions and data quality — MadziHub — Q4 FY2025/26" and submitted it for review. The frozen draft shows completeness (2 assignments, 1 approved, 1 returned), data-quality findings, a fingerprint and an "IN REVIEW — NOT APPROVED" banner.

**Test data left in the isolated database:** FY2025/26 platform periods; the Q4 FY2025/26 cycle; North Q4 approved at 25.9 % (three revisions); report #2 in review. An API scope probe during the `south.mgr` session submitted South Q4 (value 37, narrative "probe"). The planner then returned it with a note identifying it as test data. Rebuilding the dataset removes all of it. No other database was touched.

### What worked

- Contributors and reviewers land on My Work, and their queues list the right unit and period.
- Blank, pending and zero stay distinct in the submit form. Revisions cannot be edited, and each one keeps its own checks.
- Return requires a reason, and the reason reaches the contributor. Segregation of duties and unit scope are enforced on the server.
- Approved values flow into Strategic Position with their source. The frozen report states its status, period, completeness and fingerprint.

### Findings

Status: all findings below are Verified in this setup, except where the treatment calls for a product decision.

| ID | Priority | Observation | Recommended treatment |
| --- | --- | --- | --- |
| RJ-01 | P1 | **Work is routed to people who cannot open it.** `generate_assignments` sets every unit's submitter to the indicator owner (`app/modules/strategy/service.py:549`). South Q-NRW is assigned to `north.ops` in both cycles, although that account has North access only. Both "Progress update requested" notices for South open "Progress update not found." Nobody with South access has the item in a To submit queue or on My Work. `south.mgr` can submit it from the record, since approvers may submit, but is never asked to. The People dialog lists only people in scope, but it opens showing "(any contributor)" while the table shows `north.ops`. It also offers viewers (`auditor`, `board`) as submitter, verifier or approver. | Resolve the submitter per unit from scope when assignments are generated. Flag unassigned or out-of-scope units in the cycle table before it opens. Make the dialog show the current values and offer only roles that can act. |
| RJ-02 | P1 | **Hand-offs are not notified.** Nothing notifies the reviewer on submission or resubmission, the approver after verification, or the contributor on approval. A report in review appears in no approver's notices or My Work; My Work has no report category. Return notices go to the assigned contributor rather than the person who submitted. The planner's return of South reached `north.ops`, not `south.mgr`. "Requested" notices stay unread after the work is approved. | Notify the next actor at each transition and the actual submitter on return. Close or mark request notices when the work completes. Add reports awaiting approval to My Work. |
| RJ-03 | P1 | **An impossible value can be submitted without evidence.** 150 % (valid range 0–100) with the "Evidence (required)" field empty was accepted and sent to the reviewer. The failures appear only on the saved revision. | Check range and required evidence in the form before submission. **Product decision needed:** block the submission, or allow it only with an explicit acknowledgement. The server's rule of never adjusting values is unaffected either way. |
| RJ-04 | P2 | The governed Submissions report shows a returned value (South, 37) in its Value column with no qualifier. | Show returned or unapproved values as such, or omit them from the value column. |
| RJ-05 | P2 | There are two fiscal calendars. The builder added 9 catalogue fiscal years, but platform reporting periods existed only for FY2026/27. A planner cannot open a cycle or report for a past year until someone adds its periods, and the New cycle list gives no hint of this. | Explain missing periods in the cycle and report dialogs, with a link to Reporting periods. The review builder should also create platform periods for the populated year. |
| RJ-06 | P2 | **Navigation shows pages the role cannot use.** The contributor sees Access ("Could not load this page: Administrator access required."), Audit trail ("…available to administrators and auditors.") and Regulatory ("Not found.": the module answers 404 to unauthorised users by design). | Filter navigation by permission, as Slice 2 plans. Keep the server checks. |
| RJ-07 | P2 | For unit-scoped users, the System alerts bell opens with raw API text: "Error: /api/insights/summary?year=2027: organisation_scope_required: …". The bell button has no accessible name and sits over the live clock at 1440 px. | Hide the bell or scope the alerts for scoped users, show a readable message, give the button a name and fix the overlap. |
| RJ-08 | P2 | **Counts go stale, and an empty badge shows.** Progress Updates tab counts ("To submit 1", "To verify 1") and the My Work badge do not refresh after submit, return or verify, although the API queue is already empty. With nothing unread, the My Work badge renders as an empty red pill: `.mz-badge{display:inline-flex}` (`app/static/assets/css/mod-platform.css:47`) overrides `hidden`. | Refresh counts after every transition, and respect `[hidden]` for badges. |
| RJ-09 | P2 | **My Work summary tiles count only actions.** While an update waited, the reviewer's tiles read 0 / 0 / 0 / 0. The planner, who had one update to verify and one to approve, still landed on the Board. | Make the tiles cover updates and reports, and land any role with pending work on My Work (UX-05, UX-08). |
| RJ-10 | P2 | **Reviewer and approver actions are unclear.** The reviewer's most prominent button is "Submit a new revision", with Verify secondary. Verify, Approve and Open cycle take effect on one click, with no confirmation or optional note, although Return requires a reason. The decision log records verification as "Verify · Approved by north.mgr" (the mapping at `service.py:789`). Toasts read "Done." | Make the role's primary action the primary button. Confirm Approve and Open cycle, offering an optional note. Log "Verified" and use specific toasts. |
| RJ-11 | P2 | The resubmission dialog does not show the return reason. On the record, the reason sits under Decisions, below every revision. The submit dialog's final button is "Save" (UX-07). | Show the latest return reason at the top of the record and in the dialog. Label the button "Submit update" or "Submit revision". |
| RJ-12 | P2 | **Focus is lost after dialogs.** After Escape on People, a confirmed Return or a failed Save, focus goes to `body` instead of returning to the trigger. A failed submit neither focuses nor marks (`aria-invalid`) the invalid field; the message itself is correctly `role="alert"`. My Work shows eight notice buttons all named just "Open". | Return focus to the trigger, focus and mark the invalid field, and name notice buttons by their subject (Slice 3/4 components). |
| RJ-13 | P2 | **One unit and period shows three NRW figures.** Strategic Position for North, by quarter: the returns-computed "Non-revenue water 25.7 %" (no target); the plan KPI "Non-Revenue Water — No data", with the hint "select a single unit" although North is selected; and Q-NRW 31.4 %, off track against 28 %. The two numbers come from independent fictional sources (the demo seed and the synthetic returns). The product gap is that a manually reported indicator and the computed measure for the same concept are neither linked nor reconciled, and the consistency check passed. The same quarter is "Q4 FY2025/26" in Progress Updates but "Quarter from Apr 2026" in Strategic Position. Earlier quarters can be reached only through the drill-down. | Allow an indicator to reference a catalogue measure (show the computed value and warn on divergence). Fix the hint, use one period label, and add a period selector (UX-09/UX-10, Slice 2). |
| RJ-14 | P3 | Two units share the name "Riverside": a Central scheme and a North service area from the demo seed. Both appear in pickers and in the contributor's access line. This extends finding 6 above. | Qualify duplicate names with their parent, and align the seed's service areas with the returns schemes. |
| RJ-15 | P3 | Board text and card footers still cite IBNET for collection (>90 %) and DSO (<60 days), and the sidebar badge reads "IWA · IBNET ALIGNED". These values were not in Slice 1b's disputed set, but their attribution is unverified. | Check these attributions through the comparator registry (UX-11), or drop the badge. |

### Consequences for Slice 2

RJ-01, RJ-02, RJ-03 and RJ-08 are routing and correctness defects, not layout. A redesigned My Work would still show wrong or missing work until they are fixed. The recommended order is a small **Slice 1c (work routing)** first: RJ-01, RJ-02, RJ-04, RJ-05, the RJ-08 counts and badge, and RJ-03 once its product decision is made. Slice 2 then builds on correct queues. It should:

- make My Work the landing page for any role with pending work;
- have its tiles count updates and reports as well as actions;
- filter navigation by permission (RJ-06);
- handle alerts for scoped users (RJ-07);
- make each role's primary action clear (RJ-10);
- fix Strategic Position period selection and labels (RJ-13).

RJ-11 and RJ-12 belong to Slice 3's record and dialog components.

## Slice 1c implementation record

Commit: `0ba0f7f` on branch `codex-review-fixes`. Tests: 41 pass (`test_strategy_me`, `test_reporting`, `test_populated_year`). Browser QA: all six findings verified against the `madzihub-slice1c` isolated dataset (port 8096, `accounts.txt` in the scratchpad for that session). Codex review pending — handoff at `docs/reviews/2026-09-25-slice-1c-work-routing.md`.

### What was done

**RJ-01 — Out-of-scope submitter.** `scope.py` adds `user_scopes()` (every active user's Scope, keyed by username) and `closest_holders()` (the people to ask: unit-level before org-wide, lowest sufficient role, configurable exclude list). `strategy/service.py` adds a `People` class that wraps these and caches the scope map per request. `generate_assignments()` only names `ind.owner` as contributor if they can contribute to the unit; other units go unassigned. `update_assignment()` validates that a named person holds the required role on the unit, refusing with `Invalid` if not. `assignment_query()` uses a routing-aware `mine_to_do()` closure so each user's queue reflects who routing actually reaches. The cycle detail table shows routing columns (submits / verifies / approves, with the named person and the fallback note) for managers via an optional `people` parameter on `assignment_dict()`. The People dialog description was updated to state that only eligible people are shown, and the JS dropdowns are built from the filtered `assignable-users` response.

**RJ-02 — Missing hand-off notifications.** `notifications.py` adds `resolve(db, entity_type, entity_id, kinds)` which marks unread notices about a record as read once the step they requested is done. `strategy/service.py` calls `_ask()` to notify the next actor at each step and `resolve()` to close prior requests: submit asks the reviewer (or approver when there is no verification step), verify asks the approver, approve/return closes the request and notifies the actual submitter. `reporting/service.py` adds `approvers(db, inst)` (closest approver(s) for the unit, excluding the report's authors) and `_hand_off(db, scope, inst, name, reason)` (sends `report_submitted`, `report_approved` or `report_returned` and closes prior `report_submitted` requests). The reporting module's `my_work(db, scope)` is registered in `MY_WORK_PROVIDERS`; the front-end `mod-reports.js` renders the "Reports to approve" section on My Work. `platform/router.py` adds `read_only` to the assignable-users response so the JS can exclude read-only accounts.

**RJ-03 — Impossible value acknowledged, not blocked.** `strategy/service.py` adds `blocking_failures(db, a, ind, value_state, value, evidence_note)` which returns `(code, message)` pairs for out-of-range values and missing required evidence. `submit_update()` calls it and, if failures exist, requires `acknowledge_checks=True` on the request body; the acknowledgement is stored in `extra_after` and prepended to each DQA failure reason so it is visible in the revision log. `strategy/router.py` adds `acknowledge_checks: bool = False` to `SubmitIn`. The submit dialog (`mod-strategy.js`) runs a client-side `failures()` check and, if there are any, shows them in a `showChecks()` panel with an acknowledgement checkbox; the Submit button is disabled until the box is ticked. The submit label is "Submit revision" for resubmissions, "Submit update" for first submissions.

**RJ-04 — Returned/unapproved value labelled in governed reports.** `reporting/layout.py` adds `_UNAPPROVED = {"returned": "returned", "submitted": "not yet approved", "verified": "not yet approved"}` and a `_value(s, contract)` function that appends the qualifier to the cell when the assignment status is in the dict and the report's `submissions_contract` is ≥ 2. `reporting/builders.py` sets `data["submissions_contract"] = 2` after the submissions section, so the flag is frozen into the report data. Reports frozen before this change have no `submissions_contract` key and render exactly as they were approved.

**RJ-05 — Missing periods explained in dialogs; populated-year periods built.** `mod-platform.js` adds `MZ.periodsIntro(periods)` (returns a sentence listing available fiscal years and a link to Setup → Reporting periods) and `MZ.bindPeriodsLink()` (wires a click on that link to navigate there). Both the New cycle and New report dialogs call these helpers. `scripts/build_review_dataset.py` calls `periods.ensure_fiscal_year(db, populated_year.POPULATED_FY)` so the populated fiscal year has its 17 platform periods (1 year, 4 quarters, 12 months) from the first build, without a manual Setup step.

**RJ-08 — Stale counts and hidden badge.** The Progress Updates page in `mod-strategy.js` now calls the queue-count API on every `load()` invocation rather than once at page mount; `MZ.refreshUnread()` is called after every successful transition so the bell badge updates immediately. `mod-platform.js` adds `aria-label` to the badge count and calls `MZ.refreshUnread()` in the `open-note` notification handler. `mod-platform.css` adds `.mz-badge[hidden]{display:none}` with a comment explaining the specificity issue (the existing `display:inline-flex` rule would otherwise override the `hidden` attribute).

### Evidence

| Finding | Verified by |
| --- | --- |
| RJ-01 routing | Unit test: `RoutingTests` (4 cases). Browser: cycle table shows routing columns; People dialog lists only eligible users, filtered hierarchically by role. |
| RJ-02 hand-off | Unit test: `test_report_in_review_reaches_approvers_and_their_my_work`, `test_report_managers_are_asked_when_the_unit_has_no_other_approver` in `HandOffAndLabelTests`; `test_each_hand_off_asks_the_next_actor_and_closes_the_request` and `test_reminders_follow_routing` in `RoutingTests`. Browser: submitted south report → south.mgr received `report_submitted` notice; "Reports to approve" section visible on My Work with the correct entry. |
| RJ-03 acknowledgement | Unit test: `test_dqa_records_problems_without_changing_values` (updated). Browser: submit form with value 150 and no evidence showed two failures; Submit was blocked until acknowledgement checkbox was ticked; submission went through with "Range: fail", "Evidence: fail" chips and "The submitter acknowledged this and submitted anyway." in DQA. |
| RJ-04 value labels | Unit test: `test_returned_and_unapproved_values_are_labelled`. Browser: HTML output of south submission_dq report showed `150 (not yet approved)` in the Value column; reports without `submissions_contract` key showed bare values. |
| RJ-05 period guidance | Browser: New cycle dialog showed "Periods available here: FY2025/26, FY2026/27. To use another fiscal year, first add its periods under Setup › Reporting periods." Unit test `test_builds_an_isolated_populated_database`: `select count(*) from periods where fiscal_year=?` returned 17. |
| RJ-08 counts and badge | Browser: "To submit" count went 1 → 0 immediately after the Q-NRW submission. Badge `aria-label="4 unread notices"` visible with `display:flex`; after `read-all` + `refreshUnread()`: `hidden=true`, `display:none`. |

### Remaining scope

RJ-06, RJ-07, RJ-09 through RJ-15 are deferred to Slices 2 and 3 as noted under "Consequences for Slice 2". No regressions in the pre-existing `BoardPackTests`, `IncompleteScoreTests` and `DraftAndScopeTests` test classes (all pass).

## Working checklist

- [x] Consolidate browser findings, source causes and agreed review corrections.
- [ ] Preview the final Markdown and commit this document separately from application changes. (Committed separately as `2ff9c41`; rendered preview not yet done.)
- [x] Slice 1a: complete the calculation/consumer inventory before editing code.
- [x] Slice 1a: implement, pass the correctness exit gate and review snapshot changes individually; commit independently (`53c554b`).
- [x] Confirm the page-by-page fiscal-filter policy before the relevant Slice 1b changes (accepted as written, 25 September 2026).
- [x] Slice 1b: verify scope, freshness, comparator provenance and percentage-point presentation (`51e5692`).
- [x] Confirm the registry's product-default comparator values (accepted as shipped, 25 September 2026).
- [x] Build the isolated populated-year dataset with complete, measured-zero, partial, stale and empty cases.
- [x] Complete the additional-role journeys on that dataset before selecting the Slice 2 design (contributor, reviewer, approvers; findings RJ-01 to RJ-15).
- [x] Decide RJ-03 (block or acknowledge an out-of-range / missing-evidence submission) and confirm the Slice 1c ordering. Decision: acknowledge — form shows failed checks before submit; submission allowed only after ticking an explicit acknowledgement checkbox; acknowledgement recorded on the revision in the audit trail and DQA reason. Server enforces the flag. Value is never adjusted.
- [x] Slice 1c: work routing (RJ-01, RJ-02, RJ-04, RJ-05, RJ-08, and RJ-03 once decided). Commit `0ba0f7f`.
- [ ] Deliver Slices 2 and 3 with accessibility checks within each slice.
- [ ] Complete Slice 4's responsive and accessibility checks across the affected journeys.

For each slice, record the tested commit, cases, results, remaining limitations and affected paths. Preserve unrelated work, access restrictions and approved historical artifacts. Mark completion only when that slice's acceptance criteria are met.
