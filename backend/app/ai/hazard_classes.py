"""
CivicRouteAD - Hazard Classification and Municipal Response Matrix
Defines road hazard categories, severity calculation logic, and emergency action recommendations.
"""

from typing import Dict, Any, List

HAZARD_DEFINITIONS: Dict[str, Dict[str, Any]] = {
    "fallen_tree_debris": {
        "label": "Downed Tree / Heavy Debris",
        "description": "Fallen tree, large branch, timber, or rockfall blocking roadway or shoulder.",
        "base_severity": "Critical",
        "color": "#ef4444",
        "department": "Public Works & Forestry Emergency Response",
        "action": "Immediate dispatch: Clear roadway with chainsaw crew & heavy loader. Deploy temporary detour signage.",
        "icon": "tree"
    },
    "road_flooding": {
        "label": "Localized Waterlogging / Flooding",
        "description": "Standing water accumulation, submerged lanes, or localized stormwater pooling.",
        "base_severity": "High",
        "color": "#0ea5e9",
        "department": "Municipal Drainage & Stormwater Management",
        "action": "Dispatch suction pump truck. Inspect storm drains for blockages. Issue aquaplaning caution advisory.",
        "icon": "droplets"
    },
    "road_crack": {
        "label": "Road Crack / Pavement Defect",
        "description": "A model-inferred longitudinal, transverse, or alligator pavement crack; not classified as a pothole.",
        "base_severity": "Low",
        "color": "#f97316",
        "department": "Department of Transportation - Pavement Maintenance",
        "action": "Review the evidence and schedule pavement maintenance if confirmed.",
        "icon": "route"
    },
    "possible_road_anomaly": {
        "label": "Possible Road Surface Anomaly",
        "description": "A heuristic candidate based on image appearance. This is not a confirmed pothole and requires human review.",
        "base_severity": "Low",
        "color": "#a3a3a3",
        "department": "Public Works Department",
        "action": "Review the source frame; do not dispatch based on the heuristic candidate alone.",
        "icon": "search"
    },
    "pothole_damage": {
        "label": "Pothole",
        "description": "A model-inferred pothole/cavity. Road crack classes are stored separately; all machine detections remain unverified until reviewed.",
        "base_severity": "Medium",
        "color": "#f59e0b",
        "department": "Department of Transportation - Asphalt Maintenance",
        "action": "Schedule emergency cold-mix patching within 24 hours. Mark with reflective hazard cone if depth > 5cm.",
        "icon": "alert-triangle"
    },
    "powerline_hazard": {
        "label": "Downed Power Line / Utility Hazard",
        "description": "Fallen electrical cable, hanging utility wires, or damaged utility pole across the right-of-way.",
        "base_severity": "Critical",
        "color": "#dc2626",
        "department": "Electrical Utility Grid & Emergency Services",
        "action": "DANGER - Live wire risk. Cordon off 20m perimeter immediately. Coordinate rapid power shutoff.",
        "icon": "zap"
    },
    "structural_blockage": {
        "label": "Barricade / Structural Obstacle",
        "description": "Construction barrier, collapsed roadside sign, landslide barrier, or stalled obstruction.",
        "base_severity": "High",
        "color": "#8b5cf6",
        "department": "Traffic Management & Highway Patrol",
        "action": "Dispatch road patrol to reposition barriers and restore full lane width.",
        "icon": "shield-alert"
    }
}

def compute_severity(hazard_type: str, box_area_ratio: float, lateral_offset_m: float) -> str:
    """
    Computes dynamic severity rating: Critical, High, Medium, or Low
    based on hazard type, projected proximity, and lane occupancy.
    """
    base = HAZARD_DEFINITIONS.get(hazard_type, {}).get("base_severity", "Medium")
    
    # In-lane obstruction (close to center line: lateral offset < 1.8m)
    is_in_lane = abs(lateral_offset_m) < 1.8
    
    # Large obstacle (> 5% of screen area)
    is_large = box_area_ratio > 0.05
    
    if hazard_type in ("fallen_tree_debris", "powerline_hazard"):
        if is_in_lane or is_large:
            return "Critical"
        return "High"
        
    if hazard_type == "road_flooding":
        if is_in_lane and is_large:
            return "Critical"
        if is_in_lane:
            return "High"
        return "Medium"
        
    if hazard_type in ("pothole_damage", "road_crack", "possible_road_anomaly"):
        if hazard_type == "possible_road_anomaly":
            return "Low"
        if is_in_lane and is_large:
            return "High" if hazard_type == "pothole_damage" else "Medium"
        if is_in_lane:
            return "Medium" if hazard_type == "pothole_damage" else "Low"
        return "Low"
        
    if hazard_type == "structural_blockage":
        if is_in_lane:
            return "High"
        return "Medium"
        
    return base
