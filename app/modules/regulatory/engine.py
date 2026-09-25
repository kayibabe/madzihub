"""
Regulator pack engine: pure functions over a pack's content.

Pack content (see tenants/_packs/regulators/README.md for the full format):
  groups:     [{code, name, share_pct, verified}]        e.g. EWURA "KPI" and "CRR"; WASREB one group
  indicators: [{code, name, group, cluster, unit, polarity, weight, in_score, verified, source_ref,
                validation: {min, max}, scoring: {...}, madzihub_metric}]
  scoring:    {"type": "bands", "bands": [{"min", "max", "points", "label"}]}      fixed thresholds
              {"type": "peer_interpolation", "min_points", "median_points", "best_points"}
              {"type": "yes_no", "points"}                                          obligations

A pack is only usable when blockers() is empty: every group and every scored indicator is marked
verified against the cited source, and has its weight and scoring parameters.
"""
from __future__ import annotations

import statistics

ENGINE_VERSION = "1.0.0"
POLARITIES = ("higher", "lower", "yes_no")


def blockers(content: dict) -> list[str]:
    out: list[str] = []
    if not content.get("verification", {}).get("source_checked"):
        out.append("The pack as a whole is not yet checked against its source document.")
    groups = content.get("groups") or []
    if not groups:
        out.append("The pack defines no scoring groups.")
    for g in groups:
        if not g.get("verified"):
            out.append(f"Group {g.get('code')}: share not verified against the source.")
        if g.get("share_pct") is None:
            out.append(f"Group {g.get('code')}: share missing.")
    shares = [g.get("share_pct") for g in groups]
    if groups and all(s is not None for s in shares) and abs(sum(shares) - 100) > 1e-6:
        out.append(f"Group shares add up to {sum(shares):g}, not 100.")
    codes = [g.get("code") for g in groups]
    for ind in content.get("indicators") or []:
        if not ind.get("in_score", True):
            continue
        name = f"{ind.get('code')} {ind.get('name', '')}".strip()
        if not ind.get("verified"):
            out.append(f"{name}: not verified against the source.")
        if ind.get("group") not in codes:
            out.append(f"{name}: unknown group '{ind.get('group')}'.")
        if ind.get("weight") is None:
            out.append(f"{name}: weight missing.")
        sc = ind.get("scoring") or {}
        if sc.get("type") == "bands":
            bands = sc.get("bands") or []
            if not bands or any(b.get("points") is None for b in bands):
                out.append(f"{name}: scoring bands missing or incomplete.")
        elif sc.get("type") == "peer_interpolation":
            if any(sc.get(k) is None for k in ("min_points", "median_points", "best_points")):
                out.append(f"{name}: interpolation points missing.")
        elif sc.get("type") == "yes_no":
            if sc.get("points") is None:
                out.append(f"{name}: points missing.")
        else:
            out.append(f"{name}: no scoring rule.")
    return out


def validate_value(ind: dict, value) -> list[str]:
    errors = []
    if value is None:
        return errors
    rule = ind.get("validation") or {}
    if rule.get("min") is not None and value < rule["min"]:
        errors.append(f"below the minimum {rule['min']:g}")
    if rule.get("max") is not None and value > rule["max"]:
        errors.append(f"above the maximum {rule['max']:g}")
    if ind.get("polarity") == "yes_no" and value not in (0, 1):
        errors.append("must be 1 (yes) or 0 (no)")
    return errors


def _max_points(sc: dict) -> float:
    if sc["type"] == "bands":
        return max(b["points"] for b in sc["bands"])
    if sc["type"] == "peer_interpolation":
        return sc["best_points"]
    return sc["points"]


def _band_points(ind: dict, value: float) -> tuple[float, str | None]:
    for b in ind["scoring"]["bands"]:
        lo, hi = b.get("min"), b.get("max")
        if (lo is None or value >= lo) and (hi is None or value < hi):
            return b["points"], b.get("label")
    return 0.0, None


def _interpolate(ind: dict, value: float, peer_values: list[float]) -> tuple[float, str]:
    sc = ind["scoring"]
    vals = [v for v in peer_values if v is not None]
    if not vals:
        return 0.0, "no peers"
    better_is_higher = ind.get("polarity") != "lower"
    best = max(vals) if better_is_higher else min(vals)
    worst = min(vals) if better_is_higher else max(vals)
    med = statistics.median(vals)
    key = (lambda v: v) if better_is_higher else (lambda v: -v)
    v, b, w, m = key(value), key(best), key(worst), key(med)
    if v >= b:
        return float(sc["best_points"]), "best"
    if v <= w:
        return float(sc["min_points"]), "minimum"
    if v >= m:
        span = (b - m) or 1
        return sc["median_points"] + (v - m) / span * (sc["best_points"] - sc["median_points"]), "above median"
    span = (m - w) or 1
    return sc["min_points"] + (v - w) / span * (sc["median_points"] - sc["min_points"]), "below median"


def score_entity(content: dict, values: dict, peers: list[dict]) -> dict:
    groups = {g["code"]: {"code": g["code"], "name": g.get("name"), "share_pct": g["share_pct"],
                          "earned": 0.0, "possible": 0.0, "missing": []} for g in content["groups"]}
    rows = []
    for ind in content["indicators"]:
        if not ind.get("in_score", True):
            continue
        g = groups[ind["group"]]
        weight = ind["weight"]
        maxp = _max_points(ind["scoring"])
        g["possible"] += weight * maxp
        value = values.get(ind["code"])
        if value is None:
            g["missing"].append(ind["code"])
            rows.append({"code": ind["code"], "name": ind.get("name"), "value": None, "points": 0.0, "label": "missing",
                         "weighted": 0.0})
            continue
        t = ind["scoring"]["type"]
        if t == "bands":
            pts, label = _band_points(ind, value)
        elif t == "peer_interpolation":
            pts, label = _interpolate(ind, value, [p["values"].get(ind["code"]) for p in peers] + [value])
        else:
            pts, label = (float(ind["scoring"]["points"]) if value >= 1 else 0.0), ("yes" if value >= 1 else "no")
        g["earned"] += weight * pts
        rows.append({"code": ind["code"], "name": ind.get("name"), "value": value, "points": round(pts, 4),
                     "label": label, "weighted": round(weight * pts, 4)})
    total = 0.0
    for g in groups.values():
        g["score_pct"] = round(g["earned"] / g["possible"] * 100, 4) if g["possible"] else None
        g["contribution"] = round((g["score_pct"] or 0) * g["share_pct"] / 100, 4)
        total += g["contribution"]
    return {"indicators": rows, "groups": list(groups.values()), "total": round(total, 4),
            "missing": [c for g in groups.values() for c in g["missing"]]}


def league(content: dict, own_name: str, own_values: dict, peers: list[dict]) -> dict:
    """Score the utility and each peer on the same pack; rank by total (ties share a rank)."""
    entities = [{"name": own_name, "values": own_values, "own": True}] + [dict(p, own=False) for p in peers]
    results = []
    for e in entities:
        others = [p for p in entities if p is not e]
        results.append({"name": e["name"], "own": e["own"], **score_entity(content, e["values"], others)})
    results.sort(key=lambda r: -r["total"])
    rank = 0
    prev = None
    for i, r in enumerate(results, start=1):
        if r["total"] != prev:
            rank, prev = i, r["total"]
        r["rank"] = rank
    return {"engine_version": ENGINE_VERSION, "entities": results}
