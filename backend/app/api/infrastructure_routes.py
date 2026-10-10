"""Persistent nearby-infrastructure candidate store for CivicRouteAD Advanced.

Mapillary/OSM remain external evidence sources. This API stores only candidates
submitted by the dashboard and preserves their provenance and review status.
"""
from __future__ import annotations

import asyncio

import hashlib
import json
import math
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from fastapi import APIRouter, Body, Header, HTTPException
from fastapi.concurrency import run_in_threadpool
import httpx
import cv2
import numpy as np
from urllib.parse import urlparse

import uuid
from app.config import DATA_DIR, MAPILLARY_ACCESS_TOKEN, redact_secret
from app.api.report_routes import _require_staff, _load_reports, _public_report

router = APIRouter(prefix="/api")
_DB_PATH = DATA_DIR / "infrastructure_candidates.json"
_LOCK = threading.RLock()
_ALLOWED_STATUSES = {"Unverified", "Verified", "Rejected", "Resolved"}
_ALLOWED_PRIORITIES = {"Low", "Normal", "High"}
_MAX_BULK_ITEMS = 250


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _read() -> list[dict[str, Any]]:
    with _LOCK:
        if not _DB_PATH.exists():
            return []
        try:
            value = json.loads(_DB_PATH.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise HTTPException(status_code=500, detail="Infrastructure candidate store could not be read.") from exc
        return value if isinstance(value, list) else []


def _write(items: list[dict[str, Any]]) -> None:
    with _LOCK:
        _DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        temp = _DB_PATH.with_suffix(".tmp")
        temp.write_text(json.dumps(items, ensure_ascii=False, indent=2), encoding="utf-8")
        temp.replace(_DB_PATH)


def _stable_id(item: dict[str, Any]) -> str:
    identity = "|".join(str(item.get(k) or "") for k in ("source", "image_id", "detection_id", "label"))
    identity += f"|{float(item['lat']):.6f}|{float(item['lon']):.6f}"
    digest = hashlib.sha256(identity.encode("utf-8")).hexdigest()[:12]
    return f"INF-{digest.upper()}"


def _clean_candidate(raw: Any) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise HTTPException(status_code=400, detail="Each infrastructure candidate must be an object.")
    try:
        lat = float(raw.get("lat"))
        lon = float(raw.get("lon"))
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail="Candidate latitude and longitude must be numeric.") from exc
    if not math.isfinite(lat) or not math.isfinite(lon) or not (-90 <= lat <= 90) or not (-180 <= lon <= 180):
        raise HTTPException(status_code=400, detail="Candidate coordinates are outside valid latitude/longitude ranges.")

    label = str(raw.get("label") or "Infrastructure candidate").strip()[:180]
    hazard_type = str(raw.get("hazard_type") or "other_infrastructure").strip()[:80]
    source = str(raw.get("source") or "Unknown imagery source").strip()[:80]
    confidence = raw.get("confidence")
    if confidence is not None:
        try:
            confidence = float(confidence)
        except (TypeError, ValueError):
            confidence = None
        if confidence is not None and (not math.isfinite(confidence) or not 0 <= confidence <= 1):
            confidence = None
    return {
        "id": _stable_id({**raw, "lat": lat, "lon": lon, "label": label, "source": source}),
        "label": label,
        "hazard_type": hazard_type,
        "lat": round(lat, 7),
        "lon": round(lon, 7),
        "source": source,
        "image_id": str(raw.get("image_id") or "")[:120],
        "detection_id": str(raw.get("detection_id") or "")[:120],
        "image_url": str(raw.get("image_url") or "")[:1200],
        "image_page_url": str(raw.get("image_page_url") or "")[:1200],
        "captured_at": str(raw.get("captured_at") or "")[:80] or None,
        "observed_at": str(raw.get("observed_at") or _now())[:80],
        "confidence": confidence,
        "confidence_is_calibrated": bool(raw.get("confidence_is_calibrated", False)),
        "evidence_note": str(raw.get("evidence_note") or "Street-level imagery model candidate; requires human verification.")[:500],
    }


def _distance_meters(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance using the haversine formula."""
    r = 6371008.8
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    h = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.atan2(math.sqrt(h), math.sqrt(max(0.0, 1 - h)))


def _report_category(issue_type: Any, title: Any) -> tuple[str, str]:
    text = f"{issue_type or ''} {title or ''}".lower().replace("_", " ")
    if "pothole" in text or "pot hole" in text:
        return "pothole", "Resident-reported pothole"
    if "crack" in text or "pavement" in text or "road damage" in text:
        return "road_crack", "Resident-reported road damage"
    if any(word in text for word in ("flood", "waterlog", "water logging", "standing water")):
        return "waterlogging", "Resident-reported waterlogging"
    if any(word in text for word in ("tree", "branch", "debris", "landslide", "rockfall")):
        return "fallen_debris", "Resident-reported obstruction"
    return "other", "Resident-reported infrastructure issue"


@router.get("/infrastructure/nearby-reports")
def nearby_infrastructure_reports(lat: float, lon: float, radius_m: float = 1000):
    """Return privacy-minimized resident report metadata in a caller-selected radius.

    Reporter contact fields, staff notes, uploaded file paths and evidence URLs are
    deliberately excluded. These are resident reports, not independent AI detections.
    """
    if not math.isfinite(lat) or not math.isfinite(lon) or not (-90 <= lat <= 90) or not (-180 <= lon <= 180):
        raise HTTPException(status_code=400, detail="Center latitude/longitude are invalid.")
    if not math.isfinite(radius_m) or not (100 <= radius_m <= 5000):
        raise HTTPException(status_code=400, detail="Radius must be between 100 and 5000 metres.")

    results = []
    for raw in _load_reports():
        safe = _public_report(raw)
        try:
            report_lat = float(safe.get("latitude"))
            report_lon = float(safe.get("longitude"))
        except (TypeError, ValueError):
            continue
        distance_m = _distance_meters(lat, lon, report_lat, report_lon)
        if distance_m > radius_m:
            continue
        hazard_type, label = _report_category(safe.get("issue_type"), safe.get("title"))
        results.append({
            "id": str(safe.get("id") or ""),
            "label": label,
            "title": str(safe.get("title") or safe.get("issue_type") or "Resident report")[:180],
            "hazard_type": hazard_type,
            "lat": report_lat,
            "lon": report_lon,
            "distance_m": round(distance_m, 1),
            "source": "Resident-submitted report",
            "status": str(safe.get("status") or "Submitted"),
            "created_at": safe.get("created_at"),
            "location_source": safe.get("location_source"),
            "confidence": None,
            "verified": False,
        })
    results.sort(key=lambda item: item.get("distance_m", float("inf")))
    return {"count": len(results), "radius_m": radius_m, "items": results[:500], "notice": "Resident-submitted reports are not independently AI-verified."}


@router.get("/infrastructure/candidates")
def list_infrastructure_candidates():
    items = _read()
    items.sort(key=lambda x: str(x.get("last_seen_at") or x.get("observed_at") or ""), reverse=True)
    return {"count": len(items), "items": items}


@router.post("/infrastructure/candidates/bulk")
def upsert_infrastructure_candidates(payload: dict = Body(...)):
    raw_items = payload.get("items", []) if isinstance(payload, dict) else []
    if not isinstance(raw_items, list):
        raise HTTPException(status_code=400, detail="'items' must be a list.")
    if len(raw_items) > _MAX_BULK_ITEMS:
        raise HTTPException(status_code=413, detail=f"At most {_MAX_BULK_ITEMS} candidates can be saved per scan.")

    candidates = [_clean_candidate(item) for item in raw_items]
    with _LOCK:
        existing = _read()
        by_id = {item.get("id"): item for item in existing}
        added = 0
        refreshed = 0
        for candidate in candidates:
            prior = by_id.get(candidate["id"])
            if prior:
                # Preserve human review fields while refreshing source metadata.
                candidate["status"] = prior.get("status", "Unverified")
                candidate["priority"] = prior.get("priority", "Normal")
                candidate["created_at"] = prior.get("created_at", _now())
                candidate["review_note"] = prior.get("review_note", "")
                candidate["last_seen_at"] = _now()
                candidate["seen_count"] = int(prior.get("seen_count", 1)) + 1
                refreshed += 1
            else:
                candidate.update({
                    "status": "Unverified",
                    "priority": "Normal",
                    "created_at": _now(),
                    "last_seen_at": _now(),
                    "seen_count": 1,
                    "review_note": "",
                })
                added += 1
            by_id[candidate["id"]] = candidate
        combined = list(by_id.values())
        _write(combined)
    return {"ok": True, "added": added, "refreshed": refreshed, "count": len(combined), "items": candidates}


@router.patch("/infrastructure/candidates/{candidate_id}")
def update_infrastructure_candidate(
    candidate_id: str,
    payload: dict = Body(...),
    x_staff_session: Optional[str] = Header(None),
):
    # Verification/closure is a staff action and must use the same staff session
    # as the existing report desk. Public users may run scans but cannot approve them.
    _require_staff(x_staff_session)
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="Update body must be an object.")
    items = _read()
    candidate = next((item for item in items if item.get("id") == candidate_id), None)
    if not candidate:
        raise HTTPException(status_code=404, detail="Infrastructure candidate not found.")
    if "status" in payload:
        status = str(payload.get("status") or "")
        if status not in _ALLOWED_STATUSES:
            raise HTTPException(status_code=400, detail="Choose a supported review status.")
        candidate["status"] = status
    if "priority" in payload:
        priority = str(payload.get("priority") or "")
        if priority not in _ALLOWED_PRIORITIES:
            raise HTTPException(status_code=400, detail="Choose a supported priority.")
        candidate["priority"] = priority
    if "review_note" in payload:
        candidate["review_note"] = str(payload.get("review_note") or "").strip()[:1000]
    candidate["updated_at"] = _now()
    _write(items)
    return {"ok": True, "item": candidate}


# Fixed upstream hosts only: the client cannot provide arbitrary URLs.
_MAPILLARY_IMAGES_URL = "https://graph.mapillary.com/images"
_OVERPASS_URLS = (
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
    "https://maps.mail.ru/osm/tools/overpass/api/interpreter",
)
_OSM_CACHE: dict[str, tuple[float, dict[str, Any]]] = {}
_OSM_CACHE_TTL_SEC = 900.0  # 15 minutes TTL

_ALLOWED_THUMB_HOST_SUFFIXES = (".mapillary.com", ".fbcdn.net")
_MAX_MAPILLARY_IMAGES_TO_ANALYZE = 12
_MAX_THUMBNAIL_BYTES = 8 * 1024 * 1024

CAPABILITY_MATRIX: dict[str, dict[str, str]] = {
    "pothole": {
        "category": "pothole",
        "label": "Potholes",
        "mapillary_native": "Supported",
        "mapillary_note": "Identified by Mapillary's native object detection service if present.",
        "civicroute_local_ai": "Supported",
        "civicroute_note": "Trained YOLOv8 RDD2022 model (D40-Pothole class). Heuristics are marked as unverified anomalies.",
        "osm_context": "Proxy indicator only (smoothness=bad/very_bad/impassable).",
        "satellite_aerial": "Unsupported (sub-meter ground resolution required).",
        "resident_reports": "Supported (user submissions with GPS & media).",
    },
    "road_crack": {
        "category": "road_crack",
        "label": "Road cracks & damaged pavement",
        "mapillary_native": "Unsupported",
        "mapillary_note": "Mapillary does not classify pavement crack sub-types.",
        "civicroute_local_ai": "Supported",
        "civicroute_note": "Trained YOLOv8 RDD2022 model (D00 Longitudinal, D10 Transverse, D20 Alligator).",
        "osm_context": "Proxy indicator only (smoothness=bad/very_bad).",
        "satellite_aerial": "Unsupported.",
        "resident_reports": "Supported.",
    },
    "fallen_debris": {
        "category": "fallen_debris",
        "label": "Fallen trees & road obstructions",
        "mapillary_native": "Unsupported",
        "mapillary_note": "Not a primary Mapillary object detection category.",
        "civicroute_local_ai": "Supported",
        "civicroute_note": "YOLO general model detecting trees/debris in roadway.",
        "osm_context": "Proxy indicator (hazard=landslide/rockfall).",
        "satellite_aerial": "Unsupported.",
        "resident_reports": "Supported.",
    },
    "waterlogging": {
        "category": "waterlogging",
        "label": "Flooding & waterlogging",
        "mapillary_native": "Unsupported",
        "mapillary_note": "Mapillary semantic segmentation does not classify flood depth.",
        "civicroute_local_ai": "Supported",
        "civicroute_note": "YOLO / water reflection detection heuristics.",
        "osm_context": "Mapped hazard tags (hazard=flood).",
        "satellite_aerial": "Regional flood extent only; localized street-level unsupported.",
        "resident_reports": "Supported.",
    },
    "damaged_infrastructure": {
        "category": "damaged_infrastructure",
        "label": "Damaged signs & street furniture",
        "mapillary_native": "Supported",
        "mapillary_note": "Mapillary detects traffic signs, poles, and street fixtures.",
        "civicroute_local_ai": "Partial",
        "civicroute_note": "General object model for utility poles/signs.",
        "osm_context": "Mapped construction tags (highway=construction).",
        "satellite_aerial": "Unsupported.",
        "resident_reports": "Supported.",
    },
}


@router.get("/infrastructure/mapillary/status")
async def get_mapillary_status():
    """Verify server-side Mapillary authentication status without exposing secrets."""
    token = MAPILLARY_ACCESS_TOKEN
    if not token:
        return {
            "configured": False,
            "status": "not_configured",
            "message": "Mapillary access token is not configured on the server. Set MAPILLARY_ACCESS_TOKEN in .env",
            "token_preview": None,
            "docs_url": "https://www.mapillary.com/dashboard/developers",
        }
    preview = f"{token[:4]}...{token[-4:]}" if len(token) > 12 else "Configured"
    timeout = httpx.Timeout(connect=3.5, read=5.0, write=4.0, pool=3.0)
    try:
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
            res = await client.get(
                _MAPILLARY_IMAGES_URL,
                params={"access_token": token, "limit": "1", "fields": "id"},
                headers={"Authorization": f"OAuth {token}"},
            )
            if res.status_code < 400:
                return {
                    "configured": True,
                    "status": "ready",
                    "message": "Mapillary API authentication verified.",
                    "token_preview": preview,
                    "docs_url": "https://www.mapillary.com/dashboard/developers",
                }
            detail, _ = _mapillary_error_detail(res)
            detail = redact_secret(detail, token)
            if res.status_code == 401:
                return {
                    "configured": True,
                    "status": "authentication_failed",
                    "message": f"Invalid or expired Mapillary access token (HTTP 401): {detail}",
                    "token_preview": preview,
                    "docs_url": "https://www.mapillary.com/dashboard/developers",
                }
            if res.status_code == 403:
                return {
                    "configured": True,
                    "status": "insufficient_permissions",
                    "message": f"Mapillary token lacks required permissions (HTTP 403): {detail}",
                    "token_preview": preview,
                    "docs_url": "https://www.mapillary.com/dashboard/developers",
                }
            if res.status_code == 429:
                return {
                    "configured": True,
                    "status": "rate_limited",
                    "message": "Mapillary rate limit reached (HTTP 429). Please wait before scanning again.",
                    "token_preview": preview,
                    "docs_url": "https://www.mapillary.com/dashboard/developers",
                }
            return {
                "configured": True,
                "status": "provider_unavailable",
                "message": f"Mapillary returned HTTP {res.status_code}: {detail}",
                "token_preview": preview,
                "docs_url": "https://www.mapillary.com/dashboard/developers",
            }
    except (httpx.TimeoutException, httpx.NetworkError) as exc:
        return {
            "configured": True,
            "status": "provider_unavailable",
            "message": f"Mapillary API connection failed ({type(exc).__name__}). Check network connection.",
            "token_preview": preview,
            "docs_url": "https://www.mapillary.com/dashboard/developers",
        }
    except Exception as exc:
        return {
            "configured": True,
            "status": "provider_unavailable",
            "message": f"Mapillary check failed: {redact_secret(str(exc), token)}",
            "token_preview": preview,
            "docs_url": "https://www.mapillary.com/dashboard/developers",
        }


@router.get("/infrastructure/diagnostics")
async def get_infrastructure_diagnostics():
    """System-wide readiness check covering models, credentials, proxies, and capabilities."""
    from app.api.routes import runner as shared_runner
    model_status = shared_runner.detector.status() if hasattr(shared_runner, "detector") else {}
    token = MAPILLARY_ACCESS_TOKEN
    mapillary_info = {
        "configured": bool(token),
        "status": "ready" if bool(token) else "not_configured",
        "token_preview": (f"{token[:4]}...{token[-4:]}" if len(token) > 12 else ("Configured" if token else None)),
    }
    osm_info = {
        "endpoints": list(_OVERPASS_URLS),
        "cache_entries": len(_OSM_CACHE),
        "cache_ttl_seconds": _OSM_CACHE_TTL_SEC,
    }
    return {
        "ok": True,
        "timestamp": _now(),
        "mapillary": mapillary_info,
        "models": model_status,
        "osm": osm_info,
        "capability_matrix": CAPABILITY_MATRIX,
    }



def _valid_point(raw_lat: Any, raw_lon: Any) -> tuple[float, float] | None:
    """Reject missing/null/empty coords before numeric coercion (Number(null) is 0 in JS)."""
    if raw_lat is None or raw_lon is None or raw_lat == "" or raw_lon == "":
        return None
    try:
        lat, lon = float(raw_lat), float(raw_lon)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(lat) or not math.isfinite(lon) or not (-90 <= lat <= 90) or not (-180 <= lon <= 180):
        return None
    return lat, lon


def _mapillary_image_point(image: dict[str, Any]) -> tuple[float, float] | None:
    geometry = image.get("computed_geometry") or image.get("geometry") or image.get("location")
    coords = geometry.get("coordinates") if isinstance(geometry, dict) else geometry
    if not isinstance(coords, (list, tuple)) or len(coords) < 2:
        return None
    point = _valid_point(coords[1], coords[0])
    return point


def _mapillary_to_hazard_category(detection: dict[str, Any]) -> tuple[str, str] | None:
    """Map local model output to dashboard categories; CV heuristics are not confirmed faults."""
    kind = str(detection.get("type") or "").lower()
    source = str(detection.get("source") or "")
    label = str(detection.get("label") or "Infrastructure candidate")
    if kind == "pothole_damage" and source in {"pothole_segmentation_model", "rdd2022_road_damage_model"}:
        return "pothole", "Pothole candidate"
    if kind == "road_crack" and source == "rdd2022_road_damage_model":
        return "road_crack", "Road crack candidate"
    if kind in {"fallen_tree_debris", "powerline_hazard", "structural_blockage", "road_flooding"} and source == "yolo_general_model":
        if kind == "fallen_tree_debris":
            return "fallen_debris", label
        if kind == "road_flooding":
            return "waterlogging", label
        return "other", label
    # The OpenCV fallback only estimates possible surface anomalies and must not be called a pothole.
    if kind == "possible_road_anomaly" and source == "cv_surface_analyzer":
        return "other", "Possible road-surface anomaly (heuristic; verify manually)"
    return None


# Mapillary Graph API v4 native detection taxonomy (category--subcategory--object).
# Kept strictly distinct from RDD2022 benchmark classes (D00-D40) and general YOLO classes.
MAPILLARY_NATIVE_CLASS_MAPPING: dict[str, tuple[str, str]] = {
    # Potholes & road surface ruptures
    "object--pothole": ("pothole", "Mapillary-detected pothole"),
    "object--ground--pothole": ("pothole", "Mapillary-detected pothole"),
    "construction--flat--pothole": ("pothole", "Mapillary-detected pothole"),
    # Drainage / surface fixtures (often near or mistaken for road defects)
    "object--manhole": ("other", "Mapillary-detected manhole"),
    "object--catch-basin": ("waterlogging", "Mapillary-detected catch basin / storm drain"),
    # Curbs and barriers (explicitly NOT potholes)
    "construction--barrier--curb": ("other", "Mapillary-detected curb / barrier"),
    "construction--flat--curb": ("other", "Mapillary-detected curb"),
    "construction--barrier--concrete-block": ("fallen_debris", "Mapillary-detected concrete barrier"),
    "construction--barrier--guard-rail": ("other", "Mapillary-detected guard rail"),
    # Infrastructure assets
    "object--street-light": ("damaged_infrastructure", "Mapillary-detected street light"),
    "object--support--utility-pole": ("damaged_infrastructure", "Mapillary-detected utility pole"),
    "object--traffic-light": ("damaged_infrastructure", "Mapillary-detected traffic light"),
}


def mapillary_native_to_hazard(value: Any) -> tuple[str, str] | None:
    """Translate Mapillary's native taxonomy to CivicRouteAD categories.

    Mapillary Graph API v4 returns classes in format `category--subcategory--object`
    (e.g., `object--pothole`, `construction--barrier--curb`, `object--street-light`).
    This mapping is completely separate from RDD2022 benchmark classes (D00-D40).
    Curbs, barriers, and sidewalks are never mapped to potholes.
    """
    if not value:
        return None
    raw = str(value).strip().lower()
    if raw in MAPILLARY_NATIVE_CLASS_MAPPING:
        return MAPILLARY_NATIVE_CLASS_MAPPING[raw]
    if "curb" in raw or "barrier" in raw or "sidewalk" in raw:
        return "other", f"Mapillary-detected {raw.replace('--', ' ')}"
    if "pothole" in raw:
        return "pothole", "Mapillary-detected pothole"
    if "catch-basin" in raw or "catch_basin" in raw or "drain" in raw:
        return "waterlogging", "Mapillary-detected storm drain / catch basin"
    if any(k in raw for k in ("street-light", "utility-pole", "traffic-light", "traffic-sign")):
        return "damaged_infrastructure", f"Mapillary-detected {raw.replace('--', ' ')}"
    return None


def _mapillary_value_is_pothole(value: Any) -> bool:
    """Strictly identify if a Mapillary native detection value is a pothole class.

    Ensures curbs (e.g. construction--barrier--curb), markings, and barriers
    are never misclassified as potholes. Does NOT assume RDD2022 D40 label format.
    """
    raw = str(value or "").strip().lower()
    if "curb" in raw or "barrier" in raw or "sidewalk" in raw:
        return False
    return "pothole" in raw


def _mapillary_error_detail(response: httpx.Response) -> tuple[str, bool]:
    """Return a safe short API error message and whether a smaller bbox may help."""
    try:
        body = response.json()
    except Exception:
        body = {}
    error = body.get("error", {}) if isinstance(body, dict) else {}
    message = str(error.get("message") or response.text or f"HTTP {response.status_code}")
    compact = " ".join(message.split())[:260]
    transient_bbox_error = (
        "timeout" in message.lower()
        or "timed out" in message.lower()
        or str(error.get("code")) == "-2"
        or str(error.get("error_subcode")) == "3404014"
    )
    return compact, transient_bbox_error


@router.post("/infrastructure/mapillary/scan")
async def scan_mapillary_street_images(payload: dict = Body(...)):
    """Fetch nearby Mapillary thumbnails server-side and run CivicRouteAD's actual local detector.

    Mapillary provides street imagery and capture metadata; its generic object detections are
    not treated as pothole classifications. Coordinates identify the camera image position,
    not a survey-grade ground coordinate for the visible defect.
    """
    scan_id = f"scan-{uuid.uuid4().hex[:8]}"
    start_time = _now()
    center = _valid_point(payload.get("lat"), payload.get("lon"))
    if not center:
        raise HTTPException(status_code=400, detail="Valid latitude and longitude are required.")
    lat, lon = center
    try:
        radius_m = float(payload.get("radius_m", 1000))
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail="Radius must be numeric.") from exc
    if not math.isfinite(radius_m) or not 100 <= radius_m <= 5000:
        raise HTTPException(status_code=400, detail="Radius must be between 100 and 5000 metres.")

    selected_filter = str(payload.get("hazard_filter") or "all").lower().strip()
    token = str(payload.get("access_token") or payload.get("mapillary_token") or MAPILLARY_ACCESS_TOKEN or "").strip()
    if not token:
        return {
            "ok": False,
            "status": "not_configured",
            "provider_status": "not_configured",
            "message": "Mapillary access token is not configured on the server. Set MAPILLARY_ACCESS_TOKEN in .env or configure a client token.",
            "scan_id": scan_id,
            "center": [lat, lon],
            "radius_m": radius_m,
            "selected_category": selected_filter,
            "provider": "Mapillary",
            "image_count": 0,
            "images_with_valid_location": 0,
            "images_analyzed": 0,
            "images_checked_by_mapillary": 0,
            "mapillary_pothole_detections": 0,
            "candidate_count": 0,
            "candidates": [],
            "errors": ["Mapillary access token is not configured on the server. Set MAPILLARY_ACCESS_TOKEN in .env."],
            "started_at": start_time,
            "completed_at": _now(),
            "notice": "Mapillary access token is not configured. Street imagery was not queried.",
        }
    if len(token) > 2048 or any(ch.isspace() for ch in token):
        raise HTTPException(status_code=400, detail="The Mapillary access token format appears invalid.")

    lat_delta = radius_m / 111320.0
    lon_delta = radius_m / max(1000.0, 111320.0 * math.cos(math.radians(lat)))
    west = max(-180.0, lon - lon_delta)
    east = min(180.0, lon + lon_delta)
    south = max(-90.0, lat - lat_delta)
    north = min(90.0, lat + lat_delta)
    bbox = f"{west},{south},{east},{north}"
    base_params = {
        "access_token": token,
        "fields": "id,computed_geometry,thumb_1024_url,captured_at,sequence",
        "limit": "20",
    }
    headers = {"Authorization": f"OAuth {token}"}

    # Large Mapillary bounding-box searches can time out as HTTP 400 even with a
    # valid token. Start with a smaller result limit, then tile the same search box
    # into four overlapping-safe quadrants only when Mapillary explicitly reports
    # a query timeout. Invalid tokens/fields must surface as actionable errors.
    timeout = httpx.Timeout(connect=7.0, read=12.0, write=8.0, pool=5.0)
    try:
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
            image_response = await client.get(_MAPILLARY_IMAGES_URL, params={**base_params, "bbox": bbox}, headers=headers)
            upstream_images = []
            if image_response.status_code < 400:
                body = image_response.json()
                upstream_images = body.get("data", []) if isinstance(body, dict) else []
            elif image_response.status_code in (401, 403):
                detail, _ = _mapillary_error_detail(image_response)
                detail = redact_secret(detail, token)
                status_val = "authentication_failed" if image_response.status_code == 401 else "insufficient_permissions"
                return {
                    "ok": False,
                    "status": status_val,
                    "provider_status": status_val,
                    "message": f"Mapillary authentication error (HTTP {image_response.status_code}): {detail}",
                    "scan_id": scan_id,
                    "center": [lat, lon],
                    "radius_m": radius_m,
                    "selected_category": selected_filter,
                    "provider": "Mapillary",
                    "image_count": 0,
                    "images_with_valid_location": 0,
                    "images_analyzed": 0,
                    "images_checked_by_mapillary": 0,
                    "mapillary_pothole_detections": 0,
                    "candidate_count": 0,
                    "candidates": [],
                    "errors": [f"Mapillary returned HTTP {image_response.status_code}: {detail}"],
                    "started_at": start_time,
                    "completed_at": _now(),
                    "notice": "Mapillary credentials rejected. Authentication failed.",
                }
            else:
                error_detail, retry_tiled = _mapillary_error_detail(image_response)
                error_detail = redact_secret(error_detail, token)
                if not retry_tiled:
                    raise HTTPException(
                        status_code=502,
                        detail=f"Mapillary rejected the request (HTTP {image_response.status_code}). Check the access token and API permissions. Provider response: {error_detail}",
                    )
                mid_lon = lon
                mid_lat = lat
                tile_boxes = [
                    f"{west},{south},{mid_lon},{mid_lat}",
                    f"{west},{mid_lat},{mid_lon},{north}",
                    f"{mid_lon},{south},{east},{mid_lat}",
                    f"{mid_lon},{mid_lat},{east},{north}",
                ]
                async def get_tile(tile_bbox):
                    try:
                        response = await client.get(
                            _MAPILLARY_IMAGES_URL,
                            params={**base_params, "bbox": tile_bbox, "limit": "12"},
                            headers=headers,
                        )
                        if response.status_code >= 400:
                            detail, _ = _mapillary_error_detail(response)
                            detail = redact_secret(detail, token)
                            return [], f"Mapillary tile returned HTTP {response.status_code}: {detail}"
                        data = response.json()
                        rows = data.get("data", []) if isinstance(data, dict) else []
                        return (rows if isinstance(rows, list) else []), None
                    except (httpx.HTTPError, ValueError) as exc:
                        return [], f"Mapillary tile unavailable ({type(exc).__name__})"
                tile_results = await asyncio.gather(*(get_tile(tile_bbox) for tile_bbox in tile_boxes))
                deduped_images = {}
                tile_errors = []
                for rows, tile_error in tile_results:
                    if tile_error:
                        tile_errors.append(tile_error)
                    for row in rows:
                        if isinstance(row, dict) and row.get("id"):
                            deduped_images[str(row["id"])] = row
                upstream_images = list(deduped_images.values())
                if not upstream_images and tile_errors:
                    detail = "; ".join(tile_errors[:2])[:260]
                    raise HTTPException(status_code=502, detail=f"Mapillary timed out for the selected area. Try again in a moment or reduce the radius. {detail}")
            if not isinstance(upstream_images, list):
                upstream_images = []

            images = []
            for image in upstream_images:
                if not isinstance(image, dict):
                    continue
                point = _mapillary_image_point(image)
                if not point:
                    continue
                image_lat, image_lon = point
                if _distance_meters(lat, lon, image_lat, image_lon) > radius_m:
                    continue
                thumb = str(image.get("thumb_1024_url") or "")
                if not thumb:
                    continue
                parsed = urlparse(thumb)
                host = (parsed.hostname or "").lower()
                if parsed.scheme != "https" or not host or not any(host.endswith(suffix) for suffix in _ALLOWED_THUMB_HOST_SUFFIXES):
                    continue
                images.append({**image, "_lat": image_lat, "_lon": image_lon, "_thumb": thumb})

            images.sort(key=lambda item: float(item.get("captured_at") or 0), reverse=True)
            # Reduce network/model load by selecting a time-ordered, spatially diverse subset.
            selected = []
            for image in images:
                if all(_distance_meters(image["_lat"], image["_lon"], old["_lat"], old["_lon"]) >= 40 for old in selected):
                    selected.append(image)
                if len(selected) >= _MAX_MAPILLARY_IMAGES_TO_ANALYZE:
                    break

            from app.api.routes import runner as shared_runner
            detector = shared_runner.detector
            model_status = detector.status()
            visual_model_ready = bool(
                model_status.get("pothole_seg_model_loaded") or model_status.get("road_damage_model_loaded")
            )
            candidates: list[dict[str, Any]] = []
            scan_errors: list[str] = []
            images_analyzed = 0  # Images actually passed through CivicRouteAD local inference.
            images_checked_by_mapillary = 0
            mapillary_pothole_detections = 0
            if not visual_model_ready:
                scan_errors.append("CivicRouteAD local pothole/road-damage model is not loaded. Mapillary-native object detections may still be returned; local fallback detections are unavailable.")

            for image_index, image in enumerate(selected):
                image_id = str(image.get("id") or "")
                image_point = (image["_lat"], image["_lon"])
                captured_at = image.get("captured_at")
                try:
                    captured_at = datetime.fromtimestamp(float(captured_at) / 1000.0, timezone.utc).isoformat() if captured_at else None
                except (TypeError, ValueError, OSError):
                    captured_at = None

                # Prefer Mapillary's own trained semantic detections for potholes.
                native_detections = []
                native_detection_query_ok = False
                try:
                    native_response = await client.get(
                        f"https://graph.mapillary.com/{image_id}/detections",
                        params={"access_token": token, "fields": "value,created_at,geometry"},
                        headers=headers,
                    )
                    if native_response.status_code < 400:
                        native_body = native_response.json()
                        native_detections = native_body.get("data", []) if isinstance(native_body, dict) else []
                        if not isinstance(native_detections, list):
                            native_detections = []
                        native_detection_query_ok = True
                        images_checked_by_mapillary += 1
                    else:
                        detail, _ = _mapillary_error_detail(native_response)
                        detail = redact_secret(detail, token)
                        scan_errors.append(f"Mapillary object detections for image {image_id} unavailable (HTTP {native_response.status_code}): {detail}")
                except (httpx.HTTPError, ValueError) as exc:
                    scan_errors.append(f"Mapillary object detections for image {image_id} unavailable ({type(exc).__name__}).")

                native_pothole_count = 0
                for det_index, native_detection in enumerate(native_detections):
                    value = native_detection.get("value") if isinstance(native_detection, dict) else None
                    hazard_info = mapillary_native_to_hazard(value)
                    if not hazard_info:
                        continue
                    hazard_cat, hazard_lbl = hazard_info
                    if hazard_cat == "pothole":
                        native_pothole_count += 1
                        mapillary_pothole_detections += 1
                    if selected_filter not in ("all", hazard_cat):
                        continue
                    candidates.append({
                        "image_id": image_id,
                        "detection_id": f"mapillary-{image_id}-{hazard_cat}-{det_index}",
                        "label": hazard_lbl,
                        "hazard_type": hazard_cat,
                        "lat": image_point[0],
                        "lon": image_point[1],
                        "source": "Mapillary server-side object detection",
                        "image_url": image.get("_thumb"),
                        "image_page_url": f"https://www.mapillary.com/app/?pKey={image_id}",
                        "captured_at": captured_at,
                        "confidence": None,
                        "confidence_is_calibrated": False,
                        "model_source": "mapillary_object_detection",
                        "evidence_note": f"Native class '{value}' returned by Mapillary API (kept distinct from RDD2022 benchmark classes). Coordinates mark source camera position; field verification is required.",
                    })

                # Use the local model for supported non-pothole hazards, and as an
                # explicitly labelled fallback only if the Mapillary detections endpoint failed.
                wants_local_analysis = visual_model_ready and (
                    selected_filter not in ("pothole",) and selected_filter in ("all", "road_crack", "fallen_debris", "waterlogging", "other")
                    or (selected_filter in ("all", "pothole") and not native_detection_query_ok)
                )
                if not wants_local_analysis:
                    continue
                try:
                    thumb_response = await client.get(image["_thumb"])
                    if thumb_response.status_code >= 400:
                        scan_errors.append(f"Street image {image_id}: thumbnail returned HTTP {thumb_response.status_code}.")
                        continue
                    if len(thumb_response.content) > _MAX_THUMBNAIL_BYTES:
                        scan_errors.append(f"Street image {image_id}: thumbnail exceeded the size limit.")
                        continue
                    buffer = np.frombuffer(thumb_response.content, dtype=np.uint8)
                    frame = cv2.imdecode(buffer, cv2.IMREAD_COLOR)
                    if frame is None or frame.size == 0:
                        scan_errors.append(f"Street image {image_id}: thumbnail could not be decoded.")
                        continue
                    detections = await run_in_threadpool(detector.analyze_frame, frame, image_index, float(image_index), "background")
                    images_analyzed += 1
                    for detection_index, detection in enumerate(detections):
                        category = _mapillary_to_hazard_category(detection)
                        if not category:
                            continue
                        category_type, label = category
                        # When Mapillary's own object detection worked, don't allow a
                        # weaker local candidate to overrule an empty native pothole result.
                        if category_type == "pothole" and native_detection_query_ok:
                            continue
                        if selected_filter not in ("all", category_type):
                            continue
                        confidence_value = detection.get("confidence", detection.get("conf"))
                        try:
                            confidence = float(confidence_value) if confidence_value is not None else None
                        except (TypeError, ValueError):
                            confidence = None
                        if confidence is not None and (not math.isfinite(confidence) or not 0 <= confidence <= 1):
                            confidence = None
                        local_is_pothole = category_type == "pothole"
                        candidates.append({
                            "image_id": image_id,
                            "detection_id": f"{image_id}-civicroute-{detection_index}",
                            "label": ("Possible pothole (local model; verify)" if local_is_pothole else label),
                            "hazard_type": category_type,
                            "lat": image_point[0],
                            "lon": image_point[1],
                            "source": f"Mapillary street imagery + local {detection.get('source', 'AI detector')}",
                            "image_url": image.get("_thumb"),
                            "image_page_url": f"https://www.mapillary.com/app/?pKey={image_id}",
                            "captured_at": captured_at,
                            "confidence": confidence,
                            "confidence_is_calibrated": False,
                            "model_source": detection.get("source"),
                            "evidence_note": "Local AI candidate generated from street-image thumbnail. Coordinates identify the camera/image location, not the exact defect location. Capture date may be old; human verification is required.",
                        })
                except HTTPException:
                    raise
                except Exception as exc:
                    print(f"[Infrastructure] Mapillary local inference failed for image {image_id}: {redact_secret(str(exc), token)}")
                    scan_errors.append(f"Street image {image_id}: local AI processing failed.")

    except HTTPException:
        raise
    except httpx.TimeoutException as exc:
        raise HTTPException(status_code=504, detail="Mapillary request timed out. Try a smaller radius or retry later.") from exc
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail="Could not connect to Mapillary. Check internet connectivity and retry.") from exc
    except ValueError as exc:
        raise HTTPException(status_code=502, detail="Mapillary returned an invalid response. Check the access token and API availability.") from exc

    if len(upstream_images) == 0:
        status = "completed_no_coverage"
    elif len(candidates) == 0:
        status = "completed_no_detections"
    else:
        status = "completed_with_candidates"

    return {
        "ok": True,
        "status": status,
        "provider_status": "ready",
        "scan_id": scan_id,
        "center": [lat, lon],
        "selected_category": selected_filter,
        "provider": "Mapillary street imagery + Mapillary object detections + CivicRouteAD local AI fallback",
        "radius_m": radius_m,
        "image_count": len(upstream_images),
        "images_with_valid_location": len(images),
        "images_analyzed": images_analyzed,
        "images_checked_by_mapillary": images_checked_by_mapillary,
        "mapillary_pothole_detections": mapillary_pothole_detections,
        "candidate_count": len(candidates),
        "candidates": candidates,
        "errors": scan_errors[:10],
        "detector": model_status,
        "started_at": start_time,
        "completed_at": _now(),
        "notice": "Candidate coordinates mark the street-imagery camera position. They are not precise ground coordinates for the defect and must be field-verified.",
    }


@router.get("/infrastructure/osm-context")
async def get_openstreetmap_context(lat: float, lon: float, radius_m: float = 1000, category: str = "all"):
    """Backend proxy for Overpass: avoids browser CORS, caches responses, and falls back across mirrors."""
    point = _valid_point(lat, lon)
    if not point:
        raise HTTPException(status_code=400, detail="Center latitude/longitude are invalid.")
    lat, lon = point
    try:
        radius_m = float(radius_m)
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail="Radius must be numeric.") from exc
    if not math.isfinite(radius_m) or not 100 <= radius_m <= 5000:
        raise HTTPException(status_code=400, detail="Radius must be between 100 and 5000 metres.")

    category = str(category or "all").lower().strip()
    cache_key = f"{round(lat, 3)}:{round(lon, 3)}:{int(radius_m)}:{category}"
    now_ts = datetime.now(timezone.utc).timestamp()
    if cache_key in _OSM_CACHE:
        cached_ts, cached_val = _OSM_CACHE[cache_key]
        if now_ts - cached_ts < _OSM_CACHE_TTL_SEC:
            return {**cached_val, "from_cache": True}
        del _OSM_CACHE[cache_key]

    q_radius = int(round(radius_m))
    if category in ("pothole", "road_crack"):
        clauses = (
            f"way(around:{q_radius},{lat},{lon})[\"highway\"][\"smoothness\"~\"^(bad|very_bad|horrible|impassable)$\"];"
            f"way(around:{q_radius},{lat},{lon})[\"surface\"~\"^(gravel|ground|unpaved|compacted)$\"];"
        )
    elif category == "waterlogging":
        clauses = f"nwr(around:{q_radius},{lat},{lon})[\"hazard\"=\"flood\"];"
    elif category == "fallen_debris":
        clauses = f"nwr(around:{q_radius},{lat},{lon})[\"hazard\"~\"^(landslide|rockfall)$\"];"
    elif category == "damaged_infrastructure":
        clauses = f"way(around:{q_radius},{lat},{lon})[\"highway\"=\"construction\"];"
    else:
        clauses = (
            f"way(around:{q_radius},{lat},{lon})[\"highway\"][\"smoothness\"~\"^(bad|very_bad|horrible|impassable)$\"];"
            f"way(around:{q_radius},{lat},{lon})[\"highway\"=\"construction\"];"
            f"nwr(around:{q_radius},{lat},{lon})[\"hazard\"~\"^(flood|landslide|rockfall)$\"];"
            f"way(around:{q_radius},{lat},{lon})[\"surface\"~\"^(gravel|ground|unpaved)$\"];"
        )
    query = f"[out:json][timeout:10];({clauses});out center tags;"

    errors = []
    timeout = httpx.Timeout(connect=3.5, read=10.0, write=5.0, pool=3.5)
    async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
        for endpoint in _OVERPASS_URLS:
            try:
                response = await client.post(
                    endpoint,
                    data={"data": query},
                    headers={"User-Agent": "CivicRouteAD/1.0 (local infrastructure research)"},
                )
                if response.status_code >= 400:
                    errors.append(f"{endpoint.split('/')[2]} returned HTTP {response.status_code}")
                    continue
                body = response.json()
                items = []
                seen_ids = set()
                for element in body.get("elements", []) if isinstance(body, dict) else []:
                    if not isinstance(element, dict):
                        continue
                    center_point = element.get("center") if isinstance(element.get("center"), dict) else {}
                    point = _valid_point(element.get("lat", center_point.get("lat")), element.get("lon", center_point.get("lon")))
                    if not point:
                        continue
                    item_lat, item_lon = point
                    if _distance_meters(lat, lon, item_lat, item_lon) > radius_m:
                        continue
                    feat_id = f"osm-{element.get('type')}-{element.get('id')}"
                    if feat_id in seen_ids:
                        continue
                    seen_ids.add(feat_id)

                    tags = element.get("tags") if isinstance(element.get("tags"), dict) else {}
                    label, kind = "Mapped road context", "road_context"
                    if tags.get("hazard") == "flood":
                        label, kind = "Mapped flood-hazard tag", "mapped_flood_hazard"
                    elif tags.get("hazard") in {"landslide", "rockfall"}:
                        label, kind = "Mapped landslide / rockfall hazard", "mapped_slope_hazard"
                    elif tags.get("smoothness"):
                        label, kind = f"Mapped poor road smoothness: {tags['smoothness']}", "mapped_road_condition"
                    elif tags.get("highway") == "construction":
                        label, kind = "Mapped road construction", "road_work_context"
                    elif tags.get("surface"):
                        label, kind = f"Mapped surface: {tags['surface']}", "mapped_road_surface"
                    items.append({
                        "id": feat_id,
                        "lat": item_lat,
                        "lon": item_lon,
                        "label": label,
                        "kind": kind,
                        "tags": tags,
                        "source": "OpenStreetMap mapped context"
                    })
                result_payload = {
                    "ok": True,
                    "status": "ready",
                    "count": len(items),
                    "items": items[:500],
                    "provider": endpoint.split("/")[2],
                    "warnings": errors,
                    "from_cache": False,
                }
                _OSM_CACHE[cache_key] = (now_ts, result_payload)
                return result_payload
            except (httpx.HTTPError, ValueError) as exc:
                errors.append(f"{endpoint.split('/')[2]} unavailable ({type(exc).__name__})")
        return {
            "ok": False,
            "status": "temporarily_unavailable",
            "count": 0,
            "items": [],
            "provider": None,
            "warnings": errors,
            "detail": "OpenStreetMap context is temporarily unavailable. Map and other dashboard features remain usable.",
            "can_retry": True,
        }

