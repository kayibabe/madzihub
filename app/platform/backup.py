"""
Backup and restore of a MadziHub installation: the database and the file store together.

    python -m app.platform.backup create [--out DIR]       write madzihub-backup-<utc>.zip
    python -m app.platform.backup verify ARCHIVE           check every file against the manifest
    python -m app.platform.backup restore ARCHIVE --db PATH --files DIR
                                                           restore into NEW locations (never over
                                                           existing ones); point .env at them after

The archive holds a consistent copy of the SQLite database (SQLite backup API, safe while
the app runs in WAL mode), every stored file, and manifest.json with SHA-256 fingerprints
and the schema revision. For PostgreSQL, take a pg_dump alongside a --files-only archive.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
import sys
import tempfile
import zipfile
from datetime import datetime, timezone
from pathlib import Path

from app.platform import filestore


class BackupError(RuntimeError):
    pass


def _sha(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def create(out_dir: Path | None = None, files_only: bool = False) -> Path:
    from app.database import engine
    from app.migrate import _sqlite_path, database_state

    db_path = _sqlite_path(engine)
    if db_path is None and not files_only:
        raise BackupError("This database is not a SQLite file: take a pg_dump and run with --files-only.")
    out_dir = Path(out_dir or (Path(db_path).parent / "backups" if db_path else Path.cwd()))
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    target = out_dir / f"madzihub-backup-{stamp}.zip"
    manifest = {"created_at": stamp, "revision": database_state().current, "files": {}, "database": None}
    with tempfile.TemporaryDirectory() as tmp, zipfile.ZipFile(target, "x", compression=zipfile.ZIP_DEFLATED) as z:
        if not files_only:
            copy = Path(tmp) / "madzihub.db"
            src = sqlite3.connect(str(db_path))
            dst = sqlite3.connect(str(copy))
            try:
                src.backup(dst)
            finally:
                dst.close()
                src.close()
            z.write(copy, "database/madzihub.db")
            manifest["database"] = {"path": "database/madzihub.db", "sha256": _sha(copy)}
        root = filestore.root()
        for f in sorted(p for p in root.rglob("*") if p.is_file()):
            rel = f.relative_to(root).as_posix()
            z.write(f, f"files/{rel}")
            manifest["files"][rel] = _sha(f)
        z.writestr("manifest.json", json.dumps(manifest, indent=1, sort_keys=True))
    return target


def verify(archive: Path) -> dict:
    with zipfile.ZipFile(archive) as z:
        manifest = json.loads(z.read("manifest.json"))
        problems = []
        if manifest.get("database"):
            if hashlib.sha256(z.read(manifest["database"]["path"])).hexdigest() != manifest["database"]["sha256"]:
                problems.append("database copy does not match its fingerprint")
        for rel, sha in manifest["files"].items():
            try:
                data = z.read(f"files/{rel}")
            except KeyError:
                problems.append(f"missing file {rel}")
                continue
            if hashlib.sha256(data).hexdigest() != sha:
                problems.append(f"file {rel} does not match its fingerprint")
    if problems:
        raise BackupError("Backup failed verification: " + "; ".join(problems))
    return manifest


def restore(archive: Path, db_target: Path, files_target: Path) -> dict:
    """Restore into new locations only; refuses to overwrite anything."""
    manifest = verify(archive)
    db_target, files_target = Path(db_target), Path(files_target)
    if manifest.get("database") and db_target.exists():
        raise BackupError(f"{db_target} already exists; restore into a new file.")
    if files_target.exists() and any(files_target.iterdir()):
        raise BackupError(f"{files_target} is not empty; restore into a new folder.")
    with zipfile.ZipFile(archive) as z:
        if manifest.get("database"):
            db_target.parent.mkdir(parents=True, exist_ok=True)
            db_target.write_bytes(z.read(manifest["database"]["path"]))
        for rel in manifest["files"]:
            dest = files_target / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(z.read(f"files/{rel}"))
    return manifest


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="python -m app.platform.backup")
    sub = p.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("create")
    c.add_argument("--out")
    c.add_argument("--files-only", action="store_true")
    v = sub.add_parser("verify")
    v.add_argument("archive")
    r = sub.add_parser("restore")
    r.add_argument("archive")
    r.add_argument("--db", required=True)
    r.add_argument("--files", required=True)
    args = p.parse_args(argv)
    try:
        if args.cmd == "create":
            print(f"Backup written: {create(Path(args.out) if args.out else None, args.files_only)}")
        elif args.cmd == "verify":
            m = verify(Path(args.archive))
            print(f"OK: revision {m['revision']}, {len(m['files'])} file(s), database {'included' if m['database'] else 'not included'}.")
        else:
            m = restore(Path(args.archive), Path(args.db), Path(args.files))
            print(f"Restored revision {m['revision']} and {len(m['files'])} file(s). Point DATABASE_URL and "
                  "MADZI_FILE_STORE at the restored locations, then run `python -m app.migrate status`.")
    except (BackupError, zipfile.BadZipFile, FileNotFoundError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
