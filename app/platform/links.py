"""Links between records (optionally pinned to a version) and comments on records.

Both apply the owning record's scope: you can only link from a record you may
change, only to a record you may see, and a listing never reveals a linked record
the reader cannot see (it is counted as hidden instead).
"""
from __future__ import annotations

from sqlalchemy import and_, or_
from sqlalchemy.orm import Session

from app.platform import audit, entities
from app.platform.errors import Conflict, Invalid, NotFound
from app.platform.models import Comment, EntityLink
from app.platform.scope import Scope

RELATIONS = ("related", "supports", "contributes_to", "evidence", "mitigates", "treats",
             "responds_to", "supersedes", "derived_from", "implements", "affects")


def add_link(db: Session, scope: Scope, from_type: str, from_id, to_type: str, to_id, *,
             relation: str = "related", to_version: int | None = None, note: str | None = None,
             role: str = "contributor") -> EntityLink:
    if relation not in RELATIONS:
        raise Invalid(f"Relation must be one of {', '.join(RELATIONS)}.")
    src, src_type = entities.load(db, scope, from_type, from_id, role=role)
    dst, dst_type = entities.load(db, scope, to_type, to_id)
    if from_type == to_type and str(from_id) == str(to_id):
        raise Invalid("A record cannot be linked to itself.")
    if to_version is not None:
        if dst_type.versions_of is None:
            raise Invalid(f"{dst_type.label} records have no versions to pin.")
        if to_version not in dst_type.versions_of(db, dst):
            raise Invalid(f"{dst_type.label} has no version {to_version}.")
    exists = db.query(EntityLink.id).filter_by(from_type=from_type, from_id=str(from_id), to_type=to_type,
                                               to_id=str(to_id), relation=relation, to_version=to_version).first()
    if exists:
        raise Conflict("That link already exists.")
    link = EntityLink(from_type=from_type, from_id=str(from_id), to_type=to_type, to_id=str(to_id),
                      relation=relation, to_version=to_version, note=note, created_by=scope.username)
    db.add(link)
    db.flush()
    audit.record(db, scope.username, "link.add", from_type, from_id,
                 after={"to_type": to_type, "to_id": str(to_id), "relation": relation, "to_version": to_version},
                 org_unit_code=src_type.unit_of(src))
    return link


def remove_link(db: Session, scope: Scope, link_id: int, reason: str | None = None) -> None:
    link = db.get(EntityLink, link_id)
    if link is None:
        raise NotFound("Link not found.")
    src, src_type = entities.load(db, scope, link.from_type, link.from_id, role="contributor")
    if link.relation == "evidence" and link.to_version is not None and not (reason or "").strip():
        raise Invalid("Removing pinned evidence needs a reason.")
    audit.record(db, scope.username, "link.remove", link.from_type, link.from_id,
                 before={"to_type": link.to_type, "to_id": link.to_id, "relation": link.relation,
                         "to_version": link.to_version}, reason=reason, org_unit_code=src_type.unit_of(src))
    db.delete(link)


def links_for(db: Session, scope: Scope, entity_type: str, entity_id) -> dict:
    entities.load(db, scope, entity_type, entity_id)
    eid = str(entity_id)
    rows = db.query(EntityLink).filter(or_(
        and_(EntityLink.from_type == entity_type, EntityLink.from_id == eid),
        and_(EntityLink.to_type == entity_type, EntityLink.to_id == eid))).order_by(EntityLink.id).all()
    out, hidden = [], 0
    for r in rows:
        outgoing = r.from_type == entity_type and r.from_id == eid
        other_type, other_id = (r.to_type, r.to_id) if outgoing else (r.from_type, r.from_id)
        if other_type not in entities.REGISTRY or not entities.visible(db, scope, other_type, other_id):
            hidden += 1
            continue
        out.append({"id": r.id, "direction": "outgoing" if outgoing else "incoming", "relation": r.relation,
                    "to_version": r.to_version, "note": r.note, "created_by": r.created_by,
                    "created_at": r.created_at.isoformat() if r.created_at else None,
                    "other": entities.describe(db, other_type, other_id)})
    return {"links": out, "hidden": hidden}


def linked_ids(db: Session, from_type: str, from_id, to_type: str, relation: str | None = None) -> list[EntityLink]:
    q = db.query(EntityLink).filter_by(from_type=from_type, from_id=str(from_id), to_type=to_type)
    if relation:
        q = q.filter(EntityLink.relation == relation)
    return q.all()


def add_comment(db: Session, scope: Scope, entity_type: str, entity_id, body: str) -> Comment:
    obj, et = entities.load(db, scope, entity_type, entity_id)
    if scope.read_only:
        from app.platform.errors import Forbidden
        raise Forbidden("Your account is read-only.")
    body = (body or "").strip()
    if not body:
        raise Invalid("A comment cannot be empty.")
    if len(body) > 5000:
        raise Invalid("Comments are limited to 5000 characters.")
    c = Comment(entity_type=entity_type, entity_id=str(entity_id), author=scope.username, body=body)
    db.add(c)
    return c


def comments_for(db: Session, scope: Scope, entity_type: str, entity_id) -> list[dict]:
    entities.load(db, scope, entity_type, entity_id)
    rows = (db.query(Comment).filter_by(entity_type=entity_type, entity_id=str(entity_id))
            .order_by(Comment.created_at, Comment.id))
    return [{"id": c.id, "author": c.author, "body": c.body,
             "created_at": c.created_at.isoformat() if c.created_at else None} for c in rows]
