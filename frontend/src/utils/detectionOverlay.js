/**
 * Interpolate road-hazard bounding boxes between analyzed video frames.
 * Frames are generally sampled around 10 times per second by the backend. The
 * helper matches same-class boxes, interpolates their corners, and holds a lone
 * detection only for a short interval to smooth one-frame model misses.
 */
const getBox = (detection) => {
  const box = detection?.bbox;
  if (Array.isArray(box) && box.length === 4) {
    const values = box.map(Number);
    if (values.every(Number.isFinite) && values[2] > values[0] && values[3] > values[1]) return values;
  }
  // Some segmentation-only serializers supply a polygon without an explicit box.
  const polygon = Array.isArray(detection?.polygon) ? detection.polygon : null;
  const maskEnabled = detection?.has_mask === true || detection?.has_mask === 1 || String(detection?.has_mask).toLowerCase() === 'true';
  if (!maskEnabled || !polygon || polygon.length < 3 || !polygon.every((point) => Array.isArray(point) && point.length >= 2 && Number.isFinite(Number(point[0])) && Number.isFinite(Number(point[1])))) return null;
  const xs = polygon.map((point) => Number(point[0]));
  const ys = polygon.map((point) => Number(point[1]));
  const values = [Math.min(...xs), Math.min(...ys), Math.max(...xs), Math.max(...ys)];
  return values.every(Number.isFinite) && values[2] > values[0] && values[3] > values[1] ? values : null;
};

const boxIoU = (a, b) => {
  const ix1 = Math.max(a[0], b[0]);
  const iy1 = Math.max(a[1], b[1]);
  const ix2 = Math.min(a[2], b[2]);
  const iy2 = Math.min(a[3], b[3]);
  const intersection = Math.max(0, ix2 - ix1) * Math.max(0, iy2 - iy1);
  const areaA = (a[2] - a[0]) * (a[3] - a[1]);
  const areaB = (b[2] - b[0]) * (b[3] - b[1]);
  return intersection / Math.max(1, areaA + areaB - intersection);
};

const centerDistance = (a, b) => Math.hypot(
  ((a[0] + a[2]) / 2) - ((b[0] + b[2]) / 2),
  ((a[1] + a[3]) / 2) - ((b[1] + b[3]) / 2),
);

const sameClass = (a, b) => {
  if ((a?.type || 'unknown') !== (b?.type || 'unknown')) return false;
  if (a?.class_code && b?.class_code && a.class_code !== b.class_code) return false;
  return true;
};

const confidenceOf = (item) => {
  const value = Number(item?.conf ?? item?.confidence);
  return Number.isFinite(value) ? value : 0;
};

/** Return the best correspondence in the right-hand sample for a detection. */
const findMatch = (leftDetection, rightDetections, usedRight) => {
  const leftBox = getBox(leftDetection);
  if (!leftBox) return -1;
  let bestIndex = -1;
  let bestScore = -Infinity;
  for (let index = 0; index < rightDetections.length; index += 1) {
    if (usedRight.has(index) || !sameClass(leftDetection, rightDetections[index])) continue;
    const rightBox = getBox(rightDetections[index]);
    if (!rightBox) continue;
    const distance = centerDistance(leftBox, rightBox);
    const maxDimension = Math.max(
      leftBox[2] - leftBox[0], leftBox[3] - leftBox[1],
      rightBox[2] - rightBox[0], rightBox[3] - rightBox[1],
    );
    const maxDistance = Math.max(24, maxDimension * 1.6);
    const iou = boxIoU(leftBox, rightBox);
    if (iou < 0.01 && distance > maxDistance) continue;
    const score = iou + 0.15 * Math.max(0, 1 - (distance / maxDistance));
    if (score > bestScore) {
      bestScore = score;
      bestIndex = index;
    }
  }
  return bestIndex;
};

const interpolateDetection = (left, right, ratio) => {
  const leftBox = getBox(left);
  const rightBox = getBox(right);
  if (!leftBox || !rightBox) return { ...left };
  const bbox = leftBox.map((value, index) => value + ((rightBox[index] - value) * ratio));
  const confA = confidenceOf(left);
  const confB = confidenceOf(right);
  const leftPolygon = Array.isArray(left?.polygon) ? left.polygon : null;
  const rightPolygon = Array.isArray(right?.polygon) ? right.polygon : null;
  let polygon = leftPolygon;
  // Interpolate masks only when both samples have matching valid vertex counts.
  // Otherwise keep the closer sample's genuine mask instead of inventing topology.
  if (leftPolygon && rightPolygon && leftPolygon.length >= 3
      && leftPolygon.length === rightPolygon.length
      && leftPolygon.every((point, index) => Array.isArray(point) && Array.isArray(rightPolygon[index])
        && Number.isFinite(Number(point[0])) && Number.isFinite(Number(point[1]))
        && Number.isFinite(Number(rightPolygon[index][0])) && Number.isFinite(Number(rightPolygon[index][1])))) {
    polygon = leftPolygon.map((point, index) => [
      Number(point[0]) + ((Number(rightPolygon[index][0]) - Number(point[0])) * ratio),
      Number(point[1]) + ((Number(rightPolygon[index][1]) - Number(point[1])) * ratio),
    ]);
  } else if (ratio >= 0.5 && rightPolygon) {
    polygon = rightPolygon;
  }
  return {
    ...left,
    bbox: bbox.map((value) => Math.round(value * 10) / 10),
    ...(polygon ? { polygon } : {}),
    has_mask: Boolean(polygon && polygon.length >= 3 && (left.has_mask || right.has_mask)),
    conf: Math.round((confA + ((confB - confA) * ratio)) * 1000) / 1000,
  };
};

const deduplicateCloseBoxes = (detections) => {
  const kept = [];
  for (const detection of detections) {
    const box = getBox(detection);
    if (!box) continue;
    const duplicateIndex = kept.findIndex((old) => {
      if (!sameClass(old, detection)) return false;
      const oldBox = getBox(old);
      return oldBox && (boxIoU(box, oldBox) >= 0.45
        || centerDistance(box, oldBox) <= Math.max(12, Math.min(
          box[2] - box[0], box[3] - box[1], oldBox[2] - oldBox[0], oldBox[3] - oldBox[1],
        ) * 0.25));
    });
    if (duplicateIndex < 0) kept.push(detection);
    else if (confidenceOf(detection) > confidenceOf(kept[duplicateIndex])) kept[duplicateIndex] = detection;
  }
  return kept;
};

export function interpolateDetectionBoxes(leftPoint, rightPoint, targetSec, leftSec, rightSec, maxHoldSec = 0.25) {
  const leftDetections = Array.isArray(leftPoint?.detections) ? leftPoint.detections : [];
  const rightDetections = Array.isArray(rightPoint?.detections) ? rightPoint.detections : [];
  const target = Number.isFinite(Number(targetSec)) ? Number(targetSec) : 0;
  const t0 = Number.isFinite(Number(leftSec)) ? Number(leftSec) : target;
  const t1 = Number.isFinite(Number(rightSec)) ? Number(rightSec) : t0;
  const span = Math.max(0, t1 - t0);
  const ratio = span > 0 ? Math.max(0, Math.min(1, (target - t0) / span)) : 0;
  const result = [];
  const usedRight = new Set();
  const leftAge = Math.abs(target - t0);
  const rightAge = Math.abs(t1 - target);

  leftDetections.forEach((detection) => {
    const match = findMatch(detection, rightDetections, usedRight);
    if (match >= 0 && span <= 0.85) {
      usedRight.add(match);
      result.push(interpolateDetection(detection, rightDetections[match], ratio));
    } else if (leftAge <= maxHoldSec) {
      result.push(detection);
    }
  });

  rightDetections.forEach((detection, index) => {
    if (!usedRight.has(index) && rightAge <= maxHoldSec) result.push(detection);
  });

  // If no boxes were matched/held because of a slightly wide frame gap, hold the closer sample
  if (result.length === 0 && (leftDetections.length > 0 || rightDetections.length > 0)) {
    const holdCloser = leftAge <= rightAge ? leftDetections : rightDetections;
    const minAge = Math.min(leftAge, rightAge);
    if (minAge <= maxHoldSec) {
      return deduplicateCloseBoxes(holdCloser);
    }
  }

  return deduplicateCloseBoxes(result);
}
