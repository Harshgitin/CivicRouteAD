"""Fetch a pinned free RDD2022 road-damage checkpoint on first launch.

The SHA-256 pin makes the downloaded bytes verifiable. Failure is non-fatal:
CivicRouteAD can still run its bundled generic detector and labelled CV fallback.
"""
from __future__ import annotations

import hashlib
import os
import sys
import urllib.request
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent
MODEL_DIR = BACKEND_DIR / "models"
MODEL_PATH = MODEL_DIR / "yolov8s_best.pt"
URL = "https://huggingface.co/spaces/ProjectRoadDamageDetection/Automated-Road-Damage-Detection/resolve/073ad21/yolov8s_best.pt"
EXPECTED_SHA256 = "467779780996cddd6632c318c47f21003de76a2cba2c7f7489f1372f04ff5fa2"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> int:
    MODEL_DIR.mkdir(parents=True, exist_ok=True)
    if MODEL_PATH.is_file():
        try:
            if sha256(MODEL_PATH) == EXPECTED_SHA256:
                print(f"[Road model] Verified RDD2022 weights already installed: {MODEL_PATH.name}")
                return 0
            print("[Road model] Existing RDD2022 weights failed SHA-256 verification; replacing them.")
            MODEL_PATH.unlink()
        except OSError as exc:
            print(f"[Road model] Could not verify existing weights: {exc}")

    temporary_path = MODEL_PATH.with_suffix(".pt.part")
    print("[Road model] Downloading free RDD2022 road-damage weights (~22.5 MB)...")
    print("[Road model] If unavailable, startup continues with the bundled fallback detector.")
    try:
        request = urllib.request.Request(URL, headers={"User-Agent": "CivicRouteAD-local/1.0"})
        with urllib.request.urlopen(request, timeout=20) as response, temporary_path.open("wb") as output:
            while True:
                chunk = response.read(1024 * 1024)
                if not chunk:
                    break
                output.write(chunk)
        actual = sha256(temporary_path)
        if actual != EXPECTED_SHA256:
            raise ValueError(f"SHA-256 mismatch: expected {EXPECTED_SHA256}, received {actual}")
        os.replace(temporary_path, MODEL_PATH)
        print(f"[Road model] Verified RDD2022 weights installed: {MODEL_PATH}")
        return 0
    except Exception as exc:
        try:
            temporary_path.unlink(missing_ok=True)
        except OSError:
            pass
        print(f"[Road model] Optional model download failed: {exc}")
        print("[Road model] Continuing in fallback mode. Connect to the internet and rerun start.bat to retry.")
        return 0


if __name__ == "__main__":
    sys.exit(main())
