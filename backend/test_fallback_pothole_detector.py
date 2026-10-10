"""Regression test that the local OpenCV fallback can visibly box a sample pothole."""
from pathlib import Path

import cv2

from app.ai.detector import RoadHazardDetector


def test_cv_fallback_detects_bundled_approach_sample_pothole():
    backend_root = Path(__file__).resolve().parent
    video_path = backend_root / "data" / "scenarios" / "scenario_urban_potholes" / "pothole_survey.mp4"
    cap = cv2.VideoCapture(str(video_path))
    try:
        assert cap.isOpened(), "bundled pothole sample video should be readable"
        cap.set(cv2.CAP_PROP_POS_MSEC, 5000)
        ok, frame = cap.read()
        assert ok and frame is not None, "sample frame at 5 seconds should decode"
    finally:
        cap.release()

    detector = RoadHazardDetector(model_path=None)
    # Force the fallback path so this regression remains deterministic even on a
    # developer machine where the optional RDD checkpoint is installed.
    detector.model = None
    detector.road_damage_model = None
    detections = detector.analyze_frame(frame, 125, 5.0, priority="live")
    assert detections, "CV fallback should surface possible road-surface candidates on the bundled approach frame"
    assert any(
        det["type"] == "possible_road_anomaly"
        and det["source"] == "cv_surface_analyzer"
        and det["bbox"][0] < 820
        and det["bbox"][2] > 560
        and det["bbox"][1] > 450
        for det in detections
    ), f"expected a provisional candidate over the road-surface area, got {detections!r}"
    assert all(det["type"] != "pothole_damage" for det in detections), (
        "the OpenCV fallback must not label a dark region as a confirmed pothole"
    )
