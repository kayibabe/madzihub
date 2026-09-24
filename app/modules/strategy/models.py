"""
Strategy and M&E tables.

    Plan ─┬─ PlanLevel      configurable labels on stable node types
          ├─ PlanNode       results tree (pillar → objective → outcome → output) and
          │                 delivery tree (programme → initiative → activity → milestone);
          │                 delivery work "contributes_to" results through entity_links
          ├─ Indicator      the controlled reference sheet; values live in metric_values
          ├─ ReportingCycle one per plan and period ── CycleAssignment (indicator × unit)
          │                                              └─ ProgressUpdate (append-only revisions)
          │                                                   └─ DqaAssessment (append-only)
          └─ Evaluation ── ManagementResponse ── Action (platform)

"No submission" (no update row), "not applicable", "pending" and a reported zero are
four different states and are never collapsed into each other.
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    JSON, Boolean, Column, Date, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint,
)

from sqlalchemy.orm import relationship

from app.database import Base

RESULT_TYPES = ("pillar", "objective", "outcome", "output")
DELIVERY_TYPES = ("programme", "initiative", "activity", "milestone")
NODE_TYPES = RESULT_TYPES + DELIVERY_TYPES
DEFAULT_LABELS = {"pillar": "Strategic pillar", "objective": "Strategic objective", "outcome": "Outcome",
                  "output": "Output", "programme": "Programme", "initiative": "Initiative",
                  "activity": "Activity", "milestone": "Milestone"}
DELIVERY_STATUSES = ("not_started", "on_track", "at_risk", "off_track", "completed", "cancelled")
POLARITIES = ("higher", "lower", "range", "milestone", "yes_no", "kri")
FREQUENCIES = ("month", "quarter", "year")
VALUE_STATES = ("reported", "not_applicable", "pending")
DQA_CHECKS = ("validity", "range", "completeness", "timeliness", "consistency", "evidence", "reviewer")
DQA_RESULTS = ("pass", "warn", "fail")


class Plan(Base):
    __tablename__ = "plans"

    id          = Column(Integer, primary_key=True, autoincrement=True)
    code        = Column(String(40), nullable=False, unique=True)
    title       = Column(String(200), nullable=False)
    description = Column(Text, nullable=True)
    start_fy    = Column(Integer, nullable=False)          # FY-end years
    end_fy      = Column(Integer, nullable=False)
    status      = Column(String(12), nullable=False, default="draft")   # draft | active | archived
    created_by  = Column(String(60), nullable=False)
    created_at  = Column(DateTime, default=datetime.utcnow)
    approved_by = Column(String(60), nullable=True)
    approved_at = Column(DateTime, nullable=True)


class PlanLevel(Base):
    __tablename__ = "plan_levels"

    id        = Column(Integer, primary_key=True, autoincrement=True)
    plan_id   = Column(Integer, ForeignKey("plans.id", ondelete="CASCADE"), nullable=False, index=True)
    node_type = Column(String(20), nullable=False)
    label     = Column(String(60), nullable=False)
    plural    = Column(String(60), nullable=True)
    enabled   = Column(Boolean, nullable=False, default=True)

    __table_args__ = (UniqueConstraint("plan_id", "node_type", name="uq_plan_level"),)


class PlanNode(Base):
    __tablename__ = "plan_nodes"

    id            = Column(Integer, primary_key=True, autoincrement=True)
    plan_id       = Column(Integer, ForeignKey("plans.id", ondelete="CASCADE"), nullable=False, index=True)
    parent_id     = Column(Integer, ForeignKey("plan_nodes.id"), nullable=True, index=True)
    node_type     = Column(String(20), nullable=False)
    code          = Column(String(40), nullable=False)
    title         = Column(String(250), nullable=False)
    description   = Column(Text, nullable=True)
    owner         = Column(String(60), nullable=True)
    org_unit_code = Column(String(80), nullable=False, default="org")
    weight        = Column(Float, nullable=True)            # share among weighted siblings (scorecard)
    sort_order    = Column(Integer, nullable=False, default=0)
    start_date    = Column(Date, nullable=True)
    end_date      = Column(Date, nullable=True)
    status        = Column(String(15), nullable=False, default="not_started")
    budget        = Column(Float, nullable=True)
    retired       = Column(Boolean, nullable=False, default=False)
    created_at    = Column(DateTime, default=datetime.utcnow)

    __table_args__ = (UniqueConstraint("plan_id", "code", name="uq_plan_node_code"),)


class Indicator(Base):
    """Controlled reference sheet. Definition changes bump ``version`` and are audited."""
    __tablename__ = "indicators"

    id                = Column(Integer, primary_key=True, autoincrement=True)
    plan_id           = Column(Integer, ForeignKey("plans.id", ondelete="CASCADE"), nullable=False, index=True)
    node_id           = Column(Integer, ForeignKey("plan_nodes.id"), nullable=True, index=True)
    code              = Column(String(40), nullable=False)
    name              = Column(String(200), nullable=False)
    definition        = Column(Text, nullable=True)
    metric_code       = Column(String(80), nullable=False)          # values are read through the catalogue
    polarity          = Column(String(12), nullable=False, default="higher")
    unit              = Column(String(40), nullable=True)
    aggregation       = Column(String(10), nullable=False, default="sum")
    formula_text      = Column(Text, nullable=True)
    source            = Column(String(200), nullable=True)
    owner             = Column(String(60), nullable=True)
    org_unit_code     = Column(String(80), nullable=False, default="org")
    reporting_units   = Column(JSON, nullable=True)                 # units that report; default [org_unit_code]
    collection        = Column(String(10), nullable=False, default="manual")   # manual | automatic
    baseline_value    = Column(Float, nullable=True)
    baseline_date     = Column(Date, nullable=True)
    target_basis      = Column(String(200), nullable=True)
    frequency         = Column(String(10), nullable=False, default="quarter")
    evidence_required = Column(Boolean, nullable=False, default=False)
    dq_notes          = Column(Text, nullable=True)
    valid_min         = Column(Float, nullable=True)
    valid_max         = Column(Float, nullable=True)
    weight            = Column(Float, nullable=True)
    version           = Column(Integer, nullable=False, default=1)
    status            = Column(String(10), nullable=False, default="active")   # active | retired
    created_by        = Column(String(60), nullable=False)
    created_at        = Column(DateTime, default=datetime.utcnow)
    updated_at        = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (UniqueConstraint("plan_id", "code", name="uq_indicator_code"),)


class ReportingCycle(Base):
    __tablename__ = "reporting_cycles"

    id                   = Column(Integer, primary_key=True, autoincrement=True)
    plan_id              = Column(Integer, ForeignKey("plans.id", ondelete="CASCADE"), nullable=False, index=True)
    period_id            = Column(Integer, ForeignKey("periods.id"), nullable=False)
    name                 = Column(String(120), nullable=False)
    opens_on             = Column(Date, nullable=True)
    due_on               = Column(Date, nullable=True)
    require_verification = Column(Boolean, nullable=False, default=True)
    status               = Column(String(10), nullable=False, default="draft")   # draft | open | closed
    created_by           = Column(String(60), nullable=False)
    created_at           = Column(DateTime, default=datetime.utcnow)

    __table_args__ = (UniqueConstraint("plan_id", "period_id", name="uq_cycle_plan_period"),)


class CycleAssignment(Base):
    __tablename__ = "cycle_assignments"

    id                = Column(Integer, primary_key=True, autoincrement=True)
    cycle_id          = Column(Integer, ForeignKey("reporting_cycles.id", ondelete="CASCADE"), nullable=False, index=True)
    indicator_id      = Column(Integer, ForeignKey("indicators.id"), nullable=False, index=True)
    org_unit_code     = Column(String(80), nullable=False, index=True)
    contributor       = Column(String(60), nullable=True)
    reviewer          = Column(String(60), nullable=True)
    approver          = Column(String(60), nullable=True)
    status            = Column(String(15), nullable=False, default="not_submitted")
    current_update_id = Column(Integer, nullable=True)
    updated_at        = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (UniqueConstraint("cycle_id", "indicator_id", "org_unit_code", name="uq_cycle_assignment"),)


class ProgressUpdate(Base):
    """Append-only: each submission is a new revision; nothing is edited in place."""
    __tablename__ = "progress_updates"

    id                = Column(Integer, primary_key=True, autoincrement=True)
    assignment_id     = Column(Integer, ForeignKey("cycle_assignments.id", ondelete="CASCADE"), nullable=False, index=True)
    revision          = Column(Integer, nullable=False)
    value_state       = Column(String(15), nullable=False)
    value             = Column(Float, nullable=True)
    forecast          = Column(Float, nullable=True)
    narrative         = Column(Text, nullable=True)
    variance_reason   = Column(Text, nullable=True)
    corrective_action = Column(Text, nullable=True)
    evidence_note     = Column(Text, nullable=True)
    value_source      = Column(String(20), nullable=False, default="manual")   # manual | automatic
    submitted_by      = Column(String(60), nullable=False)
    submitted_at      = Column(DateTime, nullable=False, default=datetime.utcnow)
    late              = Column(Boolean, nullable=False, default=False)

    __table_args__ = (UniqueConstraint("assignment_id", "revision", name="uq_update_revision"),)


class DqaAssessment(Base):
    """Append-only data-quality results; a failed check never alters the submitted value."""
    __tablename__ = "dqa_assessments"

    id          = Column(Integer, primary_key=True, autoincrement=True)
    update_id   = Column(Integer, ForeignKey("progress_updates.id", ondelete="CASCADE"), nullable=False, index=True)
    check       = Column(String(20), nullable=False)
    result      = Column(String(6), nullable=False)
    reason      = Column(Text, nullable=True)
    assessed_by = Column(String(60), nullable=False)
    assessed_at = Column(DateTime, nullable=False, default=datetime.utcnow)


class Evaluation(Base):
    __tablename__ = "evaluations"

    id               = Column(Integer, primary_key=True, autoincrement=True)
    plan_id          = Column(Integer, ForeignKey("plans.id", ondelete="CASCADE"), nullable=False, index=True)
    title            = Column(String(200), nullable=False)
    kind             = Column(String(15), nullable=False, default="mid_term")   # mid_term | end_term | thematic | other
    scope            = Column(Text, nullable=True)
    method           = Column(Text, nullable=True)
    criteria         = Column(JSON, nullable=True)       # optional, e.g. OECD DAC criteria
    lead             = Column(String(60), nullable=True)
    org_unit_code    = Column(String(80), nullable=False, default="org")
    start_date       = Column(Date, nullable=True)
    end_date         = Column(Date, nullable=True)
    status           = Column(String(12), nullable=False, default="planned")    # planned | in_progress | completed
    findings_summary = Column(Text, nullable=True)
    limitations      = Column(Text, nullable=True)
    created_by       = Column(String(60), nullable=False)
    created_at       = Column(DateTime, default=datetime.utcnow)


class ManagementResponse(Base):
    __tablename__ = "management_responses"

    id             = Column(Integer, primary_key=True, autoincrement=True)
    evaluation_id  = Column(Integer, ForeignKey("evaluations.id", ondelete="CASCADE"), nullable=False, index=True)
    finding        = Column(Text, nullable=False)
    recommendation = Column(Text, nullable=True)
    response       = Column(String(20), nullable=True)   # accepted | partially_accepted | rejected
    response_text  = Column(Text, nullable=True)
    owner          = Column(String(60), nullable=True)
    due_date       = Column(Date, nullable=True)
    action_id      = Column(Integer, ForeignKey("actions.id"), nullable=True)
    created_by     = Column(String(60), nullable=False)
    created_at     = Column(DateTime, default=datetime.utcnow)
    responded_by   = Column(String(60), nullable=True)
    responded_at   = Column(DateTime, nullable=True)

    evaluation = relationship(Evaluation)
