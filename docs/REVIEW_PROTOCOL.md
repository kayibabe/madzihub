# MadziHub developer and reviewer protocol

How Claude Code (the developer) and Codex (the reviewer) hand work to each
other on this repository. Both tools read this file; it is the shared contract.

## Roles

- **Claude Code** implements tasks, makes corrections and runs the relevant
  validation. All code changes are made by Claude Code.
- **Codex** reviews the actual changes and evidence, and returns actionable
  findings. Codex does not take over implementation unless the user changes
  the roles.
- **The user** relays handoffs between the tools. There is no automatic
  integration; neither tool claims a handoff or review happened unless it was
  actually received.

## The loop

1. Claude Code implements and validates a task, commits it, and writes a
   **developer handoff**.
2. Codex reviews that commit and writes a **review**.
3. Claude Code responds to every finding (fix, or dispute with evidence),
   commits, and writes a new developer handoff for the next round.
4. Repeat until the **consensus** conditions below are met.

## Where handoffs live

One file per task in `docs/reviews/`, named `YYYY-MM-DD-<task-slug>.md`.
Rounds are appended to the same file, newest at the bottom, so the full
history of a task stays in one place and is committed with the code.
The user can also paste a handoff directly between tools; if so, it should
still be appended to the task file afterwards.

## Developer handoff (Claude Code to Codex)

```markdown
## Round N: developer handoff

- **Task:** one-line description and link to the requirement or slice.
- **Branch / commit:** `branch-name` at `abc1234` (range `base..abc1234` if several).
- **Files changed:** list, with one line on why each changed.
- **Acceptance criteria:** the checklist this round claims to meet.
- **Validation:** commands run and actual results (pass/fail counts, build
  output, screenshots). Label each item Verified / Inferred / Simulated / Untested.
- **Responses to previous findings:** (rounds 2+) one line per finding ID:
  Fixed in `commit`, or Disputed with the evidence.
- **Known limitations:** anything unfinished, deferred or out of scope.
- **Questions for the reviewer:** specific areas to scrutinise.
```

## Review (Codex to Claude Code)

```markdown
## Round N: review

- **Reviewed:** `branch-name` at `abc1234`.
- **Verdict:** Changes requested / Approved with minor findings / Approved.

| ID | Severity | Location | Issue | Suggested fix |
|----|----------|----------|-------|---------------|
| CR-01 | High | `path/file.ts:42` | What is wrong and how it fails | What to change |

- **Status of previous findings:** (rounds 2+) one line per ID:
  Resolved / Still open (why) / Dispute accepted.
- **Checked and fine:** areas reviewed with no findings, so coverage is visible.
```

### Finding IDs and severity

- IDs are `CR-01`, `CR-02`, ... numbered per task and never reused or
  renumbered across rounds. A new issue found in round 3 gets the next free
  number.
- Severity:
  - **High:** incorrect behaviour, data loss or corruption, security or
    privacy exposure, broken user journey. Blocks consensus.
  - **Medium:** real defect or requirement gap with a workaround, missing
    validation or test for changed behaviour. Blocks consensus.
  - **Low:** maintainability, clarity or minor UX polish. Does not block;
    may be deferred with a recorded reason.

### Finding statuses

Each finding is in exactly one state:

| Status | Set by | Meaning |
|--------|--------|---------|
| Open | Codex | Raised, not yet addressed |
| Fixed | Claude Code | Change made; cites the commit |
| Disputed | Claude Code | Not changed; cites evidence why the finding is wrong |
| Resolved | Codex | Fix verified, or dispute accepted |
| Deferred | Both | Agreed to leave for later; reason and follow-up recorded |

## Consensus

A task is complete only when all of these hold:

- Codex's latest verdict is **Approved** or **Approved with minor findings**.
- Every High and Medium finding is **Resolved**.
- Every Low finding is Resolved or Deferred with a recorded reason.
- The approved commit is the commit being delivered (no unreviewed changes
  after approval).

Agreement is grounded in the reviewed commit and its evidence; it is not
proof by itself. Any remaining limitation or unresolved disagreement is
written in the task file, and the user decides disagreements the two tools
cannot settle after two rounds on the same finding.
