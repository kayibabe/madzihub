"""
Typed workflows that share one transition helper.

Each record type declares its own states and named transitions; nothing else is
shared. ``Workflow.apply`` enforces the allowed source states and the reason rule,
changes the state, and writes the audit event in the same transaction. Who may
perform a transition (roles, segregation of duties) stays with the owning module.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy.orm import Session

from app.platform import audit
from app.platform.errors import IllegalTransition, Invalid
from app.platform.models import ApprovalStep


@dataclass(frozen=True)
class Transition:
    name: str
    sources: tuple[str, ...]
    target: str
    reason_required: bool = False
    label: str = ""


class Workflow:
    def __init__(self, entity_type: str, states: tuple[str, ...], transitions: list[Transition],
                 state_attr: str = "status"):
        self.entity_type = entity_type
        self.states = states
        self.state_attr = state_attr
        self.transitions = {t.name: t for t in transitions}
        for t in transitions:
            unknown = {t.target, *t.sources} - set(states)
            if unknown:
                raise ValueError(f"{entity_type}.{t.name} uses unknown states {sorted(unknown)}")

    def allowed(self, state: str) -> list[str]:
        return [t.name for t in self.transitions.values() if state in t.sources]

    def check(self, obj: Any, name: str, reason: str | None = None) -> Transition:
        t = self.transitions.get(name)
        current = getattr(obj, self.state_attr)
        if t is None:
            raise IllegalTransition(f"Unknown {self.entity_type} transition '{name}'.")
        if current not in t.sources:
            allowed = ", ".join(self.allowed(current)) or "none"
            raise IllegalTransition(f"Cannot {name} a {self.entity_type.replace('_', ' ')} that is "
                                    f"{current.replace('_', ' ')} (allowed now: {allowed}).")
        if t.reason_required and not (reason or "").strip():
            raise Invalid(f"A reason is required to {name} this {self.entity_type.replace('_', ' ')}.")
        return t

    def apply(self, db: Session, obj: Any, name: str, actor: str, *, reason: str | None = None,
              org_unit_code: str | None = None, entity_id: Any = None, extra_before: dict | None = None,
              extra_after: dict | None = None, step: str | None = None, decision: str | None = None) -> str:
        """Move ``obj`` along transition ``name``; returns the previous state.

        Pass ``step``/``decision`` to also record an approval step (verify, approve, return ...).
        """
        t = self.check(obj, name, reason)
        before_state = getattr(obj, self.state_attr)
        setattr(obj, self.state_attr, t.target)
        eid = entity_id if entity_id is not None else getattr(obj, "id", None)
        audit.record(db, actor, f"{self.entity_type}.{name}", self.entity_type, eid,
                     before={self.state_attr: before_state, **(extra_before or {})},
                     after={self.state_attr: t.target, **(extra_after or {})},
                     reason=(reason or "").strip() or None, org_unit_code=org_unit_code)
        if step:
            db.add(ApprovalStep(entity_type=self.entity_type, entity_id=str(eid), step=step,
                                decision=decision or t.target, actor=actor, comment=(reason or "").strip() or None))
        return before_state


def approval_history(db: Session, entity_type: str, entity_id: Any) -> list[dict]:
    rows = (db.query(ApprovalStep).filter_by(entity_type=entity_type, entity_id=str(entity_id))
            .order_by(ApprovalStep.at, ApprovalStep.id))
    return [{"step": r.step, "decision": r.decision, "actor": r.actor, "comment": r.comment,
             "at": r.at.isoformat() if r.at else None} for r in rows]
