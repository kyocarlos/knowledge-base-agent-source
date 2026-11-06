#!/usr/bin/env node
// Switches the knowledge zone pages from the in-browser sample data to the real zone API (/api/zones/<zone>/..., served by KM).
//
//   node scripts/build_zone_live.js
//
// Reads the built pages in frontend/ (no rebuild from the WiFi page), writes:
//   frontend/zones/zones-live.<hash>.js   the zones' names and texts (no sample documents) and the hook that sends the pages' /api/wifi8/* calls
//                                         to /api/zones/<zone>/*
//   frontend/zones/<zone>/index.html      loads zones-live instead of zones-data + zones-mock
//   frontend/zones/hub.<hash>.js          the home page reads each zone's real overview and feed (like it already does for WiFi)
//   frontend/hub/islands.html             loads zones-live and the new home script
// Idempotent: running it again on its own output changes nothing.
'use strict';
const fs = require('fs');
const path = require('path');
const crypto = require('crypto');

const root = path.resolve(__dirname, '..', 'frontend');
const zonesDir = path.join(root, 'zones');
const blobHash = (buffer) => crypto.createHash('sha1').update(Buffer.concat([Buffer.from(`blob ${buffer.length}\0`), buffer])).digest('hex').slice(0, 12);
const read = (file) => fs.readFileSync(file, 'utf8');
const PAGES = ['mobile', 'broadband', 'cert', 'csit', 'equipment', 'lab', 'integrations'];   // the WiFi zone has its own page and API
const KEEP = ['id', 'label', 'assistant', 'short', 'brand', 'brandTitle', 'idLabel', 'sourceLabel', 'placeholder', 'example', 'feedKicker', 'feedTitle', 'timelineLabel'];
const EXAMPLE = {
  mobile: '這個專區有哪些 5G 或 Small Cell 的文件？', csit: '最近有哪些測試報告？換手測試的結果如何？', cert: 'NCC 與 CE 認證要準備什麼？',
  equipment: '頻譜分析儀多久校驗一次？', lab: '實驗室有哪些空間與環境規範？', integrations: '本週 Jira 與 TestRail 有哪些更新？', broadband: 'XGS-PON 與 GPON 有什麼差異？',
};

// ---- the zones' names and texts: from the newest sample data file the pages load (names only, never its documents)
const pageHtml = read(path.join(zonesDir, 'cert', 'index.html'));
const dataRef = pageHtml.match(/\/zones\/(zones-data\.[0-9a-f]{12}\.js)/) || pageHtml.match(/\/zones\/(zones-live\.[0-9a-f]{12}\.js)/);
if (!dataRef) throw new Error('the cert page loads neither zones-data nor zones-live');
let config;
if (dataRef[1].startsWith('zones-data')) {
  const sandbox = {};
  new Function('window', read(path.join(zonesDir, dataRef[1])))(sandbox);
  config = {};
  for (const id of PAGES) {
    const z = sandbox.KM_ZONES[id];
    if (!z) throw new Error(`no data for zone ${id}`);
    config[id] = Object.fromEntries(KEEP.filter((k) => k in z).map((k) => [k, z[k]]));
    config[id].idLabel = '文件代碼';
    config[id].placeholder = '輸入文件名稱或關鍵字…';
    config[id].example = EXAMPLE[id];
  }
} else {
  config = null;   // already switched: keep the file as it is
}

let liveFile = dataRef[1].startsWith('zones-live') ? dataRef[1] : null;
if (config) {
  const liveJs = `(() => {
'use strict';
// Names and texts of the knowledge zones, and the hook that sends the zone pages' /api/wifi8/* calls to the zone's own API.
window.KM_ZONES = ${JSON.stringify(config, null, 1)};
const zone = document.documentElement.dataset.zone;
if (zone) {
  if (!window.KM_ZONES[zone]) throw new Error('unknown zone ' + zone);
  window.KM_ZONE_CONFIG = Object.assign({ id: zone }, window.KM_ZONES[zone]);
  const realFetch = window.fetch.bind(window);
  window.fetch = (input, init) => {
    const raw = typeof input === 'string' ? input : input.url;
    const url = new URL(raw, location.origin);
    if (!url.pathname.startsWith('/api/wifi8/')) return realFetch(input, init);
    const target = '/api/zones/' + zone + '/' + url.pathname.slice('/api/wifi8/'.length) + url.search;
    return realFetch(typeof input === 'string' ? target : new Request(target, input), init);
  };
}
})();
`;
  liveFile = `zones-live.${blobHash(Buffer.from(liveJs))}.js`;
  fs.writeFileSync(path.join(zonesDir, liveFile), liveJs);
}

// ---- the seven zone pages
for (const id of PAGES) {
  const file = path.join(zonesDir, id, 'index.html');
  let html = read(file);
  html = html.replace(/[ \t]*<script src="\/zones\/zones-data\.[0-9a-f]{12}\.js" defer><\/script>\n/, '')
    .replace(/[ \t]*<script src="\/zones\/zones-mock\.[0-9a-f]{12}\.js" defer><\/script>\n/, `  <script src="/zones/${liveFile}" defer></script>\n`)
    .replace(/\/zones\/zones-live\.[0-9a-f]{12}\.js/, `/zones/${liveFile}`)
    .replace('示範資料 · 內容依目前匯入版本提供', '內容依目前匯入版本提供');
  if (!html.includes(liveFile)) throw new Error(`${id}: zones-live not wired`);
  fs.writeFileSync(file, html);
}

// ---- the home page: every zone's numbers and news come from its own API
const islands = path.join(root, 'hub', 'islands.html');
let islandsHtml = read(islands);
const hubRef = islandsHtml.match(/\/zones\/(hub\.[0-9a-f]{12}\.js)/);
let hubJs = read(path.join(zonesDir, hubRef[1]));
if (!hubJs.includes('summarizeZone')) {
  const sample = hubJs.indexOf('function summarizeSample(id)');
  const readApi = hubJs.indexOf('async function readApi(path)');
  if (sample < 0 || readApi < 0) throw new Error('hub script: summarizeSample / readApi not found');
  const wifiStart = hubJs.indexOf('async function summarizeWifi()');
  const wifiEnd = hubJs.indexOf('async function loadAll()');
  const wifi = hubJs.slice(wifiStart, wifiEnd);
  // summarizeWifi, made generic: the same two calls against the zone's own API
  const zoneFn = wifi.replace('async function summarizeWifi()', 'async function summarizeZone(id)')
    .replace("readApi('/api/wifi8/overview'), readApi('/api/wifi8/feed')", "readApi(`/api/zones/${id}/overview`), readApi(`/api/zones/${id}/feed`)")
    .split("'wifi'").join('id');
  if (zoneFn === wifi) throw new Error('hub script: summarizeWifi did not change');
  hubJs = hubJs.slice(0, sample) + hubJs.slice(readApi, wifiEnd) + wifi + zoneFn + hubJs.slice(wifiEnd);
  const load = "const out = {}; Object.keys(ZONES).forEach((id) => { out[id] = summarizeSample(id); });\n  out.wifi = await wifi;";
  if (!hubJs.includes(load)) throw new Error('hub script: loadAll not as expected');
  hubJs = hubJs.replace(load, "const out = {}; const ids = GROUPS.flatMap((g) => g.ids).filter((id) => id !== 'wifi');\n  const zones = await Promise.all(ids.map((id) => summarizeZone(id)));\n  ids.forEach((id, i) => { out[id] = zones[i]; });\n  out.wifi = await wifi;");
}
const hubFile = `hub.${blobHash(Buffer.from(hubJs))}.js`;
fs.writeFileSync(path.join(zonesDir, hubFile), hubJs);
islandsHtml = islandsHtml.replace(/[ \t]*<script src="\/zones\/zones-data\.[0-9a-f]{12}\.js" defer><\/script>\n/, `  <script src="/zones/${liveFile}" defer></script>\n`)
  .replace(/\/zones\/zones-live\.[0-9a-f]{12}\.js/, `/zones/${liveFile}`).replace(/\/zones\/hub\.[0-9a-f]{12}\.js/, `/zones/${hubFile}`);
fs.writeFileSync(islands, islandsHtml);
console.log(JSON.stringify({ liveFile, hubFile }, null, 1));
