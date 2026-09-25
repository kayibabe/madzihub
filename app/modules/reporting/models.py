"""
Reporting tables.

    ReportTemplate (versioned) ── ReportInstance: one report for a plan, period and unit
                                   draft → in_review → approved → published (→ withdrawn)
                                   ├─ data: the frozen, normalised inputs (captured at "freeze")
                                   ├─ ReportOutput: HTML / PDF / XLSX, stored once, hashed
                                   └─ ReportAccessLog: created, frozen, submitted, reviewed,
                                      approved, published, previewed, downloaded … (append-only)

Every output is rendered from the frozen data, never from live dashboard queries.
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import JSON, Boolean, Column, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint

from app.database import Base

REPORT_KINDS = ("board_pack", "scorecard_detail", "submission_dq", "exceptions")
AUDIENCES = ("board", "management", "regulator", "internal", "public")
FORMATS = ("html", "pdf", "xlsx")


class ReportTemplate(Base):
    __tablename__ = "report_templates"

    id          = Column(Integer, primary_key=True, autoincrement=True)
    code        = Column(String(40), nullable=False)
    version     = Column(Integer, nullable=False, default=1)
    name        = Column(String(160), nullable=False)
    kind        = Column(String(20), nullable=False)
    description = Column(Text, nullable=True)
    audience    = Column(String(15), nullable=False, default="management")
    config      = Column(JSON, nullable=True)      # e.g. {"sections": [...], "commentary": [...]}
    active      = Column(Boolean, nullable=False, default=True)
    created_by  = Column(String(60), nullable=False)
    created_at  = Column(DateTime, default=datetime.utcnow)

    __table_args__ = (UniqueConstraint("code", "version", name="uq_report_template_version"),)


class ReportInstance(Base):
    __tablename__ = "report_instances"

    id                 = Column(Integer, primary_key=True, autoincrement=True)
    template_id        = Column(Integer, ForeignKey("report_templates.id"), nullable=False)
    template_version   = Column(Integer, nullable=False)
    title              = Column(String(200), nullable=False)
    plan_id            = Column(Integer, ForeignKey("plans.id"), nullable=True)
    period_id          = Column(Integer, ForeignKey("periods.id"), nullable=False)
    org_unit_code      = Column(String(80), nullable=False, index=True)
    audience           = Column(String(15), nullable=False, default="management")
    status             = Column(String(12), nullable=False, default="draft")
    data               = Column(JSON, nullable=True)          # frozen normalised inputs
    data_hash          = Column(String(64), nullable=True)
    data_version       = Column(Integer, nullable=False, default=0)   # times the data was frozen
    frozen_at          = Column(DateTime, nullable=True)
    score_snapshot_ids = Column(JSON, nullable=True)
    commentary         = Column(JSON, nullable=True)          # {section key: text}
    content_hash       = Column(String(64), nullable=True)    # data + commentary + template, at approval
    created_by         = Column(String(60), nullable=False)
    created_at         = Column(DateTime, default=datetime.utcnow)
    submitted_by       = Column(String(60), nullable=True)
    approved_by        = Column(String(60), nullable=True)
    approved_at        = Column(DateTime, nullable=True)
    published_by       = Column(String(60), nullable=True)
    published_at       = Column(DateTime, nullable=True)


class ReportOutput(Base):
    __tablename__ = "report_outputs"

    id           = Column(Integer, primary_key=True, autoincrement=True)
    instance_id  = Column(Integer, ForeignKey("report_instances.id"), nullable=False, index=True)
    format       = Column(String(5), nullable=False)
    content_hash = Column(String(64), nullable=False)    # the instance content it was rendered from
    sha256       = Column(String(64), nullable=False)
    size         = Column(Integer, nullable=False)
    storage_name = Column(String(40), nullable=False)
    generated_by = Column(String(60), nullable=False)
    generated_at = Column(DateTime, default=datetime.utcnow)

    __table_args__ = (UniqueConstraint("instance_id", "format", "content_hash", name="uq_report_output"),)


class ReportAccessLog(Base):
    """Append-only (database triggers)."""
    __tablename__ = "report_access_log"

    id          = Column(Integer, primary_key=True, autoincrement=True)
    instance_id = Column(Integer, ForeignKey("report_instances.id"), nullable=False, index=True)
    output_id   = Column(Integer, ForeignKey("report_outputs.id"), nullable=True)
    action      = Column(String(20), nullable=False)
    actor       = Column(String(60), nullable=False)
    detail      = Column(String(300), nullable=True)
    at          = Column(DateTime, nullable=False, default=datetime.utcnow)
