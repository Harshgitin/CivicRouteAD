"""
CivicRouteAD - Complete Edge-to-GIS Pipeline Runner
Coordinates video decoding, GPS synchronization, AI hazard detection & tracking,
pinhole ground projection, and GeoJSON export with explicit uncertainty flags.
"""

import os
import cv2
import json
import uuid
import numpy as np
from typing import Dict, Any, List, Optional, Callable
from app.config import RUNS_DIR
from app.ai.detector import RoadHazardDetector, HazardTracker
from app.ai.hazard_classes import compute_severity, HAZARD_DEFINITIONS
from app.geospatial.gps_parser import GPSTrajectory, parse_gpx_file, parse_csv_trajectory
from app.geospatial.projection import CameraGeometry, direct_geodesic_project, estimate_lane_location
from app.geospatial.geojson_builder import build_geojson_feature_collection


class PipelineRunner:
    def __init__(self, runs_dir=None, model_path: Optional[str] = "yolov8n.pt"):
        self.runs_dir = str(runs_dir or RUNS_DIR)
        os.makedirs(self.runs_dir, exist_ok=True)
        self.detector = RoadHazardDetector(model_path=model_path, confidence_threshold=0.35)
        self.camera_geom = CameraGeometry(camera_height_m=1.4, camera_pitch_deg=2.2)

    def process_run(
        self,
        video_path: str,
        gps_path: Optional[str] = None,
        run_id: Optional[str] = None,
        sample_step: int = 3,
        time_offset_sec: float = 0.0,
        is_synthetic: bool = False,
        output_root: Optional[str] = None,
        progress_callback: Optional[Callable[[Dict[str, Any]], None]] = None,
    ) -> Dict[str, Any]:
        """
        Analyze the entire video at a configurable frame stride. When GPS is
        supplied, detections are also geolocated and exported to GIS. Without
        GPS, the complete visual analysis still runs and detections are saved
        with null geometry instead of fabricated coordinates.
        sample_step: frame stride (e.g. 3 processes ~10 FPS from 30 FPS video).
        time_offset_sec: shifts video time relative to GPS trajectory.
        is_synthetic: flags whether data originated from a synthetic demo benchmark.
        progress_callback: optional callback for background job progress reporting.
        """
        if not run_id:
            run_id = f"run_{uuid.uuid4().hex[:8]}"
        sample_step = max(1, int(sample_step or 1))

        # Report analyses may write under a private report directory instead of
        # the static /runs directory used by the public technical analysis lab.
        run_output_dir = os.path.join(str(output_root or self.runs_dir), run_id)
        crops_dir = os.path.join(run_output_dir, "crops")
        os.makedirs(crops_dir, exist_ok=True)

        # 1. Parse the GPS trajectory when provided. Visual detection must not
        # depend on GPS; GPS only enables vehicle telemetry and geolocation.
        trajectory = None
        if gps_path:
            if gps_path.lower().endswith(".gpx"):
                trajectory = parse_gpx_file(gps_path)
            else:
                trajectory = parse_csv_trajectory(gps_path)

        # 2. Open and inspect Video
        cap = cv2.VideoCapture(video_path)
        if not cap.isOpened():
            raise ValueError(f"Could not open or decode video file: {video_path}")

        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
        width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        duration_sec = total_frames / fps if fps > 0 else 0.0

        if total_frames <= 0 or duration_sec <= 0.0:
            cap.release()
            raise ValueError(f"Video file has invalid length (frames: {total_frames}, duration: {duration_sec}s).")

        # 3. Check temporal coverage when a GPS track exists.
        coverage_report = trajectory.check_coverage(duration_sec, time_offset_sec) if trajectory else {
            "coverage_ratio": 0.0,
            "warnings": ["No synchronized GPS track supplied; visual detections are not geolocated."],
            "gaps": [],
        }
        if trajectory and coverage_report["coverage_ratio"] < 0.1:
            print(f"[PipelineRunner] Warning: Extremely low GPS/video overlap ({coverage_report['coverage_ratio']*100}%).")

        # Reset the low-rate supplementary COCO cadence for this clip. The primary
        # road-damage model still runs at every selected analysis frame.
        if hasattr(self.detector, "reset_general_model_cadence"):
            self.detector.reset_general_model_cadence()

        tracker = HazardTracker(iou_threshold=0.20, max_frame_gap=15)
        frame_telemetry = []

        frame_idx = 0
        processed_samples = 0
        last_progress_frame = -1
        progress_every = max(sample_step, int(max(total_frames, 1) * 0.025))
        if progress_callback:
            progress_callback({
                "frames_processed": 0,
                "total_frames": total_frames,
                "progress_percent": 0.0,
                "current_time_sec": 0.0,
                "sampled_frames": 0,
            })
        while cap.isOpened():
            ret, frame = cap.read()
            if not ret:
                break

            time_sec = frame_idx / fps
            vehicle_state = trajectory.get_state_at_time(time_sec, time_offset_sec) if trajectory else None

            # Scan the whole clip at the configured stride. The default upload
            # stride is ~10 sampled frames/second for a 30 FPS clip, which covers
            # moving road defects much more reliably than sparse 4-5 FPS sampling
            # while keeping the player responsive because this work is async.
            if frame_idx % sample_step == 0:
                current_detections = self.detector.analyze_frame(frame, frame_idx, time_sec, priority="background")
                tracker.update(current_detections, frame, frame_idx, time_sec)
                frame_telemetry.append({
                    "frame": frame_idx,
                    "time_sec": round(time_sec, 3),
                    "frame_width": int(width),
                    "frame_height": int(height),
                    "lat": round(vehicle_state.lat, 7) if vehicle_state and vehicle_state.lat is not None else None,
                    "lon": round(vehicle_state.lon, 7) if vehicle_state and vehicle_state.lon is not None else None,
                    "speed_kmh": round(vehicle_state.speed_kmh, 1) if vehicle_state and vehicle_state.speed_kmh is not None else None,
                    "heading_deg": round(vehicle_state.heading_deg, 1) if vehicle_state and vehicle_state.heading_deg is not None else None,
                    "is_in_coverage": vehicle_state.is_in_coverage if vehicle_state else None,
                    "detection_frame": True,
                    "detections": [
                        {
                            "type": d["type"],
                            "bbox": d["bbox"],
                            "polygon": d.get("polygon"),
                            "has_mask": bool(d.get("has_mask")),
                            "conf": d["confidence"],
                            "source": d.get("source", "cv_surface_analyzer"),
                            "verification": d.get("verification", "provisional_heuristic"),
                            "label": d.get("label") or HAZARD_DEFINITIONS.get(d["type"], {}).get("label", d["type"]),
                            "class_code": d.get("class_code")
                        }
                        for d in current_detections
                    ]
                })
                processed_samples += 1

            if progress_callback and (
                frame_idx == total_frames - 1
                or frame_idx - last_progress_frame >= progress_every
            ):
                progress_callback({
                    "frames_processed": min(frame_idx + 1, total_frames),
                    "total_frames": total_frames,
                    "progress_percent": round(min(100.0, ((frame_idx + 1) / total_frames) * 100.0), 1),
                    "current_time_sec": round(time_sec, 2),
                    "sampled_frames": processed_samples,
                })
                last_progress_frame = frame_idx

            frame_idx += 1

        cap.release()

        # 4. Finalize hazard tracks & project to ground coordinates
        raw_hazards = tracker.finish()
        final_hazards = []

        for haz in raw_hazards:
            h_id = haz["id"]
            best_t = haz["best_timestamp_sec"]
            v_state = trajectory.get_state_at_time(best_t, time_offset_sec) if trajectory else None
            bbox = haz["best_bbox"]

            # Calculate camera ground projection
            d_forward, d_lateral = self.camera_geom.project_pixel_to_ground(bbox, width, height)
            if v_state and v_state.is_in_coverage:
                h_lat, h_lon, quality, uncertainty_m = direct_geodesic_project(
                    v_state.lat,
                    v_state.lon,
                    v_state.heading_deg,
                    d_forward,
                    d_lateral,
                    vehicle_speed_kmh=v_state.speed_kmh,
                    is_in_coverage=True
                )
            elif trajectory:
                # Never reuse the first/last GPS waypoint as if it were the hazard location.
                h_lat, h_lon = None, None
                quality, uncertainty_m = 'unanchored_out_of_gps_coverage', None
            else:
                h_lat, h_lon = None, None
                quality, uncertainty_m = 'gps_track_not_supplied', None

            # Compute box area ratio
            box_area = (bbox[2] - bbox[0]) * (bbox[3] - bbox[1])
            box_area_ratio = box_area / float(width * height + 1e-5)

            severity = compute_severity(haz["type"], box_area_ratio, d_lateral)
            lane_loc = estimate_lane_location(d_lateral)

            # Save crop snapshot
            crop_filename = f"{h_id.lower()}.jpg"
            crop_path = os.path.join(crops_dir, crop_filename)
            if haz.get("crop_image") is not None and haz["crop_image"].size > 0:
                cv2.imwrite(crop_path, haz["crop_image"])
                snapshot_url = f"/api/hazard-crops/{run_id}/{crop_filename}"
            else:
                snapshot_url = ""

            final_hazards.append({
                "id": h_id,
                "type": haz["type"],
                "label": haz.get("label") or HAZARD_DEFINITIONS.get(haz["type"], {}).get("label", haz["type"]),
                "class_code": haz.get("class_code"),
                "polygon": haz.get("best_polygon"),
                "has_mask": bool(haz.get("best_has_mask")),
                "severity": severity,
                "confidence": haz["best_confidence"],
                "source": haz.get("source", "cv_surface_analyzer"),
                "verification": haz.get("verification", "provisional_heuristic"),
                "lat": h_lat,
                "lon": h_lon,
                "location_quality": quality,
                "estimated_uncertainty_m": uncertainty_m,
                "forward_distance_m": d_forward,
                "lateral_offset_m": d_lateral,
                "lane_location": lane_loc,
                "timestamp_sec": round(best_t, 2),
                "gps_timestamp": v_state.iso_time if v_state else None,
                "frame_idx": haz["best_frame_idx"],
                "duration_visible_sec": round(haz["end_time_sec"] - haz["start_time_sec"], 2),
                "snapshot_url": snapshot_url,
                "is_synthetic": is_synthetic
            })

        # 5. Generate GeoJSON Feature Collection
        meta = {
            "run_id": run_id,
            "is_synthetic": is_synthetic,
            "data_classification": "SYNTHETIC_BENCHMARK_FIXTURE" if is_synthetic else "USER_UPLOADED_UNVERIFIED",
            "geolocation_notice": (
                "Synthetic route is illustrative and not road-matched." if is_synthetic else
                "No synchronized GPS track was supplied; detections have no real-world coordinates." if not trajectory else
                "Camera-projected hazard positions are approximate; camera calibration and ground-truth accuracy have not been validated."
            ),
            "total_distance_m": getattr(trajectory, "total_distance_m", 0.0) if trajectory else 0.0,
            "duration_sec": duration_sec,
            "avg_speed_kmh": round((getattr(trajectory, "total_distance_m", 0.0) / max(1.0, duration_sec)) * 3.6, 1) if trajectory else None,
            "frame_count": total_frames,
            "fps": round(float(fps), 3),
            "sample_step": sample_step,
            "sampled_frames": len(frame_telemetry),
            "video_filename": os.path.basename(video_path),
            "gps_filename": os.path.basename(gps_path) if gps_path else None,
            "gps_available": bool(trajectory),
            "coverage_ratio": coverage_report.get("coverage_ratio", 1.0),
            "warnings": coverage_report.get("warnings", []),
            "time_offset_sec": time_offset_sec,
            "detector": self.detector.status()
        }

        geojson_data = build_geojson_feature_collection(
            final_hazards,
            trajectory.to_coordinates_list() if trajectory else [],
            meta
        )

        # Save artifacts to run folder
        geojson_path = os.path.join(run_output_dir, "hazard_map.geojson")
        with open(geojson_path, "w", encoding="utf-8") as f:
            json.dump(geojson_data, f, indent=2)

        telemetry_path = os.path.join(run_output_dir, "telemetry.json")
        with open(telemetry_path, "w", encoding="utf-8") as f:
            json.dump(frame_telemetry, f)

        summary = {
            "run_id": run_id,
            "status": "completed",
            "is_synthetic": is_synthetic,
            "metadata": meta,
            "hazards_count": len(final_hazards),
            "hazards": final_hazards,
            "geojson_url": f"/api/geojson/{run_id}",
            "telemetry_url": f"/api/telemetry/{run_id}",
            "report_url": f"/api/export/report/{run_id}"
        }

        summary_path = os.path.join(run_output_dir, "summary.json")
        with open(summary_path, "w", encoding="utf-8") as f:
            json.dump(summary, f, indent=2)

        return summary
