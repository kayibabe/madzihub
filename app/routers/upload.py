from __future__ import annotations

import io
import json
import logging
import os
import re
import time
import uuid
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.auth import get_current_user
from app.core.config import DATA_DIR, settings
from app.core.limiter import limiter
from app.core.logging import REQUEST_ID_CTX
from app.database import UploadLog, engine, get_db
from app.services.audit_log import log_event
from app.services.excel_parser import ExcelParser
from app.services.rawdata_builder import (
    BuildError,
    available_years,
    build_rawdata,
    output_file_path,
    zone_files_status,
)

log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/upload", tags=["Upload"])

_PREVIEW_DIR = DATA_DIR / "upload_previews"
_PREVIEW_DIR.mkdir(parents=True, exist_ok=True)
PREVIEW_TTL: int = 1800

ALLOWED_UPLOAD_EXTENSIONS = {".xlsx", ".xlsm"}
ALLOWED_UPLOAD_CONTENT_TYPES = {
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "application/vnd.ms-excel.sheet.macroEnabled.12",
    "application/octet-stream",
}
MAX_UPLOAD_BYTES = settings.upload_limit_mb * 1024 * 1024

MONTH_NAMES: dict[int, str] = {
    1: "January", 2: "February", 3: "March",
    4: "April", 5: "May", 6: "June",
    7: "July", 8: "August", 9: "September",
    10: "October", 11: "November", 12: "December",
}


def _validate_upload(file: UploadFile, contents: bytes) -> None:
    filename = (file.filename or "").strip()
    ext = os.path.splitext(filename)[1].lower()
    if not filename:
        raise HTTPException(status_code=400, detail="Upload file must have a filename")
    if ext not in ALLOWED_UPLOAD_EXTENSIONS:
        raise HTTPException(status_code=400, detail="Only .xlsx or .xlsm files are allowed")
    if not contents:
        raise HTTPException(status_code=400, detail="Uploaded file is empty")
    if len(contents) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail=f"Upload exceeds {settings.upload_limit_mb} MB limit")
    content_type = (file.content_type or "").strip().lower()
    if content_type and content_type not in ALLOWED_UPLOAD_CONTENT_TYPES:
        raise HTTPException(status_code=400, detail="Unsupported upload content type")


class CommitRequest(BaseModel):
    preview_token: str
    global_conflict_mode: str = "replace"
    conflict_resolutions: dict[str, str] = Field(default_factory=dict)


class BuildRequest(BaseModel):
    # Fiscal-year end-year to build (e.g. 2027 = FY2026/27). None = current FY.
    year: int | None = None
    # Smart-diff fill (default) vs. full overwrite of existing values.
    force: bool = False
    # Dry-run: compute changes but write nothing to disk.
    test: bool = False


def _save_preview(data: dict) -> str:
    token = str(uuid.uuid4())
    payload = dict(data)
    payload["_created_at"] = time.time()
    with open(_PREVIEW_DIR / f"{token}.json", "w", encoding="utf-8") as fh:
        json.dump(payload, fh)
    return token


def _load_preview(token: str) -> dict | None:
    if not re.fullmatch(r"[0-9a-f\-]{36}", token):
        return None

    path = _PREVIEW_DIR / f"{token}.json"
    if not path.exists():
        return None

    with open(path, encoding="utf-8") as fh:
        data = json.load(fh)

    created_at = data.get("_created_at", 0)
    if time.time() - created_at > PREVIEW_TTL:
        try:
            path.unlink()
        except FileNotFoundError:
            pass
        return None

    return data


def _delete_preview(token: str) -> None:
    try:
        (_PREVIEW_DIR / f"{token}.json").unlink()
    except FileNotFoundError:
        pass


def _derive_quarter(month_no: int) -> str:
    if month_no in (4, 5, 6):
        return "Q1"
    if month_no in (7, 8, 9):
        return "Q2"
    if month_no in (10, 11, 12):
        return "Q3"
    if month_no in (1, 2, 3):
        return "Q4"
    raise ValueError(f"Invalid month number: {month_no}")


def _derive_fiscal_year(year: int, month_no: int) -> str:
    # SRWB fiscal year runs April → March
    if month_no >= 4:
        return f"FY{year}/{str(year + 1)[-2:]}"
    return f"FY{year - 1}/{str(year)[-2:]}"


def _month_name(month_no: int) -> str:
    try:
        return MONTH_NAMES[month_no]
    except KeyError as exc:
        raise ValueError(f"Invalid month number: {month_no}") from exc


def _normalize_conflict_mode(mode: str | None) -> str:
    mode = (mode or "").strip().lower()
    return mode if mode in {"replace", "skip"} else "replace"


def _row_resolution_key(row: dict[str, Any]) -> str:
    return f'{row.get("zone","")}|{row.get("scheme","")}|{row.get("year","")}|{row.get("month","")}'


@router.post("/preview")
@limiter.limit("20/hour")
async def preview(request: Request, file: UploadFile = File(...), current_user=Depends(get_current_user)):
    contents = await file.read()
    _validate_upload(file, contents)
    file_buf = io.BytesIO(contents)

    raw_conn = engine.raw_connection()
    try:
        result = ExcelParser().parse(file_buf, raw_conn)
    finally:
        raw_conn.close()

    preview_data = result.to_dict()
    preview_data["filename"] = file.filename
    token = _save_preview(preview_data)
    request_id = REQUEST_ID_CTX.get()
    log.info(
        "upload_preview_created",
        extra={
            "username": current_user.username,
            "request_id": request_id,
            "upload_filename": file.filename,
            "rows": len(preview_data.get("rows", [])),
        },
    )
    log_event(None, current_user.username, "upload_preview", f"Created preview for {file.filename}", request_id=request_id)

    return {**preview_data, "preview_token": token}


# ── Step 1: Build RawData from the 5 zone workbooks (dataupdater) ──────────────

@router.get("/build-years")
def build_years(current_user=Depends(get_current_user)):
    """List the fiscal years the build tool can compile (per-year readiness)."""
    try:
        return {"years": available_years()}
    except BuildError as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/zone-files")
def zone_files(year: int | None = None, current_user=Depends(get_current_user)):
    """Pre-flight: report which zone source workbooks are present for a fiscal year."""
    try:
        files = zone_files_status(year)
    except BuildError as exc:
        raise HTTPException(status_code=500, detail=str(exc))
    missing = [f["zone"] for f in files if not f["exists"]]
    return {
        "files": files,
        "all_present": not missing,
        "missing": missing,
        "output_file": output_file_path().name,
    }


@router.post("/build-rawdata")
@limiter.limit("10/hour")
def build_rawdata_endpoint(
    request: Request,
    body: BuildRequest,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """Run the smart-diff updater against the zone workbooks → RawData_updated.xlsx."""
    try:
        result = build_rawdata(body.year, test_mode=body.test, force_overwrite=body.force)
    except BuildError as exc:
        raise HTTPException(status_code=500, detail=str(exc))
    except FileNotFoundError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:  # pragma: no cover - defensive
        log.exception("RawData build failed")
        raise HTTPException(status_code=500, detail=str(exc))

    request_id = REQUEST_ID_CTX.get()
    log.info(
        "rawdata_build_completed",
        extra={
            "username": current_user.username,
            "request_id": request_id,
            "test_mode": body.test,
            "force": body.force,
            "records_changed": result.get("records_changed", 0),
            "exit_code": result.get("exit_code"),
        },
    )
    mode = "force-refresh" if body.force else "smart-diff"
    if body.test:
        mode += " (dry-run)"
    log_event(
        db,
        current_user.username,
        "rawdata_build",
        f"Built {result.get('output_file')} [{mode}] — {result.get('records_changed', 0)} record(s) changed",
        request_id=request_id,
    )
    return result


@router.post("/preview-generated")
@limiter.limit("20/hour")
def preview_generated(request: Request, current_user=Depends(get_current_user)):
    """Step 2 hand-off: validate the workbook just produced by /build-rawdata."""
    out_path = output_file_path()
    if not out_path.exists():
        raise HTTPException(
            status_code=400,
            detail="Generated RawData file not found — run Step 1 (Build) first.",
        )

    file_buf = io.BytesIO(out_path.read_bytes())

    raw_conn = engine.raw_connection()
    try:
        result = ExcelParser().parse(file_buf, raw_conn)
    finally:
        raw_conn.close()

    preview_data = result.to_dict()
    preview_data["filename"] = out_path.name
    token = _save_preview(preview_data)
    request_id = REQUEST_ID_CTX.get()
    log.info(
        "upload_preview_created",
        extra={
            "username": current_user.username,
            "request_id": request_id,
            "upload_filename": out_path.name,
            "rows": len(preview_data.get("rows", [])),
            "source": "generated",
        },
    )
    log_event(None, current_user.username, "upload_preview", f"Created preview for {out_path.name} (generated)", request_id=request_id)

    return {**preview_data, "preview_token": token}


@router.post("/commit")
@limiter.limit("10/hour")
def commit(
    request: Request,
    body: CommitRequest,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    preview_data = _load_preview(body.preview_token)
    if preview_data is None:
        raise HTTPException(status_code=400, detail="Invalid or expired preview token")

    raw_conn = engine.raw_connection()
    try:
        stats = _execute_commit(
            conn=raw_conn,
            preview_data=preview_data,
            global_mode=body.global_conflict_mode,
            per_row_res=body.conflict_resolutions,
        )
        raw_conn.commit()
        _delete_preview(body.preview_token)
    except HTTPException:
        raw_conn.rollback()
        raise
    except Exception as exc:
        raw_conn.rollback()
        log.exception("Upload commit failed")
        raise HTTPException(status_code=500, detail=str(exc))
    finally:
        raw_conn.close()

    request_id = REQUEST_ID_CTX.get()
    log.info(
        "upload_commit_completed",
        extra={
            "username": current_user.username,
            "request_id": request_id,
            "upload_filename": preview_data.get("filename"),
            "rows_inserted": stats.get("rows_inserted", 0),
            "rows_replaced": stats.get("rows_replaced", 0),
            "rows_skipped": stats.get("rows_skipped", 0),
            "rows_errored": stats.get("rows_errored", 0),
        },
    )
    log_event(db, current_user.username, "upload_commit", f"Committed upload for {preview_data.get('filename')}", request_id=request_id)

    # Persist to upload history
    try:
        _write_upload_log(db, current_user.username, preview_data, stats)
    except Exception:
        log.warning("upload_log_write_failed", exc_info=True)

    return stats


def _write_upload_log(db: Any, username: str, preview_data: dict, stats: dict) -> None:
    rows = preview_data.get("rows", [])
    years  = sorted({int(r["year"])  for r in rows if r.get("year")})
    months = sorted({int(r["month"]) for r in rows if r.get("month")})
    if years and months:
        min_m = min(months); max_m = max(months)
        MONTHS = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec']
        period = f"{MONTHS[min_m-1]} {min(years)} – {MONTHS[max_m-1]} {max(years)}"
    else:
        period = None
    db.add(UploadLog(
        uploaded_by=username,
        filename=preview_data.get("filename"),
        period=period,
        rows_inserted=stats.get("rows_inserted", 0),
        rows_updated=stats.get("rows_replaced", 0),
        rows_skipped=stats.get("rows_skipped", 0),
        rows_errored=stats.get("rows_errored", 0),
    ))
    db.commit()


@router.get("/history")
def upload_history(db: Session = Depends(get_db), current_user=Depends(get_current_user)):
    """Return all committed upload records, newest first."""
    rows = db.query(UploadLog).order_by(UploadLog.logged_at.desc()).limit(200).all()
    return {
        "uploads": [
            {
                "id":            r.id,
                "uploaded_by":   r.uploaded_by,
                "filename":      r.filename,
                "period":        r.period,
                "rows_inserted": r.rows_inserted,
                "rows_updated":  r.rows_updated,
                "rows_skipped":  r.rows_skipped,
                "rows_errored":  r.rows_errored,
                "logged_at":     r.logged_at.isoformat() if r.logged_at else None,
            }
            for r in rows
        ]
    }


def _execute_commit(conn, preview_data: dict, global_mode: str, per_row_res: dict[str, str]) -> dict[str, Any]:
    rows = preview_data.get("rows", [])
    importable_rows = [row for row in rows if row.get("status") != "error"]

    stats: dict[str, Any] = {
        "rows_total": len(rows),
        "rows_importable": len(importable_rows),
        "rows_inserted": 0,
        "rows_replaced": 0,
        "rows_skipped": 0,
        "rows_errored": 0,
        "error_rows": [],
    }

    if not importable_rows:
        return stats

    metric_cols: list[str] = sorted({
        key
        for row in importable_rows
        for key in (row.get("metrics") or {}).keys()
    })

    dim_cols = ["zone", "scheme", "fiscal_year", "year", "month_no", "month", "quarter"]
    all_cols = dim_cols + metric_cols

    insert_sql = f"""
        INSERT INTO records ({", ".join(all_cols)})
        VALUES ({", ".join("?" for _ in all_cols)})
    """

    replace_sql = f"""
        INSERT OR REPLACE INTO records ({", ".join(all_cols)})
        VALUES ({", ".join("?" for _ in all_cols)})
    """

    exists_sql = """
        SELECT id
        FROM records
        WHERE zone = ?
          AND scheme = ?
          AND year = ?
          AND month_no = ?
        LIMIT 1
    """

    for row in importable_rows:
        try:
            zone = str(row["zone"]).strip()
            scheme = str(row["scheme"]).strip()
            year = int(row["year"])
            month_no = int(row["month"])

            if not zone:
                raise ValueError("Zone is blank")
            if not scheme:
                raise ValueError("Scheme is blank")

            month_name = _month_name(month_no)
            fiscal_year = _derive_fiscal_year(year, month_no)
            quarter = _derive_quarter(month_no)

            resolution = _normalize_conflict_mode(
                per_row_res.get(_row_resolution_key(row), global_mode)
            )

            values = [
                zone,
                scheme,
                fiscal_year,
                year,
                month_no,
                month_name,
                quarter,
            ] + [
                (row.get("metrics") or {}).get(col)
                for col in metric_cols
            ]

            existing = conn.execute(exists_sql, (zone, scheme, year, month_no)).fetchone()

            if existing:
                if resolution == "skip":
                    stats["rows_skipped"] += 1
                    continue

                conn.execute(replace_sql, values)
                stats["rows_replaced"] += 1
            else:
                conn.execute(insert_sql, values)
                stats["rows_inserted"] += 1

        except Exception as exc:
            stats["rows_errored"] += 1
            if len(stats["error_rows"]) < 50:
                stats["error_rows"].append({
                    "row_num": row.get("row_num"),
                    "zone": row.get("zone"),
                    "scheme": row.get("scheme"),
                    "year": row.get("year"),
                    "month": row.get("month"),
                    "error": str(exc),
                })

    return stats
