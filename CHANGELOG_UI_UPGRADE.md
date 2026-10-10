# CivicRouteAD — Community Reporting & Staff Workspace Upgrade

## What's changed

- Replaced the analyst-first landing page with a straightforward resident reporting portal.
- Added a short-video report flow. A separate GPX/CSV track is optional, not required.
- Added device-location capture and an interactive map pin so the reporter can select the affected location.
- Added infrastructure issue type, description, landmark, camera source/camera ID, and optional follow-up contact fields.
- Added a separate staff workspace with password gate, report metrics, search and status filtering, incident map, private evidence playback, optional GPS download, assignment, status changes, internal notes, and a staff-triggered preliminary analysis.
- Added a staff-only JSON export for analysis results.
- Stores submissions and evidence under `backend/data/` independently of synthetic benchmark scenarios.
- Kept the former technical dashboard in a separate Analysis Lab navigation section.
- Updated the launcher to attempt a frontend production build when source files are newer than the built bundle.

## Important limitations

- The selected map pin/device location represents the reported incident location, not the precise location of each object seen in a video.
- Per-object geolocation needs a synchronized GPS/trajectory and calibrated camera pipeline; any computed coordinates remain estimates that a person must validate.
- Camera source and camera ID are metadata supplied by the reporter. This prototype does not connect to live CCTV feeds.
- Local staff password defaults to `admin123` for development only. Set `CIVICROUTE_STAFF_PASSWORD` before exposing the application to any network. This prototype is not a substitute for production-grade identity management, HTTPS, security review, backups, or access auditing.
- Frontend production bundling must be run on the user's Windows machine because the supplied `node_modules` tree contains Windows native packages and cannot produce a verified Linux build in this environment.
