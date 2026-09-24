"""Reset (or create) an administrator account.

Run from the project root:
    python scripts/reset_admin.py                 # random temporary password, printed once
    python scripts/reset_admin.py --prompt        # type a password instead
    python scripts/reset_admin.py --username ops  # another admin account

The account is flagged so the user must choose a new password at next login.
"""
from __future__ import annotations

import argparse
import getpass
import secrets
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.auth import hash_password  # noqa: E402
from app.database import SessionLocal, User, create_tables  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--username", default="admin")
    ap.add_argument("--prompt", action="store_true", help="enter the password interactively")
    args = ap.parse_args()

    if args.prompt:
        password = getpass.getpass("New password (min 8 chars): ")
        if len(password) < 8 or password != getpass.getpass("Repeat: "):
            print("Passwords must match and be at least 8 characters.", file=sys.stderr)
            return 1
    else:
        password = secrets.token_urlsafe(12)

    create_tables()
    db = SessionLocal()
    try:
        user = db.query(User).filter(User.username == args.username).first()
        if user is None:
            user = User(username=args.username, role="admin", created_by="reset_admin")
            db.add(user)
        user.password_hash = hash_password(password)
        user.role = "admin"
        user.is_active = True
        user.must_change_password = True
        db.commit()
    finally:
        db.close()

    print(f"Admin account '{args.username}' is ready.")
    if not args.prompt:
        print(f"Temporary password (shown once): {password}")
    print("The password must be changed at next login.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
