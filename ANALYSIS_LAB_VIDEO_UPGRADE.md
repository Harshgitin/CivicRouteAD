# CivicRouteAD Analysis Lab — Live Video & GIS Upgrade

## Scope

This update is limited to the Analysis Lab video-to-GIS workflow. The existing page layout and other sections are retained.

## Behaviour

- Bundled benchmark footage is labelled `DEMO PLACEHOLDER`; the video panel includes `UPLOAD MP4 + GPS` / `REPLACE FOOTAGE`.
- Opening the Analysis Lab now returns a light preview first. The complete sample-video GIS analysis runs in the background, instead of holding the page behind the old full-pipeline loading screen.
- After upload, the selected clip becomes the active video. Previous demo detections and telemetry are reset.
- During playback, the browser samples the actual displayed video frames and sends them to the local FastAPI detector. Detections are drawn as labelled bounding boxes with confidence scores. Sampling adapts to playback events and avoids painting a response over a very different frame after a large seek.
- If a matching GPX/CSV is supplied, every live frame request also reads the synchronized vehicle state and estimates GPS positions for detections using the project's camera geometry. The live map can show approximate detections before the background full-video pass completes.
- Speed, heading, and vehicle coordinates are shown from the GPS trajectory at the current video timestamp. They are not invented if GPS is missing.
- The full background pass continues to analyze the same configured sample frames, build the deduplicated hazard register, and produce downloadable GeoJSON. Live frame requests are prioritized over queued background frames; the pipeline does not lower its frame stride to achieve the quicker first display. When completed artifacts arrive, persistent GIS records replace transient live markers.
- Saved telemetry is written only for frames that were actually analyzed. Playback interpolates GPS fields between these samples, reducing JSON size and write time without skipping AI inference frames.
- Browser-friendly H.264/WebM input can be hard-linked into playback storage when supported, avoiding an unnecessary full video copy; originals are left untouched.
- The map avoids repeatedly refitting its view while live points arrive, and the marker layer ignores GeoJSON hazards that have no point geometry.

## Model setup

The bundled `backend/yolov8n.pt` is general-purpose and is not trained specifically for potholes. On startup, `backend/download_road_model.py` attempts to download a free RDD2022 fine-tuned YOLOv8s checkpoint to `backend/models/yolov8s_best.pt` and verifies its SHA-256 before it can be used. It recognizes the RDD2022 pavement classes D00 (longitudinal crack), D10 (transverse crack), D20 (alligator crack), and D40 (pothole). The general model runs as a supplementary detector for other visible hazards. On slower hardware the general model is sampled less frequently when the RDD model is available. The road-damage checkpoint source advertises an MIT license; attribution and source details are in `backend/models/README.md`. Ultralytics has separate runtime license terms.

If internet access is unavailable, or the download/checksum/model load fails, startup continues with the bundled general-purpose model (when Ultralytics is installed) and a clearly labelled OpenCV heuristic fallback. The fallback uses a more sensitive small-cavity contour threshold and merges adjacent fragments into a single candidate box. It demonstrated a box on the bundled synthetic pothole approach frame in the regression test, but does not have equivalent pothole-specific capability or reliable recall on arbitrary real-world footage. Model predictions and GPS-projected coordinates are estimates and require field validation before emergency dispatch or repair decisions.

## How to test

1. Run `start.bat` and wait for the frontend build and backend server.
2. Open `http://localhost:8000`, then enter the Analysis Lab.
3. Click `UPLOAD MP4 + GPS`; select an MP4 and its matching GPX or CSV trajectory. GPS is optional for frame detection but required for real-world coordinates, speed/heading, and map geolocation.
4. Adjust the video-to-GPS offset when the recording clocks do not align, then start the run.
5. Play the selected video. Verify labels/boxes and inference status in the video panel, GPS telemetry, live map markers, and finally the persistent incident list / GeoJSON after background processing finishes.

## Verification performed in the editing environment

- Python `compileall`: passed.
- Focused backend regression suite: 7 passed (`test_video_compat.py`, `test_live_inference_priority.py`, and `test_fallback_pothole_detector.py`).
- JSX/TSX syntax parse: 15 frontend files passed; `api.js` and Vite config passed `node --check`.
- The full test suite was blocked during collection because `gpxpy` is not installed in this editing environment. A production frontend build and full live upload/inference/GPS integration could not be run because npm dependencies are not installed and network access is unavailable here. On Windows, `start.bat` installs project dependencies and attempts the optional model download.
