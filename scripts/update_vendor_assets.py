#!/usr/bin/env python3
"""
Vendor MadziHub's third-party front-end files into app/static/vendor.

MadziHub installs inside utility networks that are often offline or firewalled,
so the browser must never need a CDN. This script downloads the pinned npm
packages straight from the registry (no Node.js needed), verifies each tarball
against the registry's published integrity hash, copies the files the app uses
plus their licences, generates fonts.css and writes manifest.json with a SHA-256
per file. Tests and the release-bundle validator check files against that manifest.

To upgrade a library: change its version in PACKAGES, run this script, run the
tests, and review the diff (including manifest.json) in the PR.

    python scripts/update_vendor_assets.py
"""
from __future__ import annotations

import base64
import hashlib
import io
import json
import shutil
import tarfile
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VENDOR = ROOT / "app" / "static" / "vendor"
REGISTRY = "https://registry.npmjs.org"

# package, version, licence, {path inside package: path under vendor/}
PACKAGES = [
    ("chart.js", "4.4.1", "MIT", {
        "dist/chart.umd.js": "chart.js/chart.umd.js",
        "LICENSE.md": "chart.js/LICENSE.md",
    }),
    ("dompurify", "3.1.6", "MPL-2.0 OR Apache-2.0", {
        "dist/purify.min.js": "dompurify/purify.min.js",
        "LICENSE": "dompurify/LICENSE",
    }),
    # Used only to *write* Excel exports; 0.18.5's published advisories concern parsing files.
    ("xlsx", "0.18.5", "Apache-2.0", {
        "dist/xlsx.full.min.js": "xlsx/xlsx.full.min.js",
        "LICENSE": "xlsx/LICENSE",
    }),
    ("@fontsource-variable/inter", "5.3.0", "OFL-1.1", {
        "files/inter-latin-wght-normal.woff2": "fonts/inter/inter-latin-wght-normal.woff2",
        "files/inter-latin-ext-wght-normal.woff2": "fonts/inter/inter-latin-ext-wght-normal.woff2",
        "LICENSE": "fonts/inter/LICENSE",
    }),
    ("@fontsource/ibm-plex-mono", "5.3.0", "OFL-1.1", {
        **{f"files/ibm-plex-mono-{sub}-{w}-normal.woff2": f"fonts/ibm-plex-mono/ibm-plex-mono-{sub}-{w}-normal.woff2"
           for sub in ("latin", "latin-ext") for w in (400, 500, 600)},
        "LICENSE": "fonts/ibm-plex-mono/LICENSE",
    }),
]

# Unicode ranges from Fontsource 5.3.0 (the same subsets Google Fonts serves).
LATIN = ("U+0000-00FF,U+0131,U+0152-0153,U+02BB-02BC,U+02C6,U+02DA,U+02DC,U+0304,U+0308,U+0329,"
         "U+2000-206F,U+20AC,U+2122,U+2191,U+2193,U+2212,U+2215,U+FEFF,U+FFFD")
LATIN_EXT = ("U+0100-02BA,U+02BD-02C5,U+02C7-02CC,U+02CE-02D7,U+02DD-02FF,U+0304,U+0308,U+0329,"
             "U+1D00-1DBF,U+1E00-1E9F,U+1EF2-1EFF,U+2020,U+20A0-20AB,U+20AD-20C0,U+2113,U+2C60-2C7F,U+A720-A7FF")


def _fetch(url: str) -> bytes:
    with urllib.request.urlopen(url, timeout=120) as resp:
        return resp.read()


def _tarball(name: str, version: str) -> tarfile.TarFile:
    meta = json.loads(_fetch(f"{REGISTRY}/{name}/{version}"))
    dist = meta["dist"]
    data = _fetch(dist["tarball"])
    algo, _, expected = dist["integrity"].partition("-")
    actual = base64.b64encode(hashlib.new(algo, data).digest()).decode()
    if actual != expected:
        raise SystemExit(f"integrity mismatch for {name}@{version}")
    return tarfile.open(fileobj=io.BytesIO(data), mode="r:gz")


def _fonts_css() -> str:
    lines = ["/* Self-hosted fonts (no Google Fonts request). Family names match base.css tokens. */"]
    for sub, rng in (("latin-ext", LATIN_EXT), ("latin", LATIN)):
        lines.append(f"@font-face{{font-family:'Inter';font-style:normal;font-display:swap;font-weight:100 900;"
                     f"src:url(inter/inter-{sub}-wght-normal.woff2) format('woff2-variations'),"
                     f"url(inter/inter-{sub}-wght-normal.woff2) format('woff2');unicode-range:{rng}}}")
        for w in (400, 500, 600):
            lines.append(f"@font-face{{font-family:'IBM Plex Mono';font-style:normal;font-display:swap;font-weight:{w};"
                         f"src:url(ibm-plex-mono/ibm-plex-mono-{sub}-{w}-normal.woff2) format('woff2');"
                         f"unicode-range:{rng}}}")
    return "\n".join(lines) + "\n"


def _entry(path: Path, **info) -> dict:
    data = path.read_bytes()
    return {**info, "sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data)}


def main() -> int:
    shutil.rmtree(VENDOR, ignore_errors=True)
    manifest: dict[str, dict] = {}
    for name, version, licence, files in PACKAGES:
        with _tarball(name, version) as tar:
            for inner, dest in files.items():
                member = tar.extractfile(f"package/{inner}")
                if member is None:
                    raise SystemExit(f"{name}@{version} has no {inner}")
                target = VENDOR / dest
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(member.read())
                manifest[dest] = _entry(target, package=name, version=version, license=licence,
                                        source=f"npm:{name}@{version}/{inner}")
        print(f"  {name}@{version}: {len(files)} files")
    css = VENDOR / "fonts" / "fonts.css"
    css.write_text(_fonts_css(), encoding="utf-8")
    manifest["fonts/fonts.css"] = _entry(css, package="madzihub", version="-", license="-",
                                         source="generated from Fontsource 5.3.0 unicode ranges")
    (VENDOR / "manifest.json").write_text(json.dumps(dict(sorted(manifest.items())), indent=2) + "\n", encoding="utf-8")
    total = sum(m["bytes"] for m in manifest.values())
    print(f"Vendored {len(manifest)} files ({total // 1024} KB) into {VENDOR.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
