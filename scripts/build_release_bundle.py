from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

ROOT = Path(__file__).resolve().parents[1]
DIST = ROOT / "dist"
DIST.mkdir(exist_ok=True)
OUTPUT = DIST / "madzihub-release.zip"

# Runtime state and utility data never ship: databases, secrets, uploads, spreadsheets.
EXCLUDE_DIR_NAMES = {
    ".git", ".vs", ".claude", ".codex", ".idea", ".vscode", "__pycache__", ".pytest_cache",
    "dist", "data", "uploads", "logs", "dataupdater", "venv", ".venv",
}
EXCLUDE_FILE_NAMES = {
    "groq.key", ".env",
}
EXCLUDE_PATTERNS = [
    "*.pyc", "*.pyo", "*.pyd", "*.vsidx", "*.wsuo", "*.sqlite", "*.db", "* - Copy.*",
    "*.secret", "*.key", "*.xlsx", "*.xls", "*.csv", "secrets*",
]
INCLUDE_ALWAYS = {
    ".env.example", "README.md", "requirements.txt", "run.bat", "start.sh"
}


def should_exclude(path: Path) -> bool:
    if any(part in EXCLUDE_DIR_NAMES for part in path.parts):
        return True
    if path.name in INCLUDE_ALWAYS:
        return False
    if path.name in EXCLUDE_FILE_NAMES:
        return True
    return any(path.match(pattern) for pattern in EXCLUDE_PATTERNS)


def candidate_files() -> list[Path]:
    """Committed files only, so local documents and scratch files never ship.

    Falls back to walking the tree when this is not a git checkout
    (e.g. building from an unpacked source archive).
    """
    try:
        out = subprocess.run(["git", "ls-files", "-z"], cwd=ROOT, capture_output=True, check=True).stdout
    except (OSError, subprocess.CalledProcessError):
        return [p for p in ROOT.rglob("*") if p.is_file()]
    return [ROOT / name for name in out.decode("utf-8").split("\0") if name]


with ZipFile(OUTPUT, "w", compression=ZIP_DEFLATED) as zf:
    for path in candidate_files():
        if not path.is_file() or path == OUTPUT:
            continue
        rel = path.relative_to(ROOT)
        if should_exclude(rel):
            continue
        zf.write(path, arcname=Path("madzihub") / rel)

print(OUTPUT)
