"""
Scorecard calculation engine: pure functions, no database, no clock.

Three separate things (docs/RESEARCH_BENCHMARK.md §2):
1. achievement(): how an observed value compares with its target, applying polarity.
   The uncapped value is always kept; the capped value (scheme cap, e.g. 130 %) is rated.
2. rate(): achievement → one of the scheme's bands. The bands carry an explicit rating
   number and label; which end is best is stated by the scheme, never inferred.
3. rollup(): weighted combination of children with a coverage gate. Below the gate the
   result is "incomplete" with the covered weight and the missing items. It never
   rescales silently or counts missing data as zero: any re-basing is reported as the
   method used, and "count missing as zero" is an explicit scheme choice.

Any change to these rules must bump ENGINE_VERSION; snapshots record it.
"""
from __future__ import annotations

import hashlib
import json
import math
from dataclasses import asdict, dataclass, field

ENGINE_VERSION = "1.0.0"

POLARITIES = ("higher", "lower", "range", "milestone", "yes_no", "kri")
ZERO_TARGET_RULES = ("unscored", "binary")
LOWER_METHODS = ("linear_deviation", "ratio_inverse")
MISSING_POLICIES = ("coverage_gate", "count_as_zero")
RATING_ORDERS = ("higher_is_better", "lower_is_better")


@dataclass(frozen=True)
class Band:
    rating: int
    label: str
    min_achievement: float            # inclusive
    max_achievement: float | None     # exclusive; None = no upper bound


@dataclass(frozen=True)
class Scheme:
    cap_pct: float = 130.0
    zero_target_rule: str = "unscored"
    lower_method: str = "linear_deviation"
    missing_policy: str = "coverage_gate"
    coverage_gate_pct: float = 80.0
    rating_order: str = "higher_is_better"
    bands: tuple[Band, ...] = ()

    def best_rating(self) -> int:
        ratings = [b.rating for b in self.bands]
        return max(ratings) if self.rating_order == "higher_is_better" else min(ratings)


@dataclass
class Achievement:
    uncapped: float | None
    capped: float | None
    rule: str                        # the formula used, in words
    note: str | None = None

    @property
    def scored(self) -> bool:
        return self.capped is not None


def _floor0(v: float) -> float:
    return max(0.0, v)


def achievement(polarity: str, actual: float | None, target: float | None, scheme: Scheme,
                lower: float | None = None, upper: float | None = None) -> Achievement:
    """Percentage achievement of ``actual`` against ``target`` for one measure."""
    if polarity not in POLARITIES:
        return Achievement(None, None, "unknown polarity", f"Polarity '{polarity}' is not supported.")
    if actual is None or (isinstance(actual, float) and math.isnan(actual)):
        return Achievement(None, None, "no value", "No approved value for the period.")
    cap = scheme.cap_pct

    if polarity == "yes_no":
        v = 100.0 if actual >= 1 else 0.0
        return Achievement(v, v, "yes = 100 %, no = 0 %")

    if polarity == "kri":
        if target is None:
            return Achievement(None, None, "no appetite", "A key risk indicator needs its appetite as the target.")
        if actual <= target:
            return Achievement(100.0, 100.0, "within appetite (value ≤ appetite) = 100 %")
        if upper is not None and actual <= upper:
            return Achievement(50.0, 50.0, "above appetite but within tolerance = 50 %")
        return Achievement(0.0, 0.0, "outside tolerance = 0 %")

    if polarity == "range":
        if lower is None or upper is None:
            return Achievement(None, None, "no range", "A range indicator needs a lower and an upper bound.")
        if lower <= actual <= upper:
            return Achievement(100.0, 100.0, "inside the range = 100 %")
        width = (upper - lower) or abs(target or 0) or 1.0
        distance = (lower - actual) if actual < lower else (actual - upper)
        v = _floor0(100.0 * (1 - distance / width))
        return Achievement(v, v, "100 % × (1 − distance outside the range ÷ range width), not below 0")

    if target is None:
        return Achievement(None, None, "no target", "No target for the period.")

    if polarity == "milestone":
        if target <= 0:
            v = 100.0 if actual >= 0 else 0.0
            return Achievement(v, v, "nothing planned yet: 100 %")
        v = min(actual / target, 1.0) * 100.0
        v = _floor0(v)
        return Achievement(v, v, "% complete ÷ % planned, at most 100 %")

    if target < 0:
        return Achievement(None, None, "negative target", "Percentage achievement is undefined for a negative target.")

    if target == 0:
        if scheme.zero_target_rule == "binary":
            met = actual >= 0 if polarity == "higher" else actual <= 0
            v = 100.0 if met else 0.0
            return Achievement(v, v, "zero target, binary rule: met = 100 %, not met = 0 %")
        return Achievement(None, None, "zero target", "The target is zero; this scheme leaves such measures unscored.")

    if polarity == "higher":
        raw = actual / target * 100.0
        rule = "actual ÷ target × 100"
    elif scheme.lower_method == "ratio_inverse":
        if actual <= 0:
            raw = math.inf
            rule = "target ÷ actual × 100 (actual ≤ 0: best possible)"
        else:
            raw = target / actual * 100.0
            rule = "target ÷ actual × 100"
    else:
        raw = (2 - actual / target) * 100.0
        rule = "(2 − actual ÷ target) × 100"
    raw = _floor0(raw)
    capped = min(raw, cap)
    uncapped = None if math.isinf(raw) else round(raw, 6)
    return Achievement(uncapped, round(capped, 6), f"{rule}, not below 0, capped at {cap:g} %",
                       "Above the cap: rated at the cap." if raw > cap else None)


def validate_bands(bands: tuple[Band, ...] | list[Band], cap: float) -> list[str]:
    """Bands must be five contiguous, non-overlapping ranges from 0 covering the cap."""
    errors: list[str] = []
    if len(bands) != 5:
        errors.append("A scheme has exactly five bands.")
    ordered = sorted(bands, key=lambda b: b.min_achievement)
    if len({b.rating for b in bands}) != len(bands):
        errors.append("Each band needs its own rating number.")
    if ordered and ordered[0].min_achievement != 0:
        errors.append("The lowest band must start at 0 %.")
    for a, b in zip(ordered, ordered[1:]):
        if a.max_achievement is None or a.max_achievement != b.min_achievement:
            errors.append(f"'{a.label}' must end where '{b.label}' starts.")
    if ordered and ordered[-1].max_achievement is not None and ordered[-1].max_achievement <= cap:
        errors.append(f"The top band must reach above the cap ({cap:g} %) or be open-ended.")
    for b in bands:
        if not (b.label or "").strip():
            errors.append("Every band needs a label.")
        if b.max_achievement is not None and b.max_achievement <= b.min_achievement:
            errors.append(f"'{b.label}' ends before it starts.")
    ratings = [b.rating for b in ordered]
    if ratings not in (sorted(ratings), sorted(ratings, reverse=True)):
        errors.append("Rating numbers must run in one direction across the bands.")
    return errors


def rate(capped: float | None, scheme: Scheme) -> Band | None:
    if capped is None:
        return None
    for b in scheme.bands:
        if capped >= b.min_achievement and (b.max_achievement is None or capped < b.max_achievement):
            return b
    return None


def band_for_rating(rating: float | None, scheme: Scheme) -> Band | None:
    """The band whose rating number is nearest a weighted-average rating."""
    if rating is None or not scheme.bands:
        return None
    return min(scheme.bands, key=lambda b: (abs(b.rating - rating), -b.rating))


# Children that legitimately carry no score this period. They leave the weights, and the
# roll-up says so in its method; they are never treated as zero.
EXCLUDED_STATES = ("not_applicable", "not_due", "not_reported")


@dataclass
class Child:
    key: str
    label: str
    weight: float | None
    achievement: float | None         # capped achievement, or None
    rating: float | None
    state: str = "scored"             # scored | missing | not_applicable | not_due | incomplete | invalid
    note: str | None = None


@dataclass
class Rollup:
    achievement: float | None
    rating: float | None
    status: str                       # complete | partial | incomplete | invalid_weights | empty
    method: str
    total_weight: float
    covered_weight: float
    excluded_weight: float
    coverage_pct: float | None
    contributions: list[dict] = field(default_factory=list)
    missing: list[dict] = field(default_factory=list)
    excluded: list[dict] = field(default_factory=list)
    weighting: str = "set"            # set | equal (no weights were set at this level)


def check_weights(weights: list[float | None]) -> tuple[str, list[str]]:
    """'set' (all set, sum 100), 'equal' (none set) or 'invalid' with reasons."""
    if not weights:
        return "set", []
    given = [w for w in weights if w is not None]
    if not given:
        return "equal", []
    if len(given) != len(weights):
        return "invalid", ["Some items at this level have a weight and others do not."]
    total = sum(given)
    if abs(total - 100) > 1e-6:
        return "invalid", [f"Weights at this level add up to {total:g}, not 100."]
    if any(w < 0 for w in given):
        return "invalid", ["Weights cannot be negative."]
    return "set", []


def rollup(children: list[Child], scheme: Scheme) -> Rollup:
    if not children:
        return Rollup(None, None, "empty", "nothing to combine", 0, 0, 0, None)
    mode, problems = check_weights([c.weight for c in children])
    if mode == "invalid":
        return Rollup(None, None, "invalid_weights", "; ".join(problems), 0, 0, 0, None,
                      missing=[{"key": c.key, "label": c.label} for c in children])
    weights = {c.key: (c.weight if mode == "set" else 100.0 / len(children)) for c in children}
    excluded = [c for c in children if c.state in EXCLUDED_STATES]
    counted = [c for c in children if c not in excluded]
    total = sum(weights[c.key] for c in counted)
    excluded_w = sum(weights[c.key] for c in excluded)
    scored = [c for c in counted if c.achievement is not None and c.rating is not None]
    missing = [c for c in counted if c not in scored]
    covered = sum(weights[c.key] for c in scored)
    base = dict(total_weight=round(total, 6), covered_weight=round(covered, 6), excluded_weight=round(excluded_w, 6),
                weighting=mode,
                missing=[{"key": c.key, "label": c.label, "weight": round(weights[c.key], 6), "state": c.state,
                          "note": c.note} for c in missing],
                excluded=[{"key": c.key, "label": c.label, "weight": round(weights[c.key], 6), "state": c.state,
                           "note": c.note} for c in excluded])
    if total <= 0:
        return Rollup(None, None, "empty", "every item is excluded (not applicable or not due)", coverage_pct=None, **base)
    coverage = covered / total * 100.0

    if scheme.missing_policy == "count_as_zero":
        denom = total
        ach = sum(weights[c.key] * c.achievement for c in scored) / denom
        worst = min(b.rating for b in scheme.bands) if scheme.rating_order == "higher_is_better" else max(
            b.rating for b in scheme.bands)
        rat = (sum(weights[c.key] * c.rating for c in scored) + sum(weights[c.key] * worst for c in missing)) / denom
        method = "complete" if not missing else "missing items counted as 0 % (scheme rule)"
        status = "complete" if not missing else "partial"
    else:
        if coverage + 1e-9 < scheme.coverage_gate_pct or not scored:
            return Rollup(None, None, "incomplete",
                          f"coverage {coverage:.1f} % is below the scheme's {scheme.coverage_gate_pct:g} % gate",
                          coverage_pct=round(coverage, 4), **base)
        denom = covered
        ach = sum(weights[c.key] * c.achievement for c in scored) / denom
        rat = sum(weights[c.key] * c.rating for c in scored) / denom
        method = "complete" if not missing else f"weighted over the {coverage:.1f} % of weight that is covered"
        status = "complete" if not missing else "partial"
    if excluded:
        method += f"; {len(excluded)} item(s) not applicable or not due excluded from the weights"
    contributions = [{"key": c.key, "label": c.label, "weight": round(weights[c.key], 6),
                      "achievement": c.achievement, "rating": c.rating,
                      "share_of_score": round(weights[c.key] * c.achievement / denom, 6),
                      "share_of_rating": round(weights[c.key] * c.rating / denom, 6)} for c in scored]
    return Rollup(round(ach, 6), round(rat, 6), status, method, coverage_pct=round(coverage, 4),
                  contributions=contributions, **base)


def evaluate_tree(inputs: dict, scheme: Scheme, overrides: dict | None = None) -> dict:
    """Score a plan tree from frozen inputs (see scorecard.service.gather).

    ``inputs["nodes"]``: [{key, parent, code, title, node_type, weight}]
    ``inputs["indicators"]``: [{key, node, code, name, polarity, weight, state, actual, target, lower, upper}]
    ``overrides``: {key: {"rating": n, "reason": ...}} replaces that item's rating (and its band)
    for everything above it; the calculated value is kept alongside.
    Returns {"root": {...}, "items": {key: {...}}}.
    """
    overrides = overrides or {}
    items: dict[str, dict] = {}
    kids: dict[str | None, list[str]] = {}
    for n in inputs.get("nodes", []):
        kids.setdefault(n["parent"], []).append(n["key"])
    by_node: dict[str, list[dict]] = {}
    for i in inputs.get("indicators", []):
        by_node.setdefault(i["node"], []).append(i)
    nodes = {n["key"]: n for n in inputs.get("nodes", [])}

    def apply_override(key: str, out: dict) -> None:
        ov = overrides.get(key)
        if not ov:
            return
        band = next((b for b in scheme.bands if b.rating == ov["rating"]), None)
        out["calculated_rating"], out["calculated_label"] = out.get("rating"), out.get("rating_label")
        out["rating"], out["rating_label"] = float(ov["rating"]), band.label if band else str(ov["rating"])
        out["override"] = ov

    def indicator(i: dict) -> dict:
        out = {"type": "indicator", **{k: i.get(k) for k in ("key", "id", "code", "name", "unit", "polarity",
                                                            "weight", "actual", "target", "lower", "upper", "state",
                                                            "source", "dq", "assignment_status", "value_refs",
                                                            "target_id")}}
        if i["state"] != "measured":
            out.update(achievement=None, achievement_uncapped=None, rating=None, rating_label=None,
                       rule=None, note=i.get("note"))
        else:
            a = achievement(i["polarity"], i.get("actual"), i.get("target"), scheme, i.get("lower"), i.get("upper"))
            band = rate(a.capped, scheme)
            out.update(achievement=a.capped, achievement_uncapped=a.uncapped, rule=a.rule, note=a.note,
                       rating=float(band.rating) if band else None, rating_label=band.label if band else None,
                       state="scored" if band else "missing")
        apply_override(i["key"], out)
        items[i["key"]] = out
        return out

    def node(key: str) -> dict:
        n = nodes[key]
        child_outs = [node(k) for k in kids.get(key, [])] + [indicator(i) for i in by_node.get(key, [])]
        children = []
        for c in child_outs:
            state = c.get("state")
            if c["type"] == "node":
                state = "scored" if c["rating"] is not None and c["achievement"] is not None else (
                    "not_due" if c["status"] == "empty" and c.get("excluded_only") else "missing")
            children.append(Child(c["key"], c.get("title") or c.get("name") or c["key"], c.get("weight"),
                                  c.get("achievement"), c.get("rating"), state, c.get("note")))
        r = rollup(children, scheme)
        band = band_for_rating(r.rating, scheme)
        out = {"type": "node", "key": key, "id": n.get("id"), "code": n.get("code"), "title": n.get("title"),
               "node_type": n.get("node_type"), "weight": n.get("weight"), "children": [c["key"] for c in child_outs],
               "achievement": r.achievement, "rating": r.rating, "rating_label": band.label if band else None,
               "status": r.status, "method": r.method, "total_weight": r.total_weight,
               "covered_weight": r.covered_weight, "excluded_weight": r.excluded_weight,
               "coverage_pct": r.coverage_pct, "weighting": r.weighting, "contributions": r.contributions,
               "missing": r.missing, "excluded": r.excluded,
               "excluded_only": bool(children) and all(c.state in EXCLUDED_STATES for c in children),
               "note": None if child_outs else "Nothing measures this item yet."}
        apply_override(key, out)
        items[key] = out
        return out

    top = [node(k) for k in kids.get(None, [])]
    children = [Child(t["key"], t["title"], t.get("weight"), t["achievement"], t["rating"],
                      "scored" if t["rating"] is not None and t["achievement"] is not None else (
                          "not_due" if t["status"] == "empty" and t.get("excluded_only") else "missing"))
                for t in top]
    r = rollup(children, scheme)
    band = band_for_rating(r.rating, scheme)
    root = {"type": "plan", "key": "plan", "children": [t["key"] for t in top], "achievement": r.achievement,
            "rating": r.rating, "rating_label": band.label if band else None, "status": r.status, "method": r.method,
            "total_weight": r.total_weight, "covered_weight": r.covered_weight, "excluded_weight": r.excluded_weight,
            "coverage_pct": r.coverage_pct, "weighting": r.weighting, "contributions": r.contributions,
            "missing": r.missing, "excluded": r.excluded}
    apply_override("plan", root)
    return {"root": root, "items": items}


def inputs_hash(payload: dict) -> str:
    """Stable fingerprint of everything a snapshot was computed from."""
    blob = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(blob.encode()).hexdigest()


def scheme_dict(s: Scheme) -> dict:
    return {**asdict(s), "bands": [asdict(b) for b in s.bands]}
