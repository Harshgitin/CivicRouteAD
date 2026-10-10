"""Focused regressions for class-safe road detections and Advanced data contracts."""

import numpy as np
import pytest

from app.ai.detector import RoadHazardDetector
from app.api import infrastructure_routes
from app.api.infrastructure_routes import _clean_candidate, _distance_meters, _report_category, _stable_id
from fastapi import HTTPException


def test_rdd_class_mapping_does_not_turn_cracks_into_potholes():
    assert RoadHazardDetector._road_damage_label("D40-Pothole")[0] == "pothole_damage"
    assert RoadHazardDetector._road_damage_label("D00-Longitudinal Crack")[0] == "road_crack"
    assert RoadHazardDetector._road_damage_label("D10-Transverse Crack")[0] == "road_crack"
    assert RoadHazardDetector._road_damage_label("D20-Alligator Crack")[0] == "road_crack"


def test_curb_like_edge_mask_is_rejected_but_localized_hole_is_allowed():
    frame_shape = (1080, 1920, 3)
    curb_polygon = [[0, 80], [360, 80], [420, 1030], [0, 1070]]
    assert not RoadHazardDetector._plausible_pothole_geometry(
        frame_shape, [0, 80, 420, 1070], curb_polygon
    )
    pothole_polygon = [[650, 680], [720, 665], [785, 700], [790, 750], [710, 770], [660, 735]]
    assert RoadHazardDetector._plausible_pothole_geometry(
        frame_shape, [650, 665, 790, 770], pothole_polygon
    )


def test_heuristic_candidates_are_not_labeled_as_confirmed_potholes():
    # General model class mapping only recognizes explicit non-pothole hazards;
    # surface appearance fallback emits possible_road_anomaly elsewhere in code.
    assert RoadHazardDetector._general_hazard_label("car") == (None, None)
    assert RoadHazardDetector._general_hazard_label("tree") == (None, None)


def test_advanced_candidate_requires_valid_coordinates_and_is_stable():
    candidate = {
        "source": "Mapillary street imagery",
        "image_id": "123",
        "detection_id": "456",
        "label": "Possible pothole",
        "lat": 18.5204,
        "lon": 73.8567,
        "hazard_type": "pothole",
    }
    cleaned = _clean_candidate(candidate)
    assert cleaned["confidence"] is None
    assert cleaned["confidence_is_calibrated"] is False
    assert cleaned["id"] == _stable_id({**candidate, "lat": 18.5204, "lon": 73.8567})
    with pytest.raises(HTTPException):
        _clean_candidate({**candidate, "lat": 91})


def test_nearby_radius_uses_great_circle_distance_and_report_categories():
    assert _distance_meters(18.5204, 73.8567, 18.5204, 73.8567) == pytest.approx(0)
    assert 900 < _distance_meters(0, 0, 0, 0.01) < 1200
    assert _report_category("Pothole", "Deep road cavity")[0] == "pothole"
    assert _report_category("Road crack", "Transverse crack")[0] == "road_crack"
    assert _report_category("Flooding", "Waterlogging on road")[0] == "waterlogging"


def test_nearby_reports_are_radius_filtered_and_privacy_minimized(monkeypatch):
    monkeypatch.setattr(infrastructure_routes, "_load_reports", lambda: [
        {
            "id": "CR-000001-abcdef",
            "title": "Pothole on service road",
            "issue_type": "Pothole",
            "latitude": 18.5204,
            "longitude": 73.8567,
            "status": "Submitted",
            "created_at": "2026-01-01T10:00:00Z",
            "reporter_name": "Private Name",
            "reporter_email": "private@example.com",
            "video_path": "C:/private/evidence.mp4",
            "staff_notes": "private staff note",
        },
        {
            "id": "CR-000002-abcdef",
            "title": "Far pothole",
            "issue_type": "Pothole",
            "latitude": 18.54,
            "longitude": 73.90,
            "status": "Submitted",
        },
    ])
    result = infrastructure_routes.nearby_infrastructure_reports(18.5204, 73.8567, 1000)
    assert result["count"] == 1
    item = result["items"][0]
    assert item["hazard_type"] == "pothole"
    assert item["distance_m"] == pytest.approx(0)
    assert "reporter_name" not in item
    assert "reporter_email" not in item
    assert "video_path" not in item
    assert "staff_notes" not in item
    assert result["notice"].startswith("Resident-submitted reports")


def test_hazard_tracker_keeps_provenance_from_best_detection():
    from app.ai.detector import HazardTracker

    tracker = HazardTracker()
    frame = np.zeros((100, 100, 3), dtype=np.uint8)
    tracker.update([{
        "type": "pothole_damage",
        "label": "Pothole",
        "class_code": "POTHOLE",
        "source": "pothole_segmentation_model",
        "verification": "model_inferred_unverified",
        "confidence": 0.74,
        "bbox": [20, 30, 50, 55],
        "polygon": [[22, 34], [46, 32], [49, 50], [25, 54]],
        "has_mask": True,
    }], frame, 1, 0.2)
    tracker.update([{
        "type": "pothole_damage",
        "label": "Possible road anomaly",
        "source": "cv_surface_analyzer",
        "verification": "provisional_heuristic",
        "confidence": 0.35,
        "bbox": [20, 30, 50, 55],
        "polygon": None,
        "has_mask": False,
    }], frame, 2, 0.4)
    result = tracker.finish()
    assert len(result) == 1
    assert result[0]["source"] == "pothole_segmentation_model"
    assert result[0]["best_has_mask"] is True
    assert result[0]["best_polygon"] is not None
    assert result[0]["label"] == "Pothole"



def test_mapillary_coordinate_parser_rejects_null_as_zero():
    assert infrastructure_routes._valid_point(None, None) is None
    assert infrastructure_routes._valid_point("", "") is None
    assert infrastructure_routes._valid_point("18.52", "73.85") == (18.52, 73.85)


def test_mapillary_model_category_does_not_confirm_cv_heuristic():
    assert infrastructure_routes._mapillary_to_hazard_category({
        "type": "pothole_damage", "source": "pothole_segmentation_model"
    }) == ("pothole", "Pothole candidate")
    assert infrastructure_routes._mapillary_to_hazard_category({
        "type": "pothole_damage", "source": "cv_surface_analyzer"
    }) is None
    assert infrastructure_routes._mapillary_to_hazard_category({
        "type": "road_crack", "source": "rdd2022_road_damage_model"
    }) == ("road_crack", "Road crack candidate")


def test_mapillary_scan_prefers_native_pothole_detections(monkeypatch):
    import asyncio
    import cv2
    from app.api import routes as api_routes

    ok, encoded = cv2.imencode(".jpg", np.full((64, 96, 3), 127, dtype=np.uint8))
    assert ok
    jpg_bytes = encoded.tobytes()

    class FakeResponse:
        def __init__(self, status_code=200, body=None, content=b""):
            self.status_code = status_code
            self._body = body or {}
            self.content = content
            self.text = ""
        def json(self):
            return self._body

    class FakeClient:
        def __init__(self, *args, **kwargs): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *args): return False
        async def get(self, url, params=None, **kwargs):
            if url == infrastructure_routes._MAPILLARY_IMAGES_URL:
                return FakeResponse(body={"data": [{
                    "id": "test-image-1",
                    "computed_geometry": {"type": "Point", "coordinates": [73.8567, 18.5204]},
                    "thumb_1024_url": "https://images.mapillary.com/thumbs/test.jpg",
                    "captured_at": 1760000000000,
                }]})
            if url.endswith('/detections'):
                return FakeResponse(body={"data": [{"value": "pothole", "created_at": 1760000000000, "geometry": "encoded-polygon"}]})
            return FakeResponse(content=jpg_bytes)

    class FakeDetector:
        def status(self):
            return {"pothole_seg_model_loaded": True, "road_damage_model_loaded": True}
        def analyze_frame(self, frame, frame_idx, timestamp_sec, priority="background"):
            return [{
                "type": "pothole_damage", "label": "Pothole", "bbox": [10, 12, 35, 42],
                "confidence": 0.74, "source": "pothole_segmentation_model",
                "verification": "model_inferred_unverified",
            }]

    monkeypatch.setattr(infrastructure_routes.httpx, "AsyncClient", FakeClient)
    monkeypatch.setattr(api_routes.runner, "detector", FakeDetector())
    result = asyncio.run(infrastructure_routes.scan_mapillary_street_images({
        "lat": 18.5204, "lon": 73.8567, "radius_m": 1000,
        "access_token": "test-token", "hazard_filter": "pothole",
    }))
    assert result["images_analyzed"] == 0  # Native Mapillary detections avoid local-model curb false positives.
    assert result["images_checked_by_mapillary"] == 1
    assert result["mapillary_pothole_detections"] == 1
    assert result["candidate_count"] == 1
    candidate = result["candidates"][0]
    assert candidate["hazard_type"] == "pothole"
    assert candidate["confidence"] is None
    assert candidate["source"] == "Mapillary server-side object detection"
    assert "source camera position" in candidate["evidence_note"]


def test_osm_proxy_rejects_invalid_null_coordinates():
    import asyncio
    from fastapi import HTTPException
    with pytest.raises(HTTPException) as exc:
        asyncio.run(infrastructure_routes.get_openstreetmap_context(None, 73.85, 1000))
    assert exc.value.status_code == 400


def test_mapillary_query_timeout_is_recognized_as_retryable_bbox_failure():
    response = type("Response", (), {
        "status_code": 400,
        "text": '{"error":{"message":"The query timed out, please retry the query","code":-2,"error_subcode":3404014}}',
        "json": lambda self: {"error": {"message": "The query timed out, please retry the query", "code": -2, "error_subcode": 3404014}},
    })()
    detail, should_retry = infrastructure_routes._mapillary_error_detail(response)
    assert "timed out" in detail.lower()
    assert should_retry is True


def test_mapillary_native_detection_class_matches_pothole_only():
    assert infrastructure_routes._mapillary_value_is_pothole("pothole") is True
    assert infrastructure_routes._mapillary_value_is_pothole("road--potholes") is True
    assert infrastructure_routes._mapillary_value_is_pothole("construction--barrier") is False
    assert infrastructure_routes._mapillary_value_is_pothole(None) is False


def test_mapillary_query_timeout_retries_with_tiled_bboxes(monkeypatch):
    import asyncio
    import json
    from app.api import routes as api_routes

    class FakeResponse:
        def __init__(self, status_code=200, body=None):
            self.status_code = status_code
            self._body = body or {}
            self.text = json.dumps(self._body)
            self.content = b""
        def json(self):
            return self._body

    class FakeClient:
        def __init__(self, *args, **kwargs): self.image_queries = 0
        async def __aenter__(self): return self
        async def __aexit__(self, *args): return False
        async def get(self, url, params=None, **kwargs):
            if url == infrastructure_routes._MAPILLARY_IMAGES_URL:
                if params.get("limit") == "20":
                    return FakeResponse(400, {"error": {"message": "The query timed out, please retry the query", "code": -2, "error_subcode": 3404014}})
                return FakeResponse(body={"data": [{
                    "id": "tile-image-1",
                    "computed_geometry": {"type": "Point", "coordinates": [73.8567, 18.5204]},
                    "thumb_1024_url": "https://images.mapillary.com/thumbs/tile.jpg",
                    "captured_at": 1760000000000,
                }]})
            if url.endswith('/detections'):
                return FakeResponse(body={"data": [{"value": "pothole"}]})
            raise AssertionError(f"Unexpected upstream URL: {url}")

    class FakeDetector:
        def status(self): return {"pothole_seg_model_loaded": False, "road_damage_model_loaded": False}
        def analyze_frame(self, *args, **kwargs): raise AssertionError("Local model should not run for native Mapillary pothole detections")

    monkeypatch.setattr(infrastructure_routes.httpx, "AsyncClient", FakeClient)
    monkeypatch.setattr(api_routes.runner, "detector", FakeDetector())
    result = asyncio.run(infrastructure_routes.scan_mapillary_street_images({
        "lat": 18.5204, "lon": 73.8567, "radius_m": 1000,
        "access_token": "test-token", "hazard_filter": "pothole",
    }))
    assert result["image_count"] == 1
    assert result["images_checked_by_mapillary"] == 1
    assert result["mapillary_pothole_detections"] == 1
    assert result["candidate_count"] == 1
    assert result["candidates"][0]["source"] == "Mapillary server-side object detection"


def test_mapillary_status_reports_not_configured_when_no_token(monkeypatch):
    import asyncio
    monkeypatch.setattr(infrastructure_routes, "MAPILLARY_ACCESS_TOKEN", "")
    status = asyncio.run(infrastructure_routes.get_mapillary_status())
    assert status["configured"] is False
    assert status["status"] == "not_configured"
    assert "MAPILLARY_ACCESS_TOKEN" in status["message"]


def test_mapillary_scan_stops_on_auth_failure(monkeypatch):
    import asyncio

    class FakeResponse:
        def __init__(self):
            self.status_code = 401
            self.text = '{"error":{"message":"Invalid OAuth access token - Cannot parse access token","type":"OAuthException","code":190}}'
        def json(self):
            return {"error": {"message": "Invalid OAuth access token - Cannot parse access token", "type": "OAuthException", "code": 190}}

    class FakeClient:
        def __init__(self, *args, **kwargs):
            self.call_count = 0
        async def __aenter__(self): return self
        async def __aexit__(self, *args): return False
        async def get(self, url, params=None, **kwargs):
            self.call_count += 1
            return FakeResponse()

    fake_client = FakeClient()
    monkeypatch.setattr(infrastructure_routes.httpx, "AsyncClient", lambda *args, **kwargs: fake_client)
    result = asyncio.run(infrastructure_routes.scan_mapillary_street_images({
        "lat": 18.5204, "lon": 73.8567, "radius_m": 1000,
        "access_token": "bad-token", "hazard_filter": "pothole",
    }))
    assert result["ok"] is False
    assert result["status"] == "authentication_failed"
    assert result["candidate_count"] == 0
    assert fake_client.call_count == 1  # Did not make repetitive tiled requests on auth error!


def test_infrastructure_diagnostics_endpoint(monkeypatch):
    import asyncio
    monkeypatch.setattr(infrastructure_routes, "MAPILLARY_ACCESS_TOKEN", "MLY|sample-secret-token-123456")
    diag = asyncio.run(infrastructure_routes.get_infrastructure_diagnostics())
    assert diag["ok"] is True
    assert diag["mapillary"]["configured"] is True
    assert diag["mapillary"]["token_preview"].startswith("MLY|")
    assert "123456" not in diag["mapillary"]["token_preview"]  # Secret is redacted!
    assert "capability_matrix" in diag
    assert "pothole" in diag["capability_matrix"]
    assert "osm" in diag


def test_osm_proxy_uses_in_memory_cache(monkeypatch):
    import asyncio

    call_count = 0
    class FakeResponse:
        def __init__(self):
            self.status_code = 200
        def json(self):
            return {"elements": [{
                "type": "way", "id": 9999, "lat": 18.5204, "lon": 73.8567,
                "tags": {"highway": "primary", "smoothness": "bad"}
            }]}

    class FakeClient:
        def __init__(self, *args, **kwargs): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *args): return False
        async def post(self, url, data=None, **kwargs):
            nonlocal call_count
            call_count += 1
            return FakeResponse()

    monkeypatch.setattr(infrastructure_routes.httpx, "AsyncClient", lambda *args, **kwargs: FakeClient())
    infrastructure_routes._OSM_CACHE.clear()

    res1 = asyncio.run(infrastructure_routes.get_openstreetmap_context(18.5204, 73.8567, 1000))
    assert res1["ok"] is True
    assert res1["from_cache"] is False
    assert call_count == 1

    res2 = asyncio.run(infrastructure_routes.get_openstreetmap_context(18.5204, 73.8567, 1000))
    assert res2["ok"] is True
    assert res2["from_cache"] is True
    assert call_count == 1  # Served from cache, no upstream network call!


def test_mapillary_native_taxonomy_distinct_from_rdd2022():
    """Verify Mapillary native detection values against Mapillary Graph API taxonomy.

    Mapillary uses hierarchical classes (e.g. object--pothole, construction--barrier--curb).
    This is kept strictly distinct from RDD2022 benchmark classes (D00-D40).
    Curbs and barriers must NEVER be classified as potholes.
    """
    from app.api.infrastructure_routes import (
        mapillary_native_to_hazard,
        _mapillary_value_is_pothole,
        MAPILLARY_NATIVE_CLASS_MAPPING,
    )
    from app.ai.detector import RoadHazardDetector

    # 1. Mapillary native pothole class
    cat, lbl = mapillary_native_to_hazard("object--pothole")
    assert cat == "pothole"
    assert "Mapillary-detected pothole" in lbl
    assert _mapillary_value_is_pothole("object--pothole") is True

    # 2. Curbs and barriers must NEVER be classified as potholes
    curb_cat, curb_lbl = mapillary_native_to_hazard("construction--barrier--curb")
    assert curb_cat == "other"
    assert "pothole" not in curb_cat
    assert _mapillary_value_is_pothole("construction--barrier--curb") is False

    flat_curb_cat, flat_curb_lbl = mapillary_native_to_hazard("construction--flat--curb")
    assert flat_curb_cat == "other"
    assert "pothole" not in flat_curb_cat
    assert _mapillary_value_is_pothole("construction--flat--curb") is False

    guard_rail_cat, _ = mapillary_native_to_hazard("construction--barrier--guard-rail")
    assert guard_rail_cat != "pothole"
    assert _mapillary_value_is_pothole("construction--barrier--guard-rail") is False

    # 3. Drainage and water fixtures
    drain_cat, _ = mapillary_native_to_hazard("object--catch-basin")
    assert drain_cat == "waterlogging"

    # 4. Infrastructure fixtures (street lights, utility poles)
    light_cat, _ = mapillary_native_to_hazard("object--street-light")
    assert light_cat == "damaged_infrastructure"

    # 5. RDD2022 classes are kept separate
    # D40 is the RDD2022 class for potholes; Mapillary uses object--pothole
    rdd_type, rdd_label, rdd_code = RoadHazardDetector._road_damage_label("D40")
    assert rdd_type == "pothole_damage"
    assert rdd_code == "D40"

    # Mapillary does NOT use D40 as a native API value
    assert "D40" not in MAPILLARY_NATIVE_CLASS_MAPPING


def test_curb_false_positive_rejection_and_real_video():
    """Verify curb rejection in geometry filter and test real video frames."""
    import os
    import cv2
    from app.ai.detector import RoadHazardDetector

    detector = RoadHazardDetector()
    frame_shape = (1080, 1920, 3)

    # 1. Obvious vertical roadside curb touching left frame edge
    # [x1, y1, x2, y2]
    curb_bbox = [0, 600, 150, 1080]  # Touches left edge, tall vertical ratio
    is_valid = detector._plausible_pothole_geometry(frame_shape, curb_bbox)
    assert is_valid is False, "Side-edge vertical curb must be rejected from pothole classification"

    # 2. Horizontal road barrier/curb lip along bottom edge
    lip_bbox = [400, 1050, 1600, 1080]  # Very wide, thin, touching bottom edge
    is_valid_lip = detector._plausible_pothole_geometry(frame_shape, lip_bbox)
    assert is_valid_lip is False, "Bottom-edge horizontal curb lip must be rejected"

    # 3. Real pothole in drivable lane away from edges
    pothole_bbox = [850, 680, 1020, 780]
    is_valid_pothole = detector._plausible_pothole_geometry(frame_shape, pothole_bbox)
    assert is_valid_pothole is True, "Genuine road cavity in lane must be accepted"

    # 4. Test real video footage (pothole_survey.mp4)
    video_path = os.path.join(os.path.dirname(__file__), "data", "scenarios", "scenario_urban_potholes", "pothole_survey.mp4")
    assert os.path.isfile(video_path)
    cap = cv2.VideoCapture(video_path)
    ret, frame = cap.read()
    cap.release()
    assert ret is True
    detections = detector.analyze_frame(frame, 0, 0.0, priority="background")
    # OpenCV surface analyzer detections must be marked as possible_road_anomaly, NEVER pothole_damage
    for d in detections:
        if d.get("source") == "cv_surface_analyzer":
            assert d.get("type") == "possible_road_anomaly"
            assert d.get("label") == "Possible Road Anomaly"
            assert d.get("verification") == "provisional_heuristic"


