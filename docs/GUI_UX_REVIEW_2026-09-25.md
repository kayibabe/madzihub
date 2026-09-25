# MadziHub GUI and UX review

Reviewed 25 September 2026. Recommendation: redesign the application shell and information hierarchy in stages, preserving the utility framework, calculations, permissions and governed records.

## Consolidated delivery decision after Claude review

This decision supersedes the ordering in section 6 and makes the six-group navigation in section 2 a prototype proposal, not an approved immediate replacement.

1. **Correctness release first, independently of redesign.** Audit missing/zero handling from source aggregation through APIs, dashboards, alerts and generated reports. `report_generator.py:760` defaults an absent NRW key to zero before assigning GOOD; several ratio calculations also return zero for a zero denominator. Explicit null values need separate handling: Python `get(key, 0)` does not replace an existing null. `app-core.js:2549` can count missing collection data as a zone risk. Preserve measured zero; distinguish absent, partial, invalid-denominator, stale and not-applicable states. Show assessment coverage separately from performance. An empty alert list must not imply that all indicators were assessed.
2. **Unify applicable comparison rules.** Inventory all hardcoded thresholds and use one governed resolution path shared by screens and reports. Corporate targets, period/unit-specific strategy targets, operational warning bands and external regulatory benchmarks have different meanings. Do not flatten them into one tenant number or let tenant branding override a regulator's versioned rules. Existing tenant configuration already distinguishes collection warning levels of 75% and a zone warning of 80%; resolve intended context explicitly. Missing approved rules mean no assessment against that rule. The first release should correct the affected paths and test configurable values; wider rule migration can be a separate focused change if needed.
3. **Populate an isolated review environment.** Use twelve fiscal months of clearly synthetic data across multiple units, including empty, measured-zero, partial, stale and complete cases. Preserve the user's working database. Verify charts, aggregations, report values and layout on those cases before choosing final designs.
4. **Prototype the executive screen and board pack together.** Retain current department tabs and Performance & Governance immediately after Board during the pilot. Initial six board outcomes: NRW %, supply hours/day, water-quality compliance with sampling coverage, collection rate %, operating cost recovery ratio, and approved strategic-plan achievement with coverage. Unavailable outcomes stay explicitly unassessed; never substitute dosing coverage for safety or an ad hoc grade for approved strategic achievement. Put critical risks, capital-delivery exceptions, debtor exposure and overdue actions in a separate prioritized list, with links to detail.
5. **Validate the navigation proposal, then roll out.** Test finding a problem, tracing evidence, locating its owner/action, and obtaining the approved board pack. Only then choose whether the six-group navigation improves on the existing department structure. Standardize colours, charts, tables and mobile controls progressively. Preserve role restrictions, calculations and approved historical artifacts throughout.

Correctness exit gate: tests cover absent keys, explicit nulls, genuine zeros, zero denominators, partial scope, stale data and complete data, including unit and fiscal roll-ups; dashboard/report statuses agree for the same measure, rule, scope and period; alternate tenant thresholds appear consistently in labels and calculations. Existing approved reports must not be silently regenerated. Audit the frozen reporting hub independently: the confirmed legacy Report Centre defect alone does not establish that approved frozen reports contain the same defect.

Immediate next implementation deliverable: a focused correctness change with regression tests and a precise affected-path inventory. No navigation rewrite or new framework is part of that change. This document records the consolidated recommendation; implementation has not started.

## Scope and evidence

- **Verified in the browser:** local application at http://localhost:8000, signed-in administrator; Board, Operations/Production, Performance & Governance/My Work, Scorecard empty state, Finance, Human Resource & Administration, Infrastructure, Reports and Administration. Desktop screenshots and a 390 × 844 administration viewport were inspected. Original desktop size and Board page were restored.
- **Verified in source:** navigation definitions, KPI presentation, chart configurations, shared governance tables, reporting workflow UI, regulatory and private people-module UI. Checkout HEAD was `dc3cbb1`, with existing uncommitted changes.
- **Inferred:** usability impacts and proposed redesign; these need representative user testing.
- **Untested:** populated operational charts and large tables, full approval journeys, non-admin roles, assistive technology, measured contrast, complete mobile coverage, live integrations and production deployment. The available fiscal year contained no operational data and the scorecard had no configured plan. No data was imported or altered for this review.
- External comparisons use current official product descriptions, not hands-on vendor trials or an independent ranking. Older competitive documentation understates the newer governance and metric-catalogue implementation; it is not a current feature inventory.

Done for this review: identify concrete problems, recommend navigation and visual rules, specify chart/table placement, assess water-utility scope, and provide a prioritized implementation and validation plan. Application behavior is unchanged.

## 1. Prioritized findings

| Priority | Observed evidence | User impact | Required change |
|---|---|---|---|
| P1 | Board shows “Awaiting Data” while NRW is “GOOD,” supply hours “CRITICAL,” and the alert panel says all KPIs are within target | Missing data becomes an unsupported performance judgment | Evaluate completeness before status; show “Not assessed — no data.” Preserve genuine measured zero separately |
| P1 | Production shows the tenant NRW target as 25%, but a zone-chart note says 27% | Users cannot tell which comparator to trust | Resolve all values, labels, notes and exports from the applicable target and its provenance |
| P1 | Monthly-return panels display “LIVE”; empty scope shows “0 Zones at Risk” | Implies timeliness and assessment coverage that are not established | Show source period, last successful load, completeness and “Not assessed” where appropriate |
| P2 | Seven top-level department buttons replace the sidebar; Board contains both Consolidated Summary and Executive Dashboard; strategy, risk and reports have several entry points | Users must remember which workspace contains which version | One stable hierarchy, canonical destinations and explicit contextual shortcuts |
| P2 | Operations embeds Commercial; workforce/fleet and network topics span several departments | Business ownership and user task do not match the menu | Make Commercial visible; group operational, asset and workforce performance coherently |
| P2 | Production shows six governance/formatting badges before KPIs, repeated chart notes and large cards | Assurance metadata competes with the operational result | One concise data-status strip; move methodology to a details drawer |
| P2 | Administration retains the Reports shell and adds its own navigation; large hero explains its “design system” | Three navigation layers and irrelevant copy obscure the task | Dedicated administration context and compact task heading |
| P2 | At 390 × 844, administration filters/toolbar occupy over half the first screen and its internal menu scrolls horizontally | Basic work starts below substantial navigation overhead | Compact scope button, mobile menu and task-first stacking |
| P2 | Green, amber, purple, teal and red are used for ordinary admin counts, export buttons, cards and statuses | Colour loses its meaning as an exception signal | Neutral defaults, one brand accent and restrained semantic colours |
| P2 | Report Centre offers immediate generated reports; Reporting Hub manages frozen approval states | Users may mistake an exploratory export for an approved corporate record | One report destination with clearly separated working exports, drafts, review and approved/published records |
| P3 | Long truncated menu names, many SOON items, uppercase microcopy, emoji mixed with SVG icons and a live clock | Scanning cost without equivalent decision value | Short plain labels, consistent icons, meaningful timestamps; move roadmap items out of routine navigation |

Source anchors: `app/static/assets/js/app-core.js:2531` (missing-value status), `:2543` (collection status), `:5504` (empty alert message); `app/services/governance.py:344` (27% note); `app/static/index.html:2341` (27% chart title); `app/static/assets/js/department-tabs.js:53` (department definitions); `app/static/assets/js/mod-platform.js:193` (table renderer); `app/static/assets/js/mod-reports.js:20` (reporting workspace).

## 2. Information architecture

Use a stable left navigation with collapsible groups. Show only authorized and enabled destinations. Do not expand every group by default. Put recently used pages and favourites above the groups if user testing supports them. A Board preset can open the executive overview; an officer preset can open My Work without changing the navigation vocabulary.

| Primary destination | Contents |
|---|---|
| Home | My Work, approvals, overdue actions, notices; executive overview for board users |
| Utility Performance | Overview; Water Operations; Commercial & Customers; Finance; Assets & Infrastructure; People & Productivity |
| Strategy & Delivery | Plans/objectives, indicators, cycles, progress updates, scorecard, strategy map, evaluations |
| Governance & Compliance | Risks, audit findings, meetings/resolutions, regulatory returns |
| Reports & Evidence | Working reports, drafts, review queue, approved/published reports, controlled documents and evidence |
| Data & Administration | Sources/imports, quality/reconciliation, measures/targets, hierarchy, periods, users/access, configuration and audit |

Private contracts/appraisals remain permission-gated within the people area; relocating a menu must never broaden access. Actions should have one shared queue with contextual links from every module. Reporting periods and scoring-scheme configuration belong with setup, not routine strategy work.

Use local tabs only for views of the same subject, for example **Overview · Trends · Detail · Actions**. Do not force every transactional page into this template: actions, documents and approval queues should start with the useful list. Keep one canonical scorecard and explain any remaining legacy scorecard's distinct method until it can be retired safely.

Top bar: breadcrumb/page context, organizational scope, fiscal period, source freshness, and one primary action. Keep filters only where they affect content; user management should not appear to be filtered by a water zone or fiscal month. Store navigable page/filter state in URLs so a colleague can reopen an exact view, while enforcing access server-side.

## 3. Page hierarchy and colour

Executive overview should answer: What needs attention? Where? How serious? Who owns the response?

Proposed order:

1. Title, scope and data-through date; one primary action.
2. Compact data-quality/completeness strip, with a clear empty-state action if necessary.
3. Four to six selected outcome KPIs, each with actual, target, change and status.
4. Two useful charts: change over time and where the problem is concentrated.
5. Ranked exceptions/actions with owner and due date.
6. Detailed data, definitions and evidence on demand.

The current Board summary contains sixteen KPI cards. Retain the information in department drill-downs, but reduce the initial executive view. Important board outcomes should include service continuity, water safety, water losses, financial sustainability, delivery against plan and material risk, subject to valid data availability.

Keep MadziHub's navy/teal identity. Use off-white backgrounds, white work surfaces and dark readable text. Use teal for selection and primary actions; red for confirmed serious exceptions, amber for attention, green for assessed success, and neutral grey for missing/unassessed/not-applicable states. Ordinary counts such as “2 admins” need no warning colour. Distinguish categorical chart colours from performance-status colours and keep categories stable across pages.

Replace repeated “GOVERNED,” “READ NOTE,” and implementation-oriented copy with short user-facing explanations. Offer provenance, formula, approval state and source evidence in a common detail panel. Do not remove those controls or records; reduce their visual repetition.

Target WCAG 2.2 AA: text contrast, visible focus, keyboard operation, meaningful headings and colour-independent labels. The current governance toolkit has useful foundations (column scopes, keyboard row selection and textual badges), but that does not establish application-wide conformance. [W3C contrast guidance](https://www.w3.org/WAI/WCAG21/Understanding/contrast-minimum), [use of colour](https://www.w3.org/WAI/WCAG22/Understanding/use-of-color).

## 4. Chart and table specification

Charts support decisions; tables support exact comparison, investigation and work. Put a chart above the table only when it helps answer that page's primary question. Default registers and approval queues to tables, not decorative dashboards.

| Area | Chart and placement | Metrics/dimensions and drill-down |
|---|---|---|
| Executive | Two compact trends/comparisons after outcome KPIs | Selected outcomes vs approved target; exceptions by unit; select a unit/KPI to investigate |
| Production and NRW | Aligned time-series panels, then ranked horizontal bars | Fiscal month vs production/billed volume in m³; separate NRW % panel with target; unit vs NRW % and lost volume |
| Water balance | Reconciled stacked bars; waterfall only if components reconcile | System input, billed and other authorized consumption, apparent and real losses only where measured/estimated with provenance; never invent loss decomposition |
| Supply continuity | Line trend; labelled unit-by-month heatmap for many units | Hours/day, affected connections and interruption duration; distinguish missing cells from zero |
| Water quality | Result trends with applicable limits; exception table prominent | Parameter, sample site/date, measured value/unit, limit, failed/required/completed tests; dosing coverage alone cannot prove safe water |
| Commercial | Ranked bars and time trends | Active accounts, connection backlog, turnaround time, complaints/closure and meter exceptions; split service issues from financial performance |
| Finance | Billed/collected time series; variance bars; ageing bars if ageing data exists | Period/currency, collection ratio, cost recovery, budget variance and debtor ageing; receipts may include prior-period debt |
| Assets | Failure trend and sorted bars; map only with reliable spatial data | Failures, exposure-normalized rates, maintenance backlog, downtime, asset criticality; project timelines when project records exist |
| Strategy | Actual/target dot or bullet comparisons and expandable matrix | Objective/indicator, actual, target, achievement, direction, weight, completeness, owner and approved period |
| Governance | Action/exception tables first; risk matrix as secondary view | Risk/control/action, likelihood, impact, owner, due date, status and evidence; risk grid must link to the record |
| People | Headcount/establishment bars and separate cost trend | Filled/vacant roles, workforce ratios and cost; individual appraisal data stays restricted |
| Data management | Source freshness/status table first | Last load, expected cadence, accepted/rejected rows, reconciliation and action owner |

Prefer sorted bars to the existing numerous doughnuts when precise comparisons matter. Avoid radar charts, 3-D charts and gauge walls. Separate unlike units into aligned charts by default; any dual-axis chart must label units and scales unambiguously. Use fiscal order, direct labels, target provenance, consistent units, missing gaps, accessible data alternatives and visible scope on exports.

Tables: sticky headers and identifying columns where useful, right-aligned numbers, units in headings, consistent decimals, search/sort/filter, saved views, restrained column sets and row detail. Use pagination/server queries or virtualization only when data volumes warrant them. The shared `MZ.table` renderer provides basic rows and selection; it does not itself provide a complete sorting/pagination/column-management system. Keep monthly/quarterly/annual report matrices available for analysts and exported packs, rather than making them the initial board screen.

Preserve mathematical meaning: aggregate ratio components before calculating a ratio; distinguish cumulative flows from point-in-time balances; do not sum monthly customer counts; show how weighted averages and missing observations are handled.

## 5. Comparison with established products

| Comparator | Verified vendor capability | Implication for MadziHub |
|---|---|---|
| [Envisio](https://envisio.com/solutions/performance-analytics/) / [ClearPoint](https://www.clearpointstrategy.com/solutions/reporting) | Strategy-linked measures, ownership, dashboards and reporting | Closest comparison for performance/strategy UX; connect result, explanation, owner and action |
| [Xylem Vue](https://www.xylem.com/en-uk/brand/vue/our-solutions/xylem--vue/water-utility-management-software/) | Integrated water/wastewater data and modular network, plant and asset analytics | Make integrated data actionable; do not imply monthly reporting provides equivalent real-time operations |
| [Bentley OpenFlows Water](https://www.bentley.com/products/openflows-water) | Hydraulic modelling, water quality/energy analysis and scenario comparison | Specialist engineering capability; integrate outputs where needed rather than reproduce the modelling engine |
| [Oracle Utilities](https://docs.oracle.com/en/industries/utilities/customer-cloud-service/) | Customer care, service orders, metering and billing | Summary customer/billing indicators do not constitute a transaction system |
| [IBM Maximo](https://www.ibm.com/products/maximo) | Maintenance, inspections and asset reliability workflows | Breakdown summaries do not constitute asset lifecycle or work-order management |
| [Esri](https://www.esri.com/en-us/industries/water-utilities/business-areas/network-management) | Spatial network management and field/office asset information | Add maps only around meaningful spatial tasks and verified asset/location data |

MadziHub has broad water-utility **management reporting** coverage: production/NRW, treatment/energy, supply, customers, billing/collections/costs/debtors, workforce and network summaries. It also has substantial newer strategy, scoring, reporting, document, risk/audit, regulatory and people-workflow implementation. Those modules deserve integration into the interface, not to be described as entirely absent.

It does **not yet capture everything needed to operate an entire utility**. Priorities to validate with a utility are water-quality sampling/compliance depth, service coverage and equity, complaints and interruption response, asset maintenance/renewal, capital-project and funding delivery, cashflow/affordability, safety and climate/source-water resilience. Wastewater/sewerage and effluent compliance matter where they are within the utility's mandate. Some are configurable measures; others need new records or integration and cannot be solved by a layout change.

Recommend maintaining MadziHub as the governed performance, strategy and accountability layer above billing, ERP, SCADA, GIS, laboratory and asset systems. Source adapters and a generic connector framework do not prove a successful customer integration. Regulatory-pack machinery does not prove every pack's thresholds are independently verified; the roadmap still flags verification work.

## 6. Delivery order and acceptance

| Stage | Scope | Exit evidence |
|---|---|---|
| 1: Trust | Missing vs zero, status consistency, target labels, freshness and honest alerts | Empty, partial, stale, zero and complete fixtures produce correct labels across cards/charts/reports |
| 2: Shell | Stable navigation, canonical destinations, compact scope, breadcrumbs and mobile menu | Existing routes/actions remain reachable; correct role restrictions; browser back/deep links and scope persistence work |
| 3: Pilot screens | Executive overview, one Operations page, My Work and report entry | Representative board/officer users can identify a problem, inspect its source and find its responsible action without guidance |
| 4: Shared components | KPI, chart, table, status, empty/error states and detail drawer | Same states and semantics across all modules; keyboard, contrast, responsive and populated-table checks |
| 5: Rollout | Remaining domains, admin and report/export consistency | Existing parity and permission tests pass; approved snapshots and exported values remain unchanged |

Suggested usability acceptance targets, to validate rather than claim as achieved: locate the principal exception within 10 seconds; reach its detail within two navigation steps; identify source/period/owner without leaving the detail; preserve selected scope across applicable views; no page-level horizontal overflow at 390px (wide analytical tables may scroll within their own container).

Use representative synthetic populated data in an isolated review environment for the next design iteration. Include both roles and bad states, not just attractive successful dashboards. Begin with wireframes and shared presentation components; a new frontend framework or database redesign is not necessary for this work. Add read-model fields only where the UI cannot reliably determine completeness or provenance from existing APIs. Keep scoring rules, approvals, access checks and frozen records intact, and do not re-record numerical parity snapshots merely to make a visual redesign pass.

Completed: system-wide navigation/representative-screen review, source checks, external capability research, proposed design direction. Needs attention: identified trust defects and responsive layout. Untested: populated end-to-end usability and all-role accessibility. No application edits, migrations, commits or deployment were performed.
