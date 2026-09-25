"""
Governance and risk tables.

    Meeting ── Resolution ──► Action (platform)
    AuditFinding ──► Action(s)            auditor fields and management fields are kept apart
    RiskMatrix (per organisation: likelihood and impact scales of any size, score bands, appetite)
    Risk ── RiskControl
         ── RiskAssessment (append-only history of inherent / residual ratings)
         ──► Actions (treatments), links to plan objectives
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import JSON, Boolean, Column, Date, DateTime, ForeignKey, Integer, String, Text

from app.database import Base


class Meeting(Base):
    __tablename__ = "meetings"

    id                  = Column(Integer, primary_key=True, autoincrement=True)
    body                = Column(String(80), nullable=False)          # e.g. Board, Audit Committee
    title               = Column(String(200), nullable=False)
    meeting_date        = Column(Date, nullable=False)
    org_unit_code       = Column(String(80), nullable=False, default="org")
    status              = Column(String(20), nullable=False, default="scheduled")  # scheduled | held | minutes_approved
    minutes_document_id = Column(Integer, ForeignKey("documents.id"), nullable=True)
    secretary           = Column(String(60), nullable=True)
    created_by          = Column(String(60), nullable=False)
    created_at          = Column(DateTime, default=datetime.utcnow)


class Resolution(Base):
    __tablename__ = "resolutions"

    id              = Column(Integer, primary_key=True, autoincrement=True)
    meeting_id      = Column(Integer, ForeignKey("meetings.id"), nullable=False, index=True)
    number          = Column(String(40), nullable=False, unique=True)
    text            = Column(Text, nullable=False)
    owner           = Column(String(60), nullable=True)
    due_date        = Column(Date, nullable=True)
    org_unit_code   = Column(String(80), nullable=False, default="org")
    status          = Column(String(15), nullable=False, default="open")   # open | implemented | closed | cancelled
    action_id       = Column(Integer, ForeignKey("actions.id"), nullable=True)
    implementation_note = Column(Text, nullable=True)
    created_by      = Column(String(60), nullable=False)
    created_at      = Column(DateTime, default=datetime.utcnow)


class AuditFinding(Base):
    __tablename__ = "audit_findings"

    id                  = Column(Integer, primary_key=True, autoincrement=True)
    ref                 = Column(String(30), nullable=False, unique=True)
    audit_name          = Column(String(200), nullable=False)
    source              = Column(String(20), nullable=False, default="internal_audit")
    title               = Column(String(250), nullable=False)
    description         = Column(Text, nullable=True)
    recommendation      = Column(Text, nullable=True)
    rating              = Column(String(20), nullable=False)
    org_unit_code       = Column(String(80), nullable=False, index=True)
    auditor             = Column(String(60), nullable=False)
    owner               = Column(String(60), nullable=False)             # management owner
    status              = Column(String(20), nullable=False, default="open")
    management_response = Column(Text, nullable=True)
    agreed_due_date     = Column(Date, nullable=True)
    responded_by        = Column(String(60), nullable=True)
    responded_at        = Column(DateTime, nullable=True)
    closure_note        = Column(Text, nullable=True)
    validated_by        = Column(String(60), nullable=True)
    validated_at        = Column(DateTime, nullable=True)
    created_at          = Column(DateTime, default=datetime.utcnow)


class RiskMatrix(Base):
    __tablename__ = "risk_matrices"

    id                = Column(Integer, primary_key=True, autoincrement=True)
    name              = Column(String(120), nullable=False)
    likelihood_levels = Column(JSON, nullable=False)    # [{"value": 1, "label": "Rare", "description": ...}]
    impact_levels     = Column(JSON, nullable=False)
    bands             = Column(JSON, nullable=False)    # [{"min": 1, "max": 4, "label": "Low", "appetite": "within"}]
    active            = Column(Boolean, nullable=False, default=False)
    created_by        = Column(String(60), nullable=False)
    created_at        = Column(DateTime, default=datetime.utcnow)
    approved_by       = Column(String(60), nullable=True)
    approved_at       = Column(DateTime, nullable=True)


class Risk(Base):
    __tablename__ = "risks"

    id            = Column(Integer, primary_key=True, autoincrement=True)
    code          = Column(String(20), nullable=False, unique=True)
    title         = Column(String(250), nullable=False)
    description   = Column(Text, nullable=True)
    category      = Column(String(60), nullable=True)
    cause         = Column(Text, nullable=True)
    consequence   = Column(Text, nullable=True)
    owner         = Column(String(60), nullable=False)
    org_unit_code = Column(String(80), nullable=False, index=True)
    matrix_id     = Column(Integer, ForeignKey("risk_matrices.id"), nullable=False)
    inherent_l    = Column(Integer, nullable=True)
    inherent_i    = Column(Integer, nullable=True)
    residual_l    = Column(Integer, nullable=True)
    residual_i    = Column(Integer, nullable=True)
    status        = Column(String(10), nullable=False, default="open")      # open | closed
    review_date   = Column(Date, nullable=True)
    created_by    = Column(String(60), nullable=False)
    created_at    = Column(DateTime, default=datetime.utcnow)


class RiskControl(Base):
    __tablename__ = "risk_controls"

    id            = Column(Integer, primary_key=True, autoincrement=True)
    risk_id       = Column(Integer, ForeignKey("risks.id"), nullable=False, index=True)
    description   = Column(Text, nullable=False)
    control_type  = Column(String(12), nullable=False, default="preventive")   # preventive | detective | corrective
    owner         = Column(String(60), nullable=True)
    effectiveness = Column(String(15), nullable=False, default="not_tested")   # effective | partly | ineffective | not_tested
    last_tested   = Column(Date, nullable=True)
    retired       = Column(Boolean, nullable=False, default=False)


class RiskAssessment(Base):
    """Append-only: every change of an inherent or residual rating."""
    __tablename__ = "risk_assessments"

    id          = Column(Integer, primary_key=True, autoincrement=True)
    risk_id     = Column(Integer, ForeignKey("risks.id"), nullable=False, index=True)
    kind        = Column(String(10), nullable=False)      # inherent | residual
    likelihood  = Column(Integer, nullable=False)
    impact      = Column(Integer, nullable=False)
    score       = Column(Integer, nullable=False)
    band        = Column(String(40), nullable=True)
    note        = Column(Text, nullable=True)
    assessed_by = Column(String(60), nullable=False)
    assessed_at = Column(DateTime, nullable=False, default=datetime.utcnow)
