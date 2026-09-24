"""
Integration data model: the single repository every source feeds.

    DataSource ──► SyncRun ──► MetricValue ◄── Metric (catalogue)
        │                          │
        └── KeyMapping             └── OrgUnit (hierarchy)
                                   MetricTarget (where we are going)

One row in ``metric_values`` is one measure, for one organisational unit, for one
period, from one source. Keeping the source in the key means two systems can
report the same measure side by side; ``DataSource.priority`` decides which one
is the published figure, and the other stays visible for reconciliation.
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    JSON, Boolean, Column, Date, DateTime, Float, ForeignKey, Index, Integer,
    String, Text, UniqueConstraint,
)

from app.database import Base

SYSTEM_TYPES = ("erp", "eam", "billing", "scada", "hr", "gis", "lims", "file", "legacy", "other")
CONNECTORS = ("file", "sql", "rest", "push", "legacy_records")
AGGREGATIONS = ("sum", "avg", "last", "max", "min")
DIRECTIONS = ("higher", "lower", "range")
PERIOD_TYPES = ("day", "month", "quarter", "year")
VALUE_STATUSES = ("actual", "estimated", "pending", "na")


class OrgUnit(Base):
    """A node in the organisation tree: organisation, region, zone, scheme, plant, department..."""
    __tablename__ = "org_units"

    id         = Column(Integer, primary_key=True, autoincrement=True)
    code       = Column(String(80), nullable=False, unique=True, index=True)
    name       = Column(String(160), nullable=False)
    unit_type  = Column(String(40), nullable=False, default="unit")
    parent_id  = Column(Integer, ForeignKey("org_units.id"), nullable=True, index=True)
    is_active  = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class Metric(Base):
    """Catalogue entry. Measures are data, not database columns."""
    __tablename__ = "metrics"

    id          = Column(Integer, primary_key=True, autoincrement=True)
    code        = Column(String(80), nullable=False, unique=True, index=True)
    name        = Column(String(160), nullable=False)
    unit        = Column(String(40), nullable=True)
    category    = Column(String(60), nullable=True)
    aggregation = Column(String(10), nullable=False, default="sum")
    direction   = Column(String(10), nullable=False, default="higher")
    description = Column(Text, nullable=True)
    is_active   = Column(Boolean, nullable=False, default=True)
    created_at  = Column(DateTime, default=datetime.utcnow)


class DataSource(Base):
    """A system, file drop or feed that supplies values.

    ``config`` holds connection settings. Secrets are never stored here: config
    names environment variables (``*_env`` keys) that hold them.
    """
    __tablename__ = "data_sources"

    id                = Column(Integer, primary_key=True, autoincrement=True)
    code              = Column(String(60), nullable=False, unique=True, index=True)
    name              = Column(String(160), nullable=False)
    system_type       = Column(String(20), nullable=False, default="other")
    connector         = Column(String(20), nullable=False)
    config            = Column(JSON, nullable=False, default=dict)
    mapping           = Column(JSON, nullable=False, default=dict)
    priority          = Column(Integer, nullable=False, default=100)  # lower wins
    enabled           = Column(Boolean, nullable=False, default=True)
    owner             = Column(String(120), nullable=True)
    schedule_minutes  = Column(Integer, nullable=True)  # None = manual only
    watermark         = Column(String(64), nullable=True)
    ingest_token_hash = Column(String(128), nullable=True)
    last_run_at       = Column(DateTime, nullable=True)
    last_success_at   = Column(DateTime, nullable=True)
    created_at        = Column(DateTime, default=datetime.utcnow)
    updated_at        = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class KeyMapping(Base):
    """Crosswalk from a source's own keys (SAP cost centre, Maximo site, SCADA tag) to ours."""
    __tablename__ = "key_mappings"

    id            = Column(Integer, primary_key=True, autoincrement=True)
    source_id     = Column(Integer, ForeignKey("data_sources.id"), nullable=False, index=True)
    kind          = Column(String(20), nullable=False)  # org_unit | metric
    external_key  = Column(String(200), nullable=False)
    internal_code = Column(String(80), nullable=False)

    __table_args__ = (UniqueConstraint("source_id", "kind", "external_key", name="uq_key_mapping"),)


class SyncRun(Base):
    __tablename__ = "sync_runs"

    id               = Column(Integer, primary_key=True, autoincrement=True)
    source_id        = Column(Integer, ForeignKey("data_sources.id"), nullable=False, index=True)
    started_at       = Column(DateTime, default=datetime.utcnow, index=True)
    finished_at      = Column(DateTime, nullable=True)
    status           = Column(String(12), nullable=False, default="running")  # running|success|partial|failed
    triggered_by     = Column(String(60), nullable=True)
    rows_read        = Column(Integer, nullable=False, default=0)
    values_loaded    = Column(Integer, nullable=False, default=0)
    rows_rejected    = Column(Integer, nullable=False, default=0)
    watermark_before = Column(String(64), nullable=True)
    watermark_after  = Column(String(64), nullable=True)
    error            = Column(Text, nullable=True)
    rejects          = Column(JSON, nullable=True)  # first N rejected rows with reasons


class MetricValue(Base):
    __tablename__ = "metric_values"

    id            = Column(Integer, primary_key=True, autoincrement=True)
    metric_code   = Column(String(80), nullable=False)
    org_unit_code = Column(String(80), nullable=False)
    period_type   = Column(String(10), nullable=False, default="month")
    period_start  = Column(Date, nullable=False)
    value         = Column(Float, nullable=True)
    status        = Column(String(12), nullable=False, default="actual")
    source_id     = Column(Integer, ForeignKey("data_sources.id"), nullable=False)
    run_id        = Column(Integer, ForeignKey("sync_runs.id"), nullable=True)
    source_ref    = Column(String(300), nullable=True)  # file/row, record id, tag: lineage back to origin
    loaded_at     = Column(DateTime, default=datetime.utcnow)

    __table_args__ = (
        UniqueConstraint("metric_code", "org_unit_code", "period_type", "period_start", "source_id",
                         name="uq_metric_value"),
        Index("ix_metric_values_lookup", "metric_code", "org_unit_code", "period_type", "period_start"),
    )


class MetricTarget(Base):
    """Where we are going: a target for a measure, unit and period, with its basis."""
    __tablename__ = "metric_targets"

    id            = Column(Integer, primary_key=True, autoincrement=True)
    metric_code   = Column(String(80), nullable=False, index=True)
    org_unit_code = Column(String(80), nullable=False)
    period_type   = Column(String(10), nullable=False, default="year")
    period_start  = Column(Date, nullable=False)
    value         = Column(Float, nullable=False)
    lower         = Column(Float, nullable=True)
    upper         = Column(Float, nullable=True)
    basis         = Column(String(40), nullable=False, default="strategic_plan")  # strategic_plan|budget|regulator|internal
    note          = Column(String(300), nullable=True)
    updated_at    = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (
        UniqueConstraint("metric_code", "org_unit_code", "period_type", "period_start", "basis",
                         name="uq_metric_target"),
    )
