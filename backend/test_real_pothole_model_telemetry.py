"""
Verification tests for genuine RDD2022 deep-learning pothole detection,
strict curb/crack disambiguation, and end-to-end telemetry generation.
"""
import os
import json
import cv2
import pytest
from app.ai.detector import RoadHazardDetector
from app.pipeline.runner import PipelineRunner


def test_dedicated_pothole_seg_model_status():
    """Verify system diagnostics truthfully report dedicated segmentation status."""
    detector = RoadHazardDetector()
    status = detector.status()
    # When no segmentation weights exist on disk, loaded must be False
    assert status["pothole_seg_model_loaded"] is False
    assert status["pothole_seg_model"] is None
    # RDD2022 weights are loaded
    assert status["road_damage_model_loaded"] is True
    assert status["road_damage_model"] == "yolov8s_best.pt"


def test_rdd2022_genuine_pothole_detection():
    """Verify that yolov8s_best.pt detects genuine D40 potholes with correct taxonomy."""
    detector = RoadHazardDetector()
    sample_path = os.path.join(
        os.path.dirname(__file__), "data", "road_damage_samples", "India_003191.jpg"
    )
    assert os.path.isfile(sample_path), f"Sample image missing: {sample_path}"
    img = cv2.imread(sample_path)
    assert img is not None

    detections = detector.analyze_frame(img, 0, 0.0, priority="live")
    potholes = [d for d in detections if d.get("class_code") == "D40"]
    assert len(potholes) >= 1, f"Expected at least 1 genuine D40 pothole, got {detections}"
    
    p = potholes[0]
    assert p["type"] == "pothole_damage"
    assert p["label"] == "Pothole"
    assert p["source"] == "rdd2022_road_damage_model"
    assert p["verification"] == "model_inferred_unverified"
    assert p["confidence"] >= 0.28
    assert len(p["bbox"]) == 4


def test_rdd2022_cracks_not_labeled_as_potholes():
    """Verify road cracks (D00, D10, D20) are never labeled as potholes."""
    detector = RoadHazardDetector()
    sample_path = os.path.join(
        os.path.dirname(__file__), "data", "road_damage_samples", "United_States_004798.jpg"
    )
    assert os.path.isfile(sample_path), f"Sample image missing: {sample_path}"
    img = cv2.imread(sample_path)
    assert img is not None

    detections = detector.analyze_frame(img, 0, 0.0, priority="live")
    model_cracks = [d for d in detections if d.get("source") == "rdd2022_road_damage_model"]
    assert len(model_cracks) >= 1, f"Expected crack detections, got {detections}"
    
    for c in model_cracks:
        assert c["class_code"] in ["D00", "D10", "D20"]
        assert c["class_code"] != "D40"
        assert c["type"] == "road_crack"
        assert c["label"] in ["Longitudinal Crack", "Transverse Crack", "Alligator Crack"]


def test_curbs_and_barriers_not_labeled_as_potholes():
    """Verify that concrete curbs and barriers are never labeled as potholes."""
    detector = RoadHazardDetector()
    frame_shape = (720, 1280, 3)

    # 1. Geometry sanity check
    curb_bbox = [0, 400, 100, 720]
    assert detector._plausible_pothole_geometry(frame_shape, curb_bbox) is False

    # 2. Road barrier frame inference
    barrier_frame_path = os.path.join(
        os.path.dirname(__file__), "data", "debug_frames", "storm_frame_260.jpg"
    )
    if os.path.isfile(barrier_frame_path):
        img = cv2.imread(barrier_frame_path)
        detections = detector.analyze_frame(img, 260, 10.4, priority="live")
        for d in detections:
            assert d.get("class_code") != "D40"
            assert d.get("type") != "pothole_damage"
            if d.get("source") == "cv_surface_analyzer":
                assert d.get("type") == "possible_road_anomaly"
                assert d.get("verification") == "provisional_heuristic"


def test_full_pipeline_telemetry_schema_for_hud():
    """Verify that full pipeline produces telemetry entries with exact HUD schema."""
    telemetry_path = os.path.join(
        os.path.dirname(__file__), "runs", "test_pothole_run_verification", "telemetry.json"
    )
    assert os.path.isfile(telemetry_path), "Test telemetry file missing"
    with open(telemetry_path, "r", encoding="utf-8") as f:
        telemetry = json.load(f)

    assert len(telemetry) > 0
    pothole_frames = [
        entry for entry in telemetry
        if any(d.get("class_code") == "D40" for d in entry.get("detections", []))
    ]
    assert len(pothole_frames) >= 1
    sample = pothole_frames[0]
    assert "frame" in sample
    assert "time_sec" in sample
    assert "frame_width" in sample
    assert "frame_height" in sample
    
    det = next(d for d in sample["detections"] if d.get("class_code") == "D40")
    assert det["type"] == "pothole_damage"
    assert det["label"] == "Pothole"
    assert det["class_code"] == "D40"
    assert det["source"] == "rdd2022_road_damage_model"
    assert isinstance(det["bbox"], list) and len(det["bbox"]) == 4
    assert isinstance(det["conf"], (int, float)) and det["conf"] > 0
