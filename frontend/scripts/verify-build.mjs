import fs from 'node:fs';
import path from 'node:path';

const root = path.resolve(process.cwd());
const dist = path.join(root, 'dist');
const indexPath = path.join(dist, 'index.html');
const marker = 'civicroute-build" content="advanced-map-proxy-20261010';
const fail = (message) => {
  console.error(`[CivicRouteAD build check] FAIL: ${message}`);
  process.exit(1);
};

if (!fs.existsSync(indexPath)) fail('frontend/dist/index.html is missing. Run npm run build.');
const html = fs.readFileSync(indexPath, 'utf8');
if (!html.includes(marker)) fail('the built index.html is stale (required build marker is missing).');

const assetsDir = path.join(dist, 'assets');
if (!fs.existsSync(assetsDir)) fail('frontend/dist/assets is missing.');
const assetNames = fs.readdirSync(assetsDir).filter((name) => name.endsWith('.js'));
if (!assetNames.length) fail('no bundled JavaScript was found in frontend/dist/assets.');
const js = assetNames.map((name) => fs.readFileSync(path.join(assetsDir, name), 'utf8')).join('\n');
if (!js.includes('/api/infrastructure/mapillary/scan')) fail("the built UI does not call CivicRouteAD's backend Mapillary proxy.");
if (!js.includes('/api/infrastructure/osm-context')) fail("the built UI does not call CivicRouteAD's backend OpenStreetMap proxy.");
if (js.includes('graph.mapillary.com') || js.includes('overpass-api.de/api/interpreter') || js.includes('overpass.kumi.systems/api/interpreter')) {
  fail('the bundle contains a direct browser request to an upstream API; rebuild from current sources.');
}
console.log('[CivicRouteAD build check] PASS: current build marker and backend-proxy routes verified.');
