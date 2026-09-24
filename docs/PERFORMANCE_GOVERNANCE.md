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
