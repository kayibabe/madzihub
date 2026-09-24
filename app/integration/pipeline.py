"""
Pipeline: extract → map/validate → load, recorded as a SyncRun.

Loads are idempotent: re-running a source (or re-dropping the same file) updates
the same (metric, org unit, period, source) rows instead of duplicating them.
The watermark only advances after a load commits, so a failed run is retried
from the same point next time.
"""
from __future__ import annotations

import hashlib
import secrets
from datetime import date, datetime, timedelta

from sqlalchemy.orm import Session

from app.integration import connectors
from app.integration.mapping import Resolver, map_rows
from app.integration.models import DataSource, KeyMapping, Metric, MetricTarget, MetricValue, OrgUnit, SyncRun

STALE_RUN_AFTER = timedelta(hours=2)


class SyncBusy(RuntimeError):
    pass


def _resolver(db: Session, source: DataSource) -> tuple[Resolver, dict[str, str]]:
    org_codes = {c for (c,) in db.query(OrgUnit.code).filter(OrgUnit.is_active.is_(True))}
    metrics = db.query(Metric).filter(Metric.is_active.is_(True)).all()
    key_map = {(k.kind, k.external_key): k.internal_code
               for k in db.query(KeyMapping).filter(KeyMapping.source_id == source.id)}
    loadable = [m for m in metrics if not m.formula]  # formula measures are computed, never loaded
    return Resolver(org_codes, {m.code for m in loadable}, key_map), {m.code: m.aggregation for m in loadable}


def _load(db: Session, source: DataSource, run: SyncRun, values) -> int:
    if not values:
        return 0
    codes = {v.metric_code for v in values}
    starts = [v.period_start for v in values]
    existing = {
        (mv.metric_code, mv.org_unit_code, mv.period_type, mv.period_start): mv
        for mv in db.query(MetricValue).filter(
            MetricValue.source_id == source.id,
            MetricValue.metric_code.in_(codes),
            MetricValue.period_start >= min(starts),
            MetricValue.period_start <= max(starts),
        )
    }
    now = datetime.utcnow()
    for v in values:
        key = (v.metric_code, v.org_unit_code, v.period_type, v.period_start)
        row = existing.get(key)
        if row is None:
            row = MetricValue(metric_code=v.metric_code, org_unit_code=v.org_unit_code,
                              period_type=v.period_type, period_start=v.period_start, source_id=source.id)
            db.add(row)
            existing[key] = row
        row.value = v.value
        row.status = "actual"
        row.run_id = run.id
        row.source_ref = (v.source_ref or "")[:300] or None
        row.loaded_at = now
    return len(values)


def run_sync(db: Session, source: DataSource, triggered_by: str = "system", rows: list[dict] | None = None) -> SyncRun:
    """Run one source end to end. ``rows`` supplies data directly (push feeds, uploaded files)."""
    busy = db.query(SyncRun).filter(
        SyncRun.source_id == source.id, SyncRun.status == "running",
        SyncRun.started_at > datetime.utcnow() - STALE_RUN_AFTER,
    ).first()
    if busy:
        raise SyncBusy(f"source {source.code} already has run {busy.id} in progress")

    run = SyncRun(source_id=source.id, triggered_by=triggered_by, watermark_before=source.watermark)
    db.add(run)
    source.last_run_at = datetime.utcnow()
    db.commit()

    try:
        extracted = connectors.extract(db, source, rows)
        resolver, aggregations = _resolver(db, source)
        mapped = map_rows(extracted.rows, source.mapping or {}, resolver, aggregations)
        run.rows_read = len(extracted.rows)
        run.values_loaded = _load(db, source, run, mapped.values)
        run.rows_rejected = mapped.rows_rejected
        run.rejects = mapped.rejects or None
        run.status = "partial" if mapped.rows_rejected else "success"
        if rows is None:  # pulled runs move the watermark; pushed batches do not
            source.watermark = extracted.watermark
        run.watermark_after = source.watermark
        source.last_success_at = datetime.utcnow()
    except Exception as exc:  # recorded on the run; the caller sees the status
        db.rollback()
        run = db.get(SyncRun, run.id)
        run.status = "failed"
        run.error = f"{type(exc).__name__}: {exc}"[:2000]
    run.finished_at = datetime.utcnow()
    db.commit()
    db.refresh(run)
    return run


def test_source(db: Session, source: DataSource, rows: list[dict] | None = None, limit: int = 500) -> dict:
    """Dry run: connect, read a sample, map it, and report what *would* load. Writes nothing.

    Use it to prove a new connection and mapping before the first real run: the
    watermark does not move, no SyncRun is recorded and no values are stored.
    """
    try:
        extracted = connectors.extract(db, source, rows, limit=limit)
        resolver, aggregations = _resolver(db, source)
        mapped = map_rows(extracted.rows, source.mapping or {}, resolver, aggregations)
    except Exception as exc:
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"[:2000]}
    values = mapped.values
    columns = sorted({k for r in extracted.rows[:50] for k in r if k != "_source_ref"})
    return {
        "ok": True,
        "rows_read": len(extracted.rows),
        "sample_limit": limit,
        "columns": columns,
        "values_mapped": len(values),
        "rows_rejected": mapped.rows_rejected,
        "rejects": mapped.rejects[:50],
        "metrics": sorted({v.metric_code for v in values}),
        "org_units": sorted({v.org_unit_code for v in values}),
        "periods": {"first": min(v.period_start for v in values).isoformat(),
                    "last": max(v.period_start for v in values).isoformat()} if values else None,
        "sample_values": [{"metric": v.metric_code, "org_unit": v.org_unit_code, "period": v.period_start.isoformat(),
                           "value": v.value, "source_ref": v.source_ref} for v in values[:20]],
    }


def due_sources(db: Session, now: datetime | None = None) -> list[DataSource]:
    now = now or datetime.utcnow()
    due = []
    for s in db.query(DataSource).filter(DataSource.enabled.is_(True), DataSource.schedule_minutes.isnot(None)):
        if s.connector == "push":
            continue
        if s.last_run_at is None or s.last_run_at + timedelta(minutes=s.schedule_minutes) <= now:
            due.append(s)
    return due


# ── push-feed tokens ────────────────────────────────────────────────────────

def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def issue_ingest_token(source: DataSource) -> str:
    """New random token for a push source. Only the hash is stored; the token is shown once."""
    token = "mzi_" + secrets.token_urlsafe(32)
    source.ingest_token_hash = _hash_token(token)
    return token


def check_ingest_token(source: DataSource, token: str | None) -> bool:
    if not token or not source.ingest_token_hash:
        return False
    return secrets.compare_digest(source.ingest_token_hash, _hash_token(token))


# ── bootstrap from the existing monthly returns ─────────────────────────────

# Records columns published into the catalogue by the legacy bridge. Ratios such as
# pct_nrw are deliberately left out: they must be recomputed from their components
# at each level, never summed or averaged across schemes.
LEGACY_METRICS = [
    # code,             name,                         unit,      category,     aggregation, direction
    ("vol_produced",     "Water produced",             "m³",      "Operations", "sum",  "higher"),
    ("revenue_water",    "Revenue water",              "m³",      "Operations", "sum",  "higher"),
    ("nrw",              "Non-revenue water volume",   "m³",      "Operations", "sum",  "lower"),
    ("new_connections",  "New connections",            "count",   "Customers",  "sum",  "higher"),
    ("active_customers", "Active customers",           "count",   "Customers",  "last", "higher"),
    ("amt_billed",       "Amount billed",              "currency", "Finance",   "sum",  "higher"),
    ("cash_collected",   "Cash collected",             "currency", "Finance",   "sum",  "higher"),
]


# Ratios computed from the components above, at every level and period.
LEGACY_FORMULAS = [
    # code,                   name,                     unit, category,     direction, formula
    ("nrw_pct",               "Non-revenue water",      "%",  "Operations", "lower",  "nrw / vol_produced * 100"),
    ("collection_efficiency", "Collection efficiency",  "%",  "Finance",    "higher", "cash_collected / amt_billed * 100"),
]

# Strategic-plan actual_key → catalogue code, where the names differ.
PLAN_KEY_ALIASES = {"production": "vol_produced", "water_sold": "revenue_water", "customer_base": "active_customers"}


def _seed_plan_targets(db: Session, tenant) -> int:
    """Annual strategic-plan targets for plan KPIs the catalogue can measure."""
    from app.utils import FY_START_MONTH, fy_calendar_year

    codes = {c for (c,) in db.query(Metric.code)}
    seeded = 0
    for kpi in tenant.strategic_plan.kpis:
        code = PLAN_KEY_ALIASES.get(kpi.actual_key, kpi.actual_key) if kpi.actual_key else None
        if code not in codes:
            continue
        for fy_end, value in kpi.targets.items():
            if value is None:
                continue
            start = date(fy_calendar_year(int(fy_end), FY_START_MONTH), FY_START_MONTH, 1)
            key = dict(metric_code=code, org_unit_code="org", period_type="year", period_start=start,
                       basis="strategic_plan")
            row = db.query(MetricTarget).filter_by(**key).first()
            if row is None:
                row = MetricTarget(**key)
                db.add(row)
                seeded += 1
            row.value = float(value)
            row.note = f"{tenant.strategic_plan.title}: {kpi.name}"[:300]
    return seeded


def bootstrap_legacy(db: Session) -> dict:
    """Create the org tree, core metrics and a legacy source from the existing records table.

    Safe to run repeatedly. Returns counts of what was created.
    """
    from app.core.tenant import tenant
    from app.database import Record

    created = {"org_units": 0, "metrics": 0, "source": False, "targets": 0}
    root_code = "org"
    root = db.query(OrgUnit).filter_by(code=root_code).first()
    if root is None:
        root = OrgUnit(code=root_code, name=tenant.identity.name, unit_type="organisation")
        db.add(root)
        db.flush()
        created["org_units"] += 1

    levels = {lvl.key: lvl.label for lvl in tenant.hierarchy.levels}
    by_code = {u.code: u for u in db.query(OrgUnit)}
    for zone, scheme in db.query(Record.zone, Record.scheme).distinct():
        zcode = connectors.legacy_org_code(zone)
        if zcode not in by_code:
            by_code[zcode] = OrgUnit(code=zcode, name=zone, unit_type=levels.get("zone", "zone").lower(),
                                     parent_id=root.id)
            db.add(by_code[zcode])
            db.flush()
            created["org_units"] += 1
        scode = connectors.legacy_org_code(zone, scheme)
        if scode not in by_code:
            by_code[scode] = OrgUnit(code=scode, name=scheme, unit_type=levels.get("scheme", "scheme").lower(),
                                     parent_id=by_code[zcode].id)
            db.add(by_code[scode])
            created["org_units"] += 1

    known = {c for (c,) in db.query(Metric.code)}
    for code, name, unit, category, agg, direction in LEGACY_METRICS:
        if code not in known:
            db.add(Metric(code=code, name=name, unit=tenant.currency.code if unit == "currency" else unit,
                          category=category, aggregation=agg, direction=direction))
            created["metrics"] += 1
    for code, name, unit, category, direction, formula in LEGACY_FORMULAS:
        if code not in known:
            db.add(Metric(code=code, name=name, unit=unit, category=category, aggregation="avg",
                          direction=direction, formula=formula))
            created["metrics"] += 1
    db.flush()
    created["targets"] = _seed_plan_targets(db, tenant)

    if db.query(DataSource).filter_by(code="legacy-returns").first() is None:
        db.add(DataSource(
            code="legacy-returns", name="Monthly returns (existing MadziHub records)", system_type="legacy",
            connector="legacy_records", priority=500,
            config={"columns": [m[0] for m in LEGACY_METRICS]},
            mapping={"layout": "wide", "metrics": {m[0]: m[0] for m in LEGACY_METRICS},
                     "period": {"year_field": "year", "month_field": "month_no"},
                     "period_type": "month", "org_unit": {"field": "org_unit"}},
        ))
        created["source"] = True
    db.commit()
    return created
