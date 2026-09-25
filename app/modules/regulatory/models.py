"""
Regulatory tables.

    RegulatorPack (regulator × cycle × version; draft → approved → retired)
      content: indicators (code, name, definition, unit, polarity, cluster, weight, scoring bands,
               validation rules, verification status and source reference), peer groups,
               export template, method notes
    RegulatoryReturn ── ReturnValue (raw values as submitted/entered, with their source; never
                        overwritten: a correction is a new row that supersedes the old one)
    LeagueTableRun: a saved calculation (inputs, results, inputs hash) on an approved pack

An internal plan score is never presented as a regulator score, and a regulator score is only
calculated on an approved pack.
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import JSON, Column, Date, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint

from app.database import Base


class RegulatorPack(Base):
    __tablename__ = "regulator_packs"

    id              = Column(Integer, primary_key=True, autoincrement=True)
    regulator       = Column(String(40), nullable=False)
    jurisdiction    = Column(String(60), nullable=False)
    cycle           = Column(String(40), nullable=False)          # e.g. FY2023/24 (IMPACT 17)
    version         = Column(Integer, nullable=False, default=1)
    title           = Column(String(200), nullable=False)
    method          = Column(String(30), nullable=False)          # weighted_points
    source_title    = Column(String(300), nullable=False)
    source_url      = Column(String(500), nullable=True)
    source_accessed = Column(Date, nullable=True)
    effective_from  = Column(Date, nullable=True)
    effective_to    = Column(Date, nullable=True)
    content         = Column(JSON, nullable=False)
    content_hash    = Column(String(64), nullable=False)
    status          = Column(String(10), nullable=False, default="draft")
    imported_by     = Column(String(60), nullable=False)
    imported_at     = Column(DateTime, default=datetime.utcnow)
    approved_by     = Column(String(60), nullable=True)
    approved_at     = Column(DateTime, nullable=True)

    __table_args__ = (UniqueConstraint("regulator", "cycle", "version", name="uq_regulator_pack_version"),)


class RegulatoryReturn(Base):
    __tablename__ = "regulatory_returns"

    id            = Column(Integer, primary_key=True, autoincrement=True)
    pack_id       = Column(Integer, ForeignKey("regulator_packs.id"), nullable=False, index=True)
    org_unit_code = Column(String(80), nullable=False, default="org")
    period_label  = Column(String(40), nullable=False)
    status        = Column(String(12), nullable=False, default="draft")    # draft | submitted
    submitted_by  = Column(String(60), nullable=True)
    submitted_at  = Column(DateTime, nullable=True)
    created_by    = Column(String(60), nullable=False)
    created_at    = Column(DateTime, default=datetime.utcnow)


class ReturnValue(Base):
    """Append-only raw values; the latest row per indicator is current."""
    __tablename__ = "return_values"

    id             = Column(Integer, primary_key=True, autoincrement=True)
    return_id      = Column(Integer, ForeignKey("regulatory_returns.id"), nullable=False, index=True)
    indicator_code = Column(String(40), nullable=False)
    raw_value      = Column(Float, nullable=True)
    raw_text       = Column(String(200), nullable=True)
    source         = Column(String(120), nullable=False)       # manual | metric:<code> (with period)
    note           = Column(Text, nullable=True)
    entered_by     = Column(String(60), nullable=False)
    entered_at     = Column(DateTime, nullable=False, default=datetime.utcnow)


class LeagueTableRun(Base):
    __tablename__ = "league_table_runs"

    id          = Column(Integer, primary_key=True, autoincrement=True)
    pack_id     = Column(Integer, ForeignKey("regulator_packs.id"), nullable=False, index=True)
    return_id   = Column(Integer, ForeignKey("regulatory_returns.id"), nullable=True)
    label       = Column(String(200), nullable=False)
    inputs      = Column(JSON, nullable=False)        # own values + peer values used
    results     = Column(JSON, nullable=False)
    inputs_hash = Column(String(64), nullable=False)
    pack_hash   = Column(String(64), nullable=False)
    created_by  = Column(String(60), nullable=False)
    created_at  = Column(DateTime, default=datetime.utcnow)
