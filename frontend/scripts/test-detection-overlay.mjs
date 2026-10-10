import assert from 'node:assert/strict';
import { interpolateDetectionBoxes } from '../src/utils/detectionOverlay.js';

const left = { time_sec: 0, detections: [{ type: 'pothole_damage', label: 'Pothole', conf: 0.6, bbox: [100, 100, 160, 145] }] };
const right = { time_sec: 0.1, detections: [{ type: 'pothole_damage', label: 'Pothole', conf: 0.8, bbox: [120, 110, 190, 160] }] };
const mid = interpolateDetectionBoxes(left, right, 0.05, 0, 0.1);
assert.equal(mid.length, 1, 'corresponding pothole boxes are matched');
assert.deepEqual(mid[0].bbox, [110, 105, 175, 152.5].map((value) => Math.round(value * 10) / 10));
assert.equal(mid[0].conf, 0.7, 'confidence is interpolated');

const oneSide = interpolateDetectionBoxes(left, { time_sec: 0.1, detections: [] }, 0.08, 0, 0.1);
assert.equal(oneSide.length, 1, 'single missed sample is bridged while close in time');
const stale = interpolateDetectionBoxes(left, { time_sec: 0.5, detections: [] }, 0.4, 0, 0.5);
assert.equal(stale.length, 0, 'stale outlines do not persist after the hold window');

const separate = interpolateDetectionBoxes(
  { time_sec: 0, detections: [{ type: 'pothole_damage', bbox: [100, 100, 150, 140], conf: 0.7 }] },
  { time_sec: 0.1, detections: [{ type: 'pothole_damage', bbox: [600, 500, 670, 550], conf: 0.7 }] },
  0.05, 0, 0.1,
);
assert.equal(separate.length, 2, 'distinct potholes remain separate when boxes do not match');
console.log('4 detection overlay interpolation tests passed.');

const polygonLeft = {
  time_sec: 0,
  detections: [{ type: 'pothole_damage', has_mask: true, polygon: [[10, 10], [20, 10], [20, 20], [10, 20]], bbox: [10, 10, 20, 20], conf: 0.6 }],
};
const polygonRight = {
  time_sec: 0.1,
  detections: [{ type: 'pothole_damage', has_mask: true, polygon: [[12, 12], [24, 12], [24, 24], [12, 24]], bbox: [12, 12, 24, 24], conf: 0.8 }],
};
const polygonMid = interpolateDetectionBoxes(polygonLeft, polygonRight, 0.05, 0, 0.1);
assert.equal(polygonMid.length, 1, 'same pothole mask is matched between nearby samples');
assert.equal(polygonMid[0].has_mask, true, 'segmentation mask metadata is preserved');
assert.deepEqual(polygonMid[0].polygon[0], [11, 11], 'matching polygon vertices are interpolated');
console.log('polygon interpolation tests passed.');
