"""
CivicRouteAD - Standard RFC 7946 GeoJSON Builder
Generates feature collections combining hazard points, inspection trajectory LineStrings,
and road condition rating segments for Leaflet / MapLibre dashboards and GIS exports.
"""

from datetime import datetime, timezone
from typing import List, Dict, Any
from app.ai.hazard_classes import HAZARD_DEFINITIONS


def build_geojson_feature_collection(
    hazards: List[Dict[str, Any]],
    trajectory_coords: List[List[float]],
    metadata: Dict[str, Any]
) -> Dict[str, Any]:
    """
    Constructs an RFC 7946 compliant GeoJSON FeatureCollection containing
    hazard vector points and the road survey path LineString.
    All coordinate geometries are strictly in [longitude, latitude, elevation] order.
    """
    features: List[Dict[str, Any]] = []

    # 1. Road Inspection Trajectory LineString
    if trajectory_coords and len(trajectory_coords) >= 2:
        trajectory_feature = {
            "type": "Feature",
            "id": "survey-trajectory",
            "geometry": {
                "type": "LineString",
                "coordinates": trajectory_coords  # [[lon, lat, ele], ...]
            },
            "properties": {
                "feature_class": "survey_trajectory",
                "name": "Vehicle Dashcam Survey Route",
                "total_distance_m": metadata.get("total_distance_m", 0.0),
                "duration_sec": metadata.get("duration_sec", 0.0),
                "avg_speed_kmh": metadata.get("avg_speed_kmh", 0.0),
                "points_count": len(trajectory_coords),
                "is_synthetic": metadata.get("is_synthetic", False),
                "data_classification": metadata.get("data_classification", "USER_UPLOADED_UNVERIFIED")
            }
        }
        features.append(trajectory_feature)

    # 2. Hazard Point Features
    severity_counts = {"Critical": 0, "High": 0, "Medium": 0, "Low": 0}

    for haz in hazards:
        sev = haz.get("severity", "Medium")
        severity_counts[sev] = severity_counts.get(sev, 0) + 1
        h_type = haz.get("type", "pothole_damage")
        h_def = HAZARD_DEFINITIONS.get(h_type, {})

        lat = haz.get("lat")
        lon = haz.get("lon")
        has_valid_location = (
            isinstance(lat, (int, float)) and isinstance(lon, (int, float))
            and -90 <= lat <= 90 and -180 <= lon <= 180
        )
        point_feature = {
            "type": "Feature",
            "id": haz.get("id"),
            # GeoJSON permits null geometry; use it for unlocated detections rather than
            # publishing clamped GPS coordinates as if they represented the hazard.
            "geometry": ({
                "type": "Point",
                "coordinates": [lon, lat]  # [longitude, latitude] per RFC 7946
            } if has_valid_location else None),
            "properties": {
                "feature_class": "road_hazard",
                "hazard_id": haz.get("id"),
                "hazard_type": h_type,
                "label": haz.get("label") or h_def.get("label", h_type.replace("_", " ").title()),
                "class_code": haz.get("class_code"),
                "severity": sev,
                "confidence": haz.get("confidence", 0.8),
                "verification": haz.get("verification", "provisional_heuristic"),
                "detection_source": haz.get("source", "cv_surface_analyzer"),
                "location_quality": haz.get("location_quality", "approximate_camera_projection_unvalidated"),
                "estimated_uncertainty_m": haz.get("estimated_uncertainty_m"),
                "forward_distance_m": haz.get("forward_distance_m", 0.0),
                "lateral_offset_m": haz.get("lateral_offset_m", 0.0),
                "lane_location": haz.get("lane_location", "Center Traveled Lane"),
                "timestamp_sec": haz.get("timestamp_sec", 0.0),
                "gps_timestamp": haz.get("gps_timestamp", ""),
                "frame_idx": haz.get("frame_idx", 0),
                "snapshot_url": haz.get("snapshot_url", ""),
                "suggested_action": h_def.get("action", "Inspect roadway condition."),
                "department": h_def.get("department", "Public Works Department"),
                "marker_color": h_def.get("color", "#ef4444"),
                "is_synthetic": metadata.get("is_synthetic", False),
                "data_classification": metadata.get("data_classification", "USER_UPLOADED_UNVERIFIED")
            }
        }
        features.append(point_feature)

    collection = {
        "type": "FeatureCollection",
        "metadata": {
            "system": "CivicRouteAD - Edge-to-GIS Hazard Pipeline",
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "run_id": metadata.get("run_id", "default"),
            "is_synthetic": metadata.get("is_synthetic", False),
            "data_classification": metadata.get("data_classification") or (
                "SYNTHETIC_BENCHMARK_FIXTURE" if metadata.get("is_synthetic", False) else "USER_UPLOADED_UNVERIFIED"
            ),
            "total_hazards": len(hazards),
            "severity_summary": severity_counts,
            "route_distance_km": round(metadata.get("total_distance_m", 0.0) / 1000.0, 3),
            "coverage_ratio": metadata.get("coverage_ratio", 1.0),
            "warnings": metadata.get("warnings", []),
            "geolocation_notice": metadata.get("geolocation_notice", "Camera-projected hazard positions are approximate and not independently calibrated.")
        },
        "features": features
    }

    return collection
