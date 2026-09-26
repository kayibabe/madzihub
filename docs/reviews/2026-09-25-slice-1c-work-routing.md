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

---

## Round 1: review

- **Reviewed:** `codex-review-fixes` at `0ba0f7f` (range `620ef46..0ba0f7f`).
- **Verdict:** Changes requested.

| ID | Severity | Location | Issue | Suggested fix |
|----|----------|----------|-------|---------------|
| CR-01 | Medium | `app/platform/router.py:93`; `app/static/assets/js/mod-strategy.js:398` | The cycle detail renders the **People** control for anyone with the `strategy_manager` duty, but its `assignable-users` request requires that caller to have the contributor role on the assignment unit. A strategy manager who can manage a cycle but is a viewer on that unit therefore receives 403 and cannot correct the routing the feature identifies as unsafe. The current fixture gives the planner sufficient unit role, so it does not cover this boundary. | Authorize this endpoint for a strategy manager who can see the unit, while retaining the contributor requirement for ordinary callers, or use a dedicated manager-only endpoint. Add a regression for a strategy manager with viewer scope who can open the People dialog and save a valid reassignment. |
| CR-02 | Low | `app/platform/scope.py:193-206` | `closest_holders()` does not distinguish a direct unit grant from a parent-unit grant: after scope expansion, both are only `org_wide=False` and the same role rank. It then notifies every username in that tie. This is a workable broadcast fallback, but it is not the documented "closest" ordering and can produce a large request fan-out. | Either preserve enough grant-origin/distance information to select the nearest group, or document the current non-org-wide, lowest-role broadcast rule and record why notifying all ties is intended. |

---

## Round 2: developer response

- **Branch / commit:** `codex-review-fixes` at HEAD (after `0ba0f7f`).

| ID | Fix applied |
|----|-------------|
| CR-01 | `app/platform/router.py`: `assignable_users` now accepts callers with `strategy_manager` duty who can see the unit (`require_see`), while ordinary callers still require contributor. Regression added: `RoutingTests.test_strategy_manager_with_viewer_scope_can_read_assignable_users_and_reassign` — creates a `strategy_manager` with viewer-only scope on north, asserts 200 from `assignable-users`, asserts the reassignment PUT succeeds, and asserts a plain viewer still gets 403. |
| CR-02 | `app/platform/scope.py`: `closest_holders` docstring now documents the actual broadcast semantics — scope expansion makes direct-unit and parent-unit grants indistinguishable; all ties in the nearest (org_wide, role_rank) tier are notified intentionally; a manager who needs a single accountable actor should name them in the People dialog. No code change: the current behaviour is correct. |

### Validation

**Tests** — Verified

```
python -m pytest tests/test_strategy_me.py tests/test_reporting.py tests/test_populated_year.py -x -q
42 passed, 3708 warnings in 283.33s
```

Breakdown: 41 tests from Round 1 + 1 new `test_strategy_manager_with_viewer_scope_can_read_assignable_users_and_reassign`.

- **Checked and fine:**
  - The submitted commit adds server-side acknowledgement enforcement before a failing update is persisted; the client is advisory and the server remains authoritative.
  - Hand-off notices are resolved on the next state transition, and report approval work is derived from each caller's allowed actions, so a listed report is actionable for that caller.
  - `submissions_contract` is included in the data returned by `builders.freeze()` and therefore is part of the frozen report blob and its data hash. A column is not needed for this rendering contract unless reports must be queried or migrated by contract version.
  - `resolve()` closing every unread request of a completed step is appropriate for an entity-level workflow: a return/approval makes all earlier requests for that step obsolete. Resubmission creates a fresh request.
  - The People endpoint is requested when the **People** action opens, not when cycle detail first loads. The premise of question 4 is therefore false; client caching is unnecessary for this slice. It could be added later only if telemetry shows repeated dialog opens are costly.
  - `closest_holders()` should not introduce an arbitrary single-person tie-break. When a single accountable actor is required, a manager should name that actor in the People dialog; CR-02 covers making the fallback semantics exact.
  - **Verified:** `git diff --check 620ef46..0ba0f7f`; Python byte-compilation of the changed Python modules; `node --check` for the three changed JavaScript modules. The checkout has only documentation changes after `0ba0f7f`, so these static checks exercised the reviewed code.
  - **Developer-reported, not rerun in this review:** focused pytest suite, 41 passed; isolated browser QA.
