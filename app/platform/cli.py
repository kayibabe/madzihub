"""Scheduled jobs for the governance modules (run by Windows Task Scheduler or cron).

    python -m app.platform.cli reminders        due-soon / overdue notices (idempotent per day)
    python -m app.platform.cli periods --fy 2027 create a fiscal year's reporting periods

Uses the same .env / DATABASE_URL as the application. Nothing is sent outside the app.
"""
from __future__ import annotations

import argparse
import sys

from app import model_registry as _models  # noqa: F401
from app.database import SessionLocal


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m app.platform.cli")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("reminders", help="create due-soon and overdue notices")
    p = sub.add_parser("periods", help="create the periods of a fiscal year")
    p.add_argument("--fy", type=int, required=True, help="fiscal year, by the calendar year it ends in")
    args = parser.parse_args(argv)

    from app.migrate import SchemaNotReady, ensure_schema
    try:
        ensure_schema()
    except SchemaNotReady as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    from app.modules import load_all
    load_all()   # registers every module's reminder producers
    db = SessionLocal()
    try:
        if args.cmd == "reminders":
            from app.platform.notifications import run_reminders
            print(f"{run_reminders(db)} notice(s) created.")
        elif args.cmd == "periods":
            from app.platform import audit, periods
            created = periods.ensure_fiscal_year(db, args.fy)
            audit.record(db, "cli", "period.create_fiscal_year", "fiscal_year", args.fy, after={"periods": len(created)})
            db.commit()
            print(f"FY ending {args.fy}: {len(created)} periods present.")
    finally:
        db.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
