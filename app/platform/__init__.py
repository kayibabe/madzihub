"""Shared governance primitives used by every MadziHub module.

periods        reporting periods on the tenant fiscal calendar, with audited lock/reopen
scope          who may see and act on which organisational units (deny by default)
audit          append-only audit events with before/after state and reasons
workflow       typed state machines that share one transition + audit helper
actions        owned, dated follow-up work created by any module
entities       registry that lets links, comments and evidence reach any record safely
notifications  in-app notices and the due/overdue job (no external delivery)
"""
