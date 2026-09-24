"""
Connectors: pull raw rows out of a source system.

A connector only extracts. Mapping rows onto the catalogue happens in
``mapping.py`` so every source, whatever its protocol, goes through the same
validation. Four generic connectors cover most utility systems:

  file   CSV/Excel reports dropped in a folder (manual returns, exports from any system)
  sql    a read-only database account or view (billing/CIS, SCADA historian, SAP HANA, Maximo DB)
  rest   JSON/OData APIs (SAP OData, Maximo REST/OSLC, Workday reports, PI Web API)
  push   systems that send rows to /api/ingest/{source} themselves (SCADA gateways, scripts)

plus ``legacy_records``, which republishes MadziHub's existing monthly returns.

Secrets: config never contains a password or token. It names an environment
variable (``url_env``, ``password_env``, ``token_env``) and the value is read at run time.
"""
from __future__ import annotations

import csv
import glob
import io
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from app.core.config import DATA_DIR


class ConnectorError(RuntimeError):
    """Configuration or extraction problem that should fail the run with a readable message."""


@dataclass
class Extract:
    rows: list[dict[str, Any]]
    watermark: str | None = None  # new high-water mark to store after a successful load


SECRET_ENV_PREFIX = "MADZI_SRC_"


def _secret(config: dict, key: str, required: bool = True) -> str | None:
    env_name = config.get(key)
    if not env_name:
        if required:
            raise ConnectorError(f"config.{key} must name an environment variable holding the secret")
        return None
    # Only dedicated source variables: config must never be able to read the app's own
    # secrets (MADZI_SECRET_KEY, DATABASE_URL) and send them to a remote system.
    if not str(env_name).startswith(SECRET_ENV_PREFIX):
        raise ConnectorError(f"config.{key}: secret variables must be named {SECRET_ENV_PREFIX}*")
    value = os.getenv(str(env_name))
    if value is None and required:
        raise ConnectorError(f"environment variable {env_name} (config.{key}) is not set")
    return value


def _max_watermark(rows: Iterable[dict], field: str | None, current: str | None) -> str | None:
    if not field:
        return current
    best = current
    for row in rows:
        val = row.get(field)
        if val in (None, ""):
            continue
        text = val.isoformat() if hasattr(val, "isoformat") else str(val)
        if best is None or text > best:
            best = text
    return best


# ── file ─────────────────────────────────────────────────────────────────────

def drop_root() -> Path:
    """Folder that file sources may read from. Keeps admin-entered paths inside one tree."""
    return Path(os.getenv("MADZI_INTEGRATION_DROP_DIR", str(DATA_DIR / "dropzone"))).resolve()


def read_tabular(name: str, content: bytes, sheet: str | None = None, header_row: int = 1) -> list[dict[str, Any]]:
    """Parse CSV or Excel bytes into dict rows keyed by the header row."""
    lower = name.lower()
    if lower.endswith((".xlsx", ".xlsm")):
        import openpyxl

        wb = openpyxl.load_workbook(io.BytesIO(content), read_only=True, data_only=True)
        ws = wb[sheet] if sheet else wb.worksheets[0]
        values = list(ws.iter_rows(values_only=True))
        wb.close()
    elif lower.endswith((".csv", ".txt")):
        text = content.decode("utf-8-sig", errors="replace")
        values = list(csv.reader(io.StringIO(text)))
    else:
        raise ConnectorError(f"unsupported file type: {name} (use .csv or .xlsx)")
    if len(values) < header_row:
        return []
    header = [str(h).strip() if h is not None else "" for h in values[header_row - 1]]
    rows = []
    for idx, raw in enumerate(values[header_row:], start=header_row + 1):
        if raw is None or all(v in (None, "") for v in raw):
            continue
        row = {header[i]: raw[i] for i in range(min(len(header), len(raw))) if header[i]}
        row["_source_ref"] = f"{name}#row{idx}"
        rows.append(row)
    return rows


def _extract_file(config: dict, watermark: str | None) -> Extract:
    root = drop_root()
    pattern = config.get("path")
    if not pattern:
        raise ConnectorError("config.path is required (a file or glob inside the drop folder)")
    full = (root / pattern).resolve()
    if root != full and root not in full.parents:
        raise ConnectorError("config.path must stay inside the integration drop folder")
    files = sorted(glob.glob(str(full)))
    rows: list[dict] = []
    newest = watermark
    for path in files:
        mtime = datetime.fromtimestamp(os.path.getmtime(path), tz=timezone.utc).isoformat()
        if watermark and mtime <= watermark:
            continue  # already loaded this version of the file
        with open(path, "rb") as fh:
            rows.extend(read_tabular(os.path.basename(path), fh.read(),
                                     config.get("sheet"), int(config.get("header_row", 1))))
        newest = max(newest or mtime, mtime)
    return Extract(rows, newest)


# ── sql ──────────────────────────────────────────────────────────────────────

def _extract_sql(config: dict, watermark: str | None) -> Extract:
    from sqlalchemy import create_engine, text

    url = _secret(config, "url_env")
    query = config.get("query")
    if not query:
        raise ConnectorError("config.query is required")
    params = {"since": watermark or config.get("initial_since", "1900-01-01")}
    try:
        engine = create_engine(url)
    except Exception:
        # The parse error would echo the URL, including its password.
        raise ConnectorError(f"{config.get('url_env')} does not hold a valid database URL") from None
    try:
        with engine.connect() as conn:
            result = conn.execute(text(query), params if ":since" in query else {})
            rows = [dict(r._mapping) for r in result]
    finally:
        engine.dispose()
    for i, row in enumerate(rows):
        row.setdefault("_source_ref", f"sql#{i + 1}")
    return Extract(rows, _max_watermark(rows, config.get("watermark_field"), watermark))


# ── rest ─────────────────────────────────────────────────────────────────────

def _dig(obj: Any, path: str | None) -> Any:
    if not path:
        return obj
    for part in path.split("."):
        if obj is None:
            return None
        obj = obj.get(part) if isinstance(obj, dict) else None
    return obj


def _extract_rest(config: dict, watermark: str | None) -> Extract:
    import httpx

    base = config.get("base_url")
    if not base:
        raise ConnectorError("config.base_url is required")
    headers = {"Accept": "application/json", **(config.get("headers") or {})}
    auth = None
    a = config.get("auth") or {}
    kind = a.get("type", "none")
    if kind == "basic":
        auth = (_secret(a, "username_env"), _secret(a, "password_env"))
    elif kind == "bearer":
        headers["Authorization"] = f"Bearer {_secret(a, 'token_env')}"
    elif kind == "header":
        headers[a.get("header_name", "apikey")] = _secret(a, "token_env")
    elif kind != "none":
        raise ConnectorError(f"unknown auth type: {kind}")

    since = watermark or config.get("initial_since")
    params = {}
    for key, val in (config.get("params") or {}).items():
        if isinstance(val, str) and "{since}" in val:
            if since is None:
                continue  # first full load: drop the incremental filter
            val = val.replace("{since}", since)
        params[key] = val

    url = base.rstrip("/") + "/" + str(config.get("path", "")).lstrip("/")
    rows: list[dict] = []
    max_pages = int(config.get("max_pages", 500))
    with httpx.Client(timeout=float(config.get("timeout", 60)), verify=config.get("verify_tls", True),
                      auth=auth, headers=headers) as client:
        for _ in range(max_pages):
            # Next-page links carry their own query; an empty params dict would wipe it.
            resp = client.get(url, params=params or None)
            if resp.status_code >= 400:
                raise ConnectorError(f"{resp.status_code} from {url}")
            body = resp.json()
            page = _dig(body, config.get("records_path"))
            if isinstance(page, dict):
                page = [page]
            for item in page or []:
                if isinstance(item, dict):
                    rows.append(item)
            nxt = _dig(body, config.get("next_link_path")) if config.get("next_link_path") else None
            if not nxt:
                break
            url, params = (nxt if str(nxt).startswith("http") else base.rstrip("/") + "/" + str(nxt).lstrip("/")), {}
        else:
            raise ConnectorError(f"stopped after max_pages={max_pages}; raise it or narrow the query")
    for i, row in enumerate(rows):
        row.setdefault("_source_ref", f"rest#{i + 1}")
    return Extract(rows, _max_watermark(rows, config.get("watermark_field"), watermark))


# ── legacy_records ───────────────────────────────────────────────────────────

def legacy_org_code(zone: str, scheme: str | None = None) -> str:
    def slug(s: str) -> str:
        return "".join(ch if ch.isalnum() else "-" for ch in str(s).strip().lower()).strip("-")
    return slug(zone) if scheme is None else f"{slug(zone)}.{slug(scheme)}"


def _extract_legacy(db, config: dict, watermark: str | None) -> Extract:
    from app.database import Record

    # records has no change timestamp, so this is always a full (idempotent) reload.
    columns = [c for c in (config.get("columns") or []) if hasattr(Record, c)]
    rows = []
    for rec in db.query(Record).all():
        row = {"org_unit": legacy_org_code(rec.zone, rec.scheme), "year": rec.year, "month_no": rec.month_no,
               "_source_ref": f"records#{rec.id}"}
        for c in columns:
            row[c] = getattr(rec, c)
        rows.append(row)
    return Extract(rows, watermark)


def extract(db, source, rows: list[dict] | None = None) -> Extract:
    """Run the source's connector. ``rows`` short-circuits extraction (push, upload)."""
    if rows is not None:
        return Extract(rows, source.watermark)
    config = source.config or {}
    if source.connector == "file":
        return _extract_file(config, source.watermark)
    if source.connector == "sql":
        return _extract_sql(config, source.watermark)
    if source.connector == "rest":
        return _extract_rest(config, source.watermark)
    if source.connector == "legacy_records":
        return _extract_legacy(db, config, source.watermark)
    if source.connector == "push":
        raise ConnectorError("push sources receive data at POST /api/ingest/{code}; they cannot be pulled")
    raise ConnectorError(f"unknown connector: {source.connector}")
