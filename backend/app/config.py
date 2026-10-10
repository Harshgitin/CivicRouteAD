"""
CivicRouteAD - Global Path and Environment Configuration
"""

import os
from pathlib import Path

# Paths anchored to the backend root directory
APP_DIR = Path(__file__).resolve().parent
BACKEND_DIR = APP_DIR.parent
PROJECT_ROOT = BACKEND_DIR.parent


def _load_env_file(path: Path) -> None:
    """Load key-value environment variables from .env if not already set."""
    if not path.is_file():
        return
    try:
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, val = line.split("=", 1)
                key = key.strip()
                val = val.strip().strip("'\"")
                if key and key not in os.environ:
                    os.environ[key] = val
    except Exception as exc:
        print(f"[CivicRouteAD] Warning loading {path}: {exc}")


# Load environment variables from project root .env or backend .env
_load_env_file(PROJECT_ROOT / ".env")
_load_env_file(BACKEND_DIR / ".env")

DATA_DIR = BACKEND_DIR / "data"
SCENARIOS_DIR = DATA_DIR / "scenarios"
RUNS_DIR = BACKEND_DIR / "runs"
FRONTEND_DIST_DIR = PROJECT_ROOT / "frontend" / "dist"

# Ensure runtime directories exist
DATA_DIR.mkdir(parents=True, exist_ok=True)
SCENARIOS_DIR.mkdir(parents=True, exist_ok=True)
RUNS_DIR.mkdir(parents=True, exist_ok=True)

# Resident submissions are stored separately from bundled/demo scenarios.
REPORTS_DIR = DATA_DIR / "reports"
REPORTS_DB_PATH = DATA_DIR / "civic_reports.json"
REPORTS_DIR.mkdir(parents=True, exist_ok=True)

# Local prototype default only. Set CIVICROUTE_STAFF_PASSWORD to a unique,
# strong value before exposing this application to a network or deploying it.
STAFF_PASSWORD = os.getenv("CIVICROUTE_STAFF_PASSWORD", "admin123")

# Mapillary access token: read securely from environment only.
# Never expose or return this secret token in API responses or logs.
MAPILLARY_ACCESS_TOKEN = os.getenv("MAPILLARY_ACCESS_TOKEN", "").strip()


def redact_secret(message: str, secret: str = "") -> str:
    """Redact secret tokens from log strings or exception messages."""
    text = str(message or "")
    target = secret or MAPILLARY_ACCESS_TOKEN
    if target and len(target) >= 4:
        text = text.replace(target, "[REDACTED]")
    return text
