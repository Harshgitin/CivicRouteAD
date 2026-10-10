"""Regression tests: every uploaded clip is batch-analyzed even without GPS."""
import json
from pathlib import Path

import cv2

from app.pipeline.runner import PipelineRunner


class DeterministicPotholeDetector:
    """Cheap detector stub to exercise pipeline storage without downloading weights."""
    def status(self):
        return {
            "engine": "test-detector",
            "road_damage_model_loaded": False,
            "warnings": [],
        }

    def analyze_frame(self, frame, frame_idx, timestamp_sec, priority="background"):
        height, width = frame.shape[:2]
        # A stable candidate on each sampled frame should consolidate into one event.
        return [{
            "type": "pothole_damage",
            "label": "Pothole",
            "class_code": "D40",
            "bbox": [int(width * 0.42), int(height * 0.62), int(width * 0.56), int(height * 0.75)],
            "confidence": 0.78,
            "source": "test_road_damage_model",
            "verification": "model_inferred",
        }]


def test_full_video_analysis_works_without_gps_and_writes_boxes(tmp_path):
    backend_dir = Path(__file__).resolve().parent
    video_path = backend_dir / "data" / "scenarios" / "scenario_urban_potholes" / "pothole_survey.mp4"
    assert video_path.is_file()

    runner = PipelineRunner(runs_dir=str(tmp_path), model_path=None)
    runner.detector = DeterministicPotholeDetector()
    progress = []

    result = runner.process_run(
        video_path=str(video_path),
        gps_path=None,
        run_id="no_gps_scan_test",
        sample_step=10,
        progress_callback=progress.append,
    )

    assert result["status"] == "completed"
    assert result["metadata"]["gps_available"] is False
    assert result["metadata"]["sampled_frames"] > 1
    assert result["hazards_count"] >= 1
    assert all(hazard["lat"] is None and hazard["lon"] is None for hazard in result["hazards"])
    assert progress and progress[-1]["progress_percent"] == 100.0

    telemetry = json.loads((tmp_path / "no_gps_scan_test" / "telemetry.json").read_text())
    assert len(telemetry) == result["metadata"]["sampled_frames"]
    assert any(
        item.get("detections") and item["detections"][0]["class_code"] == "D40"
        for item in telemetry
    )

    geojson = json.loads((tmp_path / "no_gps_scan_test" / "hazard_map.geojson").read_text())
    hazard_features = [feature for feature in geojson["features"] if feature["properties"].get("feature_class") == "road_hazard"]
    assert hazard_features
    assert all(feature["geometry"] is None for feature in hazard_features)
