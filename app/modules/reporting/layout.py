"""
Turn frozen report data into a neutral document: a list of blocks that every renderer
(HTML, PDF, XLSX) draws the same way. Pure function of (meta, data, commentary).

Blocks:
  {"t": "h", "level": 1|2, "text": str}
  {"t": "p", "text": str, "tone": "normal"|"note"|"warn"}
  {"t": "kv", "items": [[label, value], ...]}
  {"t": "table", "caption": str, "columns": [str], "rows": [[str]], "num": [col index]}
"""
from __future__ import annotations

COMMENTARY_SECTIONS = {
    "board_pack": [("summary", "Executive summary"), ("decisions", "Decisions required from the board")],
    "scorecard_detail": [("summary", "Commentary")],
    "submission_dq": [("summary", "Commentary on completeness and data quality")],
    "exceptions": [("summary", "Management commentary")],
}


def _n(v, dp: int = 2) -> str:
    if v is None or v == "":
        return "—"
    try:
        f = float(v)
    except (TypeError, ValueError):
        return str(v)
    return f"{f:,.{dp}f}".rstrip("0").rstrip(".") if dp else f"{f:,.0f}"


def _pct(v) -> str:
    return "—" if v is None else f"{_n(v, 1)}%"


def _label(s) -> str:
    t = str(s or "—").replace("_", " ")
    return t[:1].upper() + t[1:]


def _commentary(kind: str, commentary: dict, which: str) -> list[dict]:
    out = []
    for key, title in COMMENTARY_SECTIONS.get(kind, []):
        if key != which:
            continue
        text = (commentary or {}).get(key)
        out += [{"t": "h", "level": 2, "text": title},
                {"t": "p", "text": text or "No commentary recorded.", "tone": "normal" if text else "note"}]
    return out


def _score_blocks(data: dict, full: bool) -> list[dict]:
    score = data.get("score")
    if not score:
        return []
    blocks: list[dict] = [{"t": "h", "level": 2, "text": "Scorecard"}]
    src = score["source"]
    if not src["approved"]:
        blocks.append({"t": "p", "tone": "warn", "text": "Not approved: no approved score snapshot exists for this "
                                                          "plan, period and unit. Figures are a live calculation."})
    sch = score["scheme"]
    root = score["root"]
    ov = root.get("override")
    if ov and root["status"] not in ("complete", "partial"):
        blocks.append({"t": "p", "tone": "warn", "text": f"Exception: the calculated score is {_label(root['status'])}, "
                                                          "so the overall rating below is a recorded override."})
    blocks.append({"t": "kv", "items": [
        ["Overall rating", "—" if root["rating"] is None else f"{_n(root['rating'])} · {root['rating_label']}"],
        *([["Rating override", f"{ov['reason']} (by {ov.get('by')}; calculated "
                               f"{'—' if root.get('calculated_rating') is None else _n(root['calculated_rating'])})"]]
          if ov else []),
        ["Weighted achievement", _pct(root["achievement"])],
        ["Status", f"{_label(root['status'])} — {root.get('method') or ''}"],
        ["Scheme", f"{sch['code']} v{sch['version']} ({_label(sch['status'])}); ratings "
                   f"{'higher' if sch['rating_order'] == 'higher_is_better' else 'lower'} is better; cap {_n(sch['cap_pct'])}%"],
        ["Score source", f"Approved snapshot #{src['snapshot_id']} (approved by {src.get('approved_by')})"
                         if src["approved"] else "Live calculation (unapproved)"]]})
    rows = score["rows"] if full else [r for r in score["rows"] if r["type"] == "node" and r["depth"] <= 1]
    blocks.append({"t": "table", "caption": "Performance by item" if full else "Strategy status by pillar and objective",
                   "columns": ["Item", "Weight", "Actual", "Target", "Achievement", "Rating", "Completeness"],
                   "num": [1, 2, 3, 4],
                   "rows": [["  " * r["depth"] + f"{r['code']} {r['title']}" + (" (override)" if r["override"] else ""),
                             "—" if r["weight"] is None else f"{_n(r['weight'], 1)}%",
                             "" if r["type"] == "node" else _n(r["actual"]),
                             "" if r["type"] == "node" else _n(r["target"]),
                             _pct(r["achievement"]),
                             "—" if r["rating"] is None else f"{_n(r['rating'])} {r['rating_label'] or ''}".strip(),
                             _label(r["status"])] for r in rows]})
    return blocks


def _trend_blocks(data: dict) -> list[dict]:
    trend = data.get("trend") or []
    if not trend:
        return [{"t": "h", "level": 2, "text": "Trend"}, {"t": "p", "tone": "note", "text": "No approved scores for earlier periods."}]
    return [{"t": "h", "level": 2, "text": "Trend"},
            {"t": "table", "caption": "Approved scores by period", "columns": ["Period", "Rating", "Achievement", "Completeness"],
             "num": [1, 2, 3], "rows": [[t["period"], f"{_n(t['rating'])} {t['rating_label'] or ''}".strip(),
                                         _pct(t["achievement"]), _pct(t["completeness_pct"])] for t in trend]}]


def _submission_rows(subs: list[dict], names: dict) -> list[list[str]]:
    return [[s["indicator"], names.get(s["org_unit_code"], s["org_unit_code"]), _label(s["status"]),
             (_n(s["value"]) if s["value_state"] == "reported" else _label(s["value_state"] or "no submission")),
             _n(s["target"]), "Yes" if s["late"] else "", str(len(s["dq_fails"])), str(len(s["dq_warns"]))] for s in subs]


def _variance_blocks(data: dict) -> list[dict]:
    subs = [s for s in data.get("submissions", []) if s["off_target"]]
    names = data.get("unit_names", {})
    if not subs:
        return [{"t": "h", "level": 2, "text": "Variance commentary"}, {"t": "p", "tone": "note", "text": "No submitted indicator is off target."}]
    return [{"t": "h", "level": 2, "text": "Variance commentary"},
            {"t": "table", "caption": "Indicators off target, with the submitter's explanation",
             "columns": ["Indicator", "Unit", "Value", "Target", "Variance reason", "Corrective action"], "num": [2, 3],
             "rows": [[s["indicator"], names.get(s["org_unit_code"], s["org_unit_code"]), _n(s["value"]), _n(s["target"]),
                       s["variance_reason"] or "Not explained", s["corrective_action"] or "—"] for s in subs]}]


def _action_blocks(data: dict, overdue_only: bool) -> list[dict]:
    acts = [a for a in data.get("actions", []) if a["overdue"] or not overdue_only]
    names = data.get("unit_names", {})
    title = "Overdue actions" if overdue_only else "Open actions"
    if not acts:
        return [{"t": "h", "level": 2, "text": title}, {"t": "p", "tone": "note", "text": "None."}]
    return [{"t": "h", "level": 2, "text": title},
            {"t": "table", "caption": title, "columns": ["Ref", "Action", "Owner", "Unit", "Due", "Status"], "num": [],
             "rows": [[a["ref"], a["title"], a["owner"], names.get(a["org_unit_code"], a["org_unit_code"]),
                       a["due_date"] or "—", _label(a["status"])] for a in acts]}]


def _risk_blocks(data: dict) -> list[dict]:
    risks = data.get("risks")
    if risks is None:
        return []
    if not risks:
        return [{"t": "h", "level": 2, "text": "Principal risks"}, {"t": "p", "tone": "note", "text": "No open risks recorded."}]
    return [{"t": "h", "level": 2, "text": "Principal risks"},
            {"t": "table", "caption": "Open risks by residual rating", "columns": ["Risk", "Owner", "Inherent", "Residual", "Appetite", "Review due"],
             "num": [], "rows": [[r["title"], r.get("owner") or "—", r.get("inherent") or "—", r.get("residual") or "—",
                                  r.get("appetite") or "—", r.get("review_date") or "—"] for r in risks]}]


def build(meta: dict, data: dict, commentary: dict | None) -> list[dict]:
    kind = data["kind"]
    commentary = commentary or {}
    blocks: list[dict] = [{"t": "h", "level": 1, "text": meta["title"]}]
    if meta["status"] not in ("approved", "published"):
        blocks.append({"t": "p", "tone": "warn", "text": f"{_label(meta['status'])} — not approved for distribution."})
    blocks.append({"t": "kv", "items": [
        ["Organisation", meta.get("organisation") or "—"], ["Unit", data["unit"]["name"]],
        ["Period", f"{data['period']['label']} ({data['period']['start']} to {data['period']['end']})"],
        *([["Plan", f"{data['plan']['code']} {data['plan']['title']}"]] if data.get("plan") else []),
        ["Audience", _label(meta.get("audience"))], ["Template", f"{meta['template']} v{meta['template_version']}"],
        ["Data frozen", f"{data['frozen_at']} UTC (version {meta['data_version']}, fingerprint {meta['data_hash'][:12]})"],
        ["Status", _label(meta["status"]) + (f", approved by {meta['approved_by']} on {meta['approved_at'][:10]}"
                                              if meta.get("approved_by") and meta.get("approved_at") else "")]]})
    if kind == "board_pack":
        blocks += _commentary(kind, commentary, "summary")
        blocks += _score_blocks(data, full=False) + _trend_blocks(data) + _variance_blocks(data) + _risk_blocks(data)
        blocks += _commentary(kind, commentary, "decisions") + _action_blocks(data, overdue_only=True)
    elif kind == "scorecard_detail":
        blocks += _score_blocks(data, full=True) + _trend_blocks(data) + _commentary(kind, commentary, "summary")
    elif kind == "submission_dq":
        subs = data.get("submissions", [])
        states = {}
        for s in subs:
            states[s["status"]] = states.get(s["status"], 0) + 1
        blocks += [{"t": "h", "level": 2, "text": "Completeness"},
                   {"t": "kv", "items": [["Assignments", str(len(subs))]] + [[_label(k), str(v)] for k, v in sorted(states.items())]
                    + [["Submitted late", str(sum(1 for s in subs if s["late"]))],
                       ["Overdue (no submission)", str(sum(1 for s in subs if s["overdue"]))]]},
                   {"t": "h", "level": 2, "text": "Submissions"},
                   {"t": "table", "caption": "Every assignment in the period", "num": [3, 4, 6, 7],
                    "columns": ["Indicator", "Unit", "Status", "Value", "Target", "Late", "DQ fails", "DQ warnings"],
                    "rows": _submission_rows(subs, data.get("unit_names", {}))}]
        issues = [[s["indicator"], data["unit_names"].get(s["org_unit_code"], s["org_unit_code"]), "Fail", x] for s in subs for x in s["dq_fails"]]
        issues += [[s["indicator"], data["unit_names"].get(s["org_unit_code"], s["org_unit_code"]), "Warning", x] for s in subs for x in s["dq_warns"]]
        blocks += [{"t": "h", "level": 2, "text": "Data-quality findings"},
                   {"t": "table", "caption": "Recorded checks (values are never adjusted)", "columns": ["Indicator", "Unit", "Result", "Finding"],
                    "num": [], "rows": issues} if issues else {"t": "p", "tone": "note", "text": "No failed or flagged checks."}]
        blocks += _commentary(kind, commentary, "summary")
    elif kind == "exceptions":
        subs = data.get("submissions", [])
        names = data.get("unit_names", {})
        blocks += _commentary(kind, commentary, "summary") + _variance_blocks(data)
        missing = [s for s in subs if s["status"] in ("not_submitted", "returned")]
        blocks += [{"t": "h", "level": 2, "text": "Missing submissions"},
                   {"t": "table", "caption": "Not submitted or returned", "columns": ["Indicator", "Unit", "Status", "Due", "Overdue"],
                    "num": [], "rows": [[s["indicator"], names.get(s["org_unit_code"], s["org_unit_code"]), _label(s["status"]),
                                         s["due_on"] or "—", "Yes" if s["overdue"] else ""] for s in missing]}
                   if missing else {"t": "p", "tone": "note", "text": "Every assignment has a submission."}]
        evid = [s for s in subs if any(f.startswith("evidence") for f in s["dq_fails"])]
        blocks += [{"t": "h", "level": 2, "text": "Missing evidence"},
                   {"t": "table", "caption": "Submissions without required evidence", "columns": ["Indicator", "Unit", "Revision"],
                    "num": [2], "rows": [[s["indicator"], names.get(s["org_unit_code"], s["org_unit_code"]), str(s["revision"])] for s in evid]}
                   if evid else {"t": "p", "tone": "note", "text": "None."}]
        stale = [s for s in data.get("sources", []) if s["overdue"] or s["last_status"] == "failed"]
        blocks += [{"t": "h", "level": 2, "text": "Stale or failing data sources"},
                   {"t": "table", "caption": "Connected sources that are overdue or failed", "columns": ["Source", "Last success", "Last run"],
                    "num": [], "rows": [[s["name"], s["last_success_at"] or "never", _label(s["last_status"])] for s in stale]}
                   if stale else {"t": "p", "tone": "note", "text": "All connected sources are current."}]
        blocks += _action_blocks(data, overdue_only=True) + _risk_blocks(data)
    return blocks
