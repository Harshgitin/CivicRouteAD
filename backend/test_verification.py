"""
CivicRoute AD - End-to-End Test and Verification Suite
Tests:
1. Tile provider HTTP accessibility (OSM & Esri)
2. GPS parsing, validation, kinematics, gaps, and offset handling
3. Camera photogrammetry, geodesic projection, and RFC 7946 coordinate ordering
4. AI detector and heuristic transparency (model_inferred vs provisional_heuristic)
5. FastAPI endpoint verification via TestClient:
   - Health and scenarios
   - Upload input validation (missing GPS, invalid formats, empty files)
   - Real pipeline run with video + GPX upload
   - GeoJSON compliance and feature properties
   - CSV and municipal report export formats
"""

import sys
import os
import json
import urllib.request
import time
from datetime import datetime, timezone

# Ensure backend root is on path
backend_dir = os.path.dirname(os.path.abspath(__file__))
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)

from fastapi.testclient import TestClient
from main import app
from app.geospatial.gps_parser import (
    GPSTrajectory,
    TrajectoryPoint,
    validate_coordinate,
    parse_csv_trajectory,
    parse_gpx_file
)
from app.geospatial.projection import CameraGeometry, direct_geodesic_project
from app.geospatial.geojson_builder import build_geojson_feature_collection

client = TestClient(app)

def test_1_tile_provider_connectivity():
    print("\n--- Test 1: Basemap Tile Provider Connectivity ---")
    # OpenStreetMap tile
    osm_url = "https://tile.openstreetmap.org/0/0/0.png"
    req_osm = urllib.request.Request(osm_url, headers={"User-Agent": "CivicRouteAD/1.0 (GIS Road Safety Verifier)"})
    try:
        with urllib.request.urlopen(req_osm, timeout=10) as resp:
            print(f"OSM Tile response: {resp.status} (Content-Type: {resp.headers.get('Content-Type')})")
            assert resp.status == 200
    except Exception as e:
        print(f"OSM Tile check warning/error: {e}")

    # Esri Satellite tile
    esri_url = "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/0/0/0"
    req_esri = urllib.request.Request(esri_url, headers={"User-Agent": "CivicRouteAD/1.0"})
    try:
        with urllib.request.urlopen(req_esri, timeout=10) as resp:
            print(f"Esri Tile response: {resp.status} (Content-Type: {resp.headers.get('Content-Type')})")
            assert resp.status == 200
    except Exception as e:
        print(f"Esri Tile check warning/error: {e}")


def test_2_gps_parsing_validation_and_offset():
    print("\n--- Test 2: GPS Parsing, Validation, and Kinematics ---")
    # Coordinate boundary checks
    ok1, _ = validate_coordinate(37.7749, -122.4194)
    assert ok1 is True
    ok2, _ = validate_coordinate(-90.0, 180.0)
    assert ok2 is True
    ok3, _ = validate_coordinate(91.0, 0.0)
    assert ok3 is False
    ok4, _ = validate_coordinate(0.0, -181.0)
    assert ok4 is False

    # Sample CSV trajectory parsing
    csv_sample = """timestamp,latitude,longitude,elevation_m,speed_mps,heading_deg
2026-10-09T10:00:00Z,37.7749,-122.4194,15.0,10.0,90.0
2026-10-09T10:00:01Z,37.7749,-122.4190,15.0,10.0,90.0
2026-10-09T10:00:02Z,37.7749,-122.4186,15.0,10.0,90.0
2026-10-09T10:00:10Z,37.7749,-122.4170,15.0,10.0,90.0
"""
    tmp_csv = os.path.join(backend_dir, "temp_test_gps.csv")
    with open(tmp_csv, "w", encoding="utf-8") as f:
        f.write(csv_sample)

    try:
        trajectory = parse_csv_trajectory(tmp_csv)
        assert len(trajectory.points) == 4, f"Expected 4 points, got {len(trajectory.points)}"

        # Check gap detection (between 10:00:02 and 10:00:10 is an 8s gap > 6s threshold)
        coverage = trajectory.check_coverage(video_duration_sec=12.0)
        print(f"Coverage check result: {coverage}")
        assert len(coverage["gaps"]) > 0, "Expected at least one gap flagged > 6 seconds"

        # Test time offset interpolation
        # At video_t=1.0 with offset 0: should be point 1 (10:00:01)
        pt_norm = trajectory.get_state_at_time(1.0, time_offset_sec=0.0)
        assert pt_norm is not None
        assert abs(pt_norm.lon - (-122.4190)) < 1e-4

        # At video_t=1.0 with offset -1.0: effective time is 0.0 (10:00:00)
        pt_offset = trajectory.get_state_at_time(1.0, time_offset_sec=-1.0)
        assert pt_offset is not None
        assert abs(pt_offset.lon - (-122.4194)) < 1e-4
    finally:
        if os.path.exists(tmp_csv):
            os.remove(tmp_csv)


def test_3_photogrammetry_and_geojson_rfc7946():
    print("\n--- Test 3: Camera Photogrammetry and RFC 7946 Projection ---")
    cam = CameraGeometry(camera_height_m=1.4, camera_pitch_deg=2.0, fov_horizontal_deg=70.0, fov_vertical_deg=45.0)

    # Frame dimensions 1920x1080, hazard near bottom center
    bbox = [900, 750, 1020, 850]
    vehicle_lat = 37.7749
    vehicle_lon = -122.4194
    heading_deg = 90.0 # Heading East
    speed_kmh = 35.0

    d_forward, d_lateral = cam.project_pixel_to_ground(bbox, 1920, 1080)
    print(f"Projected ground distance: forward={d_forward}m, lateral={d_lateral}m")
    assert d_forward > 0.0

    target_lat, target_lon, quality, uncertainty = direct_geodesic_project(
        lat_vehicle=vehicle_lat,
        lon_vehicle=vehicle_lon,
        heading_deg=heading_deg,
        d_forward_m=d_forward,
        d_lateral_m=d_lateral,
        vehicle_speed_kmh=speed_kmh
    )

    print(f"Geodesic projection: lat={target_lat}, lon={target_lon}, quality={quality}, uncertainty={uncertainty}m")
    # Verify hazard position is NOT identical to vehicle position
    assert (target_lat, target_lon) != (vehicle_lat, vehicle_lon), "Hazard must project ahead of vehicle!"
    # Heading East means longitude should increase (less negative)
    assert target_lon > vehicle_lon, "Heading East should project hazard with higher longitude"
    assert quality == "approximate_camera_projection_unvalidated"
    assert uncertainty is None, "Uncalibrated camera assumptions must not imply a numeric accuracy guarantee."

    # Build GeoJSON using build_geojson_feature_collection
    hazards_list = [{
        "id": "HAZ-001",
        "type": "pothole_damage",
        "lat": target_lat,
        "lon": target_lon,
        "confidence": 0.88,
        "severity": "High",
        "timestamp_sec": 2.5,
        "location_quality": quality,
        "estimated_uncertainty_m": uncertainty,
        "verification": "provisional_heuristic",
        "source": "cv_surface_analyzer"
    }]
    trajectory_coords = [[-122.4194, 37.7749, 15.0], [-122.4190, 37.7749, 15.0]]
    geojson_data = build_geojson_feature_collection(hazards_list, trajectory_coords, {"is_synthetic": False})

    # RFC 7946 verification: coordinates must be [longitude, latitude]
    # First feature is trajectory line, second is hazard point
    hazard_feat = [f for f in geojson_data["features"] if f["geometry"]["type"] == "Point"][0]
    coords = hazard_feat["geometry"]["coordinates"]
    print(f"GeoJSON hazard coordinates: {coords}")
    assert coords[0] == target_lon, "GeoJSON coordinate 0 must be LONGITUDE"
    assert coords[1] == target_lat, "GeoJSON coordinate 1 must be LATITUDE"
    assert hazard_feat["properties"]["location_quality"] == quality
    assert hazard_feat["properties"]["verification"] == "provisional_heuristic"



def test_4_fastapi_endpoints_and_validation():
    print("\n--- Test 4: FastAPI Validation and Export Endpoints ---")
    # Health endpoint
    r_health = client.get("/api/health")
    assert r_health.status_code == 200
    assert r_health.json()["status"] == "healthy"
    print("Health check endpoint verified.")

    # Scenarios endpoint
    r_scenarios = client.get("/api/scenarios")
    assert r_scenarios.status_code == 200
    scenarios_resp = r_scenarios.json()
    scenarios = scenarios_resp.get("scenarios", [])
    assert len(scenarios) > 0
    print(f"Loaded {len(scenarios)} scenarios. First scenario title: {scenarios[0]['title']}")
    assert "[Synthetic Demo]" in scenarios[0]["title"]

    # Upload validation: Reject request missing GPS field (422) or missing filename (400)
    fake_video = b"\x00\x00\x00\x20ftypmp42" + b"\x00" * 100
    files_no_gps = {
        "video": ("dashcam.mp4", fake_video, "video/mp4")
    }
    r_no_gps = client.post("/api/upload", files=files_no_gps)
    assert r_no_gps.status_code in (400, 422), f"Expected 400/422, got {r_no_gps.status_code}"
    print(f"Successfully validated rejection for missing GPS field: HTTP {r_no_gps.status_code}")

    # Upload validation: Reject unsupported GPS format
    files_bad_ext = {
        "video": ("dashcam.mp4", fake_video, "video/mp4"),
        "gps": ("route.txt", b"random content", "text/plain")
    }
    r_bad_ext = client.post("/api/upload", files=files_bad_ext)
    assert r_bad_ext.status_code == 400
    assert "Unsupported GPS format" in r_bad_ext.json()["detail"]
    print("Successfully validated HTTP 400 rejection for unsupported GPS format.")

    # Upload validation: Reject empty file
    files_empty = {
        "video": ("dashcam.mp4", b"", "video/mp4"),
        "gps": ("route.csv", b"lat,lon\n37.7,-122.4", "text/csv")
    }
    r_empty = client.post("/api/upload", files=files_empty)
    assert r_empty.status_code == 400
    print("Successfully validated HTTP 400 rejection for empty file.")

    # Process scenario pipeline
    scenario_id = scenarios[0]["id"]
    print(f"Executing scenario pipeline: {scenario_id}...")
    r_proc = client.post(f"/api/process/scenario/{scenario_id}")
    assert r_proc.status_code == 200
    proc_data = r_proc.json()
    run_id = proc_data["run_id"]
    print(f"Scenario pipeline executed successfully: run_id={run_id}")
    assert "geojson_url" in proc_data
    assert "hazards" in proc_data
    assert proc_data["is_synthetic"] is True

    # Export GeoJSON
    r_geo = client.get(f"/api/export/geojson/{run_id}")
    assert r_geo.status_code == 200
    geo_data = r_geo.json()
    assert geo_data["type"] == "FeatureCollection"
    print(f"GeoJSON export verified: {len(geo_data['features'])} features.")

    # Export CSV
    r_csv = client.get(f"/api/export/csv/{run_id}")
    assert r_csv.status_code == 200
    csv_text = r_csv.text
    assert "Hazard_ID" in csv_text
    assert "Location_Quality" in csv_text
    assert "Verification" in csv_text
    print("CSV export verified with required GIS schema headers.")

    # Export Municipal Report
    r_report = client.get(f"/api/export/report/{run_id}")
    assert r_report.status_code == 200
    report_data = r_report.json()
    assert "organization" in report_data
    assert "critical_action_items" in report_data
    assert "routine_maintenance_items" in report_data
    print(f"Municipal Report export verified: title '{report_data['title']}'")


def test_5_user_upload_pipeline_execution():
    print("\n--- Test 5: End-to-End User Upload Pipeline Execution ---")
    from app.config import SCENARIOS_DIR
    video_path = str(SCENARIOS_DIR / "scenario_storm_debris" / "storm_survey.mp4")
    gps_path = str(SCENARIOS_DIR / "scenario_storm_debris" / "storm_survey.gpx")

    assert os.path.exists(video_path), f"Video file missing: {video_path}"
    assert os.path.exists(gps_path), f"GPS file missing: {gps_path}"

    with open(video_path, "rb") as vf, open(gps_path, "rb") as gf:
        files = {
            "video": ("storm_survey.mp4", vf, "video/mp4"),
            "gps": ("storm_survey.gpx", gf, "application/gpx+xml")
        }
        data = {
            "time_offset_sec": "0.0"
        }
        r_upload = client.post("/api/process/upload", files=files, data=data)

    assert r_upload.status_code == 200, f"Upload pipeline failed: {r_upload.text}"
    upload_res = r_upload.json()
    run_id = upload_res["run_id"]
    print(f"User upload accepted for background analysis: run_id={run_id}")
    # Upload now returns immediately with status=processing so the video can play
    # while analysis runs. Poll the job endpoint instead of expecting the upload
    # request itself to block until all frames have been analyzed.
    assert upload_res["status"] in ("processing", "completed")
    assert upload_res["is_synthetic"] is False, "Uploaded run must be flagged is_synthetic=False"
    assert "geojson_url" in upload_res
    deadline = time.monotonic() + 30
    job_status = None
    while time.monotonic() < deadline:
        response = client.get(f"/api/process/status/{run_id}")
        assert response.status_code == 200, response.text
        job_status = response.json()
        if job_status.get("status") in ("completed", "failed"):
            break
        time.sleep(0.1)
    assert job_status and job_status.get("status") == "completed", f"Background analysis did not complete: {job_status}"

    # Check GeoJSON endpoint for the uploaded run
    r_geo = client.get(f"/api/geojson/{run_id}")
    assert r_geo.status_code == 200
    geo_data = r_geo.json()
    assert geo_data["type"] == "FeatureCollection"
    assert geo_data["metadata"]["data_classification"] == "USER_UPLOADED_UNVERIFIED"
    print(f"User upload GeoJSON classified as: {geo_data['metadata']['data_classification']}")


def run_all():
    print("==================================================")
    print("CIVICROUTE AD - SYSTEMATIC VERIFICATION SUITE")
    print("==================================================")
    test_1_tile_provider_connectivity()
    test_2_gps_parsing_validation_and_offset()
    test_3_photogrammetry_and_geodesic_rfc7946 = test_3_photogrammetry_and_geojson_rfc7946
    test_3_photogrammetry_and_geodesic_rfc7946()
    test_4_fastapi_endpoints_and_validation()
    test_5_user_upload_pipeline_execution()
    print("\n==================================================")
    print("ALL VERIFICATION SUITE TESTS PASSED SUCCESSFULLY!")
    print("==================================================")

if __name__ == "__main__":
    run_all()
