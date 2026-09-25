# Slice 1c — Work routing

Task: RJ-01, RJ-02, RJ-03, RJ-04, RJ-05, RJ-08 from the role-journey findings
(`docs/GUI_UX_REVIEW_2026-09-25.md`, Role journeys section).

---

## Round 1: developer handoff

- **Task:** Slice 1c — work routing, hand-off notifications, acknowledgement,
  value labels, period guidance and stale counts. Requirement:
  `docs/GUI_UX_REVIEW_2026-09-25.md` findings RJ-01, RJ-02, RJ-03, RJ-04,
  RJ-05, RJ-08.
- **Branch / commit:** `codex-review-fixes` at `0ba0f7f`
  (range `620ef46..0ba0f7f`).

### Files changed

| File | Why |
|------|-----|
| `app/platform/scope.py` | `user_scopes()` and `closest_holders()` helpers used throughout routing |
| `app/platform/notifications.py` | `resolve()` closes prior notices after the step they requested is done |
| `app/platform/router.py` | `read_only` flag added to `/api/platform/assignable-users` response |
| `app/modules/strategy/service.py` | `People` class; `blocking_failures()`; routing-aware queue, generation, validation, reminders and transitions |
| `app/modules/strategy/router.py` | `acknowledge_checks: bool = False` on `SubmitIn`; passes `People(db)` to `assignment_dict` for managers |
| `app/modules/reporting/service.py` | `approvers()`, `_hand_off()`, `my_work()` provider |
| `app/modules/reporting/router.py` | `MY_WORK_PROVIDERS.append(service.my_work)` |
| `app/modules/reporting/builders.py` | `submissions_contract = 2` frozen into report data |
| `app/modules/reporting/layout.py` | `_UNAPPROVED` dict; `_value(s, contract)` qualifies submitted/returned/verified values |
| `app/static/assets/js/mod-strategy.js` | Queue counts on every `load()`; submit dialog check failures, acknowledgement checkbox; `refreshUnread()` after transitions |
| `app/static/assets/js/mod-reports.js` | "Reports to approve" section; period guidance in New report dialog; `refreshUnread()` after transitions |
| `app/static/assets/js/mod-platform.js` | Badge `aria-label`; `MZ.periodsIntro()`/`MZ.bindPeriodsLink()` shared helpers; `refreshUnread()` in `open-note` handler |
| `app/static/assets/css/mod-platform.css` | `.mz-badge[hidden]{display:none}` specificity fix |
| `scripts/build_review_dataset.py` | `periods.ensure_fiscal_year()` for the populated fiscal year |
| `tests/test_strategy_me.py` | Updated `test_dqa_records_problems_without_changing_values`; added `RoutingTests` class (4 tests) |
| `tests/test_reporting.py` | Added `HandOffAndLabelTests` class (3 tests) |
| `tests/test_populated_year.py` | Period count assertion added to `test_builds_an_isolated_populated_database` |

### Acceptance criteria

- [x] RJ-01: assignments generated for users who can contribute to the unit only; out-of-scope users flagged in the cycle table; People dialog lists only eligible users by role.
- [x] RJ-02: each hand-off notifies the next actor; prior request notices close on completion; reports in review appear in approver My Work.
- [x] RJ-03: form shows failed checks before submit; submission allowed only after ticking an explicit acknowledgement; acknowledgement recorded in audit and DQA; server enforces the flag.
- [x] RJ-04: submitted/returned/verified values shown with a qualifier in governed reports; old approved reports render unmodified.
- [x] RJ-05: New cycle and New report dialogs explain available periods and link to Setup; populated-year dataset has platform periods.
- [x] RJ-08: queue counts refresh after every transition; badge hides when count is 0; badge has accessible name.

### Validation

**Tests** — Verified

```
python -m pytest tests/test_strategy_me.py tests/test_reporting.py tests/test_populated_year.py -x -q
41 passed, 3611 warnings in 280.35s
```

Breakdown: `RoutingTests` (4 new), updated `test_dqa_records_problems_without_changing_values`, `HandOffAndLabelTests` (3 new), period count assertion, all pre-existing tests.

**Browser QA** — Verified against `madzihub-slice1c` isolated dataset (port 8096, FY2026/27 data, commit `0ba0f7f`)

| Finding | What was checked | Result |
|---------|-----------------|--------|
| RJ-01 | People dialog for Q-NRW North: SUBMITS shows contributors + higher roles; VERIFIES excludes contributors; APPROVES shows only approvers. | Correct hierarchical filtering observed. |
| RJ-02 | Created and submitted a south `submission_dq` report as planner; checked south.mgr's unread notifications and My Work via API. | south.mgr received `report_submitted` ("Submitted by planner."); `reports_to_approve` returned the report with `allowed: ["return", "approve"]`; "Reports to approve" section visible on My Work UI. |
| RJ-03 | Submitted Q-NRW South with value=150 (valid range 0–100) and no evidence. | Form showed check-failure banner; Submit was disabled until acknowledgement checkbox was ticked; submission went through; revision showed "Range: fail", "Evidence: fail" chips with "The submitter acknowledged this and submitted anyway." |
| RJ-04 | Fetched HTML output of south `submission_dq` in_review report. | `<td class=num>150 (not yet approved)</td>` in the submissions table; `layout._submission_rows([sub], {})` (no contract) returns bare value; `layout._submission_rows([sub], {}, 2)` returns "30 (returned)". |
| RJ-05 | Opened the New cycle dialog as planner. | "Periods available here: FY2025/26, FY2026/27. To use another fiscal year, first add its periods under Setup › Reporting periods." Visible with an underlined link. |
| RJ-08 | Submitted Q-NRW South from Progress Updates. | "To submit" count went 1 → 0 immediately. Badge: `aria-label="4 unread notices"`, `display:flex` with notices; after `read-all` + `refreshUnread()`: `hidden=true`, `display:none`. |

### Known limitations

- **north.mgr role in the review dataset is reviewer, not approver** — the closest non-author approver for North is `admin`, whose password is a random secret not stored in `accounts.txt`. The RJ-02 browser check was done on south.mgr (south approver) instead. The unit test (`test_report_in_review_reaches_approvers_and_their_my_work`) uses a fixture with a named north approver and is the primary evidence for the North case.
- **RJ-06, RJ-07, RJ-09–RJ-15** are deferred to Slices 2 and 3 as recorded in the review document.
- **No regression on snapshot tests** — the JS/CSS files changed; the project has no snapshot tests for them. The pre-existing Python tests all pass.

### Questions for the reviewer

1. **`closest_holders` tie-breaking:** when two unit-level people have the same role rank, both are returned in sorted-username order and both are notified. Is there a case where this becomes excessive (e.g., a unit with many contributors)?
2. **`resolve()` scope:** the function closes ALL unread notices of the given kinds for the entity, not just the most recent one. If an approver returns, then re-approves after a resubmission, prior `report_submitted` notices from the first submission would already be closed. Is that the right behaviour?
3. **`submissions_contract` in frozen data:** the field is added after `freeze()`, inside `build()`, not in the model. A future migration or schema change won't touch frozen report blobs. Is this the intended durability story, or should `submissions_contract` be a column on `report_instance`?
4. **People dialog `assignable-users` endpoint:** the endpoint is now called per-assignment when the cycle detail loads for a manager, and again when each People dialog opens. For a cycle with many assignments this could be expensive. Is caching at the JS level (one call per unit, shared across the page) worth adding here?
