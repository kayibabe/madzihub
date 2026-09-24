"""Housekeeping for the governance foundation (idempotent, additive only).

- ``ensure_org_tree``: the root unit (``org``) and the tenant's top-level units
  (zones/regions), so access can be granted before any data is loaded. Run by an
  administrator (Access page, or the demo seed); not at start-up.
- ``ensure_current_periods``: the current fiscal year's periods (run at start-up).

Nothing existing is changed or removed.
"""
from __future__ import annotations

from datetime import date

from sqlalchemy.orm import Session

from app.integration.connectors import legacy_org_code
from app.integration.models import OrgUnit
from app.platform import periods
from app.platform.scope import ROOT_ORG


def ensure_org_tree(db: Session) -> int:
    from app.core.tenant import tenant

    created = 0
    root = db.query(OrgUnit).filter_by(code=ROOT_ORG).first()
    if root is None:
        root = OrgUnit(code=ROOT_ORG, name=tenant.identity.name, unit_type="organisation")
        db.add(root)
        db.flush()
        created += 1
    level = tenant.hierarchy.levels[0].label.lower() if tenant.hierarchy.levels else "zone"
    existing = {c for (c,) in db.query(OrgUnit.code)}
    for zone in tenant.hierarchy.zones:
        code = legacy_org_code(zone.name)
        if code not in existing:
            db.add(OrgUnit(code=code, name=zone.name, unit_type=level, parent_id=root.id))
            created += 1
    return created


def ensure_current_periods(db: Session, today: date | None = None) -> None:
    from app.utils import fy_end_year
    today = today or date.today()
    periods.ensure_fiscal_year(db, fy_end_year(today.year, today.month))


def at_startup(db: Session) -> None:
    ensure_current_periods(db)
    db.commit()
