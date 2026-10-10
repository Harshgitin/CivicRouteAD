# CivicRoute AD — fixes applied

This archive keeps the existing dashboard and project structure. The changes focus on the reported video playback failure and clearer data-quality metadata.

## Applied

- Added `backend/app/video_compat.py` to inspect video codecs and create an H.264 / yuv420p playback copy using FFmpeg or the optional `imageio-ffmpeg` executable. The original upload remains available for AI processing.
- Updated the included synthetic MP4 fixtures to H.264 (`avc1`) so normal HTML5 video players can play the bundled scenarios without needing to convert them on first launch.
- Updated the video endpoint to serve the actual playback-copy MIME type and disable stale caching. Returned video URLs include a cache-busting token for stable scenario run IDs.
- Updated the React video player source to handle rejected playback promises, display media errors, update duration from metadata, and format latitude/longitude hemispheres correctly.
- Kept camera-projected hazard locations explicitly approximate and synthetic routes labelled illustrative in the backend result metadata.
- Uploaded data is classified as `USER_UPLOADED_UNVERIFIED`, rather than automatically asserted to be real-world verified.
- Added `backend/requirements.txt` with the backend dependencies, including `imageio-ffmpeg` for optional automatic playback conversion.
- Added focused regression tests for browser-compatible sample videos and MP4V-to-H.264 conversion.

## Important limitations

- Built-in scenario GPS tracks are synthetic and are not guaranteed to follow actual road centerlines. They are intended to exercise the pipeline, not to demonstrate real-world navigation accuracy.
- Hazard coordinates derived from assumed camera geometry remain approximate until calibrated and validated against ground-truth hazard positions.
- This environment could not run the full backend integration tests because `gpxpy` is not installed here. Install the dependencies listed in `backend/requirements.txt` in your Windows Python environment before running the full test suite.
- The Linux build environment did not have the matching Linux Rollup optional binary from the packaged Windows `node_modules`. The existing frontend distribution is preserved. On Windows, if you want the latest player error UI bundled, run `npm install` and `npm run build` from the `frontend` folder once before starting the app.

## Playback verification

The three bundled sample videos are H.264 / `avc1`, are decodable by OpenCV, and retain their expected 10–12 second durations. The focused video compatibility regression tests pass in the build environment.
