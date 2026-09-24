"""
Registry of record types that links, comments and evidence can point at.

Each module registers its types with a loader and the unit that governs access, so
generic features (links, comments, notifications, evidence) apply the same scope
rule as the owning module. An unregistered type is refused, never guessed.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from sqlalchemy.orm import Session

from app.platform.errors import Invalid, NotFound
from app.platform.scope import Scope


@dataclass(frozen=True)
class EntityType:
    key: str
    label: str
    model: Any
    unit_of: Callable[[Any], str | None]
    title_of: Callable[[Any], str]
    # Visibility rule that replaces the plain unit check, for records seen through several
    # units (indicators) or with extra restrictions (private HR records, restricted documents).
    # It must apply the scope itself.
    can_view: Callable[[Scope, Any], bool] | None = None
    # Valid version numbers, for records that can be pinned (documents, plans).
    versions_of: Callable[[Session, Any], set[int]] | None = None
    # Page the UI opens for this record.
    page: str | None = None


REGISTRY: dict[str, EntityType] = {}


def register(entity: EntityType) -> None:
    REGISTRY[entity.key] = entity


def entity_type(key: str) -> EntityType:
    et = REGISTRY.get(key)
    if et is None:
        raise Invalid(f"Unknown record type '{key}'.")
    return et


def load(db: Session, scope: Scope, key: str, entity_id: Any, role: str = "viewer") -> tuple[Any, EntityType]:
    """The record if the user may see it (and hold ``role`` on its unit); otherwise NotFound/Forbidden."""
    et = entity_type(key)
    try:
        pk = int(entity_id)
    except (TypeError, ValueError):
        raise NotFound(f"{et.label} not found.")
    obj = db.get(et.model, pk)
    if obj is None:
        raise NotFound(f"{et.label} not found.")
    unit = et.unit_of(obj)
    # can_view, when a type defines it, replaces the plain unit check (it must apply scope itself).
    if et.can_view is not None:
        if not et.can_view(scope, obj):
            raise NotFound(f"{et.label} not found.")
    else:
        scope.require_see(unit, et.label)
    if role != "viewer":
        scope.require(unit, role, et.label.lower())
    return obj, et


def visible(db: Session, scope: Scope, key: str, entity_id: Any) -> bool:
    try:
        load(db, scope, key, entity_id)
        return True
    except (NotFound, Invalid):
        return False


def describe(db: Session, key: str, entity_id: Any) -> dict:
    """Label for display (caller has already checked visibility)."""
    et = REGISTRY.get(key)
    obj = db.get(et.model, int(entity_id)) if et else None
    return {"type": key, "id": str(entity_id), "type_label": et.label if et else key,
            "title": et.title_of(obj) if obj is not None else "(deleted)", "page": et.page if et else None,
            "org_unit_code": et.unit_of(obj) if obj is not None else None}
