"""
routers/insights.py
====================
GET /api/insights/summary   — anomaly alerts for the current FY
GET /api/insights/narrative — AI-generated executive narrative (Groq)
"""
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from app.database import get_db
from app.services.insights_engine import generate_alerts
from app.services.narrative_engine import generate_narrative

router = APIRouter(prefix="/api/insights", tags=["Insights"])

@router.get("/summary")
def get_insights(
    year: int = Query(None, description="Fiscal year end year (e.g. 2026)"),
    db: Session = Depends(get_db),
):
    return generate_alerts(db=db, year=year)

@router.get("/narrative")
def get_narrative(
    year: int = Query(None, description="Fiscal year end year (e.g. 2026)"),
    db: Session = Depends(get_db),
):
    return generate_narrative(db=db, year=year)
