"""
People tables (private HR data).

    HrPolicyConfirmation: the organisation's approved HR policy reference for a module; without an
                          active confirmation (and the module switched on in tenant.yaml) nothing works
    PerformanceContract ── ContractItem (indicator × weight): unit-level accountability, scored on
                           the approved scoring scheme from published values
    StaffAppraisal: objectives, self-assessment, appraiser assessment, acknowledgement, appeal

Private by design: an appraisal is visible only to the employee, the appraiser and HR officers
(an explicit duty that administrators do not hold implicitly). Its audit history is excluded
from the general audit trail.
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import JSON, Boolean, Column, DateTime, Float, ForeignKey, Integer, String, Text

from app.database import Base


class HrPolicyConfirmation(Base):
    __tablename__ = "hr_policy_confirmations"

    id           = Column(Integer, primary_key=True, autoincrement=True)
    module       = Column(String(30), nullable=False)          # performance_contracts | staff_appraisal
    policy_ref   = Column(String(200), nullable=False)          # e.g. "HR Manual 2025 §7, Board res. B/2025/014"
    summary      = Column(Text, nullable=True)
    active       = Column(Boolean, nullable=False, default=True)
    confirmed_by = Column(String(60), nullable=False)
    confirmed_at = Column(DateTime, default=datetime.utcnow)


class PerformanceContract(Base):
    __tablename__ = "performance_contracts"

    id              = Column(Integer, primary_key=True, autoincrement=True)
    plan_id         = Column(Integer, ForeignKey("plans.id"), nullable=False)
    period_id       = Column(Integer, ForeignKey("periods.id"), nullable=False)   # usually the fiscal year
    org_unit_code   = Column(String(80), nullable=False, index=True)
    holder          = Column(String(60), nullable=False)       # accountable manager
    supervisor      = Column(String(60), nullable=False)
    status          = Column(String(20), nullable=False, default="draft")
    evaluation      = Column(JSON, nullable=True)                # frozen scoring result at evaluation
    final_rating    = Column(Float, nullable=True)
    final_label     = Column(String(60), nullable=True)
    appeal_reason   = Column(Text, nullable=True)
    appeal_decision = Column(Text, nullable=True)
    created_by      = Column(String(60), nullable=False)
    created_at      = Column(DateTime, default=datetime.utcnow)


class ContractItem(Base):
    __tablename__ = "contract_items"

    id           = Column(Integer, primary_key=True, autoincrement=True)
    contract_id  = Column(Integer, ForeignKey("performance_contracts.id", ondelete="CASCADE"), nullable=False, index=True)
    indicator_id = Column(Integer, ForeignKey("indicators.id"), nullable=False)
    weight       = Column(Float, nullable=False)


class StaffAppraisal(Base):
    __tablename__ = "staff_appraisals"

    id                   = Column(Integer, primary_key=True, autoincrement=True)
    employee             = Column(String(60), nullable=False, index=True)
    appraiser            = Column(String(60), nullable=False, index=True)
    period_label         = Column(String(40), nullable=False)
    status               = Column(String(20), nullable=False, default="draft")
    objectives           = Column(JSON, nullable=False)          # [{"title", "weight", "measure"}]
    self_assessment      = Column(JSON, nullable=True)           # {"ratings": {i: n}, "comment"}
    appraiser_assessment = Column(JSON, nullable=True)
    overall_rating       = Column(Float, nullable=True)
    employee_comment     = Column(Text, nullable=True)
    appeal_reason        = Column(Text, nullable=True)
    appeal_decision      = Column(Text, nullable=True)
    created_by           = Column(String(60), nullable=False)
    created_at           = Column(DateTime, default=datetime.utcnow)
