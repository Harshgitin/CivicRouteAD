"""
CivicRouteAD - FastAPI REST API Router
Endpoints for processing dashcam video & GPS logs, GeoJSON export,
scenario management, crop serving, and municipal work orders.
"""

import os
import io
import csv
import json
import shutil
import time
from datetime import datetime, timezone
from typing import Optional
import cv2
import numpy as np
from fastapi import APIRouter, UploadFile, File, Form, HTTPException, BackgroundTasks
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse, Response, JSONResponse

from app.config import RUNS_DIR, SCENARIOS_DIR
from app.scenarios.scenario_manager import SCENARIOS_META, generate_scenario_files
from app.pipeline.runner import PipelineRunner
from app.video_compat import prepare_browser_playback, ensure_browser_mp4
from app.geospatial.gps_parser import parse_gpx_file, parse_csv_trajectory
from app.geospatial.geojson_builder import build_geojson_feature_collection
from app.geospatial.projection import CameraGeometry, direct_geodesic_project, estimate_lane_location
from app.ai.hazard_classes import HAZARD_DEFINITIONS, compute_severity

router = APIRouter(prefix="/api")
runner = PipelineRunner(runs_dir=str(RUNS_DIR))
_live_track_cache = {}
_live_camera_geometry = CameraGeometry(camera_height_m=1.4, camera_pitch_deg=2.2)
_SCENARIO_CACHE_VERSION = "analysis-lab-cache-v3"
_active_scenario_jobs = set()
_active_scenario_jobs_lock = __import__("threading").RLock()


def _get_live_trajectory(run_id: str):
    """Load each uploaded GPS track once for low-latency per-frame map projection."""
    run_dir = os.path.join(str(RUNS_DIR), run_id)
    metadata_path = os.path.join(run_dir, "metadata.json")
    if not os.path.isfile(metadata_path):
        return None, 0.0
    try:
        with open(metadata_path, "r", encoding="utf-8") as handle:
            metadata = json.load(handle)
        gps_filename = metadata.get("gps_filename")
        gps_available = bool(metadata.get("gps_available"))
        if not gps_available or not gps_filename:
            return None, float(metadata.get("time_offset_sec") or 0.0)
        gps_ext = os.path.splitext(str(gps_filename))[1].lower()
        if gps_ext not in (".gpx", ".csv"):
            return None, float(metadata.get("time_offset_sec") or 0.0)
        gps_path = os.path.join(run_dir, "inputs", f"input_gps{gps_ext}")
        if not os.path.isfile(gps_path):
            return None, float(metadata.get("time_offset_sec") or 0.0)
        mtime = os.path.getmtime(gps_path)
        cache_item = _live_track_cache.get(run_id)
        if not cache_item or cache_item.get("mtime") != mtime:
            trajectory = parse_gpx_file(gps_path) if gps_ext == ".gpx" else parse_csv_trajectory(gps_path)
            _live_track_cache[run_id] = {"mtime": mtime, "trajectory": trajectory}
        return _live_track_cache[run_id]["trajectory"], float(metadata.get("time_offset_sec") or 0.0)
    except Exception as exc:
        print(f"[CivicRouteAD] Live GPS projection unavailable for {run_id}: {exc}")
        return None, 0.0


@router.get("/health")
def health_check():
    return {
        "status": "healthy",
        "service": "CivicRouteAD",
        "version": "1.0.0",
        "pipeline": "Edge-to-GIS Road Hazard & Obstruction Engine",
        "detector": runner.detector.status()
    }


@router.get("/scenarios")
def list_scenarios():
    """Returns available pre-packaged test scenarios with metadata."""
    generate_scenario_files(SCENARIOS_DIR) # Ensure files exist
    return {
        "count": len(SCENARIOS_META),
        "scenarios": SCENARIOS_META
    }


@router.post("/process/scenario/{scenario_id}")
def process_scenario(scenario_id: str):
    """Processes a pre-packaged benchmark scenario through the edge-to-GIS pipeline."""
    generate_scenario_files(SCENARIOS_DIR)
    meta = next((s for s in SCENARIOS_META if s["id"] == scenario_id), None)
    if not meta:
        raise HTTPException(status_code=404, detail=f"Scenario '{scenario_id}' not found.")

    sc_dir = SCENARIOS_DIR / scenario_id
    video_path = str(sc_dir / meta["video_file"])
    gps_path = str(sc_dir / meta["gps_file"])

    if not os.path.exists(video_path) or not os.path.exists(gps_path):
        raise HTTPException(status_code=500, detail="Scenario media files missing.")

    # Older project copies may contain MPEG-4 Part 2 (`mp4v`) videos that
    # OpenCV can analyze but Chrome cannot play. Upgrade scenario media where
    # FFmpeg is available; bundled fixtures in current releases are H.264 MP4.
    compatible, compatibility_message = ensure_browser_mp4(video_path)
    if not compatible:
        print(f"[CivicRouteAD] Scenario playback note: {compatibility_message}")

    run_id = f"sc_{scenario_id}"
    result = runner.process_run(
        video_path=video_path,
        gps_path=gps_path,
        run_id=run_id,
        sample_step=3,
        is_synthetic=True
    )

    # Always refresh the playback copy. Do not keep a stale mp4v file from an
    # earlier run when the source fixture has been upgraded to H.264.
    playback = prepare_browser_playback(video_path, os.path.join(str(RUNS_DIR), run_id))
    # Add a cache-busting token because scenario run IDs are stable. Without it,
    # a browser can reuse an older unsupported mp4v response after the playback
    # file has been converted to H.264.
    playback_token = int(os.path.getmtime(playback["path"]) * 1000) if os.path.isfile(playback.get("path", "")) else run_id
    result["video_url"] = f"/api/video/{run_id}?v={playback_token}"
    result["video_playback_warning"] = playback.get("warning")
    result["video_playback_format"] = playback.get("media_type")
    return result


def _scenario_source_signature(video_path: str, gps_path: str) -> dict:
    """Small, stable cache key for bundled synthetic demo artifacts."""
    video_stat = os.stat(video_path)
    gps_stat = os.stat(gps_path)
    detector_status = runner.detector.status()
    return {
        "version": _SCENARIO_CACHE_VERSION,
        "video_size": video_stat.st_size,
        "video_mtime_ns": video_stat.st_mtime_ns,
        "gps_size": gps_stat.st_size,
        "gps_mtime_ns": gps_stat.st_mtime_ns,
        "ultralytics_available": bool(detector_status.get("ultralytics_available")),
        "general_model_loaded": bool(detector_status.get("general_model_loaded")),
        "road_damage_model_loaded": bool(detector_status.get("road_damage_model_loaded")),
        "road_damage_model": detector_status.get("road_damage_model"),
    }


def _read_json_file(path: str):
    try:
        with open(path, "r", encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, ValueError, TypeError):
        return None


def _scenario_cache_is_valid(run_dir: str, source_signature: dict) -> bool:
    manifest_path = os.path.join(run_dir, "scenario_cache.json")
    manifest = _read_json_file(manifest_path)
    status = _read_json_file(os.path.join(run_dir, "job_status.json"))
    required_files = ("summary.json", "hazard_map.geojson", "telemetry.json")
    return bool(
        manifest
        and manifest.get("source_signature") == source_signature
        and status
        and status.get("status") == "completed"
        and all(os.path.isfile(os.path.join(run_dir, name)) for name in required_files)
    )


def _background_scenario_process(scenario_id: str, meta: dict, video_path: str, gps_path: str,
                                 run_id: str, source_signature: dict) -> None:
    """Perform the expensive synthetic benchmark asynchronously after preview is served."""
    run_dir = os.path.join(str(RUNS_DIR), run_id)
    _write_job_status(run_dir, "processing", message="Demo video is ready; AI/GIS analysis continues in the background.")
    try:
        result = runner.process_run(
            video_path=video_path,
            gps_path=gps_path,
            run_id=run_id,
            sample_step=3,
            is_synthetic=True,
        )
        result.setdefault("metadata", {}).update({
            "scenario_id": scenario_id,
            "scenario_title": meta.get("title"),
            "video_filename": meta.get("video_file"),
            "gps_filename": meta.get("gps_file"),
            "analysis_cache_version": _SCENARIO_CACHE_VERSION,
        })
        _atomic_write_json(os.path.join(run_dir, "summary.json"), result)
        _atomic_write_json(os.path.join(run_dir, "scenario_cache.json"), {
            "source_signature": source_signature,
            "scenario_id": scenario_id,
            "completed_at": datetime.now(timezone.utc).isoformat(),
        })
        _write_job_status(run_dir, "completed", hazards_count=result.get("hazards_count", 0))
    except Exception as exc:
        print(f"[CivicRouteAD] Background scenario job {run_id} failed: {exc}")
        _write_job_status(run_dir, "failed", message=f"Demo GIS analysis failed: {exc}")
    finally:
        with _active_scenario_jobs_lock:
            _active_scenario_jobs.discard(run_id)


@router.get("/scenario/preview/{scenario_id}")
def preview_scenario(scenario_id: str, background_tasks: BackgroundTasks):
    """Return a playable demo immediately and do its full AI/GIS pass in the background.

    The existing synchronous /process/scenario endpoint is retained for callers that
    explicitly need a completed result. The Analysis Lab uses this non-blocking route
    so opening the page does not wait for every video frame to be analyzed.
    """
    generate_scenario_files(SCENARIOS_DIR)
    meta = next((scenario for scenario in SCENARIOS_META if scenario["id"] == scenario_id), None)
    if not meta:
        raise HTTPException(status_code=404, detail=f"Scenario '{scenario_id}' not found.")

    scenario_dir = os.path.join(str(SCENARIOS_DIR), scenario_id)
    video_path = os.path.join(scenario_dir, meta["video_file"])
    gps_path = os.path.join(scenario_dir, meta["gps_file"])
    if not os.path.isfile(video_path) or not os.path.isfile(gps_path):
        raise HTTPException(status_code=500, detail="Scenario media files are missing.")

    run_id = f"sc_{scenario_id}"
    run_dir = os.path.join(str(RUNS_DIR), run_id)
    os.makedirs(run_dir, exist_ok=True)
    source_signature = _scenario_source_signature(video_path, gps_path)

    playback = prepare_browser_playback(video_path, run_dir)
    playback_path = playback.get("path")
    playback_token = int(os.path.getmtime(playback_path) * 1000) if playback_path and os.path.isfile(playback_path) else run_id
    video_url = f"/api/video/{run_id}?v={playback_token}"

    if _scenario_cache_is_valid(run_dir, source_signature):
        summary = _read_json_file(os.path.join(run_dir, "summary.json")) or {}
        summary.update({
            "run_id": run_id,
            "status": "completed",
            "is_synthetic": True,
            "video_url": video_url,
            "video_playback_warning": playback.get("warning"),
            "video_playback_format": playback.get("media_type"),
        })
        summary.setdefault("metadata", {}).update({
            "scenario_id": scenario_id,
            "scenario_title": meta.get("title"),
            "video_filename": meta.get("video_file"),
            "gps_filename": meta.get("gps_file"),
            "is_synthetic": True,
        })
        return summary

    with _active_scenario_jobs_lock:
        already_running = run_id in _active_scenario_jobs
        if not already_running:
            # Create light preview artifacts for the map/player; final results replace these.
            trajectory = parse_gpx_file(gps_path)
            preliminary_telemetry, duration_sec = _build_preliminary_telemetry(video_path, trajectory, 0.0)
            preview_metadata = {
                "run_id": run_id,
                "scenario_id": scenario_id,
                "scenario_title": meta.get("title"),
                "is_synthetic": True,
                "data_classification": "SYNTHETIC_BENCHMARK_FIXTURE",
                "video_filename": meta.get("video_file"),
                "gps_filename": meta.get("gps_file"),
                "gps_available": True,
                "duration_sec": round(duration_sec, 3),
                "total_distance_m": float(getattr(trajectory, "total_distance_m", 0.0)),
                "coverage_ratio": 1.0,
                "geolocation_notice": "Synthetic route is illustrative and is not road-matched ground truth.",
                "warnings": ["Synthetic benchmark preview; hazard analysis is still processing."],
                "analysis_cache_version": _SCENARIO_CACHE_VERSION,
            }
            _atomic_write_json(os.path.join(run_dir, "metadata.json"), preview_metadata)
            _atomic_write_json(os.path.join(run_dir, "hazard_map.geojson"), build_geojson_feature_collection(
                [], trajectory.to_coordinates_list(), preview_metadata
            ))
            _atomic_write_json(os.path.join(run_dir, "telemetry.json"), preliminary_telemetry)
            _write_job_status(run_dir, "processing", message="Video preview ready; full AI/GIS analysis is processing in the background.")
            _active_scenario_jobs.add(run_id)
            background_tasks.add_task(
                _background_scenario_process, scenario_id, meta, video_path, gps_path, run_id, source_signature
            )

    preview_summary = {
        "run_id": run_id,
        "status": "processing",
        "is_synthetic": True,
        "metadata": {
            "run_id": run_id,
            "scenario_id": scenario_id,
            "scenario_title": meta.get("title"),
            "is_synthetic": True,
            "data_classification": "SYNTHETIC_BENCHMARK_FIXTURE",
            "video_filename": meta.get("video_file"),
            "gps_filename": meta.get("gps_file"),
            "gps_available": True,
            "duration_sec": meta.get("duration_sec", 0),
            "geolocation_notice": "Synthetic route is illustrative and not road-matched ground truth.",
        },
        "hazards_count": 0,
        "hazards": [],
        "geojson_url": f"/api/geojson/{run_id}",
        "telemetry_url": f"/api/telemetry/{run_id}",
        "video_url": video_url,
        "video_playback_warning": playback.get("warning"),
        "video_playback_format": playback.get("media_type"),
        "message": "Demo is ready. Full AI/GIS analysis continues in the background.",
    }
    return preview_summary


def _atomic_write_json(path: str, payload: dict) -> None:
    """Write JSON atomically so polling clients never observe a half-written file."""
    temp_path = f"{path}.tmp"
    with open(temp_path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2)
    os.replace(temp_path, path)


def _write_job_status(run_dir: str, status: str, **extra) -> None:
    os.makedirs(run_dir, exist_ok=True)
    payload = {
        "status": status,
        "updated_at": datetime.now(timezone.utc).isoformat(),
        **extra,
    }
    _atomic_write_json(os.path.join(run_dir, "job_status.json"), payload)


def _build_preliminary_telemetry(video_path: str, trajectory, time_offset_sec: float):
    """Create a light 5 Hz playback track before expensive AI analysis completes."""
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        raise ValueError(f"Could not open or decode video file: {video_path}")
    try:
        frame_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        fps = float(cap.get(cv2.CAP_PROP_FPS) or 30.0)
        if frame_count <= 0 or fps <= 0:
            raise ValueError("Video file has invalid duration or frame rate.")
        duration_sec = frame_count / fps
        stride = max(1, int(round(fps / 5.0)))
        output = []
        for frame_idx in range(0, frame_count, stride):
            timestamp_sec = frame_idx / fps
            state = trajectory.get_state_at_time(timestamp_sec, time_offset_sec)
            output.append({
                "frame": frame_idx,
                "time_sec": round(timestamp_sec, 3),
                "lat": round(float(state.lat), 7) if state.lat is not None else None,
                "lon": round(float(state.lon), 7) if state.lon is not None else None,
                "speed_kmh": round(float(state.speed_kmh), 2) if state.speed_kmh is not None else None,
                "heading_deg": round(float(state.heading_deg), 2) if state.heading_deg is not None else None,
                "is_in_coverage": bool(state.is_in_coverage),
                "detection_frame": False,
                "detections": [],
            })
        return output, duration_sec
    finally:
        cap.release()


def _target_video_sample_stride(video_path: str, target_samples_per_second: float = 10.0) -> int:
    """Choose a predictable full-video scan rate from the source FPS."""
    cap = cv2.VideoCapture(video_path)
    try:
        fps = float(cap.get(cv2.CAP_PROP_FPS) or 30.0) if cap.isOpened() else 30.0
    finally:
        cap.release()
    if not np.isfinite(fps) or fps <= 0:
        fps = 30.0
    return max(1, int(round(fps / max(1.0, target_samples_per_second))))


def _background_gis_process(video_path: str, gps_path: Optional[str], run_id: str, time_offset_sec: float,
                            original_video_name: str, original_gps_name: Optional[str]) -> None:
    """Scan the complete uploaded clip asynchronously; GPS adds GIS projection."""
    run_dir = os.path.join(str(RUNS_DIR), run_id)
    _write_job_status(run_dir, "processing", message="Video is ready; deeply analyzing the full clip for road damage.", progress_percent=0.0)
    try:
        def report_progress(values: dict) -> None:
            percent = float(values.get("progress_percent", 0.0))
            status_message = (
                f"Full-video AI analysis {percent:.1f}% · "
                f"{values.get('sampled_frames', 0)} sampled frames analyzed"
                + (" · GPS/GIS projection enabled" if gps_path else " · visual-only; no GPS track")
            )
            _write_job_status(
                run_dir,
                "processing",
                message=status_message,
                **values,
            )

        sample_step = _target_video_sample_stride(video_path, target_samples_per_second=10.0)
        result = runner.process_run(
            video_path=video_path,
            gps_path=gps_path or None,
            run_id=run_id,
            sample_step=sample_step,
            time_offset_sec=time_offset_sec,
            is_synthetic=False,
            progress_callback=report_progress,
        )
        result.setdefault("metadata", {})["video_filename"] = original_video_name
        result["metadata"]["gps_filename"] = original_gps_name
        result["metadata"]["gps_available"] = bool(gps_path)
        result["metadata"]["gps_processed"] = bool(gps_path)
        # Preserve the original client-side filenames in the final run summary.
        _atomic_write_json(os.path.join(run_dir, "summary.json"), result)
        _write_job_status(
            run_dir,
            "completed",
            progress_percent=100.0,
            frames_processed=result.get("metadata", {}).get("frame_count"),
            hazards_count=result.get("hazards_count", 0),
            potholes_count=sum(1 for hazard in result.get("hazards", []) if hazard.get("type") == "pothole_damage"),
            message=("Full-video AI analysis and GPS/GIS projection complete." if gps_path
                     else "Full-video AI analysis complete. Add a synchronized GPS track to map detections geographically."),
        )
    except Exception as exc:
        print(f"[CivicRouteAD] Background GIS job {run_id} failed: {exc}")
        _write_job_status(run_dir, "failed", message=f"Full-video analysis failed: {exc}")


@router.post("/process/upload")
@router.post("/upload")
async def process_upload(
    background_tasks: BackgroundTasks,
    video: UploadFile = File(...),
    gps: Optional[UploadFile] = File(None),
    time_offset_sec: Optional[float] = Form(0.0),
    run_name: Optional[str] = Form(None),
):
    """
    Store uploaded dashcam video and make it playable immediately. If a matching
    GPX/CSV track is supplied, run the full edge-to-GIS analysis in the background.
    Without GPS, the user can still use live visual inference, but the system must
    not invent geographic coordinates, speed, or heading.
    """
    if not video.filename:
        raise HTTPException(status_code=400, detail="Missing video file: select an MP4, WebM, MOV, AVI, or MKV video.")

    video_ext = os.path.splitext(video.filename)[1].lower()
    if video_ext not in [".mp4", ".webm", ".mov", ".avi", ".mkv"]:
        raise HTTPException(status_code=400, detail=f"Unsupported video format: '{video_ext}'. Accepted formats: .mp4, .webm, .mov, .avi, .mkv")

    gps_ext = None
    if gps is not None and gps.filename:
        gps_ext = os.path.splitext(gps.filename)[1].lower()
        if gps_ext not in [".gpx", ".csv"]:
            raise HTTPException(status_code=400, detail=f"Unsupported GPS format: '{gps_ext}'. Accepted formats: .gpx, .csv")

    import uuid
    run_id = f"custom_{uuid.uuid4().hex[:8]}"
    run_dir = os.path.join(str(RUNS_DIR), run_id)
    upload_dir = os.path.join(run_dir, "inputs")
    os.makedirs(upload_dir, exist_ok=True)

    video_save_path = os.path.join(upload_dir, f"input_video{video_ext}")
    video_bytes_written = 0
    with open(video_save_path, "wb") as handle:
        while True:
            chunk = await video.read(1024 * 1024)
            if not chunk:
                break
            video_bytes_written += len(chunk)
            if video_bytes_written > 500 * 1024 * 1024:
                handle.close()
                try:
                    os.remove(video_save_path)
                except OSError:
                    pass
                raise HTTPException(status_code=413, detail="Video file exceeds the 500MB size limit.")
            handle.write(chunk)
    if video_bytes_written == 0:
        try:
            os.remove(video_save_path)
        except OSError:
            pass
        raise HTTPException(status_code=400, detail="Uploaded video file is empty (0 bytes).")

    gps_save_path = None
    trajectory = None
    preliminary_telemetry = []
    if gps_ext and gps is not None:
        gps_bytes = await gps.read()
        if not gps_bytes:
            raise HTTPException(status_code=400, detail="Uploaded GPS file is empty (0 bytes).")
        if len(gps_bytes) > 25 * 1024 * 1024:
            raise HTTPException(status_code=400, detail="GPS file exceeds the 25MB size limit.")
        gps_save_path = os.path.join(upload_dir, f"input_gps{gps_ext}")
        with open(gps_save_path, "wb") as handle:
            handle.write(gps_bytes)
        try:
            trajectory = parse_gpx_file(gps_save_path) if gps_ext == ".gpx" else parse_csv_trajectory(gps_save_path)
            preliminary_telemetry, duration_sec = _build_preliminary_telemetry(
                video_save_path, trajectory, float(time_offset_sec or 0.0)
            )
        except Exception as exc:
            raise HTTPException(status_code=400, detail=f"Could not read the synchronized GPS track: {exc}")
    else:
        cap = cv2.VideoCapture(video_save_path)
        if not cap.isOpened():
            raise HTTPException(status_code=400, detail="The uploaded video could not be decoded by OpenCV.")
        frame_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        fps = float(cap.get(cv2.CAP_PROP_FPS) or 30.0)
        cap.release()
        if frame_count <= 0 or fps <= 0:
            raise HTTPException(status_code=400, detail="The uploaded video has invalid duration or frame rate.")
        duration_sec = frame_count / fps

    # The browser needs a supported H.264 playback copy. Keep the original input
    # unchanged for reproducibility and later GIS processing.
    playback = prepare_browser_playback(video_save_path, run_dir)
    playback_path = playback.get("path")
    playback_token = int(os.path.getmtime(playback_path) * 1000) if playback_path and os.path.isfile(playback_path) else run_id

    metadata = {
        "run_id": run_id,
        "is_synthetic": False,
        "data_classification": "USER_UPLOADED_UNVERIFIED",
        "video_filename": video.filename,
        "gps_filename": gps.filename if gps_save_path and gps else None,
        "gps_available": bool(gps_save_path),
        "duration_sec": round(duration_sec, 3),
        "time_offset_sec": float(time_offset_sec or 0.0),
        "total_distance_m": float(getattr(trajectory, "total_distance_m", 0.0)) if trajectory else 0.0,
        "coverage_ratio": 1.0 if trajectory else 0.0,
        "geolocation_notice": (
            "Camera-projected hazard positions are approximate and have not been independently ground-truth validated."
            if trajectory else
            "No synchronized GPS track was supplied. Live visual detections work, but map coordinates, vehicle speed, and heading are unavailable."
        ),
        "warnings": [] if trajectory else ["GPS track not supplied: visual detection is available; geographic hazard mapping is not."]
    }

    # Persist only the upload metadata needed to synchronize live inference with GPS.
    _atomic_write_json(os.path.join(run_dir, "metadata.json"), metadata)

    # Initialize valid empty GIS artifacts so the client can show the selected
    # video immediately while the background detection pass is running.
    geojson = build_geojson_feature_collection(
        [], trajectory.to_coordinates_list() if trajectory else [], metadata
    )
    _atomic_write_json(os.path.join(run_dir, "hazard_map.geojson"), geojson)
    _atomic_write_json(os.path.join(run_dir, "telemetry.json"), preliminary_telemetry)

    # Always scan the complete video, whether or not GPS was supplied. This is
    # important for the user's expected workflow: upload first, analyze the whole
    # clip, then replay it with time-synchronized pothole outlines. GPS only adds
    # geospatial anchoring and vehicle telemetry; it is not required to detect.
    result_status = "processing"
    background_tasks.add_task(
        _background_gis_process,
        video_save_path,
        gps_save_path,
        run_id,
        float(time_offset_sec or 0.0),
        video.filename,
        gps.filename if gps_save_path and gps else None,
    )
    _write_job_status(
        run_dir,
        "processing",
        progress_percent=0.0,
        message=("Video ready; complete AI road-damage analysis is running in the background." if gps_save_path
                 else "Video ready; complete AI road-damage analysis is running. GPS is optional for detection."),
    )

    result = {
        "run_id": run_id,
        "status": result_status,
        "is_synthetic": False,
        "metadata": metadata,
        "hazards_count": 0,
        "hazards": [],
        "geojson_url": f"/api/geojson/{run_id}",
        "telemetry_url": f"/api/telemetry/{run_id}",
        "live_detection_enabled": True,
        "video_url": f"/api/video/{run_id}?v={playback_token}",
        "video_playback_warning": playback.get("warning"),
        "video_playback_format": playback.get("media_type"),
    }
    return result


@router.post("/detect/frame")
async def detect_video_frame(
    frame: UploadFile = File(...),
    timestamp_sec: Optional[float] = Form(0.0),
    run_id: Optional[str] = Form(None),
):
    """Run a single live inference pass on the current uploaded-video frame."""
    if not frame.filename:
        raise HTTPException(status_code=400, detail="No video frame received.")
    content = await frame.read()
    if not content:
        raise HTTPException(status_code=400, detail="Empty frame payload.")
    if len(content) > 5 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="Frame payload exceeds 5MB.")

    encoded = np.frombuffer(content, dtype=np.uint8)
    decoded = cv2.imdecode(encoded, cv2.IMREAD_COLOR)
    if decoded is None or decoded.size == 0:
        raise HTTPException(status_code=400, detail="Frame is not a valid JPEG/PNG image.")

    height, width = decoded.shape[:2]
    timestamp = max(0.0, float(timestamp_sec or 0.0))
    started = time.perf_counter()
    try:
        detections = await run_in_threadpool(
            runner.detector.analyze_frame,
            decoded,
            int(timestamp * 10),
            timestamp,
            "live",
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Live frame inference failed: {exc}")

    trajectory = None
    time_offset = 0.0
    if run_id:
        trajectory, time_offset = _get_live_trajectory(run_id)
    vehicle_state = trajectory.get_state_at_time(timestamp, time_offset) if trajectory else None

    cleaned = []
    for item in detections:
        hazard_type = item.get("type", "unknown_hazard")
        definition = HAZARD_DEFINITIONS.get(hazard_type, {})
        bbox = [round(float(v), 2) for v in item.get("bbox", [])]
        hazard = {
            "type": hazard_type,
            "label": item.get("label") or definition.get("label", hazard_type.replace("_", " ").title()),
            "class_code": item.get("class_code"),
            "bbox": bbox,
            "polygon": [[round(float(pt[0]), 2), round(float(pt[1]), 2)] for pt in item.get("polygon", []) if isinstance(pt, (list, tuple)) and len(pt) >= 2 and np.isfinite(float(pt[0])) and np.isfinite(float(pt[1]))],
            "has_mask": bool(item.get("has_mask")),
            "conf": round(float(item.get("confidence", 0.0)), 3),
            "source": item.get("source", "unknown"),
            "verification": item.get("verification", "provisional_heuristic"),
            "timestamp_sec": round(timestamp, 3),
            "lat": None,
            "lon": None,
            "severity": "Medium",
            "location_quality": "gps_track_not_supplied",
        }
        # Live points are estimated from camera geometry and synchronized GPS;
        # the UI keeps them separate from surveyed/ground-truth incidents.
        if vehicle_state is not None and len(bbox) == 4 and vehicle_state.is_in_coverage:
            d_forward, d_lateral = _live_camera_geometry.project_pixel_to_ground(bbox, width, height)
            lat, lon, quality, uncertainty = direct_geodesic_project(
                vehicle_state.lat,
                vehicle_state.lon,
                vehicle_state.heading_deg,
                d_forward,
                d_lateral,
                vehicle_speed_kmh=vehicle_state.speed_kmh,
                is_in_coverage=True,
            )
            box_area_ratio = max(0.0, (bbox[2] - bbox[0]) * (bbox[3] - bbox[1])) / float(width * height + 1e-5)
            hazard.update({
                "lat": lat,
                "lon": lon,
                "severity": compute_severity(hazard_type, box_area_ratio, d_lateral),
                "location_quality": quality,
                "estimated_uncertainty_m": uncertainty,
                "forward_distance_m": round(float(d_forward), 2),
                "lateral_offset_m": round(float(d_lateral), 2),
                "lane_location": estimate_lane_location(d_lateral),
            })
        elif vehicle_state is not None:
            hazard["location_quality"] = "unanchored_out_of_gps_coverage"
        cleaned.append(hazard)

    vehicle_telemetry = None
    if vehicle_state is not None:
        vehicle_telemetry = {
            "lat": vehicle_state.lat,
            "lon": vehicle_state.lon,
            "speed_kmh": vehicle_state.speed_kmh,
            "heading_deg": vehicle_state.heading_deg,
            "is_in_coverage": vehicle_state.is_in_coverage,
        }

    return {
        "timestamp_sec": timestamp,
        "frame_width": width,
        "frame_height": height,
        "detections": cleaned,
        "count": len(cleaned),
        "vehicle_telemetry": vehicle_telemetry,
        "inference_ms": round((time.perf_counter() - started) * 1000, 1),
        "engine": runner.detector.status().get("engine", "local YOLO + OpenCV"),
        "model_status": runner.detector.status(),
        "warning": "Detections are predictions. GPS-projected points are approximate camera estimates, not survey-grade coordinates.",
    }


@router.get("/process/status/{run_id}")
def get_process_status(run_id: str):
    """Poll background GIS processing without blocking video playback."""
    run_dir = os.path.join(str(RUNS_DIR), run_id)
    status_path = os.path.join(run_dir, "job_status.json")
    if not os.path.isfile(status_path):
        raise HTTPException(status_code=404, detail="Processing job not found.")
    with open(status_path, "r", encoding="utf-8") as handle:
        status_data = json.load(handle)
    if status_data.get("status") == "completed":
        summary_path = os.path.join(run_dir, "summary.json")
        if os.path.isfile(summary_path):
            with open(summary_path, "r", encoding="utf-8") as handle:
                status_data["result"] = json.load(handle)
    return JSONResponse(content=status_data)


@router.get("/geojson/{run_id}")
@router.get("/export/geojson/{run_id}")
def get_geojson(run_id: str):
    """Returns the RFC 7946 GeoJSON FeatureCollection for a processed run."""
    geojson_path = os.path.join(str(RUNS_DIR), run_id, "hazard_map.geojson")
    if not os.path.exists(geojson_path):
        raise HTTPException(status_code=404, detail="GeoJSON not found for run.")

    with open(geojson_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    return JSONResponse(content=data)


@router.get("/telemetry/{run_id}")
def get_telemetry(run_id: str):
    """Returns synchronized per-frame telemetry for video playback HUD."""
    tel_path = os.path.join(str(RUNS_DIR), run_id, "telemetry.json")
    if not os.path.exists(tel_path):
        raise HTTPException(status_code=404, detail="Telemetry not found for run.")

    with open(tel_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    return JSONResponse(content=data)


@router.get("/hazard-crops/{run_id}/{filename}")
def get_hazard_crop(run_id: str, filename: str):
    """Serves extracted visual crop of a detected hazard."""
    crop_path = os.path.join(str(RUNS_DIR), run_id, "crops", filename)
    if not os.path.exists(crop_path):
        raise HTTPException(status_code=404, detail="Hazard crop snapshot not found.")
    return FileResponse(crop_path, media_type="image/jpeg")


@router.get("/video/{run_id}")
def get_video(run_id: str):
    """Serves the playback copy using the MIME type matching its real extension."""
    run_dir = os.path.join(str(RUNS_DIR), run_id)
    candidates = [
        "video.mp4", "video.webm", "video.mov", "video.avi", "video.mkv"
    ]
    video_path = next(
        (os.path.join(run_dir, name) for name in candidates if os.path.isfile(os.path.join(run_dir, name))),
        None,
    )
    if not video_path:
        raise HTTPException(status_code=404, detail="Video playback file not found for run.")
    import mimetypes
    media_type = mimetypes.guess_type(video_path)[0] or "application/octet-stream"
    return FileResponse(
        video_path,
        media_type=media_type,
        filename=None,
        headers={"Cache-Control": "no-store, max-age=0", "Pragma": "no-cache"},
    )


@router.get("/export/csv/{run_id}")
def export_csv(run_id: str):
    """Exports structured hazard incident data as a CSV table."""
    summary_path = os.path.join(str(RUNS_DIR), run_id, "summary.json")
    if not os.path.exists(summary_path):
        raise HTTPException(status_code=404, detail="Run not found.")

    with open(summary_path, "r", encoding="utf-8") as f:
        summary = json.load(f)

    hazards = summary.get("hazards", [])
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([
        "Hazard_ID", "Type", "Severity", "Confidence", "Source", "Verification",
        "Latitude", "Longitude", "Location_Quality", "Uncertainty_M",
        "Forward_Distance_M", "Lateral_Offset_M", "Lane_Location",
        "Timestamp_Sec", "GPS_Timestamp", "Is_Synthetic", "Data_Classification"
    ])

    for h in hazards:
        writer.writerow([
            h.get("id"), h.get("type"), h.get("severity"), h.get("confidence"),
            h.get("source", "cv_surface_analyzer"), h.get("verification", "provisional_heuristic"),
            h.get("lat"), h.get("lon"), h.get("location_quality", "approximate_camera_projection_unvalidated"),
            h.get("estimated_uncertainty_m"),
            h.get("forward_distance_m"), h.get("lateral_offset_m"), h.get("lane_location"),
            h.get("timestamp_sec"), h.get("gps_timestamp"),
            summary.get("is_synthetic", False),
            summary.get("metadata", {}).get("data_classification", "USER_UPLOADED_UNVERIFIED")
        ])

    csv_data = output.getvalue()
    return Response(
        content=csv_data,
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename=civicroute_hazards_{run_id}.csv"}
    )


@router.get("/export/report/{run_id}")
def export_municipal_report(run_id: str):
    """Generates a structured Municipal Emergency Work Order & Incident Report."""
    summary_path = os.path.join(str(RUNS_DIR), run_id, "summary.json")
    if not os.path.exists(summary_path):
        raise HTTPException(status_code=404, detail="Run not found.")

    with open(summary_path, "r", encoding="utf-8") as f:
        summary = json.load(f)

    meta = summary.get("metadata", {})
    hazards = summary.get("hazards", [])
    is_synthetic = summary.get("is_synthetic", False)

    report = {
        "title": "MUNICIPAL INFRASTRUCTURE & EMERGENCY ROAD HAZARD ACTION PLAN",
        "organization": "CivicRouteAD - Urban Situational Awareness System",
        "run_id": run_id,
        "data_classification": summary.get("metadata", {}).get("data_classification") or (
            "SYNTHETIC_BENCHMARK_FIXTURE" if is_synthetic else "USER_UPLOADED_UNVERIFIED"
        ),
        "is_synthetic": is_synthetic,
        "verification_notice": (
            "Synthetic demonstration data; not real-world observations."
            if is_synthetic else
            "User-uploaded data; origin and measurements have not been independently verified."
        ),
        "survey_date": meta.get("generated_at", ""),
        "route_summary": {
            "total_distance_km": round(meta.get("total_distance_m", 0.0) / 1000.0, 3),
            "survey_duration_sec": meta.get("duration_sec", 0.0),
            "average_speed_kmh": meta.get("avg_speed_kmh", 0.0),
            "total_hazards_logged": len(hazards),
            "coverage_ratio": meta.get("coverage_ratio", 1.0)
        },
        "critical_action_items": [],
        "routine_maintenance_items": []
    }

    for h in hazards:
        item = {
            "hazard_id": h.get("id"),
            "category": h.get("type"),
            "severity": h.get("severity"),
            "location_coords": f"{h.get('lat')}, {h.get('lon')}",
            "location_quality": h.get("location_quality", "approximate_camera_projection_unvalidated"),
            "estimated_uncertainty_m": (
                f"Indicative ±{float(h['estimated_uncertainty_m']):.1f} m"
                if isinstance(h.get("estimated_uncertainty_m"), (int, float))
                else "Not established; camera projection is uncalibrated"
            ),
            "detection_verification": h.get("verification", "provisional_heuristic"),
            "lane_position": h.get("lane_location"),
            "confidence": f"{int(h.get('confidence', 0) * 100)}%",
            "recommended_dispatch": "Emergency crew with heavy equipment required." if h.get("severity") in ("Critical", "High") else "Standard patch crew within 48h."
        }
        if h.get("severity") in ("Critical", "High"):
            report["critical_action_items"].append(item)
        else:
            report["routine_maintenance_items"].append(item)

    return JSONResponse(content=report)
