"""
CivicRouteAD - Backend Application Entry Point
FastAPI server powering Edge-to-GIS Road Hazard & Obstruction Mapping.
"""

import os
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import JSONResponse
from app.config import RUNS_DIR, FRONTEND_DIST_DIR, SCENARIOS_DIR
from app.api.routes import router
from app.api.report_routes import router as report_router
from app.api.infrastructure_routes import router as infrastructure_router
from app.scenarios.scenario_manager import generate_scenario_files

app = FastAPI(
    title="CivicRouteAD",
    description="Automated Road Obstruction & Hazard Mapping from Dashcam Video (Edge-to-GIS)",
    version="1.0.0"
)

# Enable CORS for frontend development and production
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include API routes
app.include_router(router)
app.include_router(report_router)
app.include_router(infrastructure_router)

# Mount runs directory for file access
os.makedirs(str(RUNS_DIR), exist_ok=True)
app.mount("/runs", StaticFiles(directory=str(RUNS_DIR)), name="runs")

# Never serve an old frontend bundle. The old bundle was still making direct
# Mapillary/Overpass browser requests after the source had been fixed, which made
# users think the fixes were ineffective. run.py/start.bat builds and validates
# this marker before starting the server.
FRONTEND_BUILD_MARKER = 'civicroute-build" content="advanced-map-proxy-20261010'
_frontend_index = FRONTEND_DIST_DIR / "index.html"
_frontend_is_current = False
if _frontend_index.exists():
    try:
        _frontend_is_current = FRONTEND_BUILD_MARKER in _frontend_index.read_text(encoding="utf-8", errors="replace")
    except OSError:
        _frontend_is_current = False

if FRONTEND_DIST_DIR.exists() and _frontend_is_current:
    app.mount("/", StaticFiles(directory=str(FRONTEND_DIST_DIR), html=True), name="frontend")
else:
    @app.get("/", include_in_schema=False)
    def frontend_build_required():
        return JSONResponse(
            status_code=503,
            content={
                "ok": False,
                "error": "The frontend production bundle is missing or outdated.",
                "next_step": "Stop old CivicRouteAD servers, then run start.bat from the project root to rebuild frontend/dist.",
                "required_build": FRONTEND_BUILD_MARKER,
            },
        )


@app.on_event("startup")
def startup_event():
    print("[CivicRouteAD] Server starting...")
    # Pre-generate scenario benchmark data
    try:
        generate_scenario_files(SCENARIOS_DIR)
        print("[CivicRouteAD] Scenario datasets verified and ready.")
    except Exception as e:
        print(f"[CivicRouteAD] Warning initializing scenarios: {e}")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
