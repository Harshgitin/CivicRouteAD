"""Resident infrastructure reports and staff review endpoints.

Public reports are kept separate from synthetic benchmark runs. Location pins
come from the reporter's browser/device or from an explicitly selected map pin;
video-only detections are never presented as precisely geolocated objects.
"""

import asyncio
import hmac
import json
import os
import re
import secrets
import shutil
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import cv2
from fastapi import APIRouter, File, Form, Header, HTTPException, UploadFile, Body
from fastapi.responses import FileResponse, JSONResponse

from app.config import REPORTS_DIR, REPORTS_DB_PATH, STAFF_PASSWORD
from app.api.routes import runner as pipeline_runner
from app.ai.detector import HazardTracker

router = APIRouter(prefix="/api")
_DB_LOCK = threading.Lock()
_SESSIONS: dict[str, float] = {}
_SESSION_TTL_SECONDS = 8 * 60 * 60
_ALLOWED_VIDEO_EXTENSIONS = {".mp4", ".webm", ".mov", ".avi", ".mkv"}
_ALLOWED_GPS_EXTENSIONS = {".gpx", ".csv"}
_MAX_VIDEO_BYTES = 500 * 1024 * 1024
_MAX_GPS_BYTES = 25 * 1024 * 1024


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _load_reports() -> list[dict]:
    with _DB_LOCK:
        if not REPORTS_DB_PATH.exists():
            return []
        try:
            data = json.loads(REPORTS_DB_PATH.read_text(encoding="utf-8"))
            return data if isinstance(data, list) else []
        except (OSError, json.JSONDecodeError):
            raise HTTPException(status_code=500, detail="The report database could not be read safely.")


def _save_reports(reports: list[dict]) -> None:
    with _DB_LOCK:
        temp_path = REPORTS_DB_PATH.with_suffix(".tmp")
        temp_path.write_text(json.dumps(reports, ensure_ascii=False, indent=2), encoding="utf-8")
        temp_path.replace(REPORTS_DB_PATH)


def _public_report(report: dict) -> dict:
    """Remove disk paths and other internal implementation details."""
    allowed = {
        "id", "created_at", "updated_at", "issue_type", "title", "description",
        "landmark", "latitude", "longitude", "location_source", "camera_source",
        "camera_id", "reporter_name", "video_name", "video_size_bytes",
        "gps_name", "status", "priority", "assigned_to", "staff_notes",
        "run_id", "data_classification", "has_video", "has_gps", "analysis_state",
        "location_label", "reporter_consent"
    }
    result = {key: report.get(key) for key in allowed if key in report}
    result["has_video"] = bool(report.get("video_path"))
    result["has_gps"] = bool(report.get("gps_path"))
    # Never return the user's contact to list endpoints; the detail endpoint
    # still returns it to authenticated staff.
    return result


def _find_report(report_id: str) -> tuple[list[dict], int, dict]:
    reports = _load_reports()
    for index, report in enumerate(reports):
        if report.get("id") == report_id:
            return reports, index, report
    raise HTTPException(status_code=404, detail="Report not found.")


def _report_storage_dir(report: dict) -> Path:
    """Return a validated per-report storage directory, refusing unsafe paths."""
    report_id = str(report.get("id") or "")
    if not re.fullmatch(r"CR-\d{6}-[A-Fa-f0-9]{6}", report_id):
        raise HTTPException(status_code=400, detail="This report has an unexpected reference format; its files were not deleted.")

    root = REPORTS_DIR.resolve()
    report_dir = (root / report_id.lower()).resolve()
    if report_dir.parent != root:
        raise HTTPException(status_code=400, detail="The report storage path is outside the reports directory.")

    # Validate every recorded file path before deleting anything. All uploads and
    # analysis artifacts for a public report are meant to live under this folder.
    for field in ("video_path", "gps_path"):
        path_text = report.get(field)
        if not path_text:
            continue
        file_path = Path(str(path_text)).resolve()
        if file_path != report_dir and report_dir not in file_path.parents:
            raise HTTPException(status_code=400, detail="A report file path points outside its own storage folder; nothing was deleted.")
    return report_dir


def _remove_report_storage(report: dict) -> None:
    report_dir = _report_storage_dir(report)
    if report_dir.exists():
        if not report_dir.is_dir():
            raise HTTPException(status_code=400, detail="The report storage entry is not a directory; nothing was deleted.")
        # This removes the private video, optional GPS track, and analysis artifacts.
        shutil.rmtree(report_dir)


def _require_staff(session: Optional[str]) -> None:
    now = time.time()
    if not session or session not in _SESSIONS or _SESSIONS[session] <= now:
        if session:
            _SESSIONS.pop(session, None)
        raise HTTPException(status_code=401, detail="Staff access expired. Please sign in again.")
    _SESSIONS[session] = now + _SESSION_TTL_SECONDS


async def _save_upload(upload: UploadFile, destination: Path, max_bytes: int) -> int:
    total = 0
    destination.parent.mkdir(parents=True, exist_ok=True)
    try:
        with destination.open("wb") as output:
            while True:
                chunk = await upload.read(1024 * 1024)
                if not chunk:
                    break
                total += len(chunk)
                if total > max_bytes:
                    raise HTTPException(status_code=413, detail=f"File is larger than the {max_bytes // (1024 * 1024)} MB limit.")
                output.write(chunk)
    finally:
        await upload.close()
    if total == 0:
        destination.unlink(missing_ok=True)
        raise HTTPException(status_code=400, detail="The selected file is empty.")
    return total


def _find_saved_video(report: dict) -> Path:
    path = Path(str(report.get("video_path") or "")).resolve()
    root = REPORTS_DIR.resolve()
    if root not in path.parents or not path.is_file():
        raise HTTPException(status_code=404, detail="Evidence video is not available on this server.")
    return path


@router.post("/staff/login")
def staff_login(payload: dict = Body(...)):
    password = str(payload.get("password") or "")
    if not hmac.compare_digest(password.encode("utf-8"), STAFF_PASSWORD.encode("utf-8")):
        # Avoid distinguishing empty password from incorrect password.
        raise HTTPException(status_code=401, detail="That staff password is not correct.")
    session = secrets.token_urlsafe(36)
    _SESSIONS[session] = time.time() + _SESSION_TTL_SECONDS
    return {
        "session": session,
        "expires_in_seconds": _SESSION_TTL_SECONDS,
        "development_password_warning": STAFF_PASSWORD == "admin123"
    }


@router.post("/staff/logout")
def staff_logout(x_staff_session: Optional[str] = Header(None)):
    if x_staff_session:
        _SESSIONS.pop(x_staff_session, None)
    return {"ok": True}


@router.get("/staff/reports")
def staff_list_reports(x_staff_session: Optional[str] = Header(None)):
    _require_staff(x_staff_session)
    reports = _load_reports()
    reports.sort(key=lambda r: r.get("created_at", ""), reverse=True)
    return {"reports": [_public_report(report) for report in reports], "count": len(reports)}


@router.delete("/staff/reports")
def staff_clear_reports(x_staff_session: Optional[str] = Header(None)):
    """Permanently delete all resident-submitted reports and their private evidence.

    Bundled demo scenarios and benchmark runs are stored elsewhere and are not touched.
    """
    _require_staff(x_staff_session)
    reports = _load_reports()
    # Validate every location before starting deletion, so a malformed legacy record
    # cannot cause us to partially clear the collection without warning.
    directories = [_report_storage_dir(report) for report in reports]
    for report_dir in directories:
        if report_dir.exists():
            if not report_dir.is_dir():
                raise HTTPException(status_code=400, detail="A report storage entry is not a directory; no report list was cleared.")
    for report_dir in directories:
        if report_dir.exists():
            shutil.rmtree(report_dir)
    _save_reports([])
    return {"ok": True, "deleted_count": len(reports), "message": "Resident reports and their stored evidence were deleted. Demo scenarios were not changed."}


@router.delete("/staff/reports/{report_id}")
def staff_delete_report(report_id: str, x_staff_session: Optional[str] = Header(None)):
    """Delete one resident report and its private uploads/analysis artifacts."""
    _require_staff(x_staff_session)
    reports, index, report = _find_report(report_id)
    _report_storage_dir(report)  # validate all paths before removing the folder
    _remove_report_storage(report)
    reports.pop(index)
    _save_reports(reports)
    return {"ok": True, "id": report_id, "message": "Report and its stored evidence were deleted."}


@router.get("/staff/reports/{report_id}")
def staff_report_detail(report_id: str, x_staff_session: Optional[str] = Header(None)):
    _require_staff(x_staff_session)
    _, _, report = _find_report(report_id)
    detail = _public_report(report)
    detail["contact"] = report.get("contact", "")
    detail["reporter_name"] = report.get("reporter_name", "")
    detail["analysis"] = report.get("analysis")
    detail["video_url"] = f"/api/staff/reports/{report_id}/evidence" if report.get("video_path") else None
    detail["gps_download_url"] = f"/api/staff/reports/{report_id}/gps" if report.get("gps_path") else None
    return detail


@router.get("/staff/reports/{report_id}/evidence")
def staff_report_evidence(report_id: str, x_staff_session: Optional[str] = Header(None)):
    _require_staff(x_staff_session)
    _, _, report = _find_report(report_id)
    path = _find_saved_video(report)
    ext = path.suffix.lower()
    media_type = {".mp4": "video/mp4", ".webm": "video/webm", ".mov": "video/quicktime", ".avi": "video/x-msvideo", ".mkv": "video/x-matroska"}.get(ext, "application/octet-stream")
    return FileResponse(path, media_type=media_type, filename=report.get("video_name") or path.name, headers={"Cache-Control": "private, no-store"})


@router.get("/staff/reports/{report_id}/gps")
def staff_report_gps(report_id: str, x_staff_session: Optional[str] = Header(None)):
    _require_staff(x_staff_session)
    _, _, report = _find_report(report_id)
    path_text = report.get("gps_path")
    if not path_text:
        raise HTTPException(status_code=404, detail="No GPS track was attached to this report.")
    path = Path(path_text).resolve()
    if REPORTS_DIR.resolve() not in path.parents or not path.is_file():
        raise HTTPException(status_code=404, detail="The GPS track is not available on this server.")
    return FileResponse(path, filename=report.get("gps_name") or path.name, headers={"Cache-Control": "private, no-store"})


@router.post("/reports")
async def create_public_report(
    video: UploadFile = File(...),
    gps: Optional[UploadFile] = File(None),
    issue_type: str = Form(...),
    title: str = Form(...),
    description: str = Form(""),
    landmark: str = Form(""),
    latitude: str = Form(...),
    longitude: str = Form(...),
    location_source: str = Form("map_pin"),
    camera_source: str = Form("Phone / dashcam"),
    camera_id: str = Form(""),
    reporter_name: str = Form(""),
    contact: str = Form(""),
    reporter_consent: str = Form("yes"),
):
    """Receive an incident video with a point location; a route file is optional."""
    video_name = Path(video.filename or "evidence.mp4").name
    video_ext = Path(video_name).suffix.lower()
    if video_ext not in _ALLOWED_VIDEO_EXTENSIONS:
        raise HTTPException(status_code=400, detail="Please upload an MP4, WebM, MOV, AVI or MKV video.")
    try:
        lat = float(latitude)
        lon = float(longitude)
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="Choose the incident location on the map or use your current location.")
    if not (-90 <= lat <= 90 and -180 <= lon <= 180):
        raise HTTPException(status_code=400, detail="The selected latitude or longitude is outside valid bounds.")
    if not str(title).strip():
        raise HTTPException(status_code=400, detail="Add a short title describing the problem.")
    if reporter_consent.lower() not in {"yes", "true", "1", "on"}:
        raise HTTPException(status_code=400, detail="Please confirm that you are allowed to share this recording.")

    gps_ext = None
    gps_name = None
    if gps is not None and gps.filename:
        gps_name = Path(gps.filename).name
        gps_ext = Path(gps_name).suffix.lower()
        if gps_ext not in _ALLOWED_GPS_EXTENSIONS:
            raise HTTPException(status_code=400, detail="The optional GPS track must be GPX or CSV.")

    short_date = datetime.now().strftime("%y%m%d")
    report_id = f"CR-{short_date}-{uuid.uuid4().hex[:6].upper()}"
    report_dir = REPORTS_DIR / report_id.lower()
    report_dir.mkdir(parents=True, exist_ok=False)
    video_path = report_dir / f"evidence{video_ext}"
    gps_path = report_dir / f"track{gps_ext}" if gps_ext else None
    try:
        video_size = await _save_upload(video, video_path, _MAX_VIDEO_BYTES)
        gps_size = 0
        if gps and gps_path:
            gps_size = await _save_upload(gps, gps_path, _MAX_GPS_BYTES)
            if gps_size == 0:
                raise HTTPException(status_code=400, detail="The optional GPS track is empty.")
    except Exception:
        for child in report_dir.glob("*"):
            child.unlink(missing_ok=True)
        report_dir.rmdir() if report_dir.exists() and not any(report_dir.iterdir()) else None
        raise

    report = {
        "id": report_id,
        "created_at": _utc_now(),
        "updated_at": _utc_now(),
        "issue_type": str(issue_type).strip()[:80],
        "title": str(title).strip()[:160],
        "description": str(description).strip()[:3000],
        "landmark": str(landmark).strip()[:300],
        "latitude": lat,
        "longitude": lon,
        "location_source": str(location_source).strip()[:40],
        "camera_source": str(camera_source).strip()[:80],
        "camera_id": str(camera_id).strip()[:100],
        "reporter_name": str(reporter_name).strip()[:100],
        "contact": str(contact).strip()[:160],
        "video_name": video_name[:255],
        "video_size_bytes": video_size,
        "video_path": str(video_path.resolve()),
        "gps_name": gps_name,
        "gps_path": str(gps_path.resolve()) if gps_path else None,
        "gps_size_bytes": gps_size,
        "status": "New",
        "priority": "Needs triage",
        "assigned_to": "",
        "staff_notes": [],
        "analysis": None,
        "analysis_state": "Ready to review",
        "run_id": None,
        "data_classification": "USER_SUBMITTED_UNVERIFIED",
        "location_label": "Reporter selected location",
        "reporter_consent": True,
    }
    reports = _load_reports()
    reports.append(report)
    _save_reports(reports)
    return {
        "ok": True,
        "id": report_id,
        "status": report["status"],
        "created_at": report["created_at"],
        "message": "Your report was received. Keep this reference number to check with the responsible team.",
        "gps_attached": bool(gps_path),
        "location": {"latitude": lat, "longitude": lon, "source": report["location_source"]},
    }


@router.get("/staff/reports/{report_id}/analysis/export")
def staff_export_analysis(report_id: str, x_staff_session: Optional[str] = Header(None)):
    """Export a review-safe JSON summary without exposing contact or disk paths."""
    _require_staff(x_staff_session)
    _, _, report = _find_report(report_id)
    analysis = report.get("analysis")
    if not analysis:
        raise HTTPException(status_code=404, detail="Run an analysis before exporting its results.")
    export = {
        "report_reference": report.get("id"),
        "created_at": report.get("created_at"),
        "issue_type": report.get("issue_type"),
        "title": report.get("title"),
        "status": report.get("status"),
        "report_location": {
            "latitude": report.get("latitude"),
            "longitude": report.get("longitude"),
            "source": report.get("location_source"),
        },
        "camera_source": report.get("camera_source"),
        "camera_id": report.get("camera_id"),
        "analysis": analysis,
        "review_notice": "Preliminary automated output. Human verification is required; do not treat this export as a confirmed defect or dispatch instruction.",
    }
    return JSONResponse(
        content=export,
        headers={"Content-Disposition": f'attachment; filename="{report_id}-analysis.json"', "Cache-Control": "private, no-store"},
    )


@router.patch("/staff/reports/{report_id}")
def staff_update_report(
    report_id: str,
    payload: dict = Body(...),
    x_staff_session: Optional[str] = Header(None),
):
    _require_staff(x_staff_session)
    reports, index, report = _find_report(report_id)
    allowed_statuses = {"New", "Reviewing", "Assigned", "Resolved", "Duplicate", "Invalid"}
    if "status" in payload:
        status = str(payload.get("status") or "")
        if status not in allowed_statuses:
            raise HTTPException(status_code=400, detail="Choose a valid report status.")
        report["status"] = status
        if status in {"Resolved", "Duplicate", "Invalid"}:
            report["closed_at"] = _utc_now()
        else:
            report.pop("closed_at", None)
    if "assigned_to" in payload:
        report["assigned_to"] = str(payload.get("assigned_to") or "").strip()[:100]
    if "latitude" in payload or "longitude" in payload:
        if "latitude" not in payload or "longitude" not in payload:
            raise HTTPException(status_code=400, detail="Both latitude and longitude are required to correct a report location.")
        try:
            new_lat = float(payload["latitude"])
            new_lon = float(payload["longitude"])
        except (TypeError, ValueError):
            raise HTTPException(status_code=400, detail="Latitude and longitude must be numeric values.")
        import math
        if not math.isfinite(new_lat) or not math.isfinite(new_lon) or not (-90 <= new_lat <= 90) or not (-180 <= new_lon <= 180):
            raise HTTPException(status_code=400, detail="The selected coordinates are outside valid latitude/longitude ranges.")
        previous = (report.get("latitude"), report.get("longitude"))
        report["latitude"], report["longitude"] = round(new_lat, 6), round(new_lon, 6)
        report["location_source"] = str(payload.get("location_source") or "staff_corrected")[:40]
        if previous != (report["latitude"], report["longitude"]):
            report.setdefault("staff_notes", []).append({
                "at": _utc_now(),
                "text": f"Incident location corrected by staff from {previous[0]}, {previous[1]} to {report['latitude']}, {report['longitude']}."
            })
    if "note" in payload:
        note = str(payload.get("note") or "").strip()
        if note:
            report.setdefault("staff_notes", []).append({"at": _utc_now(), "text": note[:2000]})
    report["updated_at"] = _utc_now()
    reports[index] = report
    _save_reports(reports)
    return {"ok": True, "report": _public_report(report)}


@router.post("/staff/reports/{report_id}/analyze")
def staff_analyze_report(report_id: str, x_staff_session: Optional[str] = Header(None)):
    """Run the existing video/GPS pipeline where possible, otherwise analyze video-only.

    Video-only findings retain timestamps and visual confidence but do not get
    invented coordinates. The citizen-selected point remains the report location.
    """
    _require_staff(x_staff_session)
    reports, index, report = _find_report(report_id)
    video_path = _find_saved_video(report)
    ext = video_path.suffix.lower()
    run_id = f"rpt_{re.sub(r'[^a-zA-Z0-9]', '', report_id.lower())}"
    report["analysis_state"] = "Analysis completed" if report.get("analysis") else "Analysis in progress"
    reports[index] = report
    _save_reports(reports)

    gps_path_text = report.get("gps_path")
    if gps_path_text:
        gps_path = Path(gps_path_text).resolve()
        if REPORTS_DIR.resolve() not in gps_path.parents or not gps_path.is_file():
            raise HTTPException(status_code=400, detail="The attached GPS track could not be found.")
        try:
            private_analysis_root = video_path.parent / "analysis_artifacts"
            summary = pipeline_runner.process_run(
                video_path=str(video_path), gps_path=str(gps_path), run_id=run_id,
                sample_step=5, is_synthetic=False, output_root=str(private_analysis_root)
            )
            # Citizen evidence/crops remain inside the private reports directory;
            # do not copy video or snapshots to the application's public /runs mount.
            for item in summary.get("hazards", []):
                item["snapshot_url"] = ""
            summary.pop("geojson_url", None)
            summary.pop("telemetry_url", None)
            summary.pop("report_url", None)
            summary["analysis_mode"] = "video_and_gps"
            summary["notice"] = "Video and an attached GPS track were analyzed. Camera-projected hazard coordinates are estimates and have not been independently verified. Staff must confirm findings before dispatch."
        except Exception as exc:
            report["analysis_state"] = "Analysis failed"
            report["analysis_error"] = str(exc)[:700]
            reports[index] = report
            _save_reports(reports)
            raise HTTPException(status_code=400, detail=f"Video/GPS analysis could not finish: {exc}")
    else:
        output_dir = video_path.parent / "analysis_artifacts" / run_id
        crops_dir = output_dir / "crops"
        crops_dir.mkdir(parents=True, exist_ok=True)
        cap = cv2.VideoCapture(str(video_path))
        if not cap.isOpened():
            raise HTTPException(status_code=400, detail="The uploaded video cannot be decoded by the analysis engine.")
        frame_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
        duration = frame_count / fps if fps > 0 else 0.0
        stride = max(1, frame_count // 120)
        frame_idx = 0
        sampled = 0
        detections = []
        tracker = HazardTracker(iou_threshold=0.25, max_frame_gap=max(15, stride * 3))
        try:
            while cap.isOpened():
                ok, frame = cap.read()
                if not ok:
                    break
                if frame_idx % stride == 0 and sampled < 120:
                    t_sec = frame_idx / fps if fps > 0 else 0.0
                    frame_detections = pipeline_runner.detector.analyze_frame(frame, frame_idx, t_sec)
                    tracker.update(frame_detections, frame, frame_idx, t_sec)
                    detections.extend({
                        "type": item.get("type", "possible_road_hazard"),
                        "confidence": round(float(item.get("confidence", 0)), 3),
                        "source": item.get("source", "cv_surface_analyzer"),
                        "verification": item.get("verification", "provisional_heuristic"),
                        "timestamp_sec": round(t_sec, 2),
                    } for item in frame_detections)
                    sampled += 1
                frame_idx += 1
        finally:
            cap.release()
        tracks = tracker.finish()
        hazards = []
        for track in tracks:
            # Keep source footage derivatives private; no public snapshot URL is emitted.
            snapshot_url = ""
            hazards.append({
                "id": track.get("id"),
                "type": track.get("type"),
                "confidence": round(float(track.get("best_confidence", 0)), 3),
                "source": track.get("source", "cv_surface_analyzer"),
                "verification": track.get("verification", "provisional_heuristic"),
                "timestamp_sec": round(float(track.get("best_timestamp_sec", 0)), 2),
                "detections_count": int(track.get("detections_count", 1)),
                "snapshot_url": snapshot_url,
                "location_quality": "not_geolocated_video_only",
                "latitude": None,
                "longitude": None,
                "review_required": True,
            })
        summary = {
            "run_id": run_id,
            "status": "completed",
            "analysis_mode": "video_only",
            "video_duration_sec": round(duration, 2),
            "frames_sampled": sampled,
            "frames_total": frame_count,
            "hazards_count": len(hazards),
            "hazards": hazards,
            "frame_observations": detections[:500],
            "notice": "Video-only analysis: these are preliminary visual flags, not confirmed defects. Without a synchronized GPS track, the system cannot calculate coordinates for individual objects. The report's map pin is the reporter-selected incident location. Human review is required before any action.",
        }
        (output_dir / "video_analysis.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")

    # Reload before saving so a fresh concurrent staff note/status change is not
    # unnecessarily overwritten with a stale version of the database.
    reports = _load_reports()
    for idx, current in enumerate(reports):
        if current.get("id") == report_id:
            current["analysis"] = summary
            current["run_id"] = summary.get("run_id")
            current["analysis_state"] = "Analysis complete — human review required"
            current["updated_at"] = _utc_now()
            reports[idx] = current
            break
    _save_reports(reports)
    return {"ok": True, "analysis": summary}
