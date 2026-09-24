"""
Organisational scope: who may see and act on which units. Deny by default.

A user's scope is resolved once per request from their grants and handed to every
service, report and export. Nothing in a module is visible without a grant:

- Administrators see everything (the private HR duty still has to be granted).
- A grant on a unit covers that unit and every unit below it; a grant on the root
  unit (``org``) is organisation-wide.
- Roles rank viewer < contributor < reviewer < approver; a higher role includes the
  lower ones. The account-level ``viewer`` role stays read-only whatever the grant.
- A user with no grants sees nothing. Organisation-wide dashboards built on the
  legacy monthly returns need an organisation-wide grant (``require_org_wide``).

Out-of-scope records are reported as "not found", so ids cannot be probed.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field

from fastapi import Depends, HTTPException
from sqlalchemy import false
from sqlalchemy.orm import Session

from app.auth import get_current_user
from app.database import User, get_db
from app.integration.models import OrgUnit
from app.platform.errors import Forbidden, Invalid, NotFound
from app.platform.models import FUNCTIONS, PRIVATE_FUNCTIONS, SCOPE_ROLES, UserFunction, UserOrgRole

ROOT_ORG = "org"
ROLE_RANK = {role: rank for rank, role in enumerate(SCOPE_ROLES)}


def _tree(db: Session) -> tuple[dict[str, list[str]], dict[str, str | None]]:
    rows = db.query(OrgUnit.id, OrgUnit.code, OrgUnit.parent_id).all()
    code_of = {uid: code for uid, code, _ in rows}
    children: dict[str, list[str]] = defaultdict(list)
    parent: dict[str, str | None] = {}
    for _, code, pid in rows:
        pcode = code_of.get(pid)
        parent[code] = pcode
        if pcode:
            children[pcode].append(code)
    return children, parent


def subtree(children: dict[str, list[str]], code: str) -> set[str]:
    out, stack = {code}, [code]
    while stack:
        for child in children.get(stack.pop(), []):
            if child not in out:
                out.add(child)
                stack.append(child)
    return out


def known_units(db: Session) -> set[str]:
    return {c for (c,) in db.query(OrgUnit.code)} | {ROOT_ORG}


@dataclass(frozen=True)
class Scope:
    username: str
    account_role: str                         # admin | user | viewer
    org_wide_role: str | None                 # role held on the root unit
    unit_roles: dict[str, str] = field(default_factory=dict)   # expanded: unit -> best role
    functions: frozenset[str] = frozenset()

    # ── identity ───────────────────────────────────────────────────────────
    @property
    def is_admin(self) -> bool:
        return self.account_role == "admin"

    @property
    def org_wide(self) -> bool:
        return self.is_admin or self.org_wide_role is not None

    @property
    def read_only(self) -> bool:
        return self.account_role == "viewer"

    def has_function(self, function: str) -> bool:
        if function in self.functions:
            return True
        return self.is_admin and function not in PRIVATE_FUNCTIONS

    # ── units ──────────────────────────────────────────────────────────────
    def role_on(self, unit: str | None) -> str | None:
        if self.is_admin:
            return "approver"
        best = self.org_wide_role
        own = self.unit_roles.get(unit or "")
        if own and (best is None or ROLE_RANK[own] > ROLE_RANK[best]):
            best = own
        return best

    def can_see(self, unit: str | None) -> bool:
        return self.role_on(unit) is not None

    def can(self, unit: str | None, role: str) -> bool:
        held = self.role_on(unit)
        if held is None:
            return False
        if role != "viewer" and self.read_only:
            return False
        return ROLE_RANK[held] >= ROLE_RANK[role]

    @property
    def visible_units(self) -> set[str] | None:
        """None means every unit."""
        return None if self.org_wide else set(self.unit_roles)

    def units_with(self, role: str) -> set[str] | None:
        if self.org_wide and self.can(ROOT_ORG, role):
            return None
        return {u for u in self.unit_roles if self.can(u, role)}

    def filter(self, query, column):
        """Restrict a query to visible units (empty scope matches nothing)."""
        units = self.visible_units
        if units is None:
            return query
        return query.filter(column.in_(sorted(units))) if units else query.filter(false())

    # ── guards ─────────────────────────────────────────────────────────────
    def require_see(self, unit: str | None, what: str = "Record") -> None:
        if not self.can_see(unit):
            raise NotFound(f"{what} not found.")

    def require(self, unit: str | None, role: str, what: str = "this record") -> None:
        self.require_see(unit)
        if not self.can(unit, role):
            if self.read_only:
                raise Forbidden("Your account is read-only.")
            raise Forbidden(f"You need the {role} role on this unit to change {what}.")

    def require_function(self, function: str) -> None:
        if not self.has_function(function):
            label = function.replace("_", " ")
            raise Forbidden(f"This needs the {label} duty.")
        if self.read_only:
            raise Forbidden("Your account is read-only.")

    def as_dict(self) -> dict:
        return {"username": self.username, "account_role": self.account_role, "org_wide": self.org_wide,
                "org_wide_role": "approver" if self.is_admin else self.org_wide_role,
                "units": None if self.org_wide else dict(sorted(self.unit_roles.items())),
                "functions": sorted(f for f in FUNCTIONS if self.has_function(f)),
                "read_only": self.read_only}


def resolve_scope(db: Session, user: User) -> Scope:
    grants = db.query(UserOrgRole.org_unit_code, UserOrgRole.role).filter(UserOrgRole.user_id == user.id).all()
    functions = frozenset(f for (f,) in db.query(UserFunction.function).filter(UserFunction.user_id == user.id))
    org_wide_role = None
    unit_roles: dict[str, str] = {}
    if grants:
        children, _ = _tree(db)
        for code, role in grants:
            if role not in ROLE_RANK:
                continue
            if code == ROOT_ORG:
                if org_wide_role is None or ROLE_RANK[role] > ROLE_RANK[org_wide_role]:
                    org_wide_role = role
                continue
            for unit in subtree(children, code):
                cur = unit_roles.get(unit)
                if cur is None or ROLE_RANK[role] > ROLE_RANK[cur]:
                    unit_roles[unit] = role
    return Scope(username=user.username, account_role=user.role, org_wide_role=org_wide_role,
                 unit_roles=unit_roles, functions=functions)


async def get_scope(user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> Scope:
    return resolve_scope(db, user)


async def require_org_wide(scope: Scope = Depends(get_scope)) -> Scope:
    """Guard for organisation-wide views (the legacy dashboards, reports and exports)."""
    if not scope.org_wide:
        raise HTTPException(403, "organisation_scope_required: this view covers the whole organisation; "
                                 "your access is limited to specific units.")
    return scope


def check_unit(db: Session, code: str) -> str:
    """A unit code that exists (or the root), for records being created or moved."""
    code = (code or "").strip()
    if code not in known_units(db):
        raise Invalid(f"Unknown organisational unit '{code}'.")
    return code


def unit_names(db: Session) -> dict[str, str]:
    names = {c: n for c, n in db.query(OrgUnit.code, OrgUnit.name)}
    names.setdefault(ROOT_ORG, "Whole organisation")
    return names
