"""
CivicRouteAD - GPS Trajectory Parser & Temporal Interpolator
Parses GPX and CSV trajectory logs, validates geographic coordinates,
calculates forward vehicle bearings/headings, speeds, checks coverage,
and performs high-precision temporal interpolation for any frame timestamp.
"""

import math
import csv
from datetime import datetime, timezone
from typing import List, Dict, Any, Optional, Tuple
import xml.etree.ElementTree as ET
try:
    import gpxpy
except ImportError:  # Video-only pothole analysis does not require GPX support.
    gpxpy = None


def validate_coordinate(lat: float, lon: float) -> Tuple[bool, str]:
    """Validates that latitude is within [-90, 90] and longitude within [-180, 180]."""
    if not isinstance(lat, (int, float)) or math.isnan(lat) or math.isinf(lat):
        return False, f"Invalid latitude value: {lat}"
    if not isinstance(lon, (int, float)) or math.isnan(lon) or math.isinf(lon):
        return False, f"Invalid longitude value: {lon}"
    if not (-90.0 <= lat <= 90.0):
        return False, f"Latitude {lat} out of valid range [-90.0, 90.0]"
    if not (-180.0 <= lon <= 180.0):
        return False, f"Longitude {lon} out of valid range [-180.0, 180.0]"
    return True, ""


def calculate_bearing(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Calculates forward initial bearing (heading) in degrees from point 1 to point 2."""
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    delta_lambda = math.radians(lon2 - lon1)

    y = math.sin(delta_lambda) * math.cos(phi2)
    x = math.cos(phi1) * math.sin(phi2) - math.sin(phi1) * math.cos(phi2) * math.cos(delta_lambda)
    bearing_rad = math.atan2(y, x)
    bearing_deg = (math.degrees(bearing_rad) + 360.0) % 360.0
    return bearing_deg


def haversine_distance(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Calculates great-circle distance in meters between two lat/lon coordinates."""
    r = 6371000.0  # Earth radius in meters
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)

    a = math.sin(dphi / 2.0) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2.0) ** 2
    c = 2.0 * math.atan2(math.sqrt(a), math.sqrt(1.0 - a))
    return r * c


class TrajectoryPoint:
    def __init__(
        self,
        time_sec: float,
        lat: float,
        lon: float,
        ele: float = 0.0,
        speed_kmh: float = 0.0,
        heading_deg: float = 0.0,
        iso_time: str = "",
        is_in_coverage: bool = True
    ):
        self.time_sec = time_sec
        self.lat = lat
        self.lon = lon
        self.ele = ele
        self.speed_kmh = speed_kmh
        self.heading_deg = heading_deg
        self.iso_time = iso_time
        self.is_in_coverage = is_in_coverage


class GPSTrajectory:
    def __init__(self, raw_points: List[TrajectoryPoint]):
        if not raw_points:
            raise ValueError("No GPS trajectory points provided.")

        # 1. Validate coordinates & filter invalid readings
        valid_points = []
        for p in raw_points:
            ok, err = validate_coordinate(p.lat, p.lon)
            if ok:
                valid_points.append(p)
            else:
                print(f"[GPSParser] Dropping invalid point at t={p.time_sec}: {err}")

        if len(valid_points) < 2:
            raise ValueError(
                f"Insufficient valid GPS points ({len(valid_points)} found). "
                "At least 2 valid points within [-90,90] lat and [-180,180] lon are required."
            )

        # 2. Sort by time_sec and deduplicate identical timestamps
        valid_points.sort(key=lambda p: p.time_sec)
        deduped: List[TrajectoryPoint] = []
        for p in valid_points:
            if not deduped:
                deduped.append(p)
            elif abs(p.time_sec - deduped[-1].time_sec) > 1e-4:
                deduped.append(p)
            else:
                # Same timestamp: update with latest reading
                deduped[-1] = p

        self.points = deduped
        self._calculate_kinematics()

    def _calculate_kinematics(self):
        """Calculates distance, headings, and speeds along consecutive points."""
        total_dist = 0.0
        for i in range(len(self.points)):
            if i < len(self.points) - 1:
                p1 = self.points[i]
                p2 = self.points[i + 1]
                dist = haversine_distance(p1.lat, p1.lon, p2.lat, p2.lon)
                dt = max(1e-4, p2.time_sec - p1.time_sec)
                calc_speed_kmh = (dist / dt) * 3.6
                calc_heading = calculate_bearing(p1.lat, p1.lon, p2.lat, p2.lon)

                if p1.heading_deg == 0.0 and dist > 0.3:
                    p1.heading_deg = calc_heading
                if p1.speed_kmh == 0.0:
                    p1.speed_kmh = calc_speed_kmh
                total_dist += dist
            else:
                if i > 0:
                    self.points[i].heading_deg = self.points[i - 1].heading_deg
                    self.points[i].speed_kmh = self.points[i - 1].speed_kmh

        self.total_distance_m = total_dist
        self.duration_sec = self.points[-1].time_sec - self.points[0].time_sec if self.points else 0.0
        self.start_time_sec = self.points[0].time_sec
        self.end_time_sec = self.points[-1].time_sec

    def check_coverage(self, video_duration_sec: float, time_offset_sec: float = 0.0) -> Dict[str, Any]:
        """
        Validates trajectory temporal coverage against the video duration.
        Detects coverage gaps, starts/ends out of bounds, and returns warnings.
        """
        video_start = time_offset_sec
        video_end = video_duration_sec + time_offset_sec

        warnings: List[str] = []
        gaps: List[Dict[str, float]] = []

        # Check start mismatch
        if video_start < self.start_time_sec - 1.0:
            diff = self.start_time_sec - video_start
            warnings.append(
                f"Video begins {diff:.1f}s before first GPS waypoint. "
                "Early detections will lack reliable GPS positioning."
            )

        # Check end mismatch
        if video_end > self.end_time_sec + 1.0:
            diff = video_end - self.end_time_sec
            warnings.append(
                f"Video extends {diff:.1f}s beyond final GPS waypoint. "
                "Trailing frames will be outside GPS coverage."
            )

        # Check internal signal gaps (> 6 seconds between consecutive fixes)
        for i in range(len(self.points) - 1):
            dt = self.points[i + 1].time_sec - self.points[i].time_sec
            if dt > 6.0:
                gaps.append({
                    "start_sec": self.points[i].time_sec,
                    "end_sec": self.points[i + 1].time_sec,
                    "gap_duration_sec": round(dt, 2)
                })

        if gaps:
            warnings.append(f"Detected {len(gaps)} GPS signal gap(s) exceeding 6s.")

        overlap_start = max(video_start, self.start_time_sec)
        overlap_end = min(video_end, self.end_time_sec)
        overlap_dur = max(0.0, overlap_end - overlap_start)
        coverage_ratio = (overlap_dur / video_duration_sec) if video_duration_sec > 0 else 1.0

        return {
            "is_valid": len(self.points) >= 2,
            "coverage_ratio": round(min(1.0, coverage_ratio), 3),
            "video_duration_sec": video_duration_sec,
            "gps_duration_sec": round(self.duration_sec, 2),
            "time_offset_sec": time_offset_sec,
            "gaps": gaps,
            "warnings": warnings
        }

    def get_state_at_time(self, t: float, time_offset_sec: float = 0.0) -> TrajectoryPoint:
        """
        Interpolates vehicle position, heading, and speed at any relative video timestamp t.
        Marks point as is_in_coverage=False if t falls outside the valid GPS trajectory.
        """
        eff_t = t + time_offset_sec

        if not self.points:
            return TrajectoryPoint(t, 0.0, 0.0, is_in_coverage=False)

        # Out-of-bounds checks
        if eff_t < self.points[0].time_sec:
            # Clamp to first point, but flag as out of coverage
            p = self.points[0]
            return TrajectoryPoint(
                time_sec=t,
                lat=p.lat,
                lon=p.lon,
                ele=p.ele,
                speed_kmh=0.0,
                heading_deg=p.heading_deg,
                iso_time=p.iso_time,
                is_in_coverage=False
            )

        if eff_t > self.points[-1].time_sec:
            p = self.points[-1]
            return TrajectoryPoint(
                time_sec=t,
                lat=p.lat,
                lon=p.lon,
                ele=p.ele,
                speed_kmh=0.0,
                heading_deg=p.heading_deg,
                iso_time=p.iso_time,
                is_in_coverage=False
            )

        # Binary search for bracket points
        low = 0
        high = len(self.points) - 1
        while low <= high:
            mid = (low + high) // 2
            if self.points[mid].time_sec <= eff_t:
                low = mid + 1
            else:
                high = mid - 1

        idx = max(0, high)
        p1 = self.points[idx]
        p2 = self.points[min(idx + 1, len(self.points) - 1)]

        dt = p2.time_sec - p1.time_sec
        if dt <= 1e-6:
            return TrajectoryPoint(
                time_sec=t,
                lat=p1.lat,
                lon=p1.lon,
                ele=p1.ele,
                speed_kmh=p1.speed_kmh,
                heading_deg=p1.heading_deg,
                iso_time=p1.iso_time,
                is_in_coverage=True
            )

        alpha = (eff_t - p1.time_sec) / dt

        # Linear interpolation for lat, lon, elevation, speed
        interp_lat = p1.lat + alpha * (p2.lat - p1.lat)
        interp_lon = p1.lon + alpha * (p2.lon - p1.lon)
        interp_ele = p1.ele + alpha * (p2.ele - p1.ele)
        interp_speed = p1.speed_kmh + alpha * (p2.speed_kmh - p1.speed_kmh)

        # Circular interpolation for heading
        diff_angle = (p2.heading_deg - p1.heading_deg + 180.0) % 360.0 - 180.0
        interp_heading = (p1.heading_deg + alpha * diff_angle + 360.0) % 360.0

        return TrajectoryPoint(
            time_sec=t,
            lat=round(interp_lat, 7),
            lon=round(interp_lon, 7),
            ele=round(interp_ele, 1),
            speed_kmh=round(interp_speed, 1),
            heading_deg=round(interp_heading, 1),
            iso_time=p1.iso_time,
            is_in_coverage=True
        )

    def to_coordinates_list(self) -> List[List[float]]:
        """Returns [[lon, lat, ele], ...] in RFC 7946 longitude-first order."""
        return [[round(p.lon, 7), round(p.lat, 7), round(p.ele, 1)] for p in self.points]


def _parse_gpx_with_standard_library(file_path: str) -> List[TrajectoryPoint]:
    """Parse standard GPX 1.0/1.1 track points without third-party packages."""
    try:
        root = ET.parse(file_path).getroot()
    except Exception as exc:
        raise ValueError(f"Failed to parse GPX XML content: {exc}")

    parsed = []
    for elem in root.iter():
        if elem.tag.rsplit("}", 1)[-1].lower() != "trkpt":
            continue
        try:
            lat = float(elem.attrib.get("lat", "nan"))
            lon = float(elem.attrib.get("lon", "nan"))
        except (TypeError, ValueError):
            continue

        children = {child.tag.rsplit("}", 1)[-1].lower(): (child.text or "").strip() for child in list(elem)}
        time_text = children.get("time", "")
        parsed_time = None
        if time_text:
            try:
                normalized = time_text[:-1] + "+00:00" if time_text.endswith(("Z", "z")) else time_text
                parsed_time = datetime.fromisoformat(normalized)
                if parsed_time.tzinfo is None:
                    parsed_time = parsed_time.replace(tzinfo=timezone.utc)
            except ValueError:
                parsed_time = None
        try:
            ele = float(children.get("ele") or 0.0)
        except ValueError:
            ele = 0.0
        try:
            # GPX <speed> is metres/second. Convert to the parser's km/h unit.
            speed_kmh = float(children.get("speed") or 0.0) * 3.6
        except ValueError:
            speed_kmh = 0.0
        parsed.append((parsed_time, lat, lon, ele, speed_kmh, time_text))

    if not parsed:
        return []
    start_epoch = next((item[0].timestamp() for item in parsed if item[0] is not None), None)
    points = []
    for index, (point_time, lat, lon, ele, speed_kmh, time_text) in enumerate(parsed):
        if point_time is not None and start_epoch is not None:
            rel_sec = point_time.timestamp() - start_epoch
            iso_time = point_time.isoformat()
        else:
            rel_sec = float(index)  # Best-effort 1Hz fallback for missing timestamps.
            iso_time = time_text
        points.append(TrajectoryPoint(
            time_sec=rel_sec,
            lat=lat,
            lon=lon,
            ele=ele,
            speed_kmh=speed_kmh,
            iso_time=iso_time,
        ))
    return points


def parse_gpx_file(file_path: str) -> GPSTrajectory:
    """Parse GPX with gpxpy when installed, or standard XML as a robust fallback."""
    points: List[TrajectoryPoint] = []
    if gpxpy is None:
        points = _parse_gpx_with_standard_library(file_path)
    else:
        try:
            with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
                gpx = gpxpy.parse(f)
        except Exception as e:
            raise ValueError(f"Failed to parse GPX XML content: {e}")

        start_datetime = None
        for track in gpx.tracks:
            for segment in track.segments:
                for pt in segment.points:
                    if start_datetime is None and pt.time:
                        start_datetime = pt.time

                    if pt.time and start_datetime:
                        rel_sec = (pt.time - start_datetime).total_seconds()
                        iso_time = pt.time.isoformat()
                    else:
                        rel_sec = float(len(points))  # Fallback to 1Hz
                        iso_time = ""

                    points.append(TrajectoryPoint(
                        time_sec=rel_sec,
                        lat=pt.latitude,
                        lon=pt.longitude,
                        ele=pt.elevation or 0.0,
                        speed_kmh=(pt.speed * 3.6) if pt.speed else 0.0,
                        iso_time=iso_time
                    ))

    if not points:
        raise ValueError(f"No valid track points found in GPX file: {file_path}")
    return GPSTrajectory(points)


def parse_csv_trajectory(file_path: str) -> GPSTrajectory:
    """
    Parses a CSV trajectory file with auto-detected headers.
    Supports columns: time/timestamp, lat/latitude, lon/longitude, speed, heading/bearing, ele/elevation.
    """
    points: List[TrajectoryPoint] = []
    try:
        with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
            reader = csv.DictReader(f)
            if not reader.fieldnames:
                raise ValueError("CSV file has no headers.")

            start_time = None
            for row in reader:
                # Normalize keys
                row_lower = {k.strip().lower(): v.strip() for k, v in row.items() if k}

                # Try parsing lat & lon
                raw_lat = row_lower.get("lat") or row_lower.get("latitude")
                raw_lon = row_lower.get("lon") or row_lower.get("longitude") or row_lower.get("lng")

                if not raw_lat or not raw_lon:
                    continue

                try:
                    lat = float(raw_lat)
                    lon = float(raw_lon)
                except ValueError:
                    continue

                ele = float(row_lower.get("ele") or row_lower.get("elevation") or row_lower.get("alt") or 0.0)
                speed = float(row_lower.get("speed") or row_lower.get("speed_kmh") or 0.0)
                heading = float(row_lower.get("heading") or row_lower.get("bearing") or 0.0)

                raw_time = row_lower.get("timestamp") or row_lower.get("time") or row_lower.get("t")
                iso_time = ""
                rel_sec = 0.0

                if raw_time:
                    try:
                        val = float(raw_time)
                        if start_time is None:
                            start_time = val
                        rel_sec = val - start_time
                    except ValueError:
                        try:
                            dt = datetime.fromisoformat(raw_time.replace("Z", "+00:00"))
                            if start_time is None:
                                start_time = dt
                            rel_sec = (dt - start_time).total_seconds()
                            iso_time = dt.isoformat()
                        except Exception:
                            rel_sec = float(len(points))
                else:
                    rel_sec = float(len(points))

                points.append(TrajectoryPoint(
                    time_sec=rel_sec,
                    lat=lat,
                    lon=lon,
                    ele=ele,
                    speed_kmh=speed,
                    heading_deg=heading,
                    iso_time=iso_time
                ))
    except Exception as e:
        raise ValueError(f"Failed to read CSV trajectory: {e}")

    if not points:
        raise ValueError(
            f"No valid coordinate rows found in CSV: {file_path}. "
            "Ensure CSV includes headers 'lat' (or 'latitude') and 'lon' (or 'longitude')."
        )

    return GPSTrajectory(points)
