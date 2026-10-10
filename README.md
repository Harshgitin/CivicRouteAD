# CivicRouteAD: Community Infrastructure Reporting & Road Hazard Analysis

![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)
![Python](https://img.shields.io/badge/Python-3.13-blue)
![React](https://img.shields.io/badge/Frontend-React_18_%2B_Leaflet-cyan)
![AI](https://img.shields.io/badge/Analysis-Computer_Vision-orange)
![GIS](https://img.shields.io/badge/GIS-Leaflet_Maps-emerald)

**CivicRouteAD** is a full-stack prototype for community infrastructure reporting and staff review. Residents can submit a short video, pin the problem location, and add useful context without needing a separate GPS file. Authorized staff get a separate report queue, map, evidence viewer, workflow status, notes, and preliminary video analysis. The original video/GPS analysis console is preserved as a separate Analysis Lab for technical experiments.

The report location comes from the reporter's selected map pin or browser/device location. Exact locations for individual objects within video require synchronized GPS and a suitable camera/geospatial model; any projected points must be checked by a person. CCTV source and camera ID fields record metadata only—this prototype does not connect to live CCTV systems. Automated flags are preliminary and must not be treated as confirmed defects or dispatch instructions.

---

## 🚀 Key Capabilities

- **Multimodal Video & GPS Ingestion**: Consumes standard dashcam video (`.mp4`, `.webm`) paired with synchronized GPX (`.gpx`) or CSV (`.csv`) trajectory logs.
- **AI Hazard Detection & Damage Classification**: Combines lightweight **Ultralytics YOLOv8** object detection with an edge Computer Vision **Road Surface Analyzer** referencing the **Sekilab RoadDamageDetector** benchmark (D00, D10, D20, D40 classes).
  - 🌲 **Downed Trees & Heavy Debris**: Fallen trunks, timber, rockfalls, and roadblocks.
  - 🌊 **Localized Flooding & Waterlogging**: Submerged lanes and standing stormwater pools.
  - 🕳️ **Potholes & Pavement Ruptures**: Deep asphalt cavities and structural pavement fissures.
  - ⚡ **Downed Powerlines & Utility Poles**: Dangling electrical cables and compromised utility poles.
  - 🚧 **Structural Blockages**: Displaced construction barriers, debris, and stalled obstacles.
- **Edge Hazard Tracking & Deduplication**: Multi-frame IoU and spatial tracking collapses repeated detections across video frames into unified hazard incidents with peak confidence and high-resolution visual crops.
- **Edge-to-GIS Photogrammetric Projection**: Translates 2D image pixel coordinates $(u, v)$ to real-world latitude and longitude $(\text{lat}, \text{lon})$ using pinhole camera road-plane geometry and Great-Circle spherical geodesics.
- **Interactive Dual-Console GIS Dashboard**:
  - **Left**: Synchronized Dashcam Video Player with real-time Augmented Reality bounding boxes and a live Telemetry HUD (Speedometer, Compass Heading, GPS Coordinates, Hazard Alert Banner).
  - **Right**: Leaflet Vector Map with basemap switching (Dark Matter, Satellite, Street), moving vehicle marker tracking the drive in real time, and pulsating hazard pins.
- **Standard RFC 7946 GeoJSON Export**: Exports ready-to-use vector feature collections containing hazard points, survey trajectories, and road condition ratings.
- **Municipal Emergency Work Order Generator**: Formats prioritized dispatch orders (Urgent Road Clearance vs. DOT Cold-Mix Patching) with 1-click printable reports.

---

## 🛰️ Advanced Infrastructure Intelligence

The **Advanced** navigation section lets a user select a location (browser permission is requested only after clicking **Use my current location**) and query a configurable radius, defaulting to 1 km. It combines three separate evidence types:

- **Mapillary street imagery and object detections** (requires a personal Mapillary access token and image coverage in the selected area). Image detections are unverified candidates tied to the source image location; they may not locate an individual defect exactly.
- **OpenStreetMap context** (for mapped road-surface/smoothness and hazard tags). These tags are context, not AI-confirmed faults.
- **Existing CivicRouteAD resident reports** with location metadata, returned without reporter contact details or evidence file paths.

The dashboard includes street/satellite/3D map modes (3D buildings depend on the external vector style and network access), candidate KPIs, category distribution, review-status filters, source links, and CSV/GeoJSON export. Street-level queries use the Mapillary API; see the [Mapillary object detection documentation](https://help.mapillary.com/hc/en-us/articles/115000967191-Object-detections). The street vector basemap uses [OpenFreeMap](https://openfreemap.org/quick_start/) and OpenStreetMap data. Satellite tiles use Esri World Imagery with provider attribution.

**Coverage and freshness limitation:** no imagery provider has guaranteed coverage or real-time awareness for every road. A satellite basemap is only a visualization/context layer in this version; this application does not claim to automatically detect individual potholes from satellite pixels. Results are candidate findings, not official confirmed defects.

### Pothole segmentation model (optional)

The detector will load a reviewed segmentation checkpoint when available at `backend/models/pothole_seg.pt`, `backend/pothole_seg.pt`, or the path specified by `CIVICROUTE_POTHOLE_SEG_MODEL`. That checkpoint is **not included in this package version**, because the latest Antigravity checkpoint was not present in the source ZIP available for this edit. Without it, the detector uses the RDD2022 model if installed and the conservative OpenCV surface-anomaly fallback; the fallback is labelled **possible road anomaly**, not confirmed pothole. Do not treat model loading alone as proof of detection quality.

For Windows launch instructions, see [Advanced Infrastructure guide](ADVANCED_INFRASTRUCTURE_GUIDE.md).

---

## 📐 Mathematical Formulation: Camera-to-Geodesic Projection

To geolocate a road hazard detected at bounding box $[x_1, y_1, x_2, y_2]$ in an image of resolution $W \times H$:

### 1. Road-Plane Optical Ray Intersection
Given camera mounting height $H_{\text{cam}} \approx 1.4\text{ m}$, camera pitch angle $\alpha \approx 2.2^\circ$, and vertical field of view $\text{FOV}_v \approx 45^\circ$:
$$\text{Focal Length: } f_y = \frac{H / 2}{\tan(\text{FOV}_v / 2)}$$
$$\text{Optical Center: } c_x = \frac{W}{2}, \quad c_y = \frac{H}{2}$$
$$\text{Vertical Ray Pitch: } \psi_y = \arctan\left(\frac{y_{\text{bottom}} - c_y}{f_y}\right)$$
$$\text{Total Ground Depression: } \gamma = \alpha + \psi_y$$
$$\text{Forward Distance: } d_{\text{forward}} = \frac{H_{\text{cam}}}{\tan(\gamma)}$$

### 2. Lateral Lane Offset
$$\text{Focal Length: } f_x = \frac{W / 2}{\tan(\text{FOV}_h / 2)}$$
$$\text{Lateral Ray Yaw: } \psi_x = \arctan\left(\frac{x_{\text{center}} - c_x}{f_x}\right)$$
$$\text{Lateral Distance: } d_{\text{lateral}} = d_{\text{forward}} \cdot \tan(\psi_x)$$

### 3. Direct Spherical Geodesic Projection
Given vehicle position $(\phi_1, \lambda_1) = (\text{lat}_v, \text{lon}_v)$ and heading $\theta_v$:
$$\text{Target Ground Distance: } D = \sqrt{d_{\text{forward}}^2 + d_{\text{lateral}}^2}, \quad \delta = \frac{D}{R_{\text{earth}}}$$
$$\text{True Target Bearing: } \beta = \left(\theta_v + \text{degrees}(\psi_x) + 360^\circ\right) \pmod{360^\circ}$$
$$\phi_2 = \arcsin\left(\sin(\phi_1)\cos(\delta) + \cos(\phi_1)\sin(\delta)\cos(\beta)\right)$$
$$\lambda_2 = \lambda_1 + \arctan2\left(\sin(\beta)\sin(\delta)\cos(\phi_1), \cos(\delta) - \sin(\phi_1)\sin(\phi_2)\right)$$

---

## ⚡ Quick Start

### 1. First-time setup (Windows)

Install **Python 3.10+** and **Node.js LTS** once. Keep an internet connection for the first launch so the start script can install the required Python and frontend packages.

### 2. Launch in 1 Click (Windows)

Double-click `start.bat`. On the first launch, it checks/installs missing backend packages, installs frontend packages, builds the current React dashboard, then starts the app in your browser at `http://localhost:8000`. Later launches reuse the installed packages and rebuild the frontend before startup. Keep the terminal window open while using the app.

**Quick-start package note:** `frontend/node_modules` is intentionally not bundled, which makes the ZIP much faster to extract. The launcher downloads those packages on the first run.

**Video playback compatibility:** the bundled synthetic MP4 fixtures are encoded as H.264 for browser playback. When uploading a source with a browser-incompatible codec, CivicRoute AD attempts to create an H.264 playback copy with FFmpeg while preserving the original for AI processing. FFmpeg can be installed on Windows and added to `PATH`; alternatively, install the optional Python-bundled executable with `python -m pip install imageio-ffmpeg`.

**Data quality note:** bundled tracks are synthetic and illustrative, not road-matched ground truth. Uploaded surveys are labelled unverified by default. Camera-projected hazard coordinates remain approximate until camera calibration and ground-truth accuracy are validated.

---

### 3. Manual Start (Backend & Frontend)
**Backend:**
```bash
cd backend
python -m uvicorn main:app --host 0.0.0.0 --port 8000 --reload
```
**Frontend (Development Mode):**
```bash
cd frontend
npm run dev
```

---

## 🧪 Pre-Packaged Benchmark Scenarios

CivicRouteAD includes 3 pre-packaged benchmark scenarios so you can test and explore immediately:

1. **Severe Storm & Downed Timber (Alpine Route)**:
   - Highway corridor with dense tree canopies obscuring satellite coverage.
   - Features fallen tree trunks across the roadway, rockfalls, and downed utility lines.
2. **Flash Flooding & Stormwater Inundation**:
   - Coastal boulevard with heavy stormwater runoff, submerged lanes, and localized waterlogging creating aquaplaning dangers.
3. **Severe Potholes & Structural Cracks (Sekilab RDD)**:
   - Urban degradation benchmark with deep asphalt cavities (D00/D10/D20) and displaced construction barricades.

You can also click **"Upload MP4 + GPS"** to upload any custom dashcam video and GPX/CSV trajectory.

---

## 🌐 REST API Reference

| Endpoint | Method | Description |
| :--- | :--- | :--- |
| `/api/health` | `GET` | Health check and system capabilities |
| `/api/infrastructure/candidates` | `GET` | Load saved Advanced street-imagery candidates |
| `/api/infrastructure/candidates/bulk` | `POST` | Save/deduplicate candidate metadata and provenance |
| `/api/infrastructure/candidates/{candidate_id}` | `PATCH` | Staff-only candidate review status/priority updates |
| `/api/infrastructure/nearby-reports?lat=...&lon=...&radius_m=1000` | `GET` | Location-tagged resident reports within radius (privacy-minimized) |
| `/api/scenarios` | `GET` | List available pre-packaged test scenarios |
| `/api/process/scenario/{id}` | `POST` | Process benchmark scenario through edge-to-GIS pipeline |
| `/api/process/upload` | `POST` | Process user-uploaded MP4 video + GPX/CSV trajectory |
| `/api/geojson/{run_id}` | `GET` | Export standard RFC 7946 GeoJSON FeatureCollection |
| `/api/telemetry/{run_id}` | `GET` | Retrieve frame-by-frame synchronized HUD telemetry |
| `/api/hazard-crops/{run_id}/{file}` | `GET` | Retrieve extracted high-resolution crop image of hazard |
| `/api/video/{run_id}` | `GET` | Stream survey dashcam video |
| `/api/export/csv/{run_id}` | `GET` | Export incident log as CSV spreadsheet |
| `/api/export/report/{run_id}` | `GET` | Export Municipal Emergency Action Plan & Work Orders |

---

## 📂 Project Structure

```
Civic_RouteAD/
├── backend/
│   ├── app/
│   │   ├── config.py             # Global path & runtime configuration
│   │   ├── ai/
│   │   │   ├── detector.py       # YOLOv8 + OpenCV Road Surface Analyzer & Tracker
│   │   │   └── hazard_classes.py # Severity calculations & municipal recommendations
│   │   ├── geospatial/
│   │   │   ├── gps_parser.py     # GPX/CSV trajectory parser & temporal interpolator
│   │   │   ├── projection.py     # Pinhole ground photogrammetry & geodesic projection
│   │   │   └── geojson_builder.py# RFC 7946 GeoJSON generator
│   │   ├── pipeline/
│   │   │   └── runner.py         # End-to-end edge-to-GIS execution engine
│   │   ├── scenarios/
│   │   │   └── scenario_manager.py # Benchmark datasets & synthetic generator
│   │   └── api/
│   │       └── routes.py         # FastAPI endpoints
│   ├── data/scenarios/           # Bundled test video feeds & GPX tracks
│   ├── runs/                     # Processed runs, GeoJSON, crops, and telemetry
│   └── main.py                   # FastAPI server entrypoint
├── frontend/
│   ├── src/
│   │   ├── components/
│   │   │   ├── Header.jsx        # Scenario switcher & export triggers
│   │   │   ├── VideoPlayerHUD.jsx# Dashcam video player with AR bounding boxes & HUD
│   │   │   ├── MapDashboard.jsx  # Interactive Leaflet GIS map with vehicle tracking
│   │   │   ├── HazardList.jsx    # Filterable incident register & snapshot zoom
│   │   │   ├── AnalyticsPanel.jsx# Infrastructure health index & KPI summary
│   │   │   ├── UploadModal.jsx   # Custom MP4 + GPX/CSV upload modal
│   │   │   └── ReportModal.jsx   # Municipal emergency work order viewer
│   │   ├── utils/api.js          # API client
│   │   ├── App.jsx               # Root application coordinator
│   │   └── index.css             # Tailwind GIS styling & Leaflet overrides
│   ├── package.json
│   └── vite.config.js
├── run.py                        # Unified 1-click Python launcher
├── start.bat                     # Windows 1-click startup script
└── README.md
```

---

## 📜 References & Benchmarks
- [Sekilab RoadDamageDetector (RDD)](https://github.com/sekilab/RoadDamageDetector)
- [comma.ai comma2k19 dataset](https://github.com/commaai/comma2k19)
- RFC 7946 GeoJSON Specification

---

## Community Reports & Staff Workspace

The app now has three separate areas in the main navigation:

- **Report a problem** — residents submit a short video, choose the infrastructure issue type, and use device location or click/drag a pin on the map. A separate GPX/CSV route is **optional**. Street/CCTV source and camera ID can be recorded where known.
- **Staff workspace** — password-protected queue of actual submissions, map, evidence playback, assignment, status updates, internal notes, and preliminary video analysis. New reports persist in `backend/data/civic_reports.json`; uploaded evidence is saved below `backend/data/reports/`.
- **Analysis lab** — the existing benchmark scenarios and technical video/GPS console. Synthetic fixtures remain separate from citizen reports.

### Local staff access and security

For local development only, the first-run staff password defaults to `admin123`. Before sharing or deploying the app, set a private password **in the server's environment** and restart the backend. In Windows PowerShell, from the project folder, run:

```powershell
$env:CIVICROUTE_STAFF_PASSWORD = "replace-this-with-a-long-private-password"
python run.py
```

The setting applies to that PowerShell session. Do not commit a real password to source control. For a public deployment, use HTTPS, a secret manager/environment variable, restricted upload size/storage, backups, and a proper identity provider/role policy rather than relying on the prototype password gate.

### Location and analysis limits

The report pin is the location selected by the resident or returned by their device. Device accuracy varies with signal and surroundings. If no synchronized GPS track is attached, video analysis can return preliminary visual flags and timestamps but cannot calculate the real-world position of each detected object; the resident's incident pin is **not** reused as the coordinates of every detection. When a GPX/CSV track is supplied, the existing camera-to-GIS pipeline can estimate coordinates, but camera projection is still approximate and requires human validation. AI/heuristic flags are not confirmed defects and should not automatically trigger dispatch.

### Frontend source edits

After editing React files, build the production frontend from `frontend`:

```powershell
cd frontend
npm install
npm run build
cd ..
python run.py
```

`run.py` serves the production bundle from `frontend/dist` at `http://localhost:8000`.
