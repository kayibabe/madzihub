# MadziHub product research benchmark

**Research checked:** 24 September 2026  
**Scope:** strategy execution and M&E, weighted scorecards, reporting hubs, document control, and adjacent governance capabilities for water and wastewater utilities.

This is a product-design benchmark, not a procurement evaluation or a claim that MadziHub is compliant with any regulator or ISO standard. Vendor pages describe their own products. Regulator methods below are tied to the cited report and year; they must not be copied forward as timeless rules.

## Executive recommendations

1. **Build a governed strategy-to-results cycle.** Connect objectives and indicators to initiatives, activities, owners, budgets, risks, and actions. Capture period-specific baselines, targets, forecasts, actuals, evidence, commentary, approvals, and evaluation responses.
2. **Keep an organization scorecard separate from regulator ranking.** The organization may choose a configurable five-band, weighted plan scheme. Regulator packs must implement that regulator's published definitions, peer rules, thresholds, weights, and reporting codes for a particular effective period.
3. **Make reports reproducible.** Generate board packs and returns from approved, frozen input snapshots; show missing submissions and exceptions; retain the template, data cut, approvals, output hash, and version.
4. **Start document control small but sound.** Release evidence attachments and controlled documents with metadata, access checks, explicit versions, approval/effective/superseded states, review dates, integrity hashes, and links to the exact evidence version. Defer retention automation and disposal policy until each customer supplies an approved schedule.
5. **Make actions and relationships shared platform capabilities.** Strategy reviews, risks, audit findings, board resolutions, and regulator exceptions should create or link to owned, dated actions with history and evidence.
6. **Treat staff appraisal as a later, restricted module.** It contains sensitive employment data and should follow customer HR policy, confidentiality rules, appeal/correction procedures, and authorization design.

## What the comparable systems demonstrate

| Reference | Publicly documented pattern | MadziHub application |
|---|---|---|
| ClearPoint Strategy | Scorecards and measures connected to objectives and initiatives; reporting workflows, update inbox, comments, history, briefings, scheduled exports. Product claims are vendor descriptions. | Strategy tree, linked delivery work, update inbox, approvals, reusable board-pack templates, revision history. Keep reports useful without AI. |
| Spider Impact | Methodology-flexible scorecards, KPI roll-ups, strategy maps, initiative tracking, alerts and role-oriented dashboards. | Support named/configurable plan structures and objective-to-initiative links; keep calculations inspectable and scheme-versioned. |
| AchieveIt | Integrated plans with item owners/cadence, automated update requests, dashboards, multi-plan reporting and board/public progress communication. | Make recurring update collection and exception-focused review easier than collecting spreadsheets; keep audience scope explicit. |
| Envisio | Public-sector strategy/performance management and public dashboards for communicating progress and project/budget status. | Design an optional publication view with selected fields and a reviewed data snapshot; internal drafts and restricted reports stay private. |
| DHIS2 | Period- and organization-unit-based, bottom-up approval; optional approve/accept stages; approval can lock data; configurable validation. | Reuse period and org-scope concepts. Define separate workflows by record type and allow a correction only through a reasoned, audited reopen. |
| DevResults | Results frameworks, period-bound indicators, and monitoring/reporting workflows for development programs. | Retain indicator definition/source/period metadata and an evidence trail; use separate evaluation records for learning and management response. |
| OECD results-based management | Clear expected results and indicators, monitoring, evaluation, risk management, learning, and accountability need to operate together. | Add evaluation plans, findings, management responses, and follow-up actions, not only KPI traffic lights. |
| WASREB | Public sector comparison and accountability through annual IMPACT reporting; indicator thresholds and scoring are published by report cycle. WARIS is the regulator's national information system. | Build a source-specific return and comparison pack. Do not imply MadziHub is WARIS or an official substitute. |
| EWURA | Annual comparative reports; FY 2023/24 method combines KPI and regulatory-compliance scores and describes indicator-level weighting and confidence considerations. | Support a different versioned pack; avoid a generic league-table formula. |
| M-Files | Metadata-led classification and views, search, workflow and version history. | Classify by metadata and relationships rather than relying on folders; store each new revision as a new immutable version. |
| ISO 31000 | Risk process includes identification, analysis, evaluation, treatment, monitoring, review, and communication. It is guidance, not a certifiable requirements checklist. | Configure risk criteria to each organization and connect treatments to actions and objectives. Do not market ISO certification. |
| ISO 9001 documented information guidance | Documents need suitable identification, format, availability, protection, and control; organizations determine what documented information their system needs. | Provide controlled-document metadata, approval and lifecycle states. Avoid claiming that a specific retention period is required by ISO 9001. |

## 1. Strategy implementation, monitoring and evaluation

### Recommended operating model

Model two connected structures:

- **Results structure:** vision or outcomes, perspectives/pillars, strategic objectives, indicators, and measures.
- **Delivery structure:** initiatives, work packages, milestones, activities, budgets, and owners.

Use links between these structures rather than a single rigid parent-child tree. A single initiative may support several objectives; one objective may depend on multiple initiatives. Keep the level labels configurable, but give each node a stable typed role so reports and permissions remain understandable.

Every result record needs an explicit period and organizational scope. Indicators should have a controlled reference sheet: plain-language name, code, definition, formula, unit, polarity, aggregation rule, source and owner, baseline and date, target and target basis, frequency, evidence requirement, and data-quality notes. Store actual, target, baseline, budget, and forecast as distinct series; do not treat a forecast as an actual or overwrite prior periods.

The reporting cycle should collect a submission, narrative, explanation of variance, evidence, forecast, and corrective action. Show `no submission`, `not applicable`, `pending review`, and numeric zero as distinct states. Preserve every submitted version. Approval should be scoped by period and organization unit, with an optional verification step before approval and lock. A returned submission needs a reason and a traceable new revision.

### Evaluation and learning

Plan mid-term and end-term evaluations separately from routine indicator updates. Each evaluation should record its scope, method, evidence, findings, limitations, management response, owner, due dates, and follow-up actions. The OECD DAC evaluation criteria (relevance, coherence, effectiveness, efficiency, impact, sustainability) are useful optional templates; they are not mandatory fields for every utility or every evaluation.

Data quality belongs in the workflow: validity/range checks, completeness, timeliness, consistency/reconciliation, and source lineage can be configured as checks. Store assessment results and reasons; do not turn a failed check into a silently adjusted value. A reviewer should see both performance and confidence in the submitted evidence.

### Proposed screens

- Strategy map with the objectives and links to initiatives.
- Expandable scorecard/tree grid with period and organizational filters.
- Indicator reference sheet and history.
- Cycle setup and assignment of owners/reviewers.
- `My updates`, overdue submissions, verification queue, and approval queue.
- Evaluation workspace with findings, response, and action follow-up.

## 2. Weighted scorecard and performance monitoring

### Separate three things

1. **Achievement:** how the observed value compares to its target, applying the measure's polarity and valid target rule.
2. **Plan rating:** how achievement maps to the organization's selected performance bands.
3. **External/regulator score:** the published external methodology, potentially including compliance, confidence, peer cluster, service benchmark, and peer-relative scores.

Never label an internal plan score as a regulator score. Save the scheme version and its effective dates with every result.

### First organization scheme

The agreed starting scheme is percentage achievement, polarity-aware, capped at 130% for rating purposes, mapped through a configurable five-band scale and combined by indicator weight. Store uncapped achievement too, so the display does not hide overachievement. A scorecard editor must require weights to sum to 100% at each weighted level and must show the calculation inputs and formula.

Before implementation, publish the exact band thresholds and the meaning/order of ratings. This is essential because schemes differ: a 1-to-5 scale can mean best-to-worst in one contract scheme and worst-to-best in another. Use scheme metadata and explicit labels; do not infer order from a number. The Kenya performance-contract calculation is evidence for a configurable contract adapter, not proof of a universal East African scale. Malawi's public water-sector strategy uses results frameworks with indicators, baselines, targets, sources of verification and risks; this research did not verify a current Malawi water-utility regulator league-table method or a matching national 1-to-5 contract scale.

The proposed 130% ceiling is a MadziHub product choice, not an exact implementation of the current Kenya FY 2025/26 public-service contract guidance. That guidance describes a 1-to-5 score where 1 is best and 5 is worst for higher-is-better indicators, an upper scoring criterion of twice target for some indicators, and a separate special case for indicators whose achievement cannot exceed 100%. Keep the MadziHub default scheme explicit and versioned; add a Kenya adapter only when reproducing the exact current contract rules and indicator-specific exceptions.

For lower-is-better measures, protect against zero targets and invalid denominators with a scheme-defined rule and a reviewable calculation; do not rely on a generic divide-by-target formula. Range/polarity indicators need separate functions. Non-numeric indicators such as milestones, yes/no obligations, and key risk indicators need distinct scoring rules.

### Missing data and roll-up policy

Do not silently rescale weights around missing children or count missing as zero. For a default plan score, report the score only when required data and a configured minimum coverage gate are satisfied; otherwise show `incomplete`, the covered weight, and the missing items. A scheme may explicitly choose another missing-value treatment, but it must be visible, approved, and included in the snapshot. The UI must keep performance status separate from data completeness and data quality.

Score snapshots should retain the source value/target IDs, indicator and scoring-scheme versions, formula/engine version, inputs hash, completeness, per-child weighted contributions, approval state, and any override with reason and audit event. Recalculation creates a new snapshot; it does not rewrite a previously approved score.

### External benchmark packs

Store each pack as versioned data with regulator, jurisdiction, cycle, source document/link, publication/effective date, peer group, codes, definitions, units, polarity, thresholds, weights, validation rules, and export template. A reviewer must approve a pack update before use. Keep raw submitted return values separately from calculated values and preserve the import/source evidence.

Recent primary-source examples show why:

- WASREB IMPACT 17 (FY 2023/24) describes a ranking based on nine KPIs with indicator-specific thresholds and scores; current WASREB pages list IMPACT 18 for FY 2024/25. Use the applicable report, not a remembered historical band.
- EWURA FY 2023/24 combines KPI score (60%) with regulatory compliance requirements score (40%); indicator scoring also considers best performer, target attainment, confidence grading, and service-level benchmarks.
- Malawi's Revised National Water Policy (2022) sets out outcomes, indicators, baselines, targets, sources of verification, assumptions/risks, and M&E coordination. This is strategy/M&E evidence, not a utility league-table specification.
- NWASCO and IBNET packs should be included only after the jurisdiction, official schema, current return, and scoring method have been confirmed from their primary sources. A pack must never be inferred from another regulator's method.

## 3. Reporting hub

Build reusable report templates with period, organizational scope, audience, and data cut. Separate working drafts from approved/published instances. For an approved instance freeze the normalized inputs, template/version, indicator and score versions, commentary, approvals, outputs and hashes. Generate it from a consistent approved snapshot, not from live mutable dashboard queries.

Core first reports:

- Executive/board performance pack with strategy status, trend, variance commentary, risk, decisions required, and overdue actions.
- Performance scorecard and supporting indicator detail.
- Submission/completeness and data-quality report.
- Exception report for adverse trends, missed targets, overdue actions, stale data and missing evidence.
- Regulator return and peer comparison, enabled only for an approved versioned pack.

Provide role-scoped views, revision/audit history, accessible HTML preview, PDF and spreadsheet export first. Add DOCX or scheduled distribution only after templates, access controls, delivery logs, and the Windows deployment path are proven. Each generated output should record who created, reviewed, approved, published, downloaded, or distributed it. Do not send external messages automatically without an explicit configured distribution action.

## 4. Document management

### Release scope

Keep two use cases distinct:

- **Evidence attachment:** a file pinned to the exact version of an update, KPI value, action, risk, finding, resolution, or report. Replacing evidence creates a new version and history entry.
- **Controlled document:** a policy, procedure, plan, or form with identifier/number, type, owner, access classification, effective date, review date, approver, status, and supersedes/superseded-by links.

Use metadata, tags, and linked records for retrieval. Store files outside public static paths. Enforce scoped authorization for upload, preview, download, search snippets, and exports. Verify file size/type, generate storage names, hash the bytes, and ensure each version's content is append-only; a hash alone does not prevent mutation. Extraction/indexing failure should be visible and must not change the original file. Start with text extraction for supported formats and make OCR optional.

Release 1 can include evidence and controlled-document workflows, master-document list, version history, and metadata/full-text search where feasible. Defer automated retention, legal holds, and disposal until each customer's legal schedule and records policy are supplied and approved. ISO 15489/16175 and jurisdiction rules need specific legal/records review before an implementation claim.

## 5. Adjacent modules and sequencing

| Module | Value | Recommended dependency/order |
|---|---|---|
| Shared action tracker | Converts strategy, review, risk, audit, and board exceptions into owned work. | Platform foundation; deliver with strategy/M&E. |
| Board/committee resolutions | Captures decision, owner, due date, evidence, and closure. | Governance registers after shared actions and document evidence. |
| Audit findings | Tracks finding, rating, response, due date, validation, and closure evidence. | Governance module after shared actions; protect auditor/management roles. |
| Enterprise risk register | Inherent/residual assessment, controls, treatments, owners, review date, and objective links. | After shared platform; adapt criteria, don't hard-code a universal 5x5 risk appetite. |
| Regulator returns and league tables | Less duplicate work and clearer peer performance. | Only after official local pack, code mapping, validation and source approval. |
| Performance contracts and staff appraisal | Cascading accountability. | Later release after policy confirmation, private HR scope, restricted roles, appeal/correction history and assessment separation. |
| Budget and capital delivery | Links resources and projects to intended outcomes. | Later; reuse versioned budgets/targets and project actions. |

## 6. Architecture review of the draft plan

- **Preserve per-install isolation.** Continue one utility per installation/database for the initial product; do not add shared-host multi-tenancy as a shortcut.
- **Reuse the metric/integration layer.** Existing `OrgUnit`, `Metric`, `MetricValue`, `MetricTarget`, source lineage, safe formula engine and position queries are the natural bridge from imported data into scorecards. Keep legacy `/api/strategic/scorecard` stable and add new `/api/strategy/*` APIs as planned.
- **Migrate deliberately.** Establish the Alembic baseline from a known schema. Do not auto-stamp an unknown or partially migrated database at application startup. Back up, fingerprint and explicitly stamp verified legacy installs; run upgrades as an operator-controlled deployment step with recovery instructions.
- **Make scope a required query boundary.** Every object service/report/export should receive a resolved user scope. Deny by default if scope is missing. Test direct routes and indirect joins/downloads, not only dashboards.
- **Keep workflows typed.** A metric submission, strategy update, report instance and controlled document have different lifecycles. Share transition/audit primitives, not one undifferentiated state machine.
- **Keep background work operationally simple.** Existing CLI plus Windows Task Scheduler is the simplest default for one-install deployments. Add in-process APScheduler only if its lifecycle, multi-worker lease, shutdown, monitoring and missed-run behaviour are demonstrated; a database lease prevents duplicates but does not by itself guarantee a missed job will run.
- **Keep the frontend modular.** New feature screens belong in separate JS/CSS modules; avoid growing `app-core.js`.
- **Add dependencies by deliverable.** Do not install all export, OCR, scheduling, and migration libraries up front. Select and verify PDF/DOCX renderers on Windows when the corresponding export phase is reached.

## 7. Revised delivery sequence and exit gates

1. **Baseline and decision record:** preserve current user work; make the rebrand checkpoint separately; add this research and reconcile the old blueprint's SRWB-reference wording; keep parity endpoints stable.
2. **Schema migration foundation:** Alembic baseline, known fresh/legacy upgrade paths, foreign keys/WAL as supported, backup/recovery notes. No automatic migration of unknown production data.
3. **Shared governance foundation:** periods, org scope/roles, audit events, typed approval workflows, correction history, and common action/evidence links. Scope tests include reports, exports, documents and nested relationships.
4. **Strategy and M&E:** plan/indicator registry, results and delivery links, cycle assignments, immutable updates, data-quality assessments, reviews and management responses.
5. **Scorecard:** pure, versioned calculation engine, exact band scheme configuration, polarity and missing-data policy, saved snapshots and overrides. Complete a full quarterly review before board-pack dependency.
6. **Reporting hub:** templates, frozen instances, audience/approval lifecycle, HTML/PDF/XLSX outputs, exception reports and export access checks.
7. **Document control:** evidence versioning and controlled documents; verify scoped access, file integrity, indexing, backup and restore.
8. **Governance and risk:** resolutions, findings, and risk register connected to actions and documents.
9. **Regulatory and HR extensions:** source-verified regulator packs first; performance contracts and staff appraisals only after jurisdiction/policy and privacy gates.

Each release slice should have defined acceptance journeys and failure cases, code review, updated docs, and a separate commit. Keep the existing parity snapshots unchanged unless an intentional API change is documented. Release evidence should include a fresh install, verified legacy upgrade, org-scoped user journey, approval/lock/correction journey, exports and backup/restore. Visual QA should cover desktop/mobile and keyboard/contrast use. Production migration, external distribution, or deployment remain separately authorized release actions.

## Sources

Primary sources were preferred. Vendor sources are used to observe feature patterns, not to validate performance claims. Accessed 24 September 2026.

### Strategy, scorecards and M&E

- [ClearPoint Strategy feature overview](https://www.clearpointstrategy.com/features)
- [ClearPoint help: reporting periods and scorecards](https://support.clearpointstrategy.com/en/articles/9099476-getting-started-guide-navigating-clearpoint)
- [Spider Impact overview and FAQ](https://www.spiderstrategies.com/faq/)
- [AchieveIt strategic planning and execution](https://www.achieveit.com/solutions/strategic-planning-software/)
- [Envisio strategic planning and performance management](https://envisio.com/)
- [DHIS2 data approval documentation](https://docs.dhis2.org/en/use/user-guides/dhis-core-version-240/approving-data/data-approval.html)
- [DHIS2 data collection and validation](https://dhis2.org/features/collect/)
- [DevResults configuration guide: results frameworks and indicators](https://help.devresults.com/help/pdfexport/id/5cda1cce8e121c0a49701862)
- [OECD: Managing for sustainable development results](https://www.oecd.org/en/publications/development-co-operation-tips-tools-insights-practices_be69e0cf-en/managing-for-sustainable-development-results_8e326a5d-en.html)
- [OECD evaluation criteria](https://www.oecd.org/en/topics/sub-issues/development-co-operation-evaluation-and-effectiveness/evaluation-criteria.html)
- [Malawi Revised National Water Policy, 2022](https://www.water.gov.mw/index.php/en/downloads/policy-documents?download=24%3Arevised-national-water-policy-28-january-2022)
- [Kenya Public Service Commission: PAS guidelines for performance rewards and sanctions](https://publicservice.go.ke/wp-content/uploads/2024/03/PAS_GUIDELINES_-_IMPLEMENTAITON_OF_PERFORMANCE_REWARDS_AND_SANCTIONS.pdf)
- [Kenya 22nd-cycle performance contracting guidelines, FY 2025/26](https://www.energy.go.ke/sites/default/files/PC%20GUIDELINES%20FOR%20FY%202025_26%20%2822ND%20CYCLE%29.pdf)

### Water regulator performance and returns

- [WASREB IMPACT reports](https://wasreb.go.ke/impact-reports/)
- [WASREB IMPACT 17, FY 2023/24](https://wasreb.go.ke/wp-content/uploads/2025/06/IMPACT-REPORT-17.pdf)
- [WASREB IMPACT 18, FY 2024/25](https://wasreb.go.ke/wp-content/uploads/2026/06/Impact-18-Report.pdf)
- [WASREB WARIS system overview](https://wasreb.go.ke/wasreb-systems/waris-system/)
- [EWURA water performance reports](https://www.ewura.go.tz/index.php/pages/water-performance-reports)
- [EWURA Water Utilities Performance Review Report, FY 2023/24](https://www.ewura.go.tz/uploads/documents/en-1743160797-Water%20Utilities%20Performance%20Review%20Report%202023-24%20Final.pdf)

### Documents and risk

- [M-Files user guide: metadata, workflow and version history](https://userguide.m-files.com/user-guide/latest/eng/intelligent_metadata_layer.html)
- [ISO documented information explanatory paper](https://committee.iso.org/sites/tc46sc11/home/news/content-left-area/news-about-standarization-in-t-1/explanatory-document-on-document.html)
- [ISO 15489-1:2016 records management principles](https://committee.iso.org/standard/62542.html)
- [ISO/TS 16175-2:2020 guidance for records-management software](https://www.iso.org/standard/74293.html)
- [ISO 31000:2018 Risk management — Guidelines](https://www.iso.org/standard/65694.html)
