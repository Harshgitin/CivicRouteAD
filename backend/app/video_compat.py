"""Utilities for producing browser-friendly video playback copies.

The original upload is never altered: computer-vision processing reads the source,
while the dashboard receives an H.264 MP4 when an FFmpeg executable is available.
"""

from __future__ import annotations

import mimetypes
import os
import shutil
import subprocess
from pathlib import Path
from typing import Optional, Tuple, Dict, Any

SUPPORTED_VIDEO_SUFFIXES = {".mp4", ".webm", ".mov", ".avi", ".mkv"}


def find_ffmpeg() -> Optional[str]:
    """Find FFmpeg on PATH, or the executable bundled by imageio-ffmpeg."""
    exe = shutil.which("ffmpeg")
    if exe:
        return exe
    try:
        import imageio_ffmpeg  # type: ignore
        exe = imageio_ffmpeg.get_ffmpeg_exe()
        if exe and os.path.isfile(exe):
            return exe
    except Exception:
        pass
    return None


def video_fourcc(path: str | Path) -> str:
    """Return the four-character codec tag reported by OpenCV, when available."""
    try:
        import cv2
        cap = cv2.VideoCapture(str(path))
        if not cap.isOpened():
            cap.release()
            return ""
        value = int(cap.get(cv2.CAP_PROP_FOURCC))
        cap.release()
        return "".join(chr((value >> (8 * i)) & 0xFF) for i in range(4)).strip().lower()
    except Exception:
        return ""


def is_browser_friendly(path: str | Path) -> bool:
    """Conservatively recognize common Chrome-friendly MP4/WebM combinations."""
    p = Path(path)
    tag = video_fourcc(p)
    if p.suffix.lower() == ".mp4" and tag in {"avc1", "h264", "x264"}:
        return True
    if p.suffix.lower() == ".webm" and tag in {"vp80", "vp90", "av01"}:
        return True
    return False


def transcode_h264_mp4(source: str | Path, destination: str | Path, ffmpeg: Optional[str] = None) -> Tuple[bool, str]:
    """Transcode a video to widely supported H.264/yuv420p MP4 using FFmpeg."""
    source_path = Path(source)
    destination_path = Path(destination)
    executable = ffmpeg or find_ffmpeg()
    if not executable:
        return False, "FFmpeg is not installed or available to CivicRoute AD."
    if not source_path.exists() or source_path.stat().st_size == 0:
        return False, "The source video is missing or empty."

    destination_path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = destination_path.with_name(f".{destination_path.stem}.converting.tmp.mp4")
    try:
        if temp_path.exists():
            temp_path.unlink()
        command = [
            executable, "-hide_banner", "-loglevel", "error", "-y",
            "-i", str(source_path),
            "-map", "0:v:0", "-map", "0:a?",
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "22",
            "-pix_fmt", "yuv420p", "-movflags", "+faststart",
            "-c:a", "aac", "-b:a", "128k",
            str(temp_path),
        ]
        completed = subprocess.run(command, capture_output=True, text=True, timeout=900)
        if completed.returncode != 0 or not temp_path.exists() or temp_path.stat().st_size < 1024:
            detail = (completed.stderr or "FFmpeg did not produce a valid playback file.").strip()
            return False, detail[-1200:]
        # Verify the result can be decoded before replacing any previous playback copy.
        try:
            import cv2
            cap = cv2.VideoCapture(str(temp_path))
            ok, _ = cap.read()
            cap.release()
            if not ok:
                return False, "FFmpeg created a file but OpenCV could not decode its first frame."
        except Exception:
            pass
        os.replace(temp_path, destination_path)
        return True, "Converted to browser-compatible H.264 MP4."
    except subprocess.TimeoutExpired:
        return False, "Video conversion exceeded the 15-minute limit."
    except Exception as exc:
        return False, f"Video conversion failed: {exc}"
    finally:
        try:
            if temp_path.exists():
                temp_path.unlink()
        except OSError:
            pass


def ensure_browser_mp4(path: str | Path) -> Tuple[bool, str]:
    """Convert a scenario MP4 in place only when it is not browser-friendly."""
    video_path = Path(path)
    if is_browser_friendly(video_path):
        return True, "Already browser-friendly."
    return transcode_h264_mp4(video_path, video_path)


def prepare_browser_playback(source: str | Path, run_dir: str | Path) -> Dict[str, Any]:
    """Create a fresh playback copy without modifying the source used for AI.

    When FFmpeg is unavailable, keep the real original extension instead of lying
    to the browser with a `video/mp4` content type for WebM/MOV/AVI files.
    """
    source_path = Path(source)
    run_path = Path(run_dir)
    run_path.mkdir(parents=True, exist_ok=True)

    # Remove stale playback copies from earlier runs so a new WebM/MOV upload
    # can never accidentally stream an old video.mp4 from the same run folder.
    for old_name in ("video.mp4", "video.webm", "video.mov", "video.avi", "video.mkv"):
        old_path = run_path / old_name
        try:
            if old_path.exists() and old_path.resolve() != source_path.resolve():
                old_path.unlink()
        except OSError:
            pass

    if is_browser_friendly(source_path):
        suffix = source_path.suffix.lower()
        target = run_path / ("video.mp4" if suffix == ".mp4" else "video.webm")
        # The source and run directory normally live on the same disk. A hard link
        # avoids copying hundreds of megabytes while preserving the original upload;
        # fall back to a normal copy on filesystems that do not support hard links.
        try:
            os.link(source_path, target)
        except OSError:
            shutil.copy2(source_path, target)
        return {
            "path": str(target),
            "filename": target.name,
            "media_type": mimetypes.guess_type(target.name)[0] or "application/octet-stream",
            "converted": False,
            "warning": None,
        }

    ffmpeg = find_ffmpeg()
    if ffmpeg:
        target = run_path / "video.mp4"
        ok, message = transcode_h264_mp4(source_path, target, ffmpeg=ffmpeg)
        if ok:
            return {
                "path": str(target),
                "filename": target.name,
                "media_type": "video/mp4",
                "converted": True,
                "warning": None,
            }
        warning = f"The video was processed, but a browser playback copy could not be made: {message}"
    else:
        warning = (
            "This video may not play in the browser because its codec is not a known browser-friendly format. "
            "Install FFmpeg or imageio-ffmpeg to enable automatic H.264 playback conversion."
        )

    suffix = source_path.suffix.lower()
    if suffix not in SUPPORTED_VIDEO_SUFFIXES:
        suffix = ".mp4"
    target = run_path / f"video{suffix}"
    shutil.copy2(source_path, target)
    return {
        "path": str(target),
        "filename": target.name,
        "media_type": mimetypes.guess_type(target.name)[0] or "application/octet-stream",
        "converted": False,
        "warning": warning,
    }
