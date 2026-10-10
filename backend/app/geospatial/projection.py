"""
CivicRouteAD - Camera Pinhole to Geodetic Ground Projection Engine
Projects pixel detections (bounding boxes) into real-world geographic coordinates (lat/lon)
using pinhole road-plane photogrammetry, vehicle heading, and direct spherical geodesics.
Provides explicit uncertainty estimates and location quality flags.
"""

import math
from typing import Dict, Any, Tuple, List, Optional


class CameraGeometry:
    def __init__(
        self,
        camera_height_m: float = 1.4,
        camera_pitch_deg: float = 2.0,
        fov_horizontal_deg: float = 70.0,
        fov_vertical_deg: float = 45.0
    ):
        self.h_cam = camera_height_m
        self.pitch_rad = math.radians(camera_pitch_deg)
        self.fov_h_rad = math.radians(fov_horizontal_deg)
        self.fov_v_rad = math.radians(fov_vertical_deg)

    def project_pixel_to_ground(
        self,
        bbox: List[int],
        frame_width: int,
        frame_height: int
    ) -> Tuple[float, float]:
        """
        Calculates forward ground distance and lateral lane offset from camera.
        Returns: (d_forward_m, d_lateral_m)
        """
        x1, y1, x2, y2 = bbox
        cx = frame_width / 2.0
        cy = frame_height / 2.0

        # Focal lengths in pixels
        fx = cx / math.tan(self.fov_h_rad / 2.0)
        fy = cy / math.tan(self.fov_v_rad / 2.0)

        # Contact point with road surface: bottom center of bounding box
        u_bottom = (x1 + x2) / 2.0
        v_bottom = y2

        # Vertical ray angle relative to optical axis
        ray_pitch = math.atan((v_bottom - cy) / fy)

        # Total depression angle below horizon
        total_depression = self.pitch_rad + ray_pitch

        # Clamp depression angle to prevent division by zero or negative angles
        min_angle = math.radians(0.8)
        if total_depression < min_angle:
            total_depression = min_angle

        # Forward distance on road plane
        d_forward = self.h_cam / math.tan(total_depression)
        # Clamped to realistic dashcam sensor sightline (1.5m to 85m)
        d_forward = max(1.5, min(85.0, d_forward))

        # Horizontal ray angle
        ray_yaw = math.atan((u_bottom - cx) / fx)
        d_lateral = d_forward * math.tan(ray_yaw)

        return round(d_forward, 2), round(d_lateral, 2)


def direct_geodesic_project(
    lat_vehicle: float,
    lon_vehicle: float,
    heading_deg: float,
    d_forward_m: float,
    d_lateral_m: float,
    vehicle_speed_kmh: float = 20.0,
    is_in_coverage: bool = True
) -> Tuple[float, float, str, Optional[float]]:
    """
    Computes real-world target (lat, lon) given vehicle position, heading,
    forward distance, and lateral offset using Great-Circle geodesic formula.

    Returns:
        (lat_target, lon_target, location_quality, estimated_uncertainty_m).
        Uncertainty is None because the default camera parameters are assumptions,
        not a calibrated error model. Do not present a numeric accuracy guarantee.
    """
    if not is_in_coverage or lat_vehicle == 0.0 or lon_vehicle == 0.0:
        return round(lat_vehicle, 7), round(lon_vehicle, 7), "unanchored_out_of_gps_coverage", None

    r_earth = 6371000.0  # Earth radius in meters

    # Total ground distance and relative azimuth
    dist_ground = math.hypot(d_forward_m, d_lateral_m)
    rel_azimuth_deg = math.degrees(math.atan2(d_lateral_m, d_forward_m))
    target_bearing_deg = (heading_deg + rel_azimuth_deg + 360.0) % 360.0

    phi1 = math.radians(lat_vehicle)
    lam1 = math.radians(lon_vehicle)
    bearing_rad = math.radians(target_bearing_deg)
    delta = dist_ground / r_earth

    sin_phi1 = math.sin(phi1)
    cos_phi1 = math.cos(phi1)
    sin_delta = math.sin(delta)
    cos_delta = math.cos(delta)

    phi2 = math.asin(sin_phi1 * cos_delta + cos_phi1 * sin_delta * math.cos(bearing_rad))
    lam2 = lam1 + math.atan2(
        math.sin(bearing_rad) * sin_delta * cos_phi1,
        cos_delta - sin_phi1 * math.sin(phi2)
    )

    lat_target = math.degrees(phi2)
    lon_target = math.degrees(lam2)

    # The camera height, pitch, FOV, object contact point and heading are not
    # calibrated against ground-truth in this prototype. A fabricated +/- metre
    # value would imply precision that has not been measured, so leave numeric
    # uncertainty unset and describe the projected position as approximate.
    heading_reliable = vehicle_speed_kmh >= 2.0
    if not heading_reliable:
        quality = "approximate_low_speed_heading_unvalidated"
    else:
        quality = "approximate_camera_projection_unvalidated"

    return round(lat_target, 7), round(lon_target, 7), quality, None


def estimate_lane_location(lateral_offset_m: float) -> str:
    """Classifies lateral position on the roadway."""
    if lateral_offset_m < -2.2:
        return "Left Shoulder / Verge"
    elif -2.2 <= lateral_offset_m < -0.7:
        return "Left Lane"
    elif -0.7 <= lateral_offset_m <= 0.7:
        return "Center Traveled Lane"
    elif 0.7 < lateral_offset_m <= 2.2:
        return "Right Lane"
    else:
        return "Right Shoulder / Verge"
