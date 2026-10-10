"""
CivicRouteAD - Scenario Manager & Synthetic Dashcam Video Generator
Provides pre-packaged benchmark scenarios (Storm Debris, Flash Flooding, Urban Potholes)
with synchronized MP4 dashcam video and GPX trajectory logs.
"""

import os
import math
import cv2
import numpy as np
from datetime import datetime, timezone, timedelta
from typing import Dict, Any, List


from app.config import SCENARIOS_DIR
from app.video_compat import ensure_browser_mp4


SCENARIOS_META = [
    {
        "id": "scenario_storm_debris",
        "title": "[Synthetic Demo] Severe Storm & Downed Timber",
        "description": "SYNTHETIC TEST FIXTURE: Simulated post-cyclonic road survey with tree canopy obscuring satellite vision. Features simulated fallen timber, rock debris, and damaged powerline.",
        "location": "Pacific Northwest Highway 101",
        "start_coords": [45.8914, -123.9615],
        "hazards_present": ["Fallen Tree", "Rockfall Debris", "Downed Powerline"],
        "duration_sec": 12.0,
        "video_file": "storm_survey.mp4",
        "gps_file": "storm_survey.gpx",
        "is_synthetic": True
    },
    {
        "id": "scenario_flash_flood",
        "title": "[Synthetic Demo] Flash Flooding & Stormwater",
        "description": "SYNTHETIC TEST FIXTURE: Simulated coastal artery with stormwater runoff, submerged lanes, and localized waterlogging creating aquaplaning hazards.",
        "location": "Coastal Boulevard Sector 4",
        "start_coords": [25.7617, -80.1918],
        "hazards_present": ["Localized Flooding", "Waterlogged Lane"],
        "duration_sec": 10.0,
        "video_file": "flood_survey.mp4",
        "gps_file": "flood_survey.gpx",
        "is_synthetic": True
    },
    {
        "id": "scenario_urban_potholes",
        "title": "[Synthetic Demo] Urban Potholes & Structural Cracks",
        "description": "SYNTHETIC TEST FIXTURE: Simulated road degradation benchmark with deep asphalt cavities (D00/D20) and displaced construction barriers.",
        "location": "Metropolitan Expressway Connector",
        "start_coords": [35.6895, 139.6917],
        "hazards_present": ["Severe Pothole (D00)", "Longitudinal Crack (D20)", "Construction Barrier"],
        "duration_sec": 10.0,
        "video_file": "pothole_survey.mp4",
        "gps_file": "pothole_survey.gpx",
        "is_synthetic": True
    }
]


def generate_scenario_files(base_dir=None):
    """
    Synthesizes illustrative dashcam videos and matching synthetic GPX tracks
    if they do not already exist. Synthetic routes are for pipeline testing and
    are not road-matched geographic ground truth.
    """
    target_dir = str(base_dir or SCENARIOS_DIR)
    os.makedirs(target_dir, exist_ok=True)

    for sc in SCENARIOS_META:
        sc_dir = os.path.join(target_dir, sc["id"])
        os.makedirs(sc_dir, exist_ok=True)

        video_path = os.path.join(sc_dir, sc["video_file"])
        gps_path = os.path.join(sc_dir, sc["gps_file"])

        if not os.path.exists(gps_path):
            _create_gpx_file(gps_path, sc)

        if not os.path.exists(video_path):
            _render_synthetic_dashcam_video(video_path, sc)

        # Existing projects may have been generated with mp4v/MPEG-4 Part 2,
        # which OpenCV can decode but browser HTML5 players may reject. Upgrade
        # old fixtures in place when FFmpeg is available.
        compatible, message = ensure_browser_mp4(video_path)
        if not compatible:
            print(f"[ScenarioManager] Playback compatibility note for {video_path}: {message}")


def _create_gpx_file(filepath: str, meta: Dict[str, Any]):
    """Generates timestamped synthetic GPX points for a demo, not road-matched ground truth."""
    start_lat, start_lon = meta["start_coords"]
    duration = int(meta["duration_sec"])
    base_time = datetime(2026, 10, 9, 8, 30, 0, tzinfo=timezone.utc)

    safe_title = meta["title"].replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    # 1 Hz synthetic trackpoints with mild curve and elevation variation.
    # This is deliberately labelled illustrative; it is not snapped to road geometry.
    gpx_lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<gpx version="1.1" creator="CivicRouteAD" xmlns="http://www.topografix.com/GPX/1/1">',
        f'  <trk><name>{safe_title}</name><trkseg>'
    ]

    curr_lat = start_lat
    curr_lon = start_lon
    curr_ele = 142.0

    # Moving roughly North-East at ~14 m/s (50 km/h)
    d_lat_step = 0.00012
    d_lon_step = 0.00010

    for s in range(duration + 1):
        t = base_time + timedelta(seconds=s)
        time_str = t.strftime("%Y-%m-%dT%H:%M:%SZ")

        # Add mild curve
        curr_lat += d_lat_step + 0.00002 * math.sin(s * 0.4)
        curr_lon += d_lon_step + 0.00001 * math.cos(s * 0.4)
        curr_ele += 0.3 * math.sin(s * 0.3)

        speed_ms = 13.8 + 1.2 * math.sin(s * 0.5)

        gpx_lines.append(
            f'    <trkpt lat="{curr_lat:.6f}" lon="{curr_lon:.6f}">'
            f'<ele>{curr_ele:.1f}</ele>'
            f'<time>{time_str}</time>'
            f'<speed>{speed_ms:.2f}</speed>'
            f'</trkpt>'
        )

    gpx_lines.extend(['  </trkseg></trk>', '</gpx>'])

    with open(filepath, "w", encoding="utf-8") as f:
        f.write("\n".join(gpx_lines))


def _render_synthetic_dashcam_video(filepath: str, meta: Dict[str, Any]):
    """
    Renders an authentic dashcam perspective video in 720p HD
    with road vanishing lines, moving lane markers, scenery, and
    realistic road hazards approaching at specific timestamps.
    """
    w, h = 1280, 720
    fps = 25
    total_frames = int(meta["duration_sec"] * fps)
    sc_id = meta["id"]

    # Use mp4v codec
    fourcc = cv2.VideoWriter_fourcc(*"mp4v")
    out = cv2.VideoWriter(filepath, fourcc, fps, (w, h))

    vanish_x = w // 2
    vanish_y = int(h * 0.42)

    for f_idx in range(total_frames):
        t_sec = f_idx / fps
        frame = np.zeros((h, w, 3), dtype=np.uint8)

        # 1. Sky and horizon background
        if sc_id == "scenario_storm_debris":
            # Overcast moody storm sky
            cv2.rectangle(frame, (0, 0), (w, vanish_y), (85, 95, 100), -1)
            # Mountain/forest silhouettes
            for mx in range(0, w, 80):
                pts = np.array([[mx, vanish_y], [mx + 40, vanish_y - 70], [mx + 80, vanish_y]], np.int32)
                cv2.fillPoly(frame, [pts], (45, 60, 50))
        elif sc_id == "scenario_flash_flood":
            # Storm rainy sky
            cv2.rectangle(frame, (0, 0), (w, vanish_y), (70, 80, 95), -1)
        else:
            # Urban highway daylight
            cv2.rectangle(frame, (0, 0), (w, vanish_y), (140, 160, 180), -1)
            # Buildings
            for bx in range(0, w, 120):
                bh = 60 + (bx % 7) * 15
                cv2.rectangle(frame, (bx, vanish_y - bh), (bx + 80, vanish_y), (110, 120, 130), -1)

        # 2. Road surface (perspective trapezoid)
        road_pts = np.array([
            [vanish_x - 70, vanish_y],
            [vanish_x + 70, vanish_y],
            [w + 150, h],
            [-150, h]
        ], np.int32)
        cv2.fillPoly(frame, [road_pts], (50, 52, 55)) # Dark asphalt

        # Road shoulders / curbs
        cv2.line(frame, (vanish_x - 70, vanish_y), (-150, h), (90, 95, 100), 6)
        cv2.line(frame, (vanish_x + 70, vanish_y), (w + 150, h), (90, 95, 100), 6)

        # 3. Moving center dashed lane lines
        cycle = (f_idx * 1.8) % 30
        for i in range(7):
            dist_fraction = ((i * 15 + cycle) % 100) / 100.0
            if dist_fraction < 0.05:
                continue
            y_start = int(vanish_y + (h - vanish_y) * (dist_fraction ** 1.8))
            y_end = int(y_start + 25 * dist_fraction)
            if y_end > h:
                break
            x_pos = int(vanish_x + (dist_fraction ** 1.8) * 10)
            thickness = max(2, int(6 * dist_fraction))
            cv2.line(frame, (x_pos, y_start), (x_pos, y_end), (220, 220, 100), thickness)

        # 4. Render Specific Road Hazards as vehicle drives toward them
        if sc_id == "scenario_storm_debris":
            # Hazard 1: Downed Tree across road (approaches between 2.0s and 6.0s)
            if 2.0 <= t_sec <= 6.5:
                progress = (t_sec - 2.0) / 4.5 # 0.0 to 1.0
                hazard_scale = progress ** 1.6
                hz_y = int(vanish_y + (h - vanish_y) * 0.75 * hazard_scale)
                hz_w = int(320 * hazard_scale)
                hz_h = int(65 * hazard_scale)
                hz_x = int(vanish_x - hz_w * 0.45)

                if hz_w > 15 and hz_y < h - 20:
                    # Draw fallen tree trunk (timber)
                    cv2.ellipse(frame, (hz_x + hz_w // 2, hz_y), (hz_w // 2, hz_h // 2), -5, 0, 360, (25, 45, 65), -1)
                    # Draw foliage / green branches
                    for fx in range(hz_x, hz_x + hz_w, max(5, int(20 * hazard_scale))):
                        cv2.circle(frame, (fx, hz_y - int(10 * hazard_scale)), int(18 * hazard_scale), (20, 80, 30), -1)

            # Hazard 2: Downed Powerline / wire across lane (7.0s to 11.0s)
            if 7.0 <= t_sec <= 11.0:
                prog2 = (t_sec - 7.0) / 4.0
                hz_scale2 = prog2 ** 1.5
                wire_y = int(vanish_y + (h - vanish_y) * 0.8 * hz_scale2)
                if wire_y < h - 10:
                    cv2.line(frame, (int(w * 0.1), wire_y - int(25 * hz_scale2)), (int(w * 0.9), wire_y + int(10 * hz_scale2)), (20, 20, 20), max(2, int(4 * hz_scale2)))
                    # Utility pole base
                    cv2.rectangle(frame, (int(w * 0.15), wire_y - int(80 * hz_scale2)), (int(w * 0.18), wire_y), (35, 55, 75), -1)

        elif sc_id == "scenario_flash_flood":
            # Hazard: Localized Road Flooding / Submerged Lane (approaches 2.0s to 8.5s)
            if 2.0 <= t_sec <= 8.5:
                progress = (t_sec - 2.0) / 6.5
                flood_scale = progress ** 1.5
                fl_y = int(vanish_y + (h - vanish_y) * 0.78 * flood_scale)
                fl_w = int(450 * flood_scale)
                fl_h = int(110 * flood_scale)
                fl_x = int(vanish_x - fl_w * 0.5)

                if fl_w > 20 and fl_y < h - 20:
                    # Water pool polygon with specular reflection
                    flood_poly = np.array([
                        [fl_x, fl_y],
                        [fl_x + fl_w, fl_y],
                        [fl_x + int(fl_w * 1.1), fl_y + fl_h],
                        [fl_x - int(fl_w * 0.1), fl_y + fl_h]
                    ], np.int32)
                    overlay = frame.copy()
                    cv2.fillPoly(overlay, [flood_poly], (140, 110, 70)) # Murky water pool
                    cv2.addWeighted(overlay, 0.75, frame, 0.25, 0, frame)
                    # Specular water highlights
                    for i in range(4):
                        ripple_y = fl_y + int((i + 1) * fl_h * 0.2)
                        cv2.line(frame, (fl_x + int(fl_w * 0.2), ripple_y), (fl_x + int(fl_w * 0.8), ripple_y), (220, 210, 190), max(1, int(2 * flood_scale)))

        elif sc_id == "scenario_urban_potholes":
            # Hazard 1: Severe Pothole (D00/D10) (approaches 1.5s to 5.5s)
            if 1.5 <= t_sec <= 5.5:
                prog = (t_sec - 1.5) / 4.0
                scale = prog ** 1.6
                pt_y = int(vanish_y + (h - vanish_y) * 0.8 * scale)
                pt_w = int(140 * scale)
                pt_h = int(60 * scale)
                pt_x = int(vanish_x + 50 * scale)

                if pt_w > 10 and pt_y < h - 15:
                    # Pothole dark cavity
                    cv2.ellipse(frame, (pt_x, pt_y), (pt_w // 2, pt_h // 2), 10, 0, 360, (20, 22, 24), -1)
                    # Jagged asphalt rupture edges
                    cv2.ellipse(frame, (pt_x, pt_y), (pt_w // 2, pt_h // 2), 10, 0, 360, (75, 78, 80), max(2, int(3 * scale)))

            # Hazard 2: Displaced Barrier / Structural Blockage (approaches 5.5s to 9.5s)
            if 5.5 <= t_sec <= 9.5:
                prog2 = (t_sec - 5.5) / 4.0
                scale2 = prog2 ** 1.6
                br_y = int(vanish_y + (h - vanish_y) * 0.82 * scale2)
                br_w = int(130 * scale2)
                br_h = int(120 * scale2)
                br_x = int(vanish_x - int(120 * scale2))

                if br_w > 10 and br_y < h - 15:
                    # Orange construction barricade
                    cv2.rectangle(frame, (br_x, br_y - br_h), (br_x + br_w, br_y), (20, 110, 230), -1)
                    # White reflective stripes
                    for s_y in range(br_y - br_h + int(15 * scale2), br_y, max(5, int(30 * scale2))):
                        cv2.rectangle(frame, (br_x, s_y), (br_x + br_w, s_y + int(10 * scale2)), (240, 240, 240), -1)

        # 5. Dashcam HUD overlay watermark (authentic real-time telemetry HUD)
        speed_disp = 48.0 + 3.0 * math.sin(t_sec * 0.6)
        hud_text = f"CAM-01  |  {datetime.now().strftime('%Y-%m-%d')}  {t_sec:05.2f}s  |  SPD: {speed_disp:.1f} KM/H  |  GPS: LOCKED"
        cv2.putText(frame, hud_text, (30, h - 30), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 0), 3)
        cv2.putText(frame, hud_text, (30, h - 30), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (220, 240, 255), 1)

        out.write(frame)

    out.release()
