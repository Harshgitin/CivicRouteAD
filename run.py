"""
CivicRouteAD - Unified Application Launcher
Launches the full-stack edge-to-GIS hazard mapping web application.
Automatically starts the FastAPI server and opens the interactive dashboard in your browser.
"""

import sys
import os
import webbrowser
import time
import subprocess
import socket
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
BACKEND_DIR = BASE_DIR / "backend"

BUILD_MARKER = 'civicroute-build" content="advanced-map-proxy-20261010'


def ensure_frontend_build():
    """Require a freshly built bundle so the app cannot silently serve stale JS.

    A stale bundle previously continued to call Mapillary and Overpass directly
    from the browser, making backend-proxy fixes appear ineffective. Refuse to
    start on an outdated frontend when a build fails.
    """
    if os.environ.get("CIVICROUTE_SKIP_FRONTEND_BUILD") == "1":
        index_path = BASE_DIR / "frontend" / "dist" / "index.html"
        if index_path.exists() and BUILD_MARKER in index_path.read_text(encoding="utf-8", errors="replace"):
            print("[i] Frontend build skipped; required build marker is present.")
            return
        raise SystemExit("[ERROR] Refusing to serve stale frontend: build marker is missing. Unset CIVICROUTE_SKIP_FRONTEND_BUILD and run start.bat.")
    frontend_dir = BASE_DIR / "frontend"
    dist_dir = frontend_dir / "dist"
    index_bundle = dist_dir / "index.html"
    source_paths = [frontend_dir / "index.html", frontend_dir / "package.json"]
    src_dir = frontend_dir / "src"
    if src_dir.exists():
        source_paths.extend(path for path in src_dir.rglob("*") if path.is_file())
    newest_source = max((path.stat().st_mtime for path in source_paths if path.exists()), default=0)
    newest_bundle = max((path.stat().st_mtime for path in dist_dir.rglob("*") if path.is_file()), default=0) if dist_dir.exists() else 0
    bundle_has_marker = False
    if index_bundle.exists():
        try:
            bundle_has_marker = BUILD_MARKER in index_bundle.read_text(encoding="utf-8", errors="replace")
        except OSError:
            bundle_has_marker = False
    if index_bundle.exists() and newest_bundle >= newest_source and bundle_has_marker:
        print("[i] Frontend production bundle is current (build marker verified).")
        return

    # npm.cmd is a Windows command shim, so Windows needs shell=True while
    # Unix-like environments should invoke npm directly without a shell.
    build_command = "npm.cmd run build" if os.name == "nt" else ["npm", "run", "build"]
    print("[*] Frontend source changed; building the updated React dashboard...")
    try:
        result = subprocess.run(
            build_command,
            cwd=str(frontend_dir),
            shell=(os.name == "nt"),
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        if result.returncode != 0:
            print(result.stdout)
            raise SystemExit("[ERROR] Frontend build failed. The server will not start with the stale bundle. Open PowerShell in frontend and run: npm install; npm run build")
        print(result.stdout)
        if not index_bundle.exists() or BUILD_MARKER not in index_bundle.read_text(encoding="utf-8", errors="replace"):
            raise SystemExit("[ERROR] Frontend build finished but the required build marker is missing. Verify the correct frontend folder is being built.")
        print("[✓] Updated frontend bundle is ready and verified.")
    except OSError as exc:
        raise SystemExit(f"[ERROR] Could not run npm ({exc}). Install Node.js, then run npm install and npm run build inside frontend.") from exc


def ensure_port_available(port=8000):
    """Avoid leaving an older server on port 8000 while launching a new build."""
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=0.35):
            raise SystemExit(
                f"[ERROR] Port {port} is already serving a process. Stop the previous CivicRouteAD terminal with Ctrl+C, then run start.bat again. "
                "The launcher will not start a second copy because that can make the browser continue showing old code."
            )
    except ConnectionRefusedError:
        return
    except socket.timeout:
        return
    except OSError:
        return


def main():
    ensure_port_available()
    print("=" * 70)
    print("           CivicRouteAD - Automated Road Hazard & GIS Mapping")
    print("       Edge-to-GIS Dashcam Photogrammetry & Situational Awareness")
    print("=" * 70)

    # Refresh built assets before FastAPI mounts frontend/dist.
    ensure_frontend_build()

    # Change directory to backend
    os.chdir(str(BACKEND_DIR))
    sys.path.insert(0, str(BACKEND_DIR))

    # Import uvicorn and app
    try:
        import uvicorn
        from app.scenarios.scenario_manager import generate_scenario_files
        from app.config import SCENARIOS_DIR
        print("[*] Pre-checking scenario datasets...")
        generate_scenario_files(SCENARIOS_DIR)
        print("[✓] Scenario datasets verified and ready.")
    except Exception as e:
        print(f"[!] Warning during scenario check: {e}")

    url = "http://localhost:8000"
    print(f"\n[🚀] Starting CivicRouteAD server at: {url}")
    print("[💡] Serving API endpoints and React GIS Dashboard simultaneously.")
    print("[ℹ] Press Ctrl+C to stop the server anytime.\n")

    # Open browser automatically after slight delay
    def open_browser():
        time.sleep(1.2)
        webbrowser.open(url)

    import threading
    threading.Thread(target=open_browser, daemon=True).start()

    # Run uvicorn
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=False)

if __name__ == "__main__":
    main()
