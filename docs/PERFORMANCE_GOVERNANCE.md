# Performance & Governance modules

This guide covers the modules added on top of the dashboards: the shared governance
foundation, strategy and M&E, the scorecard engine, the reporting hub, document control,
governance and risk, regulator packs, and performance contracts and appraisals.
The roadmap and the reasoning behind each design choice are in
[RESEARCH_BENCHMARK.md](RESEARCH_BENCHMARK.md) §7.

All of it appears in the app under the **Performance & Governance** tab. APIs live under
`/api/platform/*` (shared foundation) and one prefix per module.

---

## 1. Shared governance foundation

### Access: deny by default

| Concept | Meaning |
|---|---|
| **Account role** | `admin`, `user` or `viewer` (unchanged). A `viewer` account is read-only everywhere, whatever else it is granted. |
| **Unit grant** | A role on an organisational unit: `viewer` < `contributor` < `reviewer` < `approver`. A grant covers the unit and every unit below it. |
| **Organisation-wide grant** | A grant on the root unit `org`. Needed for the organisation-wide dashboards, reports and exports (everything outside this workspace). |
| **Duty** | An organisation-wide responsibility: strategy manager, report manager, document controller, board secretary, auditor, risk manager, regulatory officer, HR officer. |

- A person with **no grant sees nothing**. Administrators see every unit and hold every duty
  except **HR officer**, which must be granted explicitly so appraisal data is never visible by default.
- A person limited to some units lands on **My Work** and only sees the Performance &
  Governance workspace. Every list, detail, link, comment, history and download is filtered
  to their units; records outside their scope answer "not found" so ids cannot be probed.
- Grants and duties are set on **Setup & Assurance › Access & Scope** (administrators).
  "Add configured regions to the tree" creates the root and the tenant's regions if the
  organisation tree is still empty.

**Upgrade note (revision 0002).** Before this release every signed-in user could read every
dashboard. The migration keeps that behaviour explicit: each existing non-admin account is
granted organisation-wide `viewer` access, and each grant is written to the audit trail.
Accounts created afterwards start with no access until an administrator grants it.

### Periods

Months, quarters and the year are created per fiscal year on the tenant's fiscal calendar
(the current year automatically at start-up; others from **Reporting Periods** or
`python -m app.platform.cli periods --fy 2027`). An administrator can **lock** a period:
every module then refuses changes to it, including months inside a locked quarter or year.
**Reopening needs a reason**, and both steps are audited.

### Audit trail

`audit_events` records who changed what, when, the state before and after, and the reason.
It is append-only: database triggers reject `UPDATE` and `DELETE` (SQLite and PostgreSQL).
Administrators and auditors read it on **Audit Trail**; everyone can read the history of a
record they can see.

### Actions

Owned, dated follow-up work, raised from any module (evaluation responses, audit findings,
risks, resolutions) or directly.

    open → in progress → completed → closed        (cancel from open/in progress; reopen from completed/closed)

- Raising needs the contributor role on the unit; the owner must be able to see the unit.
- Completing needs a note. **Closing verifies the work and must be done by a reviewer who
  is not the owner.** Cancelling, reopening and moving an agreed due date need a reason.
- Owners can report progress but cannot re-date or re-assign their own actions.

### Links, comments, notices

- **Links** join any two records (e.g. an initiative *contributes to* an objective) and can
  pin an exact version (evidence). You can only link from a record you may change to one you
  may see; links to records outside your access are counted as hidden, never shown.
- **Comments** are kept in order and never edited.
- **Notices** appear in My Work. `python -m app.platform.cli reminders` (schedule it daily)
  adds due-soon and overdue notices once per item per day. Nothing is e-mailed: external
  distribution needs its own, explicitly configured and authorised release step.

### Scheduling the reminder job (Windows)

    schtasks /Create /TN "MadziHub reminders" /SC DAILY /ST 06:00 ^
      /TR "\"C:\MadziHub\venv\Scripts\python.exe\" -m app.platform.cli reminders" /RU SYSTEM

Run it from the install folder (set "Start in" to the MadziHub folder) so it uses the same `.env`.

### Demo data

`python -m app.demo_seed` adds fictional people, grants and records to the **demo** tenant
only (it refuses any other tenant) and prints the demo passwords once.

---

## 2. Strategy and M&E

**Pages:** Plans & Indicators · Reporting Cycles · Progress Updates · Evaluations. **API:** `/api/strategy/*`.

### Plan structure

- A plan has two trees: **results** (pillar → objective → outcome → output) and **delivery**
  (programme → initiative → activity → milestone). Delivery work is *linked* to the results it
  serves ("contributes to"); one initiative can serve several objectives.
- Each plan can rename its levels (e.g. "Focus area") on **Level labels**; the underlying types
  stay fixed so reports and permissions stay consistent. A level in use cannot be switched off.
- Strategy managers (duty) shape plans. An item's owner, or an approver on its unit, may report
  a delivery item's status. Plans move draft → active → archived (archiving needs a reason).
- People limited to some units see the items for their units, plus the parent items as context
  (titles only).
- `Import configured plan` turns `strategic_plan` in `tenant.yaml` into a draft plan: a pillar per
  focus area, an indicator per KPI, and the annual targets. It is idempotent.

### Indicator reference sheet

Name, definition, the result it measures, polarity (higher / lower / range / milestone / yes-no /
key risk indicator), unit, formula, aggregation, frequency, collection (manual, or automatic from
connected systems), source, owner, responsible and reporting units, baseline and date, target basis,
evidence requirement, valid range and data-quality notes. **Changing a definition field needs a
reason and creates a new version**; administrative fields (owner, notes, units) do not.

Targets are stored with the catalogue targets (tagged with the plan), per unit and period, on the
fiscal calendar. Changing an agreed target needs a reason. Values are never stored on the indicator:
approved manual figures are published to the measure catalogue under the *strategy-updates* source,
so every figure is read the same way as data from connected systems.

### Reporting cycles and progress updates

1. A strategy manager creates a cycle for a period, **generates** one assignment per indicator of
   that frequency and per reporting unit, names who submits / verifies / approves (or leaves it to
   anyone with the role on the unit) and **opens** it. Contributors are notified.
2. The contributor submits a figure, forecast, narrative, variance reason, corrective action and
   evidence. Every submission is a **new numbered revision**; revisions cannot be edited (database
   triggers enforce it).
3. Automatic data-quality checks run on submission and are recorded, never "fixed": timeliness,
   valid range, completeness (off target without an explanation), evidence, and consistency with
   the previous period and with any connected system reporting the same figure. Reviewers can add
   their own assessments.
4. A reviewer **verifies** (optional per cycle), an approver **approves**; nobody verifies or approves
   their own submission. Returning needs a reason. Approval publishes the figure.
5. An approved figure is corrected only by **reopening with a reason**; the next approval replaces
   the published value and the audit trail keeps both.

"No submission", **pending** (figure not yet available; cannot be approved), **not applicable**
(needs an explanation; published as *n/a*, never zero) and a reported **zero** are always distinct.
A locked period or a closed cycle refuses submissions and decisions.

### Evaluations

Mid-term, end-term and thematic evaluations record scope, method, optional criteria (the OECD DAC
criteria are offered as a template, not required), findings and limitations. Every finding needs a
**management response** before the evaluation can be completed; accepted and partially accepted
recommendations create an owned, dated **action** linked back to the finding.

---

## 3. Scorecard engine

**Pages:** Scorecard (with Weights) · Strategy Map · Scoring Schemes. **API:** `/api/scorecard/*`.
The calculation is `app/modules/scorecard/engine.py`: pure functions, versioned (`ENGINE_VERSION`).

### Three separate things

1. **Achievement** — how the approved value compares with its target:

   | Polarity | Rule |
   |---|---|
   | Higher is better | actual ÷ target × 100 |
   | Lower is better | (2 − actual ÷ target) × 100 (default), or target ÷ actual × 100 (scheme option) |
   | Range | 100 inside the range; outside, 100 × (1 − distance ÷ range width) |
   | Milestone | % complete ÷ % planned, at most 100 |
   | Yes / no | yes = 100, no = 0 |
   | Key risk indicator | within appetite (target) 100; within tolerance (upper) 50; beyond 0 |

   Never below 0. **Capped for rating** at the scheme cap (default 130 %); the **uncapped value is
   kept and shown**. A zero target is left unscored by default (or binary met/not met, by scheme
   choice); a negative target is unscored.
2. **Rating** — the capped achievement falls into one of five bands. The scheme states which end is
   best; it is never inferred from the numbers.
3. **Roll-up** — children are combined by weight at each level (pillar ← objectives ← indicators).
   Each level's weights add up to 100 or are all blank (equal shares, shown as such).
   - Items that are **not applicable**, **not due** in this period (e.g. an annual indicator in a
     quarter) or **not reported by this unit** leave the weights; the method says so.
   - Items with **no approved value** or **no target** count as *missing*. Below the scheme's
     **coverage gate** (default 80 % of weight) the level is **incomplete**: no score, with the
     covered weight and the missing items listed. Above it, the score is weighted over the covered
     weight and the method states the coverage. Missing data is never scored as zero, unless a
     scheme explicitly chooses "count missing as 0 %".
   - A node's rating is the weight-averaged rating of its children; its label is the nearest band.

Performance (rating), completeness (coverage) and data quality (DQA fails/warnings from the
progress update) are separate columns.

### Proposed default scheme — requires sign-off

| Rating | Label | Capped achievement |
|---|---|---|
| 5 | Exceeded | 110 % and above |
| 4 | Achieved | 100 % to below 110 % |
| 3 | Nearly achieved | 90 % to below 100 % |
| 2 | Below target | 70 % to below 90 % |
| 1 | Well below target | below 70 % |

Cap 130 %, coverage gate 80 %, zero targets unscored, lower-is-better (2 − a/t). This is
MadziHub's proposal, not a regulator's or government method. It is created as a **draft**; scores
calculated with a draft scheme are *provisional* and cannot be approved. A strategy manager other
than the author signs a scheme off. An approved scheme is never edited: changes are a new version.

### Snapshots

A snapshot freezes the inputs (the metric-value and target row ids, values, weights, data-quality
flags), the scheme and engine versions, an **inputs hash**, and the full result. Recalculating makes
a **new** snapshot; approving it supersedes the previous approved one, which is kept. On a draft,
an approver may **override** an item's rating with a reason; the calculated value stays visible and
the override is re-evaluated from the frozen inputs (never from live data). Snapshots are taken by
a reviewer or strategy manager and approved by an approver on the unit who did not take it. A
locked period accepts no new snapshots or approvals.

A snapshot whose overall score is **incomplete** (below the coverage gate), has invalid weights or
has nothing to combine **cannot be approved**. The only exception is an explicit override of the
overall (plan) rating, with a reason: it is audited, and board packs and scorecard reports show it
as an exception with the reason, who made it and the calculated value. A board pack or scorecard
report also refuses approval if its frozen score is incomplete without such an override.

### Strategy map

Pillars with their objectives coloured by rating (from the latest approved snapshot, else a live
calculation, labelled as such), and the programmes and initiatives that serve them. A table with
the same information follows the map for screen-reader and print use.

---

## 4. Reporting hub

**Page:** Reporting Hub. **API:** `/api/reports-hub/*`.

### Reports

| Template | Contents |
|---|---|
| Board performance pack | Executive summary, strategy status by pillar/objective, trend of approved scores, variance commentary (off-target indicators with the submitter's reason and corrective action), principal risks, decisions required, overdue actions |
| Scorecard and indicator detail | Every item and indicator: weight, actual, target, achievement, rating, completeness |
| Submissions and data quality | Completeness of the period's assignments and every recorded data-quality finding |
| Exception report | Off-target indicators, missing submissions, missing evidence, stale or failing sources, overdue actions |

### Lifecycle

    draft ──submit──► in review ──approve──► approved ──publish──► published
      ▲                   │ return (reason)       └──────── withdraw (reason) ──► withdrawn

- Report managers (duty), or reviewers on the unit, create reports. Creating a report **freezes its
  data** from governed sources (approved score snapshots, submissions, actions, source health).
  While it is a draft the data can be refreshed; each refresh is a new data version with its own
  fingerprint. Commentary is written in the draft.
- Approval needs the approver role on the unit or the report-manager duty, and **someone other than
  the author**. Board packs and scorecard reports can only be approved once the score snapshot they
  show is approved. Approval fixes a content fingerprint (data + commentary + template).
- At approval the HTML, PDF and XLSX outputs are rendered **from the frozen data**, stored outside
  the web root (see *File store*), and their SHA-256 recorded. Every later download is served from
  storage after an integrity check; a tampered file is refused. Drafts are rendered on request and
  marked "not approved".
- Every creation, freeze, decision, preview and download is written to the report's **access log**
  (append-only).
- **No external distribution.** Reports are downloaded; e-mail or scheduled distribution is not part
  of this release and needs its own configured, authorised step.

### Formats

- **HTML** is the accessible format: real headings, captioned tables with header cells, print styles.
  It is shown in the app inside a sandboxed frame (no scripts).
- **PDF** is produced by *reportlab* (pure Python, no system libraries; chosen for Windows installs
  over WeasyPrint, which needs the GTK runtime). Its built-in fonts cover Latin-1, so a few symbols
  are written out (≥ becomes ">="). The PDF is not tagged for screen readers; use the HTML.
- **XLSX**: a "Report" sheet with everything, plus one sheet per table (numbers stored as numbers).

### File store

Generated reports (and uploaded documents) are kept in `MADZI_FILE_STORE` (default `data/files`).
Files are written once with app-generated names, never overwritten, and checked against their
recorded hash when read. **Back this folder up together with the database** (see the deployment runbook).

---

## 5. Document control

**Page:** Documents (Master list · All documents · Search). **API:** `/api/documents/*`.

### Types

| Type | Controlled | Number | Review | Formats |
|---|---|---|---|---|
| Policy | yes | POL-0001 | 36 months | PDF, Word |
| Procedure | yes | PRO-… | 24 months | PDF, Word |
| Plan | yes | PLN-… | 12 months | PDF, Word, Excel |
| Form / template | yes | FRM-… | 24 months | PDF, Word, Excel |
| Evidence, Report, Minutes | no | — | — | as configured (minutes default to *confidential*) |

### Controlled documents

    draft ──approve──► approved ──make effective──► effective ──(next revision becomes effective)──► superseded
      withdraw (reason) is possible before a document is superseded

- Created by document controllers (duty) or reviewers on the unit; each gets the next number.
- Files are uploaded while the document is a draft. Approval is by the named approver or a
  document controller, never by the owner or the last uploader; the approved version is recorded.
- After approval the document cannot change: **Start revision** creates revision *n + 1* (same
  number) as a draft; when it becomes effective, the previous revision is superseded.
- Making a document effective sets its review date from the type's interval; owners get
  due-soon and overdue review notices from the daily reminder job.

### Evidence

Any record's *Linked records* panel has **Attach evidence file**. The file becomes a document
under the record's unit and the record is linked to that **exact version**. Replacing the file adds
a version and a new pinned link; the earlier one stays. Evidence on a progress update satisfies
the "evidence required" data-quality check.

### Uploads, storage and access

- The extension must be allowed for the type **and** the content must really be that kind of file
  (PDF header, Office package structure, image signature, text without binary or HTML); renamed
  executables and scripts are refused. Size is limited by `UPLOAD_LIMIT_MB`.
- Files go to the append-only file store with an app-generated name and their SHA-256; every
  download re-checks the fingerprint and is written to the audit trail.
- Unit scope applies to documents, versions, downloads and search. Classification narrows it:
  *confidential* needs the reviewer role on the unit; *restricted* is limited to the named owner and
  approver and document controllers. The people named on a document always see it.

### Search

Text is extracted from PDF (pypdf), Word, Excel, CSV and text files for full-text search (SQLite
FTS5; PostgreSQL full-text search at query time). If extraction fails the upload still succeeds,
the failure is shown on the version, and the file is untouched. Scanned PDFs have no text (OCR is
not included). Results and snippets only ever come from documents the reader may open.

Retention schedules, legal holds and disposal are **not** automated in this release: they need
each utility's approved records schedule first.

---

## 6. Governance and risk

**Pages:** Meetings & Resolutions · Audit Findings · Risk Register. **API:** `/api/governance/*`.
The Board menu's Risk Register, Audit Findings and Board Resolutions entries open the same pages.

### Meetings and resolutions (board secretary duty)

    meeting:    scheduled → held → minutes approved (the minutes document must be attached)
    resolution: open ─implement (owner, note)→ implemented ─close (secretary, not the owner)→ closed
                open ─cancel (reason)→ cancelled;  reopen (reason) from implemented or closed

Resolutions are numbered per body and year (e.g. `B/2026/001`). A resolution with an owner creates
an owned, dated action linked back to it.

### Audit findings — auditor and management kept apart

    open ─respond (management)→ response submitted ─accept (auditor)→ agreed
          ↑─────────── reject response (auditor, reason) ───────────┘
    agreed ─request closure (management, note)→ closure requested ─validate (auditor)→ closed
             ↑──────────── reject closure (auditor, reason) ─────────────┘
    closed ─reopen (auditor, reason)→ agreed

- Only people holding the **auditor** duty (granted explicitly; administrators do not act as
  auditors) raise, rate and edit findings, accept responses and validate closure.
- Only **management** — the named owner or an approver on the unit — responds (with an agreed
  date) and asks for closure. Someone holding the auditor duty can never do that, and the owner can
  never validate.
- Accepting the response creates the follow-up action; a finding cannot be closed while any of its
  actions is still open. Ratings: critical, high, medium, low.

### Risk register

- **Criteria are the organisation's own.** A risk manager defines a matrix: likelihood and impact
  scales of any size (2–10 levels each, with your own labels), score bands (likelihood × impact) and
  the appetite of each band (within, tolerance, outside). Templates are offered as starting points
  only; nothing assumes a 5×5 grid and MadziHub makes no ISO 31000 certification claim. A matrix
  with rated risks cannot be edited: create a new one and activate it.
- Risks carry owner, unit, category, cause, consequence, review date, inherent and residual ratings
  (every re-rating is kept in an append-only history with its reason), controls with their
  effectiveness, **treatments as actions**, and links to the plan objectives they affect.
- Owners are reminded of due and overdue reviews. Open risks outside appetite appear in exception
  reports; the principal risks appear in the board pack.

---

## 7. Regulator packs, returns and league tables

**Page:** Regulatory. **API:** `/api/regulatory/*`. **Pack files:** `tenants/_packs/regulators/`
(format and verification rules in that folder's README).

- A regulator's method is a **versioned, source-cited pack**. Regulatory officers (duty) import a
  pack file as a draft, fill and verify its figures against the cited report (every edit needs a
  reason and is audited), and a **second** regulatory officer approves it. Approval is refused
  while anything is unverified or missing, and retires the previous approved version for that cycle.
- **Returns** use an approved pack. Raw values are kept as entered, with their source (manual or a
  catalogue measure for the fiscal year), in an append-only history; each value is checked against
  the pack's validation rules. A submitted return is final. Returns export to Excel in the pack's
  template.
- **League tables** score the utility and the peer values you enter on the same approved pack and
  are saved with their inputs and fingerprints. Only a **submitted** return can supply the
  utility's own values (a draft's values can still change). They are MadziHub comparisons for management use,
  **never presented as an official regulator ranking**, and an internal plan score is never
  presented as a regulator score.
- **Shipped drafts (not approved):** WASREB IMPACT 17 (FY 2023/24) and EWURA FY 2023/24. Their
  structure was verified from the reports; their numbers could not be read reliably from the PDF
  text and are left empty for a reviewer to fill from the cited tables. NWASCO and IBNET packs are
  deliberately not shipped until their sources are verified.

---

## 8. Performance contracts and staff appraisal

**Page:** Contracts & Appraisals. **API:** `/api/people/*`.

- **Gated.** Each module stays off until an HR officer records the organisation's *approved* HR
  policy for it (policy reference, audited), and it can be switched off entirely with
  `modules.performance_contracts: false` / `modules.staff_appraisal: false` in `tenant.yaml`.
- **Private.** A contract or appraisal is visible only to the people named on it and to HR
  officers. The HR officer duty must be granted explicitly; administrators do not hold it, and unit
  approvers do not see appraisals. These records never appear in the general audit trail.
- **Contracts** (HR officer drafts; holder signs; supervisor countersigns and evaluates): items are
  plan indicators with weights summing to 100, scored on the signed-off scoring scheme from
  published values and targets; the evaluation is frozen on the contract. The holder accepts or
  appeals; an HR officer who is not party to the contract decides, optionally adjusting the rating.
  An adjusted rating must lie within the rating range of the scheme the contract was evaluated on,
  and its label is re-derived from that scheme's bands.
- **Appraisals** (HR officer or appraiser sets objectives with weights summing to 100): the employee
  agrees and self-assesses, the appraiser appraises (overall = weighted mean, on a stated 1–5 scale
  where 5 is best), the employee acknowledges or appeals, an uninvolved HR officer decides. After
  closure an HR officer can correct the rating with a reason; every step, before and after, stays in
  the record's history.
- No country-specific contract method is implemented. A Kenya performance-contract adapter will
  only be added when it can reproduce the exact current rules and indicator-specific exceptions.
