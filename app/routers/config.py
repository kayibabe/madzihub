"""
routers/config.py — installation configuration for the UI
==========================================================
    GET /api/config/public  → name, title, colours, logo (no auth; login screen)
    GET /api/config/logo    → the tenant logo, or the neutral MadziHub mark
    GET /api/config         → full client configuration (authenticated)

Identity fields edited by an administrator in the organisation profile
(org_profile table) override the tenant YAML; everything else comes from
tenants/<MADZI_TENANT>/tenant.yaml.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict

from fastapi import APIRouter, Depends
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.auth import get_current_user
from app.core.tenant import tenant
from app.database import OrgProfile, get_db

router = APIRouter(prefix="/api/config", tags=["Configuration"])

DEFAULT_LOGO = Path(__file__).resolve().parents[1] / "static" / "brand" / "madzihub-mark.svg"

# org_profile column → identity key
_ORG_OVERRIDES = {
    "org_name": "name", "short_name": "short_name", "regulator": "regulator",
    "country": "country", "registration_no": "registration_no",
    "contact_email": "contact_email", "contact_phone": "contact_phone",
    "website": "website", "service_area_km2": "service_area_km2",
    "population_served": "population_served",
}


def _apply_org_profile(cfg: Dict[str, Any], db: Session) -> Dict[str, Any]:
    profile = db.query(OrgProfile).filter(OrgProfile.id == 1).first()
    if not profile:
        return cfg
    identity = dict(cfg.get("identity") or {})
    for col, key in _ORG_OVERRIDES.items():
        value = getattr(profile, col, None)
        if value not in (None, ""):
            identity[key] = value
    cfg["identity"] = identity
    cfg["name"] = identity.get("name", cfg.get("name"))
    cfg["short_name"] = identity.get("short_name", cfg.get("short_name"))
    return cfg


@router.get("/public")
def public_config(db: Session = Depends(get_db)) -> Dict[str, Any]:
    cfg = tenant.public_dict()
    cfg["identity"] = tenant.identity.model_dump()
    cfg = _apply_org_profile(cfg, db)
    cfg.pop("identity")
    return cfg


@router.get("/logo", include_in_schema=False)
def logo():
    path = tenant.logo_path or DEFAULT_LOGO
    return FileResponse(path, headers={"Cache-Control": "public, max-age=3600"})


@router.get("", dependencies=[Depends(get_current_user)])
def client_config(db: Session = Depends(get_db)) -> Dict[str, Any]:
    return _apply_org_profile(tenant.client_dict(), db)
