"""
Scorecard tables.

    ScoringScheme (versioned; draft → approved → retired) ── ScoringBand ×5
    ScoreSnapshot: one calculation for plan × period × unit, frozen with its inputs

A snapshot is never recalculated in place: recalculating creates a new snapshot, and
approving it supersedes the previous approved one. Overrides are stored on the draft
snapshot with their reason (and in the audit trail); approved snapshots are read-only.
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    JSON, Column, Date, DateTime, Float, ForeignKey, Index, Integer, String, Text, UniqueConstraint,
)
from sqlalchemy.orm import relationship

from app.database import Base


class ScoringScheme(Base):
    __tablename__ = "scoring_schemes"

    id                = Column(Integer, primary_key=True, autoincrement=True)
    code              = Column(String(40), nullable=False)
    version           = Column(Integer, nullable=False, default=1)
    name              = Column(String(160), nullable=False)
    description       = Column(Text, nullable=True)
    status            = Column(String(10), nullable=False, default="draft")    # draft | approved | retired
    effective_from    = Column(Date, nullable=True)
    effective_to      = Column(Date, nullable=True)
    rating_order      = Column(String(20), nullable=False, default="higher_is_better")
    cap_pct           = Column(Float, nullable=False, default=130.0)
    zero_target_rule  = Column(String(12), nullable=False, default="unscored")
    lower_method      = Column(String(20), nullable=False, default="linear_deviation")
    missing_policy    = Column(String(20), nullable=False, default="coverage_gate")
    coverage_gate_pct = Column(Float, nullable=False, default=80.0)
    created_by        = Column(String(60), nullable=False)
    created_at        = Column(DateTime, default=datetime.utcnow)
    approved_by       = Column(String(60), nullable=True)
    approved_at       = Column(DateTime, nullable=True)

    bands = relationship("ScoringBand", order_by="ScoringBand.min_achievement", cascade="all, delete-orphan")

    __table_args__ = (UniqueConstraint("code", "version", name="uq_scheme_version"),)


class ScoringBand(Base):
    __tablename__ = "scoring_bands"

    id              = Column(Integer, primary_key=True, autoincrement=True)
    scheme_id       = Column(Integer, ForeignKey("scoring_schemes.id", ondelete="CASCADE"), nullable=False, index=True)
    rating          = Column(Integer, nullable=False)
    label           = Column(String(60), nullable=False)
    min_achievement = Column(Float, nullable=False)
    max_achievement = Column(Float, nullable=True)


class ScoreSnapshot(Base):
    __tablename__ = "score_snapshots"

    id               = Column(Integer, primary_key=True, autoincrement=True)
    plan_id          = Column(Integer, ForeignKey("plans.id"), nullable=False)
    period_id        = Column(Integer, ForeignKey("periods.id"), nullable=False)
    org_unit_code    = Column(String(80), nullable=False)
    scheme_id        = Column(Integer, ForeignKey("scoring_schemes.id"), nullable=False)
    scheme_version   = Column(Integer, nullable=False)
    engine_version   = Column(String(20), nullable=False)
    inputs_hash      = Column(String(64), nullable=False)
    status           = Column(String(12), nullable=False, default="draft")    # draft | approved | superseded
    provisional      = Column(Integer, nullable=False, default=0)             # 1 = scheme not yet approved
    achievement      = Column(Float, nullable=True)
    rating           = Column(Float, nullable=True)
    rating_label     = Column(String(60), nullable=True)
    completeness_pct = Column(Float, nullable=True)
    covered_weight   = Column(Float, nullable=True)
    result           = Column(JSON, nullable=False)      # the full tree with inputs and contributions
    overrides        = Column(JSON, nullable=True)       # {node_key: {rating, label, reason, by, at}}
    note             = Column(Text, nullable=True)
    created_by       = Column(String(60), nullable=False)
    created_at       = Column(DateTime, default=datetime.utcnow)
    approved_by      = Column(String(60), nullable=True)
    approved_at      = Column(DateTime, nullable=True)
    supersedes_id    = Column(Integer, ForeignKey("score_snapshots.id"), nullable=True)

    __table_args__ = (Index("ix_score_snapshots_scope", "plan_id", "period_id", "org_unit_code"),)
