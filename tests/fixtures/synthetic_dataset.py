"""Deterministic synthetic dataset for parity snapshot tests.

Every value here is generated. The zone names mirror the reference tenant's
hierarchy so the reference configuration can be exercised, but no figure is
real utility data.
"""
from __future__ import annotations

from sqlalchemy import Boolean, Float, Integer

MONTH_NAMES = [
    "January", "February", "March", "April", "May", "June",
    "July", "August", "September", "October", "November", "December",
]

REFERENCE_ZONES = {
    "Liwonde":  ["Liwonde", "Balaka", "Machinga"],
    "Mangochi": ["Mangochi", "Monkey Bay"],
    "Mulanje":  ["Mulanje", "Thyolo", "Phalombe"],
    "Ngabu":    ["Ngabu", "Chikwawa"],
    "Zomba":    ["Zomba", "Chinamwali", "Domasi"],
}

# FY-end years 2024 and 2025 (April 2023 .. March 2025), plus one month of FY2026.
PERIODS = (
    [(2023, m) for m in range(4, 13)]
    + [(2024, m) for m in range(1, 13)]
    + [(2025, m) for m in range(1, 5)]
)


def _quarter(month_no: int, fy_start: int = 4) -> str:
    idx = (month_no - fy_start) % 12
    return f"Q{idx // 3 + 1}"


def _fy_label(year: int, month_no: int, fy_start: int = 4) -> str:
    end = year + 1 if month_no >= fy_start else year
    return f"FY{end - 1}/{str(end)[-2:]}"


def _value(col_idx: int, z: int, s: int, year: int, month: int, integer: bool) -> float:
    # Smooth, strictly positive, deterministic; distinct per column/zone/scheme/month.
    base = 100 + (col_idx * 37) % 900
    v = base * (1 + z * 0.35) * (1 + s * 0.2) * (1 + ((year * 12 + month) % 17) / 40.0)
    return float(int(v)) if integer else round(v, 2)


def build_records(Record, zones=None, fy_start: int = 4):
    zones = zones or REFERENCE_ZONES
    skip = {"id", "zone", "scheme", "fiscal_year", "year", "month_no", "month", "quarter"}
    numeric = [
        (i, c) for i, c in enumerate(Record.__table__.columns)
        if c.name not in skip and isinstance(c.type, (Float, Integer)) and not isinstance(c.type, Boolean)
    ]
    rows = []
    for z, (zone, schemes) in enumerate(zones.items()):
        for s, scheme in enumerate(schemes):
            for year, month in PERIODS:
                data = {
                    "zone": zone, "scheme": scheme, "year": year, "month_no": month,
                    "month": MONTH_NAMES[month - 1],
                    "quarter": _quarter(month, fy_start),
                    "fiscal_year": _fy_label(year, month, fy_start),
                }
                for idx, col in numeric:
                    data[col.name] = _value(idx, z, s, year, month, isinstance(col.type, Integer))
                # Keep the core water balance internally consistent.
                produced = data.get("vol_produced", 0.0)
                data["revenue_water"] = round(produced * (0.62 + z * 0.03), 2)
                data["nrw"] = round(produced - data["revenue_water"], 2)
                data["pct_nrw"] = round(data["nrw"] / produced * 100, 2) if produced else 0.0
                rows.append(Record(**{k: v for k, v in data.items() if hasattr(Record, k)}))
    return rows
