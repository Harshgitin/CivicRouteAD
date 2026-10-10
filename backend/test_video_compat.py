"""Focused regression tests for browser-friendly video handling.

Run from backend/: python -m pytest -q test_video_compat.py
"""
from pathlib import Path
import tempfile

import cv2
import numpy as np
import pytest

from app.video_compat import (
    find_ffmpeg,
    is_browser_friendly,
    prepare_browser_playback,
    transcode_h264_mp4,
    video_fourcc,
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SCENARIOS_DIR = PROJECT_ROOT / "backend" / "data" / "scenarios"


@pytest.mark.parametrize(
    "scenario_folder, filename, expected_duration",
    [
        ("scenario_storm_debris", "storm_survey.mp4", 12),
        ("scenario_flash_flood", "flood_survey.mp4", 10),
        ("scenario_urban_potholes", "pothole_survey.mp4", 10),
    ],
)
def test_bundled_scenario_video_is_browser_friendly(scenario_folder, filename, expected_duration):
    path = SCENARIOS_DIR / scenario_folder / filename
    assert path.is_file(), f"Missing bundled test video: {path}"
    assert is_browser_friendly(path), f"Video is not tagged as browser-friendly: {video_fourcc(path)}"

    cap = cv2.VideoCapture(str(path))
    ok, frame = cap.read()
    fps = cap.get(cv2.CAP_PROP_FPS)
    frame_count = cap.get(cv2.CAP_PROP_FRAME_COUNT)
    cap.release()

    assert ok and frame is not None and frame.size > 0
    assert fps > 0
    assert abs(frame_count / fps - expected_duration) < 0.2


def test_unsupported_mp4v_gets_h264_playback_copy_when_ffmpeg_available():
    ffmpeg = find_ffmpeg()
    if not ffmpeg:
        pytest.skip("FFmpeg/imageio-ffmpeg is not available in this environment")

    with tempfile.TemporaryDirectory(prefix="civicroute-video-test-") as tmp:
        tmp_path = Path(tmp)
        source = tmp_path / "source_mp4v.mp4"
        destination = tmp_path / "playback" / "video.mp4"

        writer = cv2.VideoWriter(
            str(source), cv2.VideoWriter_fourcc(*"mp4v"), 10.0, (320, 240)
        )
        assert writer.isOpened(), "OpenCV could not create the MP4V test fixture"
        for index in range(20):
            frame = np.zeros((240, 320, 3), dtype=np.uint8)
            frame[:, :] = (index * 5 % 255, 90, 160)
            cv2.putText(frame, f"Frame {index}", (30, 120), cv2.FONT_HERSHEY_SIMPLEX, 1.0, (240, 240, 240), 2)
            writer.write(frame)
        writer.release()
        assert source.stat().st_size > 0
        assert not is_browser_friendly(source)

        success, message = transcode_h264_mp4(source, destination, ffmpeg=ffmpeg)
        assert success, message
        assert destination.is_file() and destination.stat().st_size > 0
        assert is_browser_friendly(destination), f"Output codec not browser-friendly: {video_fourcc(destination)}"

        cap = cv2.VideoCapture(str(destination))
        ok, frame = cap.read()
        duration = cap.get(cv2.CAP_PROP_FRAME_COUNT) / max(cap.get(cv2.CAP_PROP_FPS), 1e-6)
        cap.release()
        assert ok and frame is not None and frame.size > 0
        assert abs(duration - 2.0) < 0.25


def test_prepare_playback_does_not_mutate_original_and_returns_path():
    source = SCENARIOS_DIR / "scenario_storm_debris" / "storm_survey.mp4"
    before = source.stat().st_size
    with tempfile.TemporaryDirectory(prefix="civicroute-playback-test-") as tmp:
        result = prepare_browser_playback(source, tmp)
        path = Path(result["path"])
        assert path.is_file()
        assert result["media_type"] == "video/mp4"
        assert is_browser_friendly(path)
        assert source.stat().st_size == before
