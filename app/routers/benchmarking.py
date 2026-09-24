"""
routers/benchmarking.py
───────────────────────
Serves the SRWB Benchmarking Tool (WUP001–WUP107) as a filtered report,
sourced live from the records table.

GET /api/benchmarking/indicators  — ordered indicator metadata (+ sections)
GET /api/benchmarking/monthly      — per-month derived values for the selection

Both honour the same zones / schemes / months / year filters used by the rest
of the dashboard, so the global slicer state "just works" on this page.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.database import get_db
from app.services.benchmarking import build_benchmarking, indicator_metadata

router = APIRouter(prefix="/api/benchmarking", tags=["Benchmarking"])


@router.get("/indicators")
def benchmarking_indicators() -> List[Dict[str, Any]]:
    """Static metadata — the frontend builds its report rows from this."""
    return indicator_metadata()


@router.get("/monthly")
def benchmarking_monthly(
    zones: Optional[str] = Query(None),
    schemes: Optional[str] = Query(None),
    months: Optional[str] = Query(None),
    year: Optional[int] = Query(None),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    """Derived WUP indicator values per FY month for the selected scope."""
    return build_benchmarking(zones, schemes, months, year, db)
