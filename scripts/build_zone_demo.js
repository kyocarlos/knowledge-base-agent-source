#!/usr/bin/env node
// Builds the demo pages of the other knowledge zones from the WiFi zone page (frontend/wifi8/), which is only read, never changed.
//
//   node scripts/build_zone_demo.js
//
// Output (frontend/zones/): zone.<hash>.js (the WiFi page script with the zone's names and texts), zone.<hash>.css (a copy of the WiFi style sheet),
// zones-mock.<hash>.js (the browser-side stand-in for /api/wifi8/*), zones-data.<hash>.js (sample data of every zone) and <zone>/index.html.
// Every replacement must match the WiFi page exactly the expected number of times; if the WiFi page changes, this stops instead of producing a page
// that quietly differs from it.
'use strict';
const fs = require('fs');
const path = require('path');
const crypto = require('crypto');

const root = path.resolve(__dirname, '..', 'frontend');
const wifi = path.join(root, 'wifi8');
const src = path.join(root, 'zones', 'src');
const out = path.join(root, 'zones');

const blobHash = (buffer) => crypto.createHash('sha1').update(Buffer.concat([Buffer.from(`blob ${buffer.length}\0`), buffer])).digest('hex').slice(0, 12);
const read = (file) => fs.readFileSync(file, 'utf8').replace(/\r\n/g, '\n');

function replaceAll(text, rules, label) {
  let result = text;
  for (const [from, to, expected = 1] of rules) {
    const parts = result.split(from);
    if (parts.length - 1 !== expected) throw new Error(`${label}: expected ${expected} match(es) of ${JSON.stringify(from.slice(0, 70))}, found ${parts.length - 1}`);
    result = parts.join(to);
  }
  return result;
}

const wifiFiles = fs.readdirSync(wifi);
const jsName = wifiFiles.find((f) => /^wifi8\.[0-9a-f]{12}\.js$/.test(f));
const cssName = wifiFiles.find((f) => /^wifi8\.[0-9a-f]{12}\.css$/.test(f));
if (!jsName || !cssName) throw new Error('WiFi page assets not found');

const zoneJsRules = [
  ["  const navGroups = [", "  const ZONE = window.KM_ZONE_CONFIG;\n  const navGroups = ["],
  ["['ai', '♙', 'WiFi 知識助理', true]", "['ai', '♙', ZONE.assistant, true]"],
  ["ai: ['WiFi 知識助理', '使用現有 WiFi Agent 進行可追溯問答'],", "ai: [ZONE.assistant, `使用${ZONE.label}文件與 ${ZONE.short} Agent 進行可追溯問答`],"],
  ["research: ['研究主題', '建立與管理 WiFi 研究主題'],", "research: ['研究主題', `建立與管理 ${ZONE.short} 研究主題`],"],
  ["'wfa-downloads': ['WFA 下載', '管理 Wi-Fi Alliance 文件來源'],", "'wfa-downloads': ['文件下載', '管理文件來源'],"],
  ["settings: ['設定', '調整 WiFi 知識專區設定'],", "settings: ['設定', `調整${ZONE.label}設定`],"],
  ["$('#page-title').textContent = 'WiFi 知識專區';", "$('#page-title').textContent = ZONE.label;"],
  ["document.title = `${title} · WiFi 知識專區`;", "document.title = `${title} · ${ZONE.label}`;"],
  ['placeholder="ELR、NPCA、WFA ID…"', 'placeholder="${ZONE.placeholder}"'],
  ["hit.wfa_document_id ? `WFA ${hit.wfa_document_id}` : ''", "hit.wfa_document_id ? `${ZONE.idLabel} ${hit.wfa_document_id}` : ''"],
  ["item.wfa_document_id ? `WFA ${item.wfa_document_id}` : ''", "item.wfa_document_id ? `${ZONE.idLabel} ${item.wfa_document_id}` : ''"],
  ["['WFA ID',doc.wfa_document_id]", "[ZONE.idLabel,doc.wfa_document_id]"],
  ['placeholder="輸入中文短詞、縮寫或 WFA ID"', 'placeholder="輸入中文短詞、縮寫或${ZONE.idLabel}"'],
  ["${s.sources.wfa} 份 WFA・", "${s.sources.wfa} 份${ZONE.sourceLabel}・"],
  ["正在調用 WiFi Agent…", "正在調用 ${ZONE.short} Agent…"],
  ["panel('WiFi 知識助理', ", "panel(ZONE.assistant, "],
  ["我會使用 WiFi 專區的文件與版本關係回答，並保留引用與工具步驟。", "我會使用${ZONE.label}的文件與版本關係回答，並保留引用與工具步驟。"],
  ['placeholder="例如：ELR 的規格重點是什麼？"', 'placeholder="${ZONE.example}"'],
  ["'wifi8.conversation.v1'", "`km.zone.${ZONE.id}.conversation.v1`"],
  ['<span class="feed-kicker">Wi-Fi 8 Watch</span><h2>Wi-Fi 8 動態</h2>', '<span class="feed-kicker">${ZONE.feedKicker}</span><h2>${ZONE.feedTitle}</h2>'],
  ["IEEE 802.11bn (UHR) 進度", "${ZONE.timelineLabel}"],
  ["'<p class=\"feed-empty\">本週沒有符合 Wi-Fi 的新動態。</p>'", "`<p class=\"feed-empty\">本週沒有符合 ${ZONE.short} 的新動態。</p>`"],
  ["WiFi 專區已更新", "本專區已更新"],
];

const zoneJs = replaceAll(read(path.join(wifi, jsName)), zoneJsRules, 'zone.js');
const zoneJsFile = `zone.${blobHash(Buffer.from(zoneJs))}.js`;

const cssBuffer = fs.readFileSync(path.join(wifi, cssName));
const zoneCssFile = `zone.${blobHash(cssBuffer)}.css`;

const mockParts = fs.readdirSync(src).filter((f) => /^mock-\d+-.*\.js$/.test(f)).sort().map((f) => read(path.join(src, f)));
const mockJs = `(() => {\n'use strict';\n${mockParts.join('\n')}})();\n`;
const mockFile = `zones-mock.${blobHash(Buffer.from(mockJs))}.js`;

const dataParts = fs.readdirSync(src).filter((f) => /^data-.*\.js$/.test(f)).sort().map((f) => read(path.join(src, f)));
const dataJs = `window.KM_ZONES = window.KM_ZONES || {};\n${dataParts.join('\n')}`;
const dataFile = `zones-data.${blobHash(Buffer.from(dataJs))}.js`;

// Zone ids and texts come from the data files (the same objects the page reads at run time).
const sandbox = { window: {} };
new Function('window', dataJs)(sandbox.window);
const zones = sandbox.window.KM_ZONES;

const indexTemplate = read(path.join(wifi, 'index.html'));
const indexRules = (z) => [
  ['<html lang="zh-Hant">', `<html lang="zh-Hant" data-zone="${z.id}">`],
  ['<title>WiFi 知識專區</title>', `<title>${z.label}</title>`],
  ['/wifi8/wifi8.957774158ba4.css', `/zones/${zoneCssFile}`],
  ['aria-label="WiFi 知識專區導覽"', `aria-label="${z.label}導覽"`],
  ['aria-label="WiFi 知識專區首頁"', `aria-label="${z.label}首頁"`],
  ['<small>WiFi knowledge zone</small>', `<small>${z.brand}</small>`],
  ['<h1 id="page-title">WiFi 知識專區</h1>', `<h1 id="page-title">${z.label}</h1>`],
  ['正在讀取 WiFi 知識專區…', `正在讀取${z.label}…`],
  ['aria-label="Wi-Fi 8 動態"', `aria-label="${z.feedTitle}"`],
  ['<span>WiFi Knowledge Zone · KM DEV</span><span>內容依目前匯入版本提供</span>', `<span>${z.brandTitle} · KM DEV</span><span>示範資料 · 內容依目前匯入版本提供</span>`],
  ['WiFi 知識專區需要 JavaScript 才能顯示。', `${z.label}需要 JavaScript 才能顯示。`],
  ['<a class="back-link" href="/chat-v2.html">返回知識中樞</a>', '<a class="back-link" href="/hub/">返回知識中樞</a>'],
  [`<script src="/wifi8/${jsName}" defer></script>`, `<script src="/zones/${dataFile}" defer></script>\n  <script src="/zones/${mockFile}" defer></script>\n  <script src="/zones/${zoneJsFile}" defer></script>`],
];
if (!read(path.join(wifi, 'index.html')).includes('/wifi8/wifi8.957774158ba4.css')) throw new Error('WiFi index.html no longer uses the expected style sheet');

// Clean earlier output, then write.
// The home page (/hub/): its own script and style sheet, the zones' sample data and the WiFi style sheet.
const hubJs = `(() => {\n'use strict';\n${fs.readdirSync(src).filter((f) => /^hub-\d+-.*\.js$/.test(f)).sort().map((f) => read(path.join(src, f))).join('\n')}})();\n`;
const hubJsFile = `hub.${blobHash(Buffer.from(hubJs))}.js`;
const hubCss = read(path.join(src, 'hub.css'));
const hubCssFile = `hub.${blobHash(Buffer.from(hubCss))}.css`;
const hubHtml = replaceAll(read(path.join(src, 'hub-template.html')), [['{{BASECSS}}', zoneCssFile], ['{{HUBCSS}}', hubCssFile], ['{{DATA}}', dataFile], ['{{HUBJS}}', hubJsFile]], 'hub index');

for (const f of fs.readdirSync(out)) if (/^(zone|zones-mock|zones-data|hub)\.[0-9a-f]{12}\.(js|css)$/.test(f)) fs.unlinkSync(path.join(out, f));
fs.writeFileSync(path.join(out, hubJsFile), hubJs);
fs.writeFileSync(path.join(out, hubCssFile), hubCss);
fs.mkdirSync(path.join(root, 'hub'), { recursive: true });
fs.writeFileSync(path.join(root, 'hub', 'index.html'), hubHtml);
fs.writeFileSync(path.join(out, zoneJsFile), zoneJs);
fs.writeFileSync(path.join(out, zoneCssFile), cssBuffer);
fs.writeFileSync(path.join(out, mockFile), mockJs);
fs.writeFileSync(path.join(out, dataFile), dataJs);
for (const z of Object.values(zones)) {
  fs.mkdirSync(path.join(out, z.id), { recursive: true });
  fs.writeFileSync(path.join(out, z.id, 'index.html'), replaceAll(indexTemplate, indexRules(z), `index ${z.id}`));
}
console.log(JSON.stringify({ zones: Object.keys(zones), zoneJsFile, zoneCssFile, mockFile, dataFile }, null, 1));
