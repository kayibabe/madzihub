"""
Document tables.

    DocumentType ── Document ── DocumentVersion (append-only: file, sha256, extracted text)

- Evidence: a document of an evidence type, linked to the record it supports through an
  ``evidence`` entity link pinned to the exact version. Replacing the file adds a version
  and a new pinned link; the earlier link (and file) stay as history.
- Controlled documents (policies, procedures, plans, forms) carry a number and revision,
  owner, approver, classification, effective and review dates, and move
  draft → approved → effective → superseded (or withdrawn). Files can only be added while
  a document is a draft; a change after approval is a new revision (a new document with the
  same number that supersedes the old one when it becomes effective).
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    JSON, Boolean, Column, Date, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint,
)

from app.database import Base

CLASSIFICATIONS = ("public", "internal", "confidential", "restricted")
DOC_STATUSES = ("draft", "approved", "effective", "superseded", "withdrawn", "active")


class DocumentType(Base):
    __tablename__ = "document_types"

    id                     = Column(Integer, primary_key=True, autoincrement=True)
    code                   = Column(String(30), nullable=False, unique=True)
    name                   = Column(String(120), nullable=False)
    controlled             = Column(Boolean, nullable=False, default=False)
    number_prefix          = Column(String(10), nullable=True)
    review_interval_months = Column(Integer, nullable=True)
    allowed_extensions     = Column(JSON, nullable=False)          # e.g. ["pdf", "docx"]
    metadata_fields        = Column(JSON, nullable=True)           # [{"key", "label", "required"}]
    default_classification = Column(String(15), nullable=False, default="internal")
    active                 = Column(Boolean, nullable=False, default=True)


class Document(Base):
    __tablename__ = "documents"

    id              = Column(Integer, primary_key=True, autoincrement=True)
    type_id         = Column(Integer, ForeignKey("document_types.id"), nullable=False, index=True)
    number          = Column(String(30), nullable=True, index=True)
    revision        = Column(Integer, nullable=False, default=1)
    title           = Column(String(250), nullable=False)
    description     = Column(Text, nullable=True)
    org_unit_code   = Column(String(80), nullable=False, index=True)
    owner           = Column(String(60), nullable=False)
    approver        = Column(String(60), nullable=True)
    classification  = Column(String(15), nullable=False, default="internal")
    status          = Column(String(12), nullable=False, default="draft")
    tags            = Column(JSON, nullable=True)
    doc_metadata    = Column("metadata", JSON, nullable=True)
    effective_date  = Column(Date, nullable=True)
    review_date     = Column(Date, nullable=True)
    supersedes_id   = Column(Integer, ForeignKey("documents.id"), nullable=True)
    current_version = Column(Integer, nullable=False, default=0)
    approved_version = Column(Integer, nullable=True)
    approved_by     = Column(String(60), nullable=True)
    approved_at     = Column(DateTime, nullable=True)
    created_by      = Column(String(60), nullable=False)
    created_at      = Column(DateTime, default=datetime.utcnow)
    updated_at      = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (UniqueConstraint("number", "revision", name="uq_document_number_revision"),)


class DocumentVersion(Base):
    """Append-only (database triggers). The file itself is in the file store."""
    __tablename__ = "document_versions"

    id                = Column(Integer, primary_key=True, autoincrement=True)
    document_id       = Column(Integer, ForeignKey("documents.id"), nullable=False, index=True)
    version           = Column(Integer, nullable=False)
    filename          = Column(String(255), nullable=False)
    extension         = Column(String(10), nullable=False)
    mime              = Column(String(100), nullable=False)
    size              = Column(Integer, nullable=False)
    sha256            = Column(String(64), nullable=False)
    storage_name      = Column(String(40), nullable=False)
    text_content      = Column(Text, nullable=True)
    extraction_status = Column(String(12), nullable=False)       # ok | empty | unsupported | failed
    extraction_error  = Column(String(300), nullable=True)
    change_note       = Column(Text, nullable=True)
    uploaded_by       = Column(String(60), nullable=False)
    uploaded_at       = Column(DateTime, nullable=False, default=datetime.utcnow)

    __table_args__ = (UniqueConstraint("document_id", "version", name="uq_document_version"),)
