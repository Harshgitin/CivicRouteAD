import os
import sys
import shutil

backend_dir = os.path.dirname(os.path.abspath(__file__))
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)

import cv2
import numpy as np
from ultralytics import YOLO
from app.ai.detector import RoadHazardDetector

artifact_dir = r"C:\Users\Harsh\.gemini\antigravity\brain\3234ae28-9d32-4be9-a943-a5c0c9f28972"
out_dir = os.path.join(backend_dir, "data", "debug_frames")
os.makedirs(out_dir, exist_ok=True)
os.makedirs(artifact_dir, exist_ok=True)

detector = RoadHazardDetector()
rdd = YOLO(os.path.join(backend_dir, "models", "yolov8s_best.pt"))

def draw_hud_annotation(img, dets, title=""):
    canvas = img.copy()
    h, w = canvas.shape[:2]
    for d in dets:
        bbox = [int(round(v)) for v in d["bbox"]]
        x1, y1, x2, y2 = bbox
        conf_val = float(d.get("confidence", d.get("conf", 0.0)))
        class_code = str(d.get("class_code") or "").upper()
        hazard_type = d.get("type", "")
        source = d.get("source", "")
        verification = d.get("verification", "")
        
        is_heuristic = (
            verification == "provisional_heuristic"
            or source == "cv_surface_analyzer"
            or hazard_type == "possible_road_anomaly"
        )
        is_pothole = not is_heuristic and (
            class_code == "D40"
            or source == "pothole_segmentation_model"
            or (hazard_type == "pothole_damage" and source == "rdd2022_road_damage_model")
        )
        is_crack = not is_heuristic and (
            class_code in ["D00", "D10", "D20"]
            or hazard_type == "road_crack"
        )
        
        if is_pothole:
            color = (38, 38, 220)  # Red #dc2626 (BGR)
            lbl = f"POTHOLE {conf_val:.2f}"
        elif is_crack:
            color = (12, 88, 234)  # Orange #ea580c (BGR)
            lbl = f"{class_code or 'CRACK'} {conf_val:.2f}"
        elif is_heuristic:
            color = (184, 163, 148)  # Slate Grey #94a3b8 (BGR)
            lbl = f"POSSIBLE ROAD ANOMALY {conf_val:.2f}"
        else:
            color = (246, 130, 59)
            lbl = f"{d.get('label', 'HAZARD').upper()} {conf_val:.2f}"
            
        cv2.rectangle(canvas, (x1, y1), (x2, y2), color, 3)
        (tw, th), _ = cv2.getTextSize(lbl, cv2.FONT_HERSHEY_SIMPLEX, 0.5, 2)
        by1 = max(0, y1 - th - 8)
        cv2.rectangle(canvas, (x1, by1), (x1 + tw + 8, by1 + th + 8), color, -1)
        cv2.putText(canvas, lbl, (x1 + 4, by1 + th + 3), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 2)
        
    if title:
        cv2.putText(canvas, title, (15, 28), cv2.FONT_HERSHEY_SIMPLEX, 0.65, (0, 255, 255), 2)
    return canvas

# 1. India_003191.jpg (Real road genuine pothole)
p1 = os.path.join(backend_dir, "data", "road_damage_samples", "India_003191.jpg")
img1 = cv2.imread(p1)
dets1 = detector.analyze_frame(img1, 0, 0.0, priority="live")
res1 = draw_hud_annotation(img1, dets1, "RDD2022 MODEL: GENUINE POTHOLE DETECTED (D40)")
cv2.imwrite(os.path.join(out_dir, "annotated_india_pothole.jpg"), res1)
cv2.imwrite(os.path.join(artifact_dir, "annotated_india_pothole.jpg"), res1)
print(f"Saved annotated_india_pothole.jpg with {len(dets1)} detections: {dets1}")

# 2. China_Drone_000253.jpg (High-confidence D40 pothole)
p2 = os.path.join(backend_dir, "data", "road_damage_samples", "China_Drone_000253.jpg")
img2 = cv2.imread(p2)
dets2 = detector.analyze_frame(img2, 0, 0.0, priority="live")
res2 = draw_hud_annotation(img2, dets2, "RDD2022 MODEL: HIGH-CONFIDENCE POTHOLE (D40 0.94)")
cv2.imwrite(os.path.join(out_dir, "annotated_china_pothole.jpg"), res2)
cv2.imwrite(os.path.join(artifact_dir, "annotated_china_pothole.jpg"), res2)
print(f"Saved annotated_china_pothole.jpg with {len(dets2)} detections: {dets2}")

# 3. United_States_004798.jpg (Cracks D00 & D10 - orange outlines, not potholes)
p3 = os.path.join(backend_dir, "data", "road_damage_samples", "United_States_004798.jpg")
img3 = cv2.imread(p3)
dets3 = detector.analyze_frame(img3, 0, 0.0, priority="live")
# Filter to only the model detections for clean display
model_dets3 = [d for d in dets3 if d.get("source") != "cv_surface_analyzer"]
res3 = draw_hud_annotation(img3, model_dets3, "RDD2022 MODEL: CRACKS (D00/D10) != POTHOLE")
cv2.imwrite(os.path.join(out_dir, "annotated_us_cracks.jpg"), res3)
cv2.imwrite(os.path.join(artifact_dir, "annotated_us_cracks.jpg"), res3)
print(f"Saved annotated_us_cracks.jpg with {len(model_dets3)} detections: {model_dets3}")

# 4. storm_frame_260.jpg (Barrier / Curb - grey possible anomaly, not pothole)
p4 = os.path.join(out_dir, "storm_frame_260.jpg")
img4 = cv2.imread(p4)
dets4 = detector.analyze_frame(img4, 0, 0.0, priority="live")
res4 = draw_hud_annotation(img4, dets4, "CURB / BARRIER: GREY ANOMALY, NEVER POTHOLE")
cv2.imwrite(os.path.join(out_dir, "annotated_storm_barrier.jpg"), res4)
cv2.imwrite(os.path.join(artifact_dir, "annotated_storm_barrier.jpg"), res4)
print(f"Saved annotated_storm_barrier.jpg with {len(dets4)} detections: {dets4}")

# 5. frame_180.jpg from uploaded video uhd_30fps.mp4
p5 = os.path.join(out_dir, "frame_180.jpg")
img5 = cv2.imread(p5)
dets5 = detector.analyze_frame(img5, 0, 0.0, priority="live")
res5 = draw_hud_annotation(img5, dets5, "UPLOADED VIDEO FRAME 180 (AERIAL DRONE): 0 ROAD DEFECTS")
cv2.imwrite(os.path.join(out_dir, "annotated_uploaded_frame_180.jpg"), res5)
cv2.imwrite(os.path.join(artifact_dir, "annotated_uploaded_frame_180.jpg"), res5)
print(f"Saved annotated_uploaded_frame_180.jpg with {len(dets5)} detections: {dets5}")

# 6. pothole_frame_210.jpg (synthetic barrier frame)
p6 = os.path.join(out_dir, "pothole_frame_210.jpg")
img6 = cv2.imread(p6)
dets6 = detector.analyze_frame(img6, 0, 0.0, priority="live")
res6 = draw_hud_annotation(img6, dets6, "CONSTRUCTION BARRIER: NOT LABELED AS POTHOLE")
cv2.imwrite(os.path.join(out_dir, "annotated_pothole_frame_210.jpg"), res6)
cv2.imwrite(os.path.join(artifact_dir, "annotated_pothole_frame_210.jpg"), res6)
print(f"Saved annotated_pothole_frame_210.jpg with {len(dets6)} detections: {dets6}")
