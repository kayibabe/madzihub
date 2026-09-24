"""
routers/reports.py

Unified monthly-report endpoint. The dashboard report pages now depend on the
same deduped monthly payload builder used by the panel endpoints so new source
fields stay visible across both APIs.
"""
from __future__ import annotations

from typing import Optional, List, Dict, Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.database import get_db
from app.routers.panels import _base

router = APIRouter(prefix="/api/reports", tags=["Reports"])


@router.get("/monthly")
def reports_monthly(
    zones: Optional[str] = Query(None),
    schemes: Optional[str] = Query(None),
    months: Optional[str] = Query(None),
    year: Optional[int] = Query(None),
    db: Session = Depends(get_db),
) -> List[Dict[str, Any]]:
    """
    Return one deduped record per FY month with the full report payload.

    This endpoint intentionally mirrors the shared monthly builder used by
    `/api/panels/*` so newly ingested workbook fields are available to any
    report consumer without maintaining a second aggregation implementation.
    """
    _, _, monthly = _base(zones, schemes, months, year, db)
    return monthly
