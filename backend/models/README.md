# Optional road-damage-specific model

`yolov8s_best.pt` is downloaded by `backend/download_road_model.py` on first launch when a network connection is available. The script pins the Hugging Face Space file and verifies SHA-256 before use.

Source: ProjectRoadDamageDetection / Automated-Road-Damage-Detection (Hugging Face Spaces)
Model: YOLOv8s fine-tuned on RDD2022, classes D00 (longitudinal crack), D10 (transverse crack), D20 (alligator crack), D40 (pothole).
License advertised by that Space: MIT. See the source Space README for attribution and dataset citation. Ultralytics runtime has separate license terms.

If download is unavailable, CivicRouteAD starts with the bundled general YOLO checkpoint and clearly identified OpenCV heuristic fallback. This fallback does not have equivalent pothole-specific accuracy.
