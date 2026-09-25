"""
Position: where we were, where we are, where we are going, for one measure and unit.

Published value rule. When several sources report the same measure, unit and
period, the source with the lowest ``priority`` wins. The others remain in
``metric_values`` for reconciliation (see ``reconciliation``).

Roll-up rules.
- Across the organisation: a unit with no value of its own gets the total of its
  leaf units, for ``sum`` measures only.
- Across time: quarters and fiscal years are built from monthly values using
  each measure's aggregation, with ``months_reporting`` so a year-to-date figure
  is never mistaken for a full year.
- Ratios are formula measures, computed from their rolled-up components at
  every level. Averages of ratios are never taken.
"""
from __future__ import annotations

import calendar
from collections import defaultdict
from datetime import date, datetime

from sqlalchemy.orm import Session

from app.integration import formulas
from app.integration.mapping import period_start
from app.integration.models import DataSource, Metric, MetricTarget, MetricValue, OrgUnit


def descendants(db: Session, code: str) -> list[str]:
    units = db.query(OrgUnit.id, OrgUnit.code, OrgUnit.parent_id).all()
    children = defaultdict(list)
    ids = {}
    for uid, ucode, parent in units:
        children[parent].append((uid, ucode))
        ids[ucode] = uid
    if code not in ids:
        return []
    out, stack = [], [ids[code]]
    while stack:
        for cid, ccode in children.get(stack.pop(), []):
            out.append(ccode)
            stack.append(cid)
    return out


def _stored_series(db: Session, metric: Metric, org_code: str, period_type: str) -> tuple[list[dict], bool]:
    """Loaded values at one grain: the unit's own, else the sum of its leaf units. Returns (series, rolled_up)."""
    priorities = {s.id: (s.priority, s.code, s.name) for s in db.query(DataSource)}

    def best(units: list[str]) -> dict[tuple[str, date], MetricValue]:
        q = db.query(MetricValue).filter(MetricValue.metric_code == metric.code,
                                         MetricValue.period_type == period_type,
                                         MetricValue.org_unit_code.in_(units),
                                         MetricValue.value.isnot(None))
        chosen: dict[tuple[str, date], MetricValue] = {}
        for mv in q:
            key = (mv.org_unit_code, mv.period_start)
            cur = chosen.get(key)
            if cur is None or priorities[mv.source_id][0] < priorities[cur.source_id][0]:
                chosen[key] = mv
        return chosen

    own = best([org_code])
    if own:
        series = [{"period": p.isoformat(), "value": mv.value, "source": priorities[mv.source_id][1],
                   "source_ref": mv.source_ref, "loaded_at": mv.loaded_at.isoformat() if mv.loaded_at else None}
                  for (_, p), mv in sorted(own.items(), key=lambda kv: kv[0][1])]
        return series, False

    if metric.aggregation != "sum":
        return [], False
    kids = descendants(db, org_code)
    if not kids:
        return [], False
    # Only leaf-level values are added, so a zone total and its schemes are never double counted.
    parents_with_children = {p for (p,) in db.query(OrgUnit.parent_id).filter(OrgUnit.parent_id.isnot(None))}
    leaf_codes = {u.code for u in db.query(OrgUnit).filter(OrgUnit.code.in_(kids))
                  if u.id not in parents_with_children}
    totals: dict[date, dict] = {}
    for (_, p), mv in best(sorted(leaf_codes)).items():
        t = totals.setdefault(p, {"value": 0.0, "units": 0, "sources": set(), "loaded_at": None})
        t["value"] += mv.value
        t["units"] += 1
        t["sources"].add(priorities[mv.source_id][1])
        if mv.loaded_at and (t["loaded_at"] is None or mv.loaded_at > t["loaded_at"]):
            t["loaded_at"] = mv.loaded_at
    series = [{"period": p.isoformat(), "value": t["value"], "source": ",".join(sorted(t["sources"])),
               "units_reporting": t["units"], "units_expected": len(leaf_codes),
               "loaded_at": t["loaded_at"].isoformat() if t["loaded_at"] else None}
              for p, t in sorted(totals.items())]
    return series, True


_MONTHS_IN = {"quarter": 3, "year": 12}


def _aggregate_in_time(monthly: list[dict], aggregation: str, period_type: str) -> list[dict]:
    """Monthly series → quarters or fiscal years, with how many months reported."""
    groups: dict[date, list[dict]] = defaultdict(list)
    for item in monthly:
        groups[period_start(date.fromisoformat(item["period"]), period_type)].append(item)
    out = []
    for p, items in sorted(groups.items()):
        nums = [i["value"] for i in items]
        if aggregation == "sum":
            value = sum(nums)
        elif aggregation == "avg":
            # Time-weighted: each month counts by its days, so February does not weigh as much
            # as March. Observation counts are not stored; a measure that needs observation
            # weighting should be a formula over two sum measures (total / count).
            days = [calendar.monthrange(*date.fromisoformat(i["period"]).timetuple()[:2])[1] for i in items]
            value = sum(v * d for v, d in zip(nums, days)) / sum(days)
        elif aggregation == "max":
            value = max(nums)
        elif aggregation == "min":
            value = min(nums)
        else:  # last: the latest month in the period
            value = max(items, key=lambda i: i["period"])["value"]
        loaded = [i["loaded_at"] for i in items if i.get("loaded_at")]
        item = {"period": p.isoformat(), "value": value,
                "source": ",".join(sorted({s for i in items for s in str(i["source"]).split(",")})),
                "months_reporting": len(items), "months_expected": _MONTHS_IN[period_type],
                "loaded_at": max(loaded) if loaded else None}
        if aggregation == "avg":
            item["time_weighting"] = "days_in_month"
        out.append(item)
    return out


def _formula_series(db: Session, metric: Metric, org_code: str, period_type: str,
                    stack: tuple[str, ...]) -> tuple[list[dict], bool]:
    refs = sorted(formulas.references(metric.formula))
    catalogue = {m.code: m for m in db.query(Metric).filter(Metric.code.in_(refs))}
    if not refs or set(refs) - set(catalogue) or set(refs) & set(stack):
        return [], False  # invalid or circular: validated on save, guarded here too
    comps: dict[str, dict[str, dict]] = {}
    rolled = False
    for code in refs:
        series, info = _series(db, catalogue[code], org_code, period_type, (*stack, metric.code))
        comps[code] = {item["period"]: item for item in series}
        rolled = rolled or info["rolled_up"]
    out = []
    for p in sorted(set.intersection(*(set(c) for c in comps.values()))):
        inputs = {code: comps[code][p]["value"] for code in refs}
        value = formulas.evaluate(metric.formula, inputs)
        if value is None:
            continue  # division by zero: missing, not zero
        parts = [comps[code][p] for code in refs]
        item = {"period": p, "value": value, "formula": metric.formula, "inputs": inputs,
                "source": ",".join(sorted({s for i in parts for s in str(i["source"]).split(",")})),
                "loaded_at": max((i["loaded_at"] for i in parts if i.get("loaded_at")), default=None)}
        reporting = [i["months_reporting"] for i in parts if "months_reporting" in i]
        if reporting:
            item["months_reporting"] = min(reporting)
            item["months_expected"] = _MONTHS_IN[period_type]
        out.append(item)
    return out, rolled


def _series(db: Session, metric: Metric, org_code: str, period_type: str,
            stack: tuple[str, ...] = ()) -> tuple[list[dict], dict]:
    if metric.formula:
        series, rolled = _formula_series(db, metric, org_code, period_type, stack)
        return series, {"rolled_up": rolled, "derived": "formula"}
    series, rolled = _stored_series(db, metric, org_code, period_type)
    if not series and period_type in _MONTHS_IN:
        monthly, rolled = _stored_series(db, metric, org_code, "month")
        return _aggregate_in_time(monthly, metric.aggregation, period_type), {"rolled_up": rolled,
                                                                            "derived": "from_month"}
    return series, {"rolled_up": rolled, "derived": None}


def published_series(db: Session, metric: Metric, org_code: str, period_type: str,
                     start: date | None = None, end: date | None = None) -> tuple[list[dict], dict]:
    """Published values by period, with how they were obtained.

    Returns (series, info) where info["rolled_up"] says values were summed from
    child units and info["derived"] is None, "from_month" (quarters/years built
    from monthly values) or "formula".
    """
    series, info = _series(db, metric, org_code, period_type)
    if start:
        series = [s for s in series if s["period"] >= start.isoformat()]
    if end:
        series = [s for s in series if s["period"] <= end.isoformat()]
    return series, info


def _trend(series: list[dict], direction: str, window: int = 3) -> dict | None:
    if len(series) < window * 2:
        return None
    recent = sum(s["value"] for s in series[-window:]) / window
    prior = sum(s["value"] for s in series[-2 * window:-window]) / window
    change = None if prior == 0 else (recent - prior) / abs(prior) * 100
    improving = None
    # Changes under 0.1% are noise (often float rounding), not a direction.
    moved = abs(recent - prior) > 1e-3 * max(abs(prior), abs(recent), 1e-9)
    if direction in ("higher", "lower") and moved:
        improving = (recent > prior) == (direction == "higher")
    return {"window": window, "recent_avg": recent, "prior_avg": prior,
            "change_pct": None if change is None else round(change, 2), "improving": improving}


# Comparator types a target row can carry, kept distinct: a plan target is never read as a
# regulatory benchmark or a budget figure. The strategic plan is the primary comparator.
BASIS_LABELS = {"strategic_plan": "Strategic plan target", "budget": "Budget",
                "regulator": "Regulatory target", "internal": "Internal target"}
PRIMARY_BASIS = "strategic_plan"


def _comparator(t: MetricTarget, metric: Metric, org_code: str, plans: dict[int, str]) -> dict:
    """A target with its provenance: type, source, unit, scope, period and version."""
    return {"period": t.period_start.isoformat(), "period_type": t.period_type, "value": t.value,
            "lower": t.lower, "upper": t.upper, "basis": t.basis, "note": t.note,
            "comparator": {"type": t.basis, "label": BASIS_LABELS.get(t.basis, t.basis),
                           "source": plans.get(t.plan_id) or "Entered in Data Sources → Targets",
                           "unit": metric.unit, "org_unit": org_code,
                           "period": t.period_start.isoformat(), "period_type": t.period_type,
                           "version": f"target #{t.id}"
                                      + (f", updated {t.updated_at.date().isoformat()}" if t.updated_at else "")}}


def _gap(metric: Metric, current: dict, tgt: dict) -> dict:
    diff = current["value"] - tgt["value"]
    on_track = None
    if metric.direction == "higher":
        on_track = diff >= 0
    elif metric.direction == "lower":
        on_track = diff <= 0
    elif tgt["lower"] is not None and tgt["upper"] is not None:
        on_track = tgt["lower"] <= current["value"] <= tgt["upper"]
    complete = current.get("months_reporting", 0) >= current.get("months_expected", 0)
    note = None
    if not complete and metric.aggregation == "sum":
        # A year-to-date total against a full-year target is not a verdict. For a formula,
        # aggregation declares its period meaning: "sum" accumulates over the period
        # (e.g. produced - billed), anything else is a ratio comparable at any point.
        on_track = None
        note = (f"{current['months_reporting']} of {current['months_expected']} months reported; "
                "total is year-to-date")
    return {"target_period": tgt["period"], "target": tgt["value"], "actual": current["value"],
            "difference": diff, "on_track": on_track, "basis": tgt["basis"],
            "period_complete": complete, "note": note, "comparator": tgt["comparator"]}


def position(db: Session, metric: Metric, org_code: str, period_type: str = "month",
             start: date | None = None, end: date | None = None) -> dict:
    from app.modules.strategy.models import Plan

    series, info = published_series(db, metric, org_code, period_type, start, end)
    plans = {p.id: f"{p.code}: {p.title}" for p in db.query(Plan)}
    targets = [
        _comparator(t, metric, org_code, plans)
        for t in db.query(MetricTarget).filter(MetricTarget.metric_code == metric.code,
                                              MetricTarget.org_unit_code == org_code)
                                       .order_by(MetricTarget.period_start, MetricTarget.basis)
    ]
    current = series[-1] if series else None
    if current and current.get("loaded_at"):
        age = datetime.utcnow() - datetime.fromisoformat(current["loaded_at"])
        current = {**current, "data_age_days": age.days}

    # Only a target for exactly this period and grain assesses it: an earlier period's target is
    # never carried forward silently. Each basis is resolved on its own; the strategic plan is primary.
    gap, other_gaps, target_note = None, [], None
    if current:
        same = [t for t in targets if t["period_type"] == period_type and t["period"] == current["period"]]
        for tgt in same:
            g = _gap(metric, current, tgt)
            if tgt["basis"] == PRIMARY_BASIS:
                gap = g
            else:
                other_gaps.append(g)
        if gap is None:
            earlier = [t for t in targets if t["period_type"] == period_type and t["basis"] == PRIMARY_BASIS
                       and t["period"] < current["period"]]
            target_note = ("No strategic-plan target for this period; not assessed"
                           + (f" (latest target {earlier[-1]['value']:g} is for the period from {earlier[-1]['period']})"
                              if earlier else ""))

    future = [t for t in targets if t["period_type"] == period_type
              and (current is None or t["period"] > current["period"])]
    return {
        "metric": {"code": metric.code, "name": metric.name, "unit": metric.unit,
                   "aggregation": metric.aggregation, "direction": metric.direction,
                   "formula": metric.formula},
        "org_unit": org_code,
        "period_type": period_type,
        "rolled_up": info["rolled_up"],
        "derived": info["derived"],
        "where_we_were": series[:-1],
        "where_we_are": current,
        "where_we_are_going": future,
        "gap_to_target": gap,
        "other_comparators": other_gaps,
        "target_note": target_note,
        "trend": _trend(series, metric.direction),
    }


def reconciliation(db: Session, metric_code: str, org_code: str, period_type: str = "month") -> list[dict]:
    """Periods where two or more sources disagree, largest difference first."""
    names = {s.id: s.code for s in db.query(DataSource)}
    grouped: dict[date, list[MetricValue]] = defaultdict(list)
    for mv in db.query(MetricValue).filter_by(metric_code=metric_code, org_unit_code=org_code,
                                              period_type=period_type):
        if mv.value is not None:
            grouped[mv.period_start].append(mv)
    out = []
    for p, vals in grouped.items():
        if len({round(v.value, 6) for v in vals}) > 1:
            lo, hi = min(v.value for v in vals), max(v.value for v in vals)
            out.append({"period": p.isoformat(), "spread": hi - lo,
                        "values": [{"source": names[v.source_id], "value": v.value, "source_ref": v.source_ref}
                                   for v in vals]})
    return sorted(out, key=lambda r: -r["spread"])


APPROVED_UPDATES_SOURCE = "strategy-updates"   # app.modules.strategy.service.MANUAL_SOURCE


def freshness_state(s: dict) -> str:
    """One explicit state per source, so absence of a problem is never read as "current".

    current       scheduled, and succeeded within twice its interval
    overdue       scheduled, and has not succeeded within twice its interval
    failed        the last run failed
    disabled      switched off
    no_ingestion  enabled but no run has succeeded and no value has ever been received
    not_scheduled receives values without a schedule (uploads, pushes, approved updates):
                  freshness is not judged against a schedule; see last_value_at
    """
    if not s["enabled"]:
        return "disabled"
    if s["last_status"] == "failed":
        return "failed"
    if s["overdue"]:
        return "overdue"
    if not s["values"] and not s["last_success_at"]:
        return "no_ingestion"
    return "current" if s["feed"] == "scheduled" else "not_scheduled"


def freshness(db: Session) -> list[dict]:
    """Per source: when it last ran, last succeeded, and whether it is overdue. Trust starts here."""
    from sqlalchemy import func

    from app.integration.models import SyncRun

    now = datetime.utcnow()
    out = []
    for s in db.query(DataSource).order_by(DataSource.priority, DataSource.code):
        last = db.query(SyncRun).filter_by(source_id=s.id).order_by(SyncRun.id.desc()).first()
        overdue = None
        if s.schedule_minutes and s.enabled:
            ref = s.last_success_at
            overdue = ref is None or (now - ref).total_seconds() > s.schedule_minutes * 60 * 2
        last_value_at = db.query(func.max(MetricValue.loaded_at)).filter(MetricValue.source_id == s.id).scalar()
        feed = ("approved_updates" if s.code == APPROVED_UPDATES_SOURCE
                else "scheduled" if s.schedule_minutes else "unscheduled")
        out.append({
            "code": s.code, "name": s.name, "system_type": s.system_type, "connector": s.connector,
            "enabled": s.enabled, "priority": s.priority, "owner": s.owner,
            "last_run_at": s.last_run_at.isoformat() if s.last_run_at else None,
            "last_success_at": s.last_success_at.isoformat() if s.last_success_at else None,
            "last_status": last.status if last else None,
            "last_error": last.error if last and last.status == "failed" else None,
            "overdue": overdue,
            "values": db.query(MetricValue).filter_by(source_id=s.id).count(),
            "feed": feed,
            "last_value_at": last_value_at.isoformat() if last_value_at else None,
        })
        out[-1]["freshness"] = freshness_state(out[-1])
    return out
