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

**Recommended fiscal-filter policy — pending product confirmation before implementing scope changes.** This decision does not block Slice 1a. Inventory every page and map it to the agreed policy before changing the shared header.

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

## Working checklist

- [x] Consolidate browser findings, source causes and agreed review corrections.
- [ ] Preview the final Markdown and commit this document separately from application changes.
- [ ] Slice 1a: complete the calculation/consumer inventory before editing code.
- [ ] Slice 1a: implement, pass the correctness exit gate and review snapshot changes individually; commit independently.
- [ ] Confirm the page-by-page fiscal-filter policy before the relevant Slice 1b changes.
- [ ] Slice 1b: verify scope, freshness, comparator provenance and percentage-point presentation.
- [ ] Complete populated-year and additional-role journeys before selecting the Slice 2 design.
- [ ] Deliver Slices 2 and 3 with accessibility checks within each slice.
- [ ] Complete Slice 4's responsive and accessibility checks across the affected journeys.

For each slice, record the tested commit, cases, results, remaining limitations and affected paths. Preserve unrelated work, access restrictions and approved historical artifacts. Mark completion only when that slice's acceptance criteria are met.
