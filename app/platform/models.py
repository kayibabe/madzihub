"""
Shared governance tables.

    Period ──────────── status open|locked; reopening needs a reason (audited)
    UserOrgRole ─────── user × org unit × role; a grant covers the unit and everything below it
    UserFunction ────── organisation-wide duties (auditor, risk manager, HR officer ...)
    AuditEvent ──────── append-only: who did what to which record, before/after, why
    ApprovalStep ────── each verify/approve/return decision on any typed workflow
    Action ──────────── owned, dated follow-up work, raised by any module
    EntityLink ──────── typed relation between two records, optionally pinned to a version
    Comment ─────────── discussion on a record (never edited in place)
    Notification ────── in-app notice for one user
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    JSON, Column, Date, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint,
)

from app.database import Base

PERIOD_TYPES = ("month", "quarter", "year")
PERIOD_STATUSES = ("open", "locked")

# Roles granted on an organisational unit, lowest to highest. A higher role includes the lower ones.
SCOPE_ROLES = ("viewer", "contributor", "reviewer", "approver")

# Organisation-wide duties. Administrators hold every duty except the private HR one,
# which must be granted explicitly so that appraisal data is never visible by default.
FUNCTIONS = (
    "strategy_manager",     # plans, indicators, cycles, scoring schemes
    "report_manager",       # report templates and instances
    "document_controller",  # document types, controlled documents
    "board_secretary",      # meetings and resolutions
    "auditor",              # audit findings: ratings, validation, closure
    "risk_manager",         # risk criteria and register oversight
    "regulatory_officer",   # regulator packs and returns
    "hr_officer",           # performance contracts and staff appraisals (private)
)
PRIVATE_FUNCTIONS = ("hr_officer",)

ACTION_STATUSES = ("open", "in_progress", "completed", "closed", "cancelled")
ACTION_PRIORITIES = ("low", "medium", "high", "critical")


class Period(Base):
    __tablename__ = "periods"

    id          = Column(Integer, primary_key=True, autoincrement=True)
    period_type = Column(String(10), nullable=False)
    start_date  = Column(Date, nullable=False)
    end_date    = Column(Date, nullable=False)
    label       = Column(String(40), nullable=False)
    fiscal_year = Column(Integer, nullable=False, index=True)   # FY-end year
    status      = Column(String(10), nullable=False, default="open")
    locked_at   = Column(DateTime, nullable=True)
    locked_by   = Column(String(60), nullable=True)
    created_at  = Column(DateTime, default=datetime.utcnow)

    __table_args__ = (UniqueConstraint("period_type", "start_date", name="uq_period_type_start"),)


class UserOrgRole(Base):
    __tablename__ = "user_org_roles"

    id            = Column(Integer, primary_key=True, autoincrement=True)
    user_id       = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    org_unit_code = Column(String(80), nullable=False)
    role          = Column(String(20), nullable=False, default="viewer")
    granted_by    = Column(String(60), nullable=True)
    granted_at    = Column(DateTime, default=datetime.utcnow)

    __table_args__ = (UniqueConstraint("user_id", "org_unit_code", name="uq_user_org_role"),)


class UserFunction(Base):
    __tablename__ = "user_functions"

    id         = Column(Integer, primary_key=True, autoincrement=True)
    user_id    = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    function   = Column(String(40), nullable=False)
    granted_by = Column(String(60), nullable=True)
    granted_at = Column(DateTime, default=datetime.utcnow)

    __table_args__ = (UniqueConstraint("user_id", "function", name="uq_user_function"),)


class AuditEvent(Base):
    """Append-only. The migration adds triggers that reject UPDATE and DELETE."""
    __tablename__ = "audit_events"

    id            = Column(Integer, primary_key=True, autoincrement=True)
    at            = Column(DateTime, nullable=False, default=datetime.utcnow, index=True)
    actor         = Column(String(60), nullable=False, index=True)
    action        = Column(String(80), nullable=False)
    entity_type   = Column(String(40), nullable=False)
    entity_id     = Column(String(40), nullable=False)
    org_unit_code = Column(String(80), nullable=True)
    before        = Column(JSON, nullable=True)
    after         = Column(JSON, nullable=True)
    reason        = Column(Text, nullable=True)
    request_id    = Column(String(64), nullable=True)

    __table_args__ = (Index("ix_audit_events_entity", "entity_type", "entity_id"),)


class ApprovalStep(Base):
    __tablename__ = "approval_steps"

    id          = Column(Integer, primary_key=True, autoincrement=True)
    entity_type = Column(String(40), nullable=False)
    entity_id   = Column(String(40), nullable=False)
    step        = Column(String(30), nullable=False)       # submit | verify | approve | review | publish ...
    decision    = Column(String(20), nullable=False)       # approved | returned | rejected | submitted
    actor       = Column(String(60), nullable=False)
    comment     = Column(Text, nullable=True)
    at          = Column(DateTime, nullable=False, default=datetime.utcnow)

    __table_args__ = (Index("ix_approval_steps_entity", "entity_type", "entity_id"),)


class Action(Base):
    __tablename__ = "actions"

    id              = Column(Integer, primary_key=True, autoincrement=True)
    ref             = Column(String(20), nullable=False, unique=True)
    title           = Column(String(200), nullable=False)
    description     = Column(Text, nullable=True)
    owner           = Column(String(60), nullable=False, index=True)
    org_unit_code   = Column(String(80), nullable=False, index=True)
    due_date        = Column(Date, nullable=True)
    priority        = Column(String(10), nullable=False, default="medium")
    status          = Column(String(15), nullable=False, default="open", index=True)
    source_type     = Column(String(40), nullable=True)    # e.g. evaluation_response, audit_finding, risk
    source_id       = Column(String(40), nullable=True)
    progress_note   = Column(Text, nullable=True)
    completion_note = Column(Text, nullable=True)
    completed_at    = Column(DateTime, nullable=True)
    closed_by       = Column(String(60), nullable=True)
    created_by      = Column(String(60), nullable=False)
    created_at      = Column(DateTime, default=datetime.utcnow)
    updated_at      = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (Index("ix_actions_source", "source_type", "source_id"),)


class EntityLink(Base):
    __tablename__ = "entity_links"

    id         = Column(Integer, primary_key=True, autoincrement=True)
    from_type  = Column(String(40), nullable=False)
    from_id    = Column(String(40), nullable=False)
    to_type    = Column(String(40), nullable=False)
    to_id      = Column(String(40), nullable=False)
    to_version = Column(Integer, nullable=True)             # pin: exact document version, plan version ...
    relation   = Column(String(40), nullable=False, default="related")
    note       = Column(String(300), nullable=True)
    created_by = Column(String(60), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    __table_args__ = (
        UniqueConstraint("from_type", "from_id", "to_type", "to_id", "relation", "to_version",
                         name="uq_entity_link"),
        Index("ix_entity_links_from", "from_type", "from_id"),
        Index("ix_entity_links_to", "to_type", "to_id"),
    )


class Comment(Base):
    __tablename__ = "comments"

    id          = Column(Integer, primary_key=True, autoincrement=True)
    entity_type = Column(String(40), nullable=False)
    entity_id   = Column(String(40), nullable=False)
    author      = Column(String(60), nullable=False)
    body        = Column(Text, nullable=False)
    created_at  = Column(DateTime, default=datetime.utcnow)

    __table_args__ = (Index("ix_comments_entity", "entity_type", "entity_id"),)


class Notification(Base):
    __tablename__ = "notifications"

    id          = Column(Integer, primary_key=True, autoincrement=True)
    username    = Column(String(60), nullable=False, index=True)
    kind        = Column(String(40), nullable=False)
    title       = Column(String(200), nullable=False)
    body        = Column(Text, nullable=True)
    entity_type = Column(String(40), nullable=True)
    entity_id   = Column(String(40), nullable=True)
    dedupe_key  = Column(String(120), nullable=True)        # one reminder per key (e.g. action overdue on a date)
    created_at  = Column(DateTime, default=datetime.utcnow)
    read_at     = Column(DateTime, nullable=True)

    __table_args__ = (UniqueConstraint("username", "dedupe_key", name="uq_notification_dedupe"),)
