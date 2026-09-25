"""Governed comparators for the operational dashboard KPIs (UX-11).

One rule per measure, used by the API flags, the report scorecard and (injected into
app-core.js) every dashboard card, so equivalent contexts resolve to the same verdict.

A rule states what each verdict boundary is and where it comes from, kept distinct:
  corporate_target   the utility's own target (tenant configuration)
  operational_band   an internal alert band (tenant configuration or product default)
  benchmark          an external reference (context only unless it is the stated boundary)
A value is GOOD at or beyond ``good``, WATCH up to ``warn``, otherwise HIGH. A missing value
or a measure without a rule is Not assessed; there is no fallback to another rule.

Product defaults marked ``default`` were chosen where screens disagreed and still need product
confirmation (docs/GUI_UX_REVIEW_2026-09-25.md, Slice 1b record).
"""
from __future__ import annotations

import hashlib
import json
import math

from app.core.tenant import tenant

REGISTRY_VERSION = 1

# key: (measure, unit, direction, good boundary, warn boundary, context)
# Each boundary: (type, source, tenant section, tenant key, default value)
_RULES = {
    "nrw_pct": ("Non-revenue water", "%", "lower",
                ("corporate_target", "Corporate NRW target", "targets", "nrw_pct", 27.0),
                ("operational_band", "NRW action threshold", "thresholds", "nrw_warn", 35.0),
                [("benchmark", "IWA international reference", 20.0)]),
    "collection_rate": ("Collection rate", "%", "higher",
                        ("benchmark", "IBNET collection benchmark", "thresholds", "coll_good", 90.0),
                        ("operational_band", "Collection alert band", "thresholds", "coll_warn", 75.0), []),
    "op_ratio": ("Operating ratio", "ratio", "lower",
                 ("benchmark", "World Bank operating-ratio reference", None, None, 0.8),
                 ("operational_band", "Full cost recovery", None, None, 1.0), []),
    "dso": ("Days sales outstanding", "days", "lower",
            ("benchmark", "IBNET debtor-days reference", None, None, 60.0),
            ("operational_band", "Debtor-days alert band", None, None, 90.0), []),
    "stuck_pct": ("Stuck meters", "% of metered connections", "lower",
                  ("operational_band", "Stuck-meter target band (default)", "thresholds", "stuck_pct_good", 5.0),
                  ("operational_band", "Stuck-meter alert threshold", "thresholds", "stuck_pct_warn", 8.0), []),
    "staff_per_1000_conn": ("Staff per 1,000 connections", "staff / 1,000 connections", "lower",
                            ("corporate_target", "Staffing target", "targets", "staff_per_1000_conn", 13.0),
                            ("operational_band", "Staffing alert band (default)", "thresholds", "staff_per_1000_conn_warn", 20.0),
                            [("benchmark", "IBNET good practice (as cited in earlier reports; unverified)", 5.0)]),
    "breakdowns_per_1k": ("Breakdowns per 1,000 connections", "breakdowns / 1,000 connections", "lower",
                          ("operational_band", "Network reliability band (default)", "thresholds", "breakdowns_per_1k_good", 5.0),
                          ("operational_band", "Network reliability alert band (default)", "thresholds", "breakdowns_per_1k_warn", 10.0), []),
    "active_conn_ratio": ("Active connection ratio", "% of metered connections", "higher",
                          ("operational_band", "Meter activity band (default)", "thresholds", "active_conn_good", 90.0),
                          ("operational_band", "Meter activity alert band (default)", "thresholds", "active_conn_warn", 75.0), []),
    "payroll_cost_ratio": ("Payroll cost ratio", "% of revenue", "lower",
                           ("operational_band", "Payroll cost band (default)", "thresholds", "payroll_good", 35.0),
                           ("operational_band", "Payroll cost alert band (default)", "thresholds", "payroll_warn", 50.0), []),
    "supply_hours": ("Supply hours per day", "hours / day", "higher",
                     ("operational_band", "Continuity band (default)", "thresholds", "supply_good", 20.0),
                     ("operational_band", "Continuity alert band (default)", "thresholds", "supply_warn", 16.0), []),
    "energy_intensity": ("Energy intensity", "kWh / m³", "lower",
                         ("benchmark", "IWA energy-intensity reference", None, None, 0.5),
                         ("operational_band", "Energy alert band (default)", "thresholds", "energy_warn", 0.8), []),
}


def _value(section, key, default):
    if section is None:
        return default, False
    configured = getattr(tenant, section, {}) or {}
    return (configured[key], True) if key in configured else (default, False)


def version() -> str:
    cfg = json.dumps({"targets": tenant.targets, "thresholds": tenant.thresholds}, sort_keys=True)
    return f"comparators v{REGISTRY_VERSION} · {tenant.key} config {hashlib.sha256(cfg.encode()).hexdigest()[:8]}"


def rule(key: str) -> dict | None:
    """The governed rule for a measure, with each boundary's type and source; None if ungoverned."""
    spec = _RULES.get(key)
    if spec is None:
        return None
    measure, unit, direction, good, warn, context = spec
    out = {"key": key, "measure": measure, "unit": unit, "direction": direction, "version": version(),
           "context": [{"type": t, "source": s, "value": v} for t, s, v in context]}
    for name, (ctype, source, section, cfg_key, default) in (("good", good), ("warn", warn)):
        value, configured = _value(section, cfg_key, default)
        out[name] = value
        out[f"{name}_comparator"] = {
            "type": ctype, "source": source, "value": value,
            "origin": f"tenant {section}.{cfg_key}" if configured else "product default"}
    return out


def rules() -> dict[str, dict]:
    return {k: rule(k) for k in _RULES}


def assess(key: str, value) -> str:
    """GOOD / WATCH / HIGH against the governed rule; NOT ASSESSED without a value or rule."""
    r = rule(key)
    if r is None or value is None or not math.isfinite(value):
        return "NOT ASSESSED"
    lower = r["direction"] == "lower"
    if (value <= r["good"]) if lower else (value >= r["good"]):
        return "GOOD"
    if (value <= r["warn"]) if lower else (value >= r["warn"]):
        return "WATCH"
    return "HIGH"


def benchmark_text(key: str) -> str:
    """Short comparator label for reports, e.g. "≤13 (Staffing target)"."""
    r = rule(key)
    op = "≤" if r["direction"] == "lower" else "≥"
    return f"{op}{r['good']:g} ({r['good_comparator']['source']})"
