from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.database import get_db
from app.services.governance import (
    build_chart_governance_registry,
    build_compliance_overview,
    build_data_quality_status,
    build_evidence_ladder,
    build_governance_bundle,
    build_page_export_governance,
    build_kpi_governance_status,
    build_page_visual_standards,
    build_water_quality_module,
)

router = APIRouter(prefix="/api/compliance", tags=["Compliance"])


@router.get("/overview")
def compliance_overview(db: Session = Depends(get_db)):
    return build_compliance_overview(db)


@router.get("/water-quality")
def water_quality_module(db: Session = Depends(get_db)):
    return build_water_quality_module(db)


@router.get("/data-quality-status")
def data_quality_status(db: Session = Depends(get_db)):
    return build_data_quality_status(db)


@router.get("/kpi-governance")
def kpi_governance():
    return build_kpi_governance_status()


@router.get("/chart-standards")
def chart_standards():
    return build_chart_governance_registry()


@router.get("/page-standards")
def page_standards():
    return build_page_visual_standards()


@router.get("/governance-bundle")
def governance_bundle():
    return build_governance_bundle()



@router.get("/kpi-definitions")
def kpi_definitions():
    return build_kpi_governance_status()


@router.get("/evidence-ladder")
def evidence_ladder():
    return build_evidence_ladder()


@router.get("/page-export-governance")
def page_export_governance(page_key: str | None = None, db: Session = Depends(get_db)):
    return build_page_export_governance(db, page_key=page_key)
