"""Regression tests for keeping browser-driven frame detection responsive."""
import threading
import time

from app.ai.detector import RoadHazardDetector


def test_live_frame_jumps_ahead_of_waiting_background_frame(monkeypatch):
    detector = RoadHazardDetector(model_path=None)
    first_background_started = threading.Event()
    release_first_background = threading.Event()
    order = []

    def fake_infer(_frame, frame_idx, _timestamp_sec, **_kwargs):
        if frame_idx == 0:
            first_background_started.set()
            assert release_first_background.wait(timeout=2), "test timed out while releasing first inference"
        order.append(frame_idx)
        return []

    monkeypatch.setattr(detector, "_analyze_frame_locked", fake_infer)

    first = threading.Thread(target=detector.analyze_frame, args=(None, 0, 0.0, "background"))
    queued_background = threading.Thread(target=detector.analyze_frame, args=(None, 2, 0.2, "background"))
    live = threading.Thread(target=detector.analyze_frame, args=(None, 1, 0.1, "live"))

    first.start()
    assert first_background_started.wait(timeout=2), "first background inference never started"
    queued_background.start()
    # Allow the background call to enter its wait before submitting the live request.
    time.sleep(0.05)
    live.start()
    time.sleep(0.05)
    release_first_background.set()

    for thread in (first, queued_background, live):
        thread.join(timeout=3)
        assert not thread.is_alive(), "inference-priority thread failed to finish"

    assert order == [0, 1, 2], f"interactive live frame should run before queued background frame; got {order}"


def test_live_detector_skips_general_coco_model(monkeypatch):
    """The COCO model adds latency but is not trained to find potholes."""
    import numpy as np

    detector = RoadHazardDetector(model_path=None)
    calls = []

    class FakeGeneralModel:
        def predict(self, **kwargs):
            calls.append(kwargs)
            return []

    detector.model = FakeGeneralModel()
    detector.road_damage_model = None
    frame = np.zeros((120, 160, 3), dtype=np.uint8)
    detector._analyze_frame_locked(frame, 20, 2.0, skip_general=True)
    assert calls == [], "live video inference should reserve compute for road-surface detection"


def test_general_coco_model_runs_at_supplementary_cadence():
    """Full-video pothole inference should not run COCO on every sampled frame."""
    import numpy as np

    detector = RoadHazardDetector(model_path=None)
    calls = []

    class FakeGeneralModel:
        def predict(self, **kwargs):
            calls.append(kwargs)
            return []

    detector.model = FakeGeneralModel()
    detector.road_damage_model = None
    frame = np.zeros((120, 160, 3), dtype=np.uint8)
    for frame_idx, timestamp in enumerate([0.0, 0.1, 0.2, 0.95, 1.05, 1.2]):
        detector._analyze_frame_locked(frame, frame_idx, timestamp, skip_general=False)
    assert len(calls) == 2, f"expected one COCO pass near each second boundary, got {len(calls)}"
