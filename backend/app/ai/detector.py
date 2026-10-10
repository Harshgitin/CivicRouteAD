"""
CivicRouteAD - Road Hazard Detection & Tracking Engine
Integrates YOLOv8 object detection with Computer Vision Road Surface Analysis
for potholes, fallen debris, localized flooding, and structural blockages.
Includes temporal tracking to deduplicate hazards across consecutive frames.
"""

import os
import threading
import cv2
import numpy as np
from typing import List, Dict, Any, Tuple, Optional
from app.ai.hazard_classes import HAZARD_DEFINITIONS, compute_severity

try:
    from ultralytics import YOLO
    YOLO_AVAILABLE = True
except ImportError:
    YOLO_AVAILABLE = False


class RoadHazardDetector:
    """Local road-hazard detector with a road-damage-specific model when installed.

    The RDD2022 model is specialized for pavement defects (D00/D10/D20/D40).
    The bundled COCO model remains a secondary detector for other visible hazards.
    If the specialized weights are unavailable, the application still works using
    the bundled detector plus clearly labelled, low-confidence CV heuristics.
    """

    def __init__(
        self,
        model_path: Optional[str] = "yolov8n.pt",
        confidence_threshold: float = 0.30,
        road_damage_model_path: Optional[str] = None,
    ):
        from pathlib import Path

        self.conf_threshold = float(confidence_threshold)
        # Live video requests share these model weights with the offline GIS job.
        # Ultralytics predictors are not thread-safe, so serialize inference while
        # prioritizing interactive playback frames over queued background frames.
        self._inference_condition = threading.Condition(threading.RLock())
        self._inference_busy = False
        self._pending_live_inferences = 0
        self._last_general_second = None
        # Slightly lower confidence improves recall for small/distant D40 potholes
        # in forward-facing dashcam frames. The UI labels confidence explicitly so
        # these predictions are not presented as verified ground truth.
        # Confidence is model- and class-specific. The segmentation model gets a
        # conservative floor; RDD crack candidates use a lower threshold than D40
        # potholes because their score distributions differ. All thresholds can be
        # tuned locally without editing source code.
        self.pothole_seg_conf_threshold = float(os.getenv("POTHOLE_SEG_CONF", "0.35"))
        self.rdd_pothole_conf_threshold = float(os.getenv("RDD_POTHOLE_CONF", "0.28"))
        self.rdd_crack_conf_threshold = float(os.getenv("RDD_CRACK_CONF", "0.20"))
        self.model = None
        self.road_damage_model = None
        self.pothole_seg_model = None
        self.general_model_name = None
        self.road_damage_model_name = None
        self.pothole_seg_model_name = None
        self.model_load_warnings = []
        backend_dir = Path(__file__).resolve().parents[2]

        if not YOLO_AVAILABLE:
            self.model_load_warnings.append("ultralytics is not installed; AI model inference is unavailable")
            return

        # Resolve bundled relative weights against backend/ rather than process CWD.
        if model_path:
            supplied = Path(model_path)
            candidate = supplied if supplied.is_absolute() else backend_dir / supplied
            general_path = candidate if candidate.is_file() else supplied
        else:
            general_path = None

        if general_path:
            try:
                self.model = YOLO(str(general_path))
                self.general_model_name = str(general_path)
            except Exception as exc:
                self.model_load_warnings.append(f"General model could not load: {exc}")
                print(f"[Detector] Warning: could not load general model {general_path}: {exc}")

        if road_damage_model_path:
            road_path = Path(road_damage_model_path)
        else:
            road_path = backend_dir / "models" / "yolov8s_best.pt"
        if not road_path.is_absolute():
            road_path = backend_dir / road_path

        if road_path.is_file():
            try:
                self.road_damage_model = YOLO(str(road_path))
                self.road_damage_model_name = str(road_path)
                print(f"[Detector] Road-damage-specific RDD2022 weights loaded: {road_path}")
            except Exception as exc:
                self.model_load_warnings.append(f"RDD2022 model could not load: {exc}")
                print(f"[Detector] Warning: could not load RDD2022 model {road_path}: {exc}")
        else:
            self.model_load_warnings.append(
                "RDD2022 road-damage weights are not installed; using general YOLO plus CV fallback"
            )

        # Optional single-purpose instance segmentation weights. No model is
        # fabricated or downloaded from an unverified URL: provide the reviewed
        # checkpoint at backend/models/pothole_seg.pt or set the environment path.
        configured_seg_path = os.getenv("CIVICROUTE_POTHOLE_SEG_MODEL", "").strip()
        seg_candidates = []
        if configured_seg_path:
            configured = Path(configured_seg_path).expanduser()
            seg_candidates.append(configured if configured.is_absolute() else backend_dir / configured)
        seg_candidates.extend([backend_dir / "models" / "pothole_seg.pt", backend_dir / "pothole_seg.pt"])
        seg_path = next((candidate for candidate in seg_candidates if candidate.is_file()), None)
        if seg_path:
            try:
                self.pothole_seg_model = YOLO(str(seg_path))
                self.pothole_seg_model_name = str(seg_path)
                print(f"[Detector] Dedicated pothole segmentation weights loaded: {seg_path}")
            except Exception as exc:
                self.model_load_warnings.append(f"Pothole segmentation model could not load: {exc}")
                print(f"[Detector] Warning: pothole segmentation model could not load {seg_path}: {exc}")
        else:
            self.model_load_warnings.append(
                "Dedicated pothole segmentation weights not found; add backend/models/pothole_seg.pt to enable instance masks"
            )

    def reset_general_model_cadence(self) -> None:
        """Reset the supplementary model's per-second limiter for a new clip."""
        with self._inference_condition:
            self._last_general_second = None

    def status(self) -> Dict[str, Any]:
        """Safe runtime diagnostics for the Analysis Lab and /api/health."""
        loaded = []
        if self.pothole_seg_model is not None:
            loaded.append("Pothole Segmentation")
        if self.road_damage_model is not None:
            loaded.append("RDD2022")
        if self.model is not None:
            loaded.append("YOLO")
        loaded.append("OpenCV candidate fallback")
        return {
            "ultralytics_available": YOLO_AVAILABLE,
            "general_model_loaded": self.model is not None,
            "general_model": os.path.basename(self.general_model_name) if self.general_model_name else None,
            "road_damage_model_loaded": self.road_damage_model is not None,
            "road_damage_model": os.path.basename(self.road_damage_model_name) if self.road_damage_model_name else None,
            "pothole_seg_model_loaded": self.pothole_seg_model is not None,
            "pothole_seg_model": os.path.basename(self.pothole_seg_model_name) if self.pothole_seg_model_name else None,
            "confidence_thresholds": {
                "pothole_segmentation": self.pothole_seg_conf_threshold,
                "rdd_pothole": self.rdd_pothole_conf_threshold,
                "rdd_crack": self.rdd_crack_conf_threshold,
            },
            "engine": " + ".join(loaded),
            "warnings": list(self.model_load_warnings),
        }

    @staticmethod
    def _road_damage_label(class_name: str):
        """Map RDD2022 classes conservatively; only D40 is a pothole."""
        name = str(class_name or "").strip().lower().replace("_", " ").replace("-", " ")
        compact = name.replace(" ", "")
        if "d40" in compact or "pothole" in name or name in {"hole", "road cavity", "road cavity defect"}:
            return "pothole_damage", "Pothole", "D40"
        if "d00" in compact or "longitudinal" in name:
            return "road_crack", "Longitudinal Crack", "D00"
        if "d10" in compact or "transverse" in name:
            return "road_crack", "Transverse Crack", "D10"
        if "d20" in compact or "alligator" in name:
            return "road_crack", "Alligator Crack", "D20"
        if "crack" in name:
            return "road_crack", str(class_name).title(), "road_crack"
        return None, None, None

    @staticmethod
    def _dedicated_pothole_name(class_name: str) -> bool:
        """Accept only explicit pothole-class labels from the specialized model."""
        name = str(class_name or "").strip().lower().replace("_", " ").replace("-", " ")
        compact = "".join(name.split())
        return ("pothole" in compact or "pot hole" in name or compact in {"roadcavity", "potholes"})

    @staticmethod
    def _plausible_pothole_geometry(frame_shape, bbox, polygon=None) -> bool:
        """Reject obvious frame-edge curbs/barriers before calling a region a pothole.

        This is a conservative sanity gate, not a pothole classifier: semantic class
        evidence is still required. Long, frame-attached regions are common curb or
        barrier false positives in dashcam views, so they are left for review rather
        than labeled as a pothole. Small genuine defects remain eligible.
        """
        try:
            height, width = int(frame_shape[0]), int(frame_shape[1])
            x1, y1, x2, y2 = [float(value) for value in bbox]
        except (TypeError, ValueError, IndexError):
            return False
        if height <= 0 or width <= 0 or x2 <= x1 or y2 <= y1:
            return False
        x1, x2 = max(0.0, x1), min(float(width), x2)
        y1, y2 = max(0.0, y1), min(float(height), y2)
        box_width, box_height = x2 - x1, y2 - y1
        if box_width <= 1 or box_height <= 1:
            return False
        width_ratio = box_width / width
        height_ratio = box_height / height
        area_ratio = (box_width * box_height) / float(width * height)
        aspect_ratio = box_width / box_height

        # An individual pothole should not occupy most of a frame. Very large masks
        # are usually road surface, a curb, shadow, or a segmentation spill.
        if area_ratio > 0.32:
            return False

        touches_vertical_edge = x1 <= width * 0.012 or x2 >= width * 0.988
        if touches_vertical_edge and height_ratio >= 0.18 and (width_ratio >= 0.065 or aspect_ratio < 0.40):
            return False
        # Long, thin full-width regions are typically curb lips/road markings rather
        # than a localized cavity. Keep the rule conservative so elongated potholes
        # away from the image boundary are not rejected.
        touches_horizontal_edge = y1 <= height * 0.01 or y2 >= height * 0.99
        if touches_horizontal_edge and width_ratio >= 0.30 and height_ratio <= 0.12:
            return False

        if polygon and len(polygon) >= 3:
            xs = [float(point[0]) for point in polygon if len(point) >= 2]
            ys = [float(point[1]) for point in polygon if len(point) >= 2]
            if len(xs) >= 3 and len(ys) >= 3:
                mask_width = max(xs) - min(xs)
                mask_height = max(ys) - min(ys)
                mask_touches_edge = min(xs) <= width * 0.008 or max(xs) >= width * 0.992
                # A segmentation region spilling from the side edge and continuing
                # for a large fraction of the frame height resembles a curb/barrier.
                if mask_touches_edge and mask_height >= height * 0.22 and mask_width >= width * 0.045:
                    return False
        return True

    @staticmethod
    def _general_hazard_label(class_name: str):
        """Map general model names conservatively; don't relabel every road object as a hazard."""
        name = str(class_name or "").lower()
        # A standing tree is ordinary scenery, not a fallen-tree incident.
        if any(k in name for k in ["fallen tree", "downed tree", "branch", "log", "wood debris", "rockfall", "debris"]):
            return "fallen_tree_debris", "Possible Downed Tree / Heavy Debris"
        if any(k in name for k in ["flood", "waterlogging", "standing water"]):
            return "road_flooding", "Localized Waterlogging / Flooding"
        if any(k in name for k in ["wire", "cable", "powerline"]):
            return "powerline_hazard", "Downed Power Line / Utility Hazard"
        if any(k in name for k in ["barrier", "barricade", "roadblock", "blockage"]):
            return "structural_blockage", "Barricade / Structural Obstacle"
        return None, None

    def analyze_frame(
        self,
        frame: np.ndarray,
        frame_idx: int,
        timestamp_sec: float,
        priority: str = "background",
    ) -> List[Dict[str, Any]]:
        """Serialize model calls but let live video frames jump ahead of queued GIS frames."""
        is_live = priority == "live"
        with self._inference_condition:
            if is_live:
                self._pending_live_inferences += 1
                try:
                    while self._inference_busy:
                        self._inference_condition.wait()
                finally:
                    self._pending_live_inferences -= 1
                self._inference_busy = True
            else:
                # When an interactive request is waiting, let it take the next slot.
                while self._inference_busy or self._pending_live_inferences > 0:
                    self._inference_condition.wait()
                self._inference_busy = True

        try:
            # Interactive playback focuses on road damage/CV cavity candidates. The
            # general COCO model is not trained for potholes, and running it on every
            # live frame adds latency without improving pothole recall. The full-video
            # pass runs the general model at a low supplementary cadence instead.
            skip_general = is_live
            return self._analyze_frame_locked(frame, frame_idx, timestamp_sec, skip_general=skip_general)
        finally:
            with self._inference_condition:
                self._inference_busy = False
                self._inference_condition.notify_all()

    def _analyze_frame_locked(
        self,
        frame: np.ndarray,
        frame_idx: int,
        timestamp_sec: float,
        skip_general: bool = False,
    ) -> List[Dict[str, Any]]:
        """Infer hazards for one frame using local weights; outputs pixel-space boxes."""
        detections: List[Dict[str, Any]] = []

        # Dedicated pothole segmentation runs first. Only an explicit pothole class
        # name is accepted as POTHOLE; a mask alone is never sufficient to classify
        # a curb, barrier, shadow, or arbitrary surface region as a pothole.
        if self.pothole_seg_model is not None:
            try:
                seg_results = self.pothole_seg_model.predict(
                    source=frame, conf=self.pothole_seg_conf_threshold,
                    imgsz=768 if not skip_general else 640,
                    iou=0.45, max_det=40, verbose=False
                )
                for result in seg_results:
                    names = result.names
                    mask_polygons = getattr(getattr(result, "masks", None), "xy", None) or []
                    boxes = getattr(result, "boxes", None)
                    if boxes is None:
                        continue
                    for box_index, box in enumerate(boxes):
                        class_id = int(box.cls[0].item())
                        class_name = names.get(class_id, str(class_id)) if isinstance(names, dict) else names[class_id]
                        if not self._dedicated_pothole_name(class_name):
                            continue
                        confidence = float(box.conf[0].item())
                        if confidence < self.pothole_seg_conf_threshold:
                            continue
                        x1, y1, x2, y2 = [int(round(v)) for v in box.xyxy[0].tolist()]
                        polygon = []
                        if box_index < len(mask_polygons):
                            polygon = [[round(float(pt[0]), 1), round(float(pt[1]), 1)] for pt in mask_polygons[box_index]
                                       if len(pt) >= 2 and np.isfinite(pt[0]) and np.isfinite(pt[1])]
                        candidate = {
                            "type": "pothole_damage",
                            "label": "Pothole",
                            "class_code": "D40",
                            "bbox": [x1, y1, x2, y2],
                            "confidence": round(confidence, 3),
                            "source": "pothole_segmentation_model",
                            "verification": "model_inferred_unverified",
                            "has_mask": len(polygon) >= 3,
                        }
                        if len(polygon) >= 3:
                            candidate["polygon"] = polygon
                        if not self._plausible_pothole_geometry(frame.shape, candidate["bbox"], polygon):
                            print(f"[Detector] Rejected pothole-segmentation candidate as likely edge/curb false positive: bbox={candidate['bbox']} confidence={confidence:.3f}")
                            continue
                        if not self._overlaps_any(candidate["bbox"], detections, iou_thresh=0.35):
                            detections.append(candidate)
            except Exception as exc:
                print(f"[Detector] Pothole segmentation inference failed on frame {frame_idx}: {exc}")

        # RDD2022 provides pothole D40 and crack D00/D10/D20 classes. Its confidence
        # floor is deliberately lower only at model output; class-specific filtering
        # is applied below. Cracks are never mislabeled as potholes.
        if self.road_damage_model is not None:
            try:
                results = self.road_damage_model.predict(
                    source=frame, conf=min(self.rdd_pothole_conf_threshold, self.rdd_crack_conf_threshold, 0.12),
                    # The offline pass is the full-video analysis stage. Use a
                    # modestly larger input there to recover small road defects;
                    # live preview inference stays at 640 for responsiveness.
                    imgsz=768 if not skip_general else 640,
                    iou=0.45, max_det=60, verbose=False
                )
                for result in results:
                    names = result.names
                    for box in result.boxes:
                        class_id = int(box.cls[0].item())
                        class_name = names.get(class_id, str(class_id)) if isinstance(names, dict) else names[class_id]
                        hazard_type, label, class_code = self._road_damage_label(class_name)
                        if not hazard_type:
                            continue
                        x1, y1, x2, y2 = [int(round(v)) for v in box.xyxy[0].tolist()]
                        confidence = float(box.conf[0].item())
                        required_confidence = self.rdd_pothole_conf_threshold if class_code == "D40" else self.rdd_crack_conf_threshold
                        if confidence < required_confidence:
                            continue
                        if class_code == "D40" and not self._plausible_pothole_geometry(frame.shape, [x1, y1, x2, y2]):
                            print(f"[Detector] Rejected RDD D40 candidate as likely edge/curb false positive: bbox={[x1, y1, x2, y2]} confidence={confidence:.3f}")
                            continue
                        candidate = {
                            "type": hazard_type,
                            "label": label,
                            "class_code": class_code,
                            "bbox": [x1, y1, x2, y2],
                            "confidence": round(confidence, 3),
                            "source": "rdd2022_road_damage_model",
                            "verification": "model_inferred_unverified",
                        }
                        if not self._overlaps_any(candidate["bbox"], detections, iou_thresh=0.35):
                            detections.append(candidate)
            except Exception as exc:
                print(f"[Detector] RDD2022 inference failed on frame {frame_idx}: {exc}")

        # The general-purpose COCO model supplies supplementary obstruction classes,
        # but it is not trained to detect potholes. Run it at most once per second
        # rather than on every 10-FPS road-damage sample; this saves substantial CPU
        # time without reducing the sampling rate of the specialized pothole model.
        # A remembered bucket prevents close samples (e.g. 0.95s and 1.05s) from
        # causing two costly COCO passes for the same second.
        second_bucket = int(round(float(timestamp_sec)))
        near_second_boundary = abs(float(timestamp_sec) - second_bucket) <= 0.075
        run_general_model = False
        if not skip_general and self.model is not None and near_second_boundary:
            with self._inference_condition:
                if self._last_general_second != second_bucket:
                    self._last_general_second = second_bucket
                    run_general_model = True
        if self.model is not None and run_general_model:
            try:
                results = self.model.predict(
                    source=frame, conf=self.conf_threshold,
                    imgsz=640, max_det=40, verbose=False
                )
                for result in results:
                    names = result.names
                    for box in result.boxes:
                        class_id = int(box.cls[0].item())
                        class_name = names.get(class_id, str(class_id)) if isinstance(names, dict) else names[class_id]
                        hazard_type, label = self._general_hazard_label(class_name)
                        if not hazard_type:
                            continue
                        x1, y1, x2, y2 = [int(v) for v in box.xyxy[0].tolist()]
                        candidate = {
                            "type": hazard_type,
                            "label": label,
                            "bbox": [x1, y1, x2, y2],
                            "confidence": round(float(box.conf[0].item()), 3),
                            "source": "yolo_general_model",
                            "verification": "model_inferred",
                        }
                        if not self._overlaps_any(candidate["bbox"], detections):
                            detections.append(candidate)
            except Exception as exc:
                print(f"[Detector] General YOLO inference failed on frame {frame_idx}: {exc}")

        # CV is a supplementary *candidate* source, not a pothole classifier. It
        # may suggest a dark/irregular road patch even when ML weights are loaded,
        # but must never convert that region into a confirmed POTHOLE label.
        has_model_pothole = any(
            item.get("type") == "pothole_damage"
            and item.get("source") in {"pothole_segmentation_model", "rdd2022_road_damage_model"}
            for item in detections
        )
        if not has_model_pothole:
            cv_detections = self._detect_road_features_cv(frame)
            for item in cv_detections:
                if not self._overlaps_any(item["bbox"], detections, iou_thresh=0.2):
                    detections.append(item)

        return detections

    def _detect_road_features_cv(self, frame: np.ndarray) -> List[Dict[str, Any]]:
        """
        Computer Vision road surface analyzer for pothole cavities,
        water sheen/flooding, and timber obstructions on the drivable surface.
        """
        h, w = frame.shape[:2]
        road_roi_y = int(h * 0.45) # Lower 55% of the frame is the road
        road_roi = frame[road_roi_y:, :]
        rh, rw = road_roi.shape[:2]
        cv_results = []

        gray = cv2.cvtColor(road_roi, cv2.COLOR_BGR2GRAY)
        blurred = cv2.GaussianBlur(gray, (7, 7), 0)

        # A. Detect dark localized road cavities (Potholes / Asphalt Ruptures)
        # Potholes exhibit sharp edge gradients and significantly darker asphalt core
        thresh_dark = cv2.adaptiveThreshold(
            blurred, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
            cv2.THRESH_BINARY_INV, 31, 7
        )
        kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))
        morph_dark = cv2.morphologyEx(thresh_dark, cv2.MORPH_OPEN, kernel)
        contours, _ = cv2.findContours(morph_dark, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

        for cnt in contours:
            area = cv2.contourArea(cnt)
            # Use a lower minimum area than a generic blob detector: distant
            # potholes occupy a very small fraction of the road ROI. A 0.3% floor
            # missed both halves of the bundled approach shot (each was ~0.08%).
            # Keep the upper limit and the geometry/darkness checks below to reject
            # broad shadows and road-edge regions.
            if (rh * rw * 0.0005) < area < (rh * rw * 0.08):
                bx, by, bw, bh = cv2.boundingRect(cnt)
                # Reject road edges / horizon regions. These often form huge dark
                # half-frame contours in synthetic footage and must never become
                # fake pothole boxes. True cavity candidates should be localized.
                box_area_ratio = (bw * bh) / float(rh * rw + 1e-5)
                touches_side_edge = bx <= 2 or (bx + bw) >= (rw - 3)
                if touches_side_edge or bw > rw * 0.42 or bh > rh * 0.45 or box_area_ratio > 0.075:
                    continue
                aspect_ratio = bw / float(bh + 1e-5)
                # Potholes are generally somewhat elliptical or horizontal
                if 0.5 < aspect_ratio < 4.0:
                    # Calculate mean intensity of region vs surrounding road
                    mask = np.zeros_like(gray)
                    cv2.drawContours(mask, [cnt], -1, 255, -1)
                    mean_val = cv2.mean(gray, mask=mask)[0]
                    road_mean = np.mean(gray)

                    if mean_val < road_mean * 0.75: # Darker than surrounding road
                        abs_y1 = road_roi_y + by
                        abs_y2 = road_roi_y + by + bh
                        abs_x1 = bx
                        abs_x2 = bx + bw
                        cv_results.append({
                            "type": "possible_road_anomaly",
                            "label": "Possible Road Anomaly",
                            "bbox": [abs_x1, abs_y1, abs_x2, abs_y2],
                            "confidence": round(min(0.49, 0.30 + (area / (rh * rw * 0.08)) * 0.15), 3),
                            "source": "cv_surface_analyzer",
                            "verification": "provisional_heuristic"
                        })

        # Merge adjacent fragments from a single cavity. Thresholding can split a
        # dark pothole into two neighboring contours, which otherwise appear as two
        # narrow boxes. Merge only when they share most of their vertical span and
        # overlap or nearly touch horizontally; this does not add confidence.
        merged = []
        for candidate in sorted(cv_results, key=lambda item: item["bbox"][0]):
            x1, y1, x2, y2 = candidate["bbox"]
            match_index = None
            for index, existing in enumerate(merged):
                ex1, ey1, ex2, ey2 = existing["bbox"]
                vertical_overlap = max(0, min(y2, ey2) - max(y1, ey1))
                vertical_min = max(1, min(y2 - y1, ey2 - ey1))
                horizontal_gap = max(0, max(x1 - ex2, ex1 - x2))
                max_width = max(x2 - x1, ex2 - ex1)
                if vertical_overlap / vertical_min >= 0.50 and horizontal_gap <= max_width * 0.35:
                    match_index = index
                    break
            if match_index is None:
                merged.append(candidate)
                continue
            existing = merged[match_index]
            ex1, ey1, ex2, ey2 = existing["bbox"]
            union_box = [min(x1, ex1), min(y1, ey1), max(x2, ex2), max(y2, ey2)]
            existing["bbox"] = union_box
            # Mark the wider merged region as a single provisional heuristic. Do not
            # inflate the confidence as a result of box merging.
            existing["confidence"] = min(existing["confidence"], candidate["confidence"])

        # Flooding is intentionally NOT inferred from smooth/low-texture asphalt.
        # That shortcut produced false positives (ordinary roads scored as 90%+ flooding).
        # Flooding should only be emitted by a validated hazard model or human annotation.

        return merged

    def _overlaps_any(self, bbox: List[int], existing: List[Dict[str, Any]], iou_thresh: float = 0.3) -> bool:
        for item in existing:
            if self._compute_iou(bbox, item["bbox"]) > iou_thresh:
                return True
        return False

    @staticmethod
    def _compute_iou(b1: List[int], b2: List[int]) -> float:
        x1 = max(b1[0], b2[0])
        y1 = max(b1[1], b2[1])
        x2 = min(b1[2], b2[2])
        y2 = min(b1[3], b2[3])
        inter_area = max(0, x2 - x1) * max(0, y2 - y1)
        area1 = (b1[2] - b1[0]) * (b1[3] - b1[1])
        area2 = (b2[2] - b2[0]) * (b2[3] - b2[1])
        denom = area1 + area2 - inter_area
        return inter_area / denom if denom > 0 else 0.0


class HazardTracker:
    """
    Maintains temporal tracking of hazards across frames.
    Merges detections of the same physical hazard into a consolidated event,
    recording peak confidence, optimal crop snapshot, and closest distance.
    """
    def __init__(self, iou_threshold: float = 0.25, max_frame_gap: int = 15):
        self.iou_threshold = iou_threshold
        self.max_frame_gap = max_frame_gap
        self.active_tracks: List[Dict[str, Any]] = []
        self.completed_tracks: List[Dict[str, Any]] = []
        self.next_id = 1

    def update(
        self,
        detections: List[Dict[str, Any]],
        frame: np.ndarray,
        frame_idx: int,
        timestamp_sec: float
    ):
        matched_track_indices = set()
        h, w = frame.shape[:2]

        for det in detections:
            best_match_idx = None
            best_iou = self.iou_threshold

            for idx, track in enumerate(self.active_tracks):
                if track["type"] == det["type"] and (frame_idx - track["last_frame_idx"]) <= self.max_frame_gap:
                    iou = RoadHazardDetector._compute_iou(det["bbox"], track["last_bbox"])
                    if iou > best_iou:
                        best_iou = iou
                        best_match_idx = idx

            if best_match_idx is not None:
                # Update existing track
                matched_track_indices.add(best_match_idx)
                track = self.active_tracks[best_match_idx]
                track["detections_count"] += 1
                track["last_frame_idx"] = frame_idx
                track["last_bbox"] = det["bbox"]
                track["end_time_sec"] = timestamp_sec

                # Keep source, label and geometry tied to the strongest observed
                # detection. Otherwise a weaker heuristic later in the track could
                # overwrite the provenance of the model's best frame.
                if det["confidence"] > track["best_confidence"]:
                    track["best_confidence"] = det["confidence"]
                    track["label"] = det.get("label", track.get("label"))
                    track["class_code"] = det.get("class_code", track.get("class_code"))
                    track["source"] = det.get("source", track.get("source"))
                    track["verification"] = det.get("verification", track.get("verification", "model_inferred_unverified"))
                    track["best_bbox"] = det["bbox"]
                    track["best_polygon"] = det.get("polygon")
                    track["best_has_mask"] = bool(det.get("has_mask"))
                    track["best_frame_idx"] = frame_idx
                    track["best_timestamp_sec"] = timestamp_sec
                    # Extract crop
                    bx1, by1, bx2, by2 = det["bbox"]
                    pad_x = int((bx2 - bx1) * 0.15)
                    pad_y = int((by2 - by1) * 0.15)
                    c_x1 = max(0, bx1 - pad_x)
                    c_y1 = max(0, by1 - pad_y)
                    c_x2 = min(w, bx2 + pad_x)
                    c_y2 = min(h, by2 + pad_y)
                    track["crop_image"] = frame[c_y1:c_y2, c_x1:c_x2].copy()
            else:
                # Start new track
                bx1, by1, bx2, by2 = det["bbox"]
                pad_x = int((bx2 - bx1) * 0.15)
                pad_y = int((by2 - by1) * 0.15)
                c_x1 = max(0, bx1 - pad_x)
                c_y1 = max(0, by1 - pad_y)
                c_x2 = min(w, bx2 + pad_x)
                c_y2 = min(h, by2 + pad_y)
                crop = frame[c_y1:c_y2, c_x1:c_x2].copy()

                new_track = {
                    "id": f"HAZ-{self.next_id:03d}",
                    "type": det["type"],
                    "label": det.get("label", det["type"].replace("_", " ").title()),
                    "class_code": det.get("class_code"),
                    "source": det.get("source", "cv_surface_analyzer"),
                    "verification": det.get("verification", "provisional_heuristic"),
                    "start_time_sec": timestamp_sec,
                    "end_time_sec": timestamp_sec,
                    "first_frame_idx": frame_idx,
                    "last_frame_idx": frame_idx,
                    "detections_count": 1,
                    "best_confidence": det["confidence"],
                    "best_bbox": det["bbox"],
                    "best_polygon": det.get("polygon"),
                    "best_has_mask": bool(det.get("has_mask")),
                    "last_bbox": det["bbox"],
                    "best_frame_idx": frame_idx,
                    "best_timestamp_sec": timestamp_sec,
                    "crop_image": crop
                }
                self.next_id += 1
                self.active_tracks.append(new_track)

        # Check for expired tracks
        remaining_active = []
        for idx, track in enumerate(self.active_tracks):
            if (frame_idx - track["last_frame_idx"]) > self.max_frame_gap:
                self.completed_tracks.append(track)
            else:
                remaining_active.append(track)
        self.active_tracks = remaining_active

    def finish(self) -> List[Dict[str, Any]]:
        """Flushes all active tracks and returns consolidated list of hazard events."""
        self.completed_tracks.extend(self.active_tracks)
        self.active_tracks = []
        # Filter spurious single-frame blips with very low confidence
        filtered = [t for t in self.completed_tracks if (t["detections_count"] >= 2 or t["best_confidence"] >= 0.50)]
        return filtered
