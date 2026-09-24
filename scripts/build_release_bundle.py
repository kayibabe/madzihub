from __future__ import annotations

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


with ZipFile(OUTPUT, "w", compression=ZIP_DEFLATED) as zf:
    for path in ROOT.rglob("*"):
        if path.is_dir() or path == OUTPUT:
            continue
        rel = path.relative_to(ROOT)
        if should_exclude(rel):
            continue
        zf.write(path, arcname=Path("madzihub") / rel)

print(OUTPUT)
