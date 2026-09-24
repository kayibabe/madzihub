#!/usr/bin/env python3
"""
scripts/extract_from_html.py

One-time helper: reads the embedded DB_RECORDS constant from the existing
srwb_dashboard_v3.html and writes it to data/records.json so import_data.py
can seed the database.

Usage:
    python scripts/extract_from_html.py
    python scripts/extract_from_html.py --html path/to/dashboard.html --out data/records.json
"""
import argparse
import json
import os
import re
import sys

DEFAULT_HTML = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "..", "srwb_dashboard_v3.html"
)
DEFAULT_OUT  = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "data", "records.json"
)


def extract(html_path: str, out_path: str):
    print(f"Reading: {html_path}")

    with open(html_path, encoding="utf-8") as f:
        content = f.read()

    m = re.search(r"const DB_RECORDS\s*=\s*(\[.*?\]);", content, re.DOTALL)
    if not m:
        print("ERROR: DB_RECORDS not found in the HTML file.")
        sys.exit(1)

    raw_json = m.group(1)
    records  = json.loads(raw_json)
    print(f"  Found {len(records)} records")

    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "w") as f:
        json.dump(records, f, indent=2)

    print(f"  Written: {out_path}")
    print()
    print("Next step:")
    print("  python scripts/import_data.py")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--html", default=DEFAULT_HTML)
    parser.add_argument("--out",  default=DEFAULT_OUT)
    args = parser.parse_args()
    extract(args.html, args.out)


if __name__ == "__main__":
    main()
