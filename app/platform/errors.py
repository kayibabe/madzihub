"""Domain errors raised by platform and module services; main.py turns them into JSON responses.

Services stay free of FastAPI so they can run from the CLI and from tests unchanged.
"""
from __future__ import annotations


class PlatformError(Exception):
    status_code = 400

    def __init__(self, detail: str):
        super().__init__(detail)
        self.detail = detail


class NotFound(PlatformError):
    status_code = 404


class Forbidden(PlatformError):
    """The user may not see or change this record (also used for out-of-scope reads)."""
    status_code = 403


class Conflict(PlatformError):
    status_code = 409


class IllegalTransition(Conflict):
    pass


class PeriodLocked(Conflict):
    pass


class Invalid(PlatformError):
    status_code = 422
