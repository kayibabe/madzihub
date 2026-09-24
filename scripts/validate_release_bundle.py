from __future__ import annotations

import sys
import zipfile
from pathlib import Path

FORBIDDEN_PARTS = [
    '.git/', '.vs/', '__pycache__/', '.pytest_cache/', 'uploads/', 'data/',
    'srwb.secret', 'groq.key', '.pyc', ' - Copy',
]

ALLOWED_DOC_ONLY = {'.md', '.txt', '.example', '.yml', '.yaml', '.json', '.toml', '.ini', '.cfg', '.bat', '.sh', '.py', '.html', '.css', '.js', '.png', '.svg', '.ico'}


def validate_bundle(zip_path: Path) -> int:
    if not zip_path.exists():
        print(f"[FAIL] Bundle not found: {zip_path}")
        return 1

    failures: list[str] = []
    with zipfile.ZipFile(zip_path) as zf:
        names = zf.namelist()
        for name in names:
            normalized = name.replace('\\', '/')
            if any(part in normalized for part in FORBIDDEN_PARTS):
                failures.append(f"Forbidden path or file in bundle: {normalized}")
        if not any(name.endswith('requirements.txt') for name in names):
            failures.append('Bundle missing requirements.txt')
        if not any(name.endswith('.env.example') for name in names):
            failures.append('Bundle missing .env.example')
        if not any(name.endswith('app/main.py') for name in names):
            failures.append('Bundle missing app/main.py')

    if failures:
        print('[FAIL] Release bundle validation failed:')
        for item in failures:
            print(f' - {item}')
        return 1

    print(f"[OK] Bundle validation passed: {zip_path}")
    return 0


if __name__ == '__main__':
    target = Path(sys.argv[1]) if len(sys.argv) > 1 else Path('dist/opswebmobile-release.zip')
    raise SystemExit(validate_bundle(target))
