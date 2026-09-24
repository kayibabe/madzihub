from __future__ import annotations

import hashlib
import json
import sys
import zipfile
from pathlib import Path

VENDOR_PREFIX = 'app/static/vendor/'

FORBIDDEN_PARTS = [
    '.git/', '.vs/', '__pycache__/', '.pytest_cache/', 'uploads/', 'data/',
    'dataupdater/', '.secret', 'groq.key', '.pyc', ' - Copy', '.xlsx', '.xls', '.db',
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
        failures.extend(_vendor_failures(zf, names))

    if failures:
        print('[FAIL] Release bundle validation failed:')
        for item in failures:
            print(f' - {item}')
        return 1

    print(f"[OK] Bundle validation passed: {zip_path}")
    return 0


def _vendor_failures(zf: zipfile.ZipFile, names: list[str]) -> list[str]:
    """Offline installs need every vendored library and font, byte-identical to the manifest."""
    by_suffix = {n.replace('\\', '/'): n for n in names}
    manifest_name = next((n for n in by_suffix if n.endswith(VENDOR_PREFIX + 'manifest.json')), None)
    if manifest_name is None:
        return [f'Bundle missing {VENDOR_PREFIX}manifest.json (vendored front-end assets)']
    prefix = manifest_name[: -len('manifest.json')]
    manifest = json.loads(zf.read(by_suffix[manifest_name]))
    problems = []
    for rel, info in manifest.items():
        name = by_suffix.get(prefix + rel)
        if name is None:
            problems.append(f'Bundle missing vendored file {VENDOR_PREFIX}{rel}')
        elif hashlib.sha256(zf.read(name)).hexdigest() != info['sha256']:
            problems.append(f'Vendored file changed: {VENDOR_PREFIX}{rel} (checksum differs from manifest)')
    return problems


if __name__ == '__main__':
    target = Path(sys.argv[1]) if len(sys.argv) > 1 else Path('dist/madzihub-release.zip')
    raise SystemExit(validate_bundle(target))
