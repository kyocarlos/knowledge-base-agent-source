(() => {
'use strict';
// Home page of the knowledge zones (part 1 of 2): which zones exist, and what each one reports. scripts/build_zone_demo.js joins the parts into one script.
// WiFi is read from its real API; the other zones are summarised from the sample data in zones-data.js.
const ZONES = window.KM_ZONES || {};
const DAY = 86400000;
const GROUPS = [
  { label: '通訊與認證技術', ids: ['wifi', 'mobile', 'broadband', 'cert'] },
  { label: '驗證與實驗室資源', ids: ['csit', 'equipment', 'lab', 'integrations'] },
];
const META = {
  wifi: { label: 'WiFi 知識專區', icon: '⌁', tagline: 'Wi-Fi 8／802.11bn 規格與 WFA 文件問答', url: '/wifi8/', live: true },
  mobile: { icon: '◌', tagline: '3GPP 規範、LTE／5G NR，以及 CPE 與 Small Cell 技術文件' },
  broadband: { icon: '≋', tagline: 'PON／Cable 技術與 Broadband Forum 規範' },
  csit: { icon: '◈', tagline: 'CSIT 測試報告、申請單與測試計畫' },
  cert: { icon: '✦', tagline: 'Wi-Fi、藍牙、GCF、PTCRB 認證與法規' },
  integrations: { icon: '⌕', tagline: 'Confluence、Jira、TestRail 整合查詢' },
  equipment: { icon: '▣', tagline: '設備資訊、預約規範與校驗' },
  lab: { icon: '⚗', tagline: '實驗室規劃、建置與測試環境' },
  admin: { icon: '▤', tagline: '週報、工時、人事行政與請款' },
};
Object.keys(ZONES).forEach((id) => { META[id] = Object.assign({ label: ZONES[id].label, url: `/zones/${id}/`, live: false }, META[id]); });
// zone names as the menu and the islands show them
Object.assign(META.mobile, { label: '行動通訊知識專區' }); Object.assign(META.cert, { label: '認證知識專區' }); Object.assign(META.csit, { label: '產品驗證專區' }); Object.assign(META.equipment, { label: '設備儀器專區' }); Object.assign(META.lab, { label: '實驗室管理專區' });
const zoneUrl = (id, route = 'overview') => `${META[id].url}#/${route}`;

async function readApi(path) {
  const response = await fetch(path, { credentials: 'same-origin', headers: { Accept: 'application/json' } });
  if (response.status === 401) { location.assign('/login.html?next=%2Fhub%2F'); throw new Error('登入已過期'); }
  if (!response.ok) throw new Error(`HTTP ${response.status}`);
  return response.json();
}
async function summarizeWifi() {
  try {
    const [overview, feed] = await Promise.all([readApi('/api/wifi8/overview'), readApi('/api/wifi8/feed')]);
    const counts = overview.counts || {}; const updates = feed.updates || {};
    return {
      id: 'wifi', ok: true, current: Number(counts.current_documents || 0), history: Number(counts.superseded_documents || 0),
      events: (updates.events || []).map((e) => ({ zone: 'wifi', type: e.type, time: Date.parse(e.at) || 0, title: e.title || e.revision_id, publisher: e.publisher, role: e.document_role, version: e.version_label })),
      items: ((feed.digest || {}).items || []).map((i) => ({ zone: 'wifi', source: i.source_name, time: Date.parse(i.published) || 0, title: i.title, summary: i.summary || i.excerpt || '', older: i.older })),
      recent: (updates.recent || []).map((d) => ({ zone: 'wifi', title: d.title, publisher: d.publisher, role: d.document_role, date: d.document_date })),
      highlights: (feed.digest || {}).highlights || [],
      attention: (overview.attention || []).map((a) => ({ zone: 'wifi', level: a.level, title: a.title, detail: a.detail })),
    };
  } catch (_) { return { id: 'wifi', ok: false, events: [], items: [], recent: [], highlights: [], attention: [] }; }
}
async function summarizeWifi() {
  try {
    const [overview, feed] = await Promise.all([readApi('/api/wifi8/overview'), readApi('/api/wifi8/feed')]);
    const counts = overview.counts || {}; const updates = feed.updates || {};
    return {
      id: 'wifi', ok: true, current: Number(counts.current_documents || 0), history: Number(counts.superseded_documents || 0),
      events: (updates.events || []).map((e) => ({ zone: 'wifi', type: e.type, time: Date.parse(e.at) || 0, title: e.title || e.revision_id, publisher: e.publisher, role: e.document_role, version: e.version_label })),
      items: ((feed.digest || {}).items || []).map((i) => ({ zone: 'wifi', source: i.source_name, time: Date.parse(i.published) || 0, title: i.title, summary: i.summary || i.excerpt || '', older: i.older })),
      recent: (updates.recent || []).map((d) => ({ zone: 'wifi', title: d.title, publisher: d.publisher, role: d.document_role, date: d.document_date })),
      highlights: (feed.digest || {}).highlights || [],
      attention: (overview.attention || []).map((a) => ({ zone: 'wifi', level: a.level, title: a.title, detail: a.detail })),
    };
  } catch (_) { return { id: 'wifi', ok: false, events: [], items: [], recent: [], highlights: [], attention: [] }; }
}
async function summarizeZone(id) {
  try {
    const [overview, feed] = await Promise.all([readApi(`/api/zones/${id}/overview`), readApi(`/api/zones/${id}/feed`)]);
    const counts = overview.counts || {}; const updates = feed.updates || {};
    return {
      id: id, ok: true, current: Number(counts.current_documents || 0), history: Number(counts.superseded_documents || 0),
      events: (updates.events || []).map((e) => ({ zone: id, type: e.type, time: Date.parse(e.at) || 0, title: e.title || e.revision_id, publisher: e.publisher, role: e.document_role, version: e.version_label })),
      items: ((feed.digest || {}).items || []).map((i) => ({ zone: id, source: i.source_name, time: Date.parse(i.published) || 0, title: i.title, summary: i.summary || i.excerpt || '', older: i.older })),
      recent: (updates.recent || []).map((d) => ({ zone: id, title: d.title, publisher: d.publisher, role: d.document_role, date: d.document_date })),
      highlights: (feed.digest || {}).highlights || [],
      attention: (overview.attention || []).map((a) => ({ zone: id, level: a.level, title: a.title, detail: a.detail })),
    };
  } catch (_) { return { id: id, ok: false, events: [], items: [], recent: [], highlights: [], attention: [] }; }
}
async function loadAll() {
  const wifi = summarizeWifi();
  const out = {}; const ids = GROUPS.flatMap((g) => g.ids).filter((id) => id !== 'wifi');
  const zones = await Promise.all(ids.map((id) => summarizeZone(id)));
  ids.forEach((id, i) => { out[id] = zones[i]; });
  out.wifi = await wifi;
  Object.values(out).forEach((s) => { s.week = s.events.filter((e) => Date.now() - e.time <= 7 * DAY).length; s.latest = s.events.slice().sort((a, b) => b.time - a.time)[0] || null; });
  return out;
}

// Home page of the knowledge zones (part 1.5 of 3): the zone cards as an archipelago. Every zone is an island with its own "library"; a click shows the
// zone's numbers beside the map, the label links to the zone. The numbers come from hub.data (the same data the cards used). The drawing is plain SVG:
// no 3D library, no image files, and every island is a real link, so keyboard and screen readers work.
const Islands = (() => {
  const R = 74, K = 0.56, GAP = 1.3, T = 20;
  const esc = (s) => String(s).replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  const pts = (list) => list.map((p) => p[0].toFixed(1) + ',' + p[1].toFixed(1)).join(' ');
  const hex = (s = 1) => [0, 1, 2, 3, 4, 5].map((i) => { const a = Math.PI / 3 * i; return [R * s * Math.cos(a), R * s * Math.sin(a) * K]; });
  const shade = (hexColor, f) => { const n = parseInt(hexColor.slice(1), 16); const c = (v) => Math.max(0, Math.min(255, Math.round(v * f))); return `rgb(${c(n >> 16)},${c((n >> 8) & 255)},${c(n & 255)})`; };

  function roof(x, y, w, h, rh, color) {
    const top = y - h, apex = [x, top - w * 0.5 - rh];
    const left = [[x - w, top - w * 0.5], [x, top], apex], right = [[x, top], [x + w, top - w * 0.5], apex];
    return `<polygon points="${pts(left)}" fill="${shade(color, .82)}"/><polygon points="${pts(right)}" fill="${color}"/>`;
  }
  const tree = (x, y, s = 1) => `<rect x="${x - 2 * s}" y="${y - 12 * s}" width="${4 * s}" height="${12 * s}" fill="var(--trunk)"/><ellipse cx="${x}" cy="${y + 1}" rx="${9 * s}" ry="${3.5 * s}" fill="var(--shadow)"/>`
    + `<circle cx="${x}" cy="${y - 20 * s}" r="${11 * s}" fill="var(--leaf)"/><circle cx="${x - 3 * s}" cy="${y - 23 * s}" r="${7 * s}" fill="var(--leaf2)"/>`;
  const pine = (x, y, s = 1) => `<ellipse cx="${x}" cy="${y + 1}" rx="${8 * s}" ry="${3 * s}" fill="var(--shadow)"/><path d="M${x},${y - 34 * s} L${x + 10 * s},${y - 10 * s} L${x - 10 * s},${y - 10 * s} Z" fill="var(--leaf2)"/><path d="M${x},${y - 24 * s} L${x + 12 * s},${y} L${x - 12 * s},${y} Z" fill="var(--leaf)"/>`;
  /* ---- libraries: one per zone, each with its own style and a sculpture that says what the zone is about ---- */
  const box = (x, y, wl, wr, h, wall, wall2) => `<polygon points="${pts([[x - wl, y - wl * .5], [x, y], [x, y - h], [x - wl, y - h - wl * .5]])}" fill="${wall2}"/><polygon points="${pts([[x, y], [x + wr, y - wr * .5], [x + wr, y - h - wr * .5], [x, y - h]])}" fill="${wall}"/>`;
  const cube = (x, y, w, h, a = 'var(--wall)', b = 'var(--wall2)') => box(x, y, w, w, h, a, b);
  const topFace = (x, y, wl, wr, h, fill) => { const t = y - h; return `<polygon points="${pts([[x - wl, t - wl * .5], [x, t], [x + wr, t - wr * .5], [x + wr - wl, t - wr * .5 - wl * .5]])}" fill="${fill}"/>`; };
  const rq = (x, y, w, u0, u1, v0, v1, fill) => { const f = (u, v) => [x + w * u, y - w * .5 * u - v]; return `<polygon points="${pts([f(u0, v0), f(u1, v0), f(u1, v1), f(u0, v1)])}" fill="${fill}"/>`; };
  const lq = (x, y, w, u0, u1, v0, v1, fill) => { const f = (u, v) => [x - w * u, y - w * .5 * u - v]; return `<polygon points="${pts([f(u0, v0), f(u1, v0), f(u1, v1), f(u0, v1)])}" fill="${fill}"/>`; };
  const cols = (face, x, y, w, n, v0, v1, fill) => Array.from({ length: n }, (_, i) => face(x, y, w, (i + .3) / n, (i + .62) / n, v0, v1, fill)).join('');
  const cyl = (x, y, r, h, a = 'var(--wall)', b = 'var(--wall2)') => `<path d="M${x - r},${y - h} L${x - r},${y} A${r},${r * .4} 0 0 0 ${x + r},${y} L${x + r},${y - h} Z" fill="${a}"/><path d="M${x - r},${y - h} L${x - r},${y} A${r},${r * .4} 0 0 0 ${x},${y + r * .4} L${x},${y - h} Z" fill="${b}"/>`;
  const line = (x1, y1, x2, y2, c, w = 1.4) => `<line x1="${x1}" y1="${y1}" x2="${x2}" y2="${y2}" stroke="${c}" stroke-width="${w}" stroke-linecap="round"/>`;
  const wifiMark = (cx, cy, s, c, sw = 1.6) => [1, 2, 3].map((k) => { const r = s * k * 3.4, d = r * .707; return `<path d="M${cx - d},${cy - d} A${r},${r} 0 0 1 ${cx + d},${cy - d}" fill="none" stroke="${c}" stroke-width="${sw}" stroke-linecap="round"/>`; }).join('') + `<circle cx="${cx}" cy="${cy}" r="${1.6 * s}" fill="${c}"/>`;
  const star = (cx, cy, r, c) => `<polygon points="${pts(Array.from({ length: 10 }, (_, i) => { const a = -Math.PI / 2 + i * Math.PI / 5, q = i % 2 ? r * .45 : r; return [cx + q * Math.cos(a), cy + q * Math.sin(a)]; }))}" fill="${c}"/>`;
  const gear = (x, y, r, c) => Array.from({ length: 8 }, (_, i) => `<rect x="-1.7" y="${-r - 2.4}" width="3.4" height="4.6" fill="${c}" transform="translate(${x},${y}) rotate(${i * 45})"/>`).join('') + `<circle cx="${x}" cy="${y}" r="${r}" fill="${c}"/><circle cx="${x}" cy="${y}" r="${r * .42}" fill="var(--top)"/>`;
  const DARK = '#27434a', GLASS = '#7fcbe6', GOLD = '#f2b632';

  const BUILD = {
    /* Wi-Fi: glass pavilion with an access point (disc, antennas, signal arcs) on the roof */
    wifi: (x, y, g) => box(x, y, 19, 19, 20, 'var(--wall)', 'var(--wall2)') + rq(x, y, 19, .1, .9, 5, 16, GLASS) + [1, 2, 3].map((k) => rq(x, y, 19, k * .225 - .012, k * .225 + .012, 5, 16, '#e6f4f8')).join('')
      + lq(x, y, 19, .15, .85, 5, 16, '#5fb4d3') + topFace(x, y, 19, 19, 20, g.rim)
      + `<rect x="${x - 1.3}" y="${y - 39}" width="2.6" height="10" fill="#b9c7cb"/><ellipse cx="${x}" cy="${y - 40}" rx="11" ry="4" fill="#dfe9eb"/><ellipse cx="${x}" cy="${y - 41.5}" rx="10" ry="3.1" fill="#fff"/><circle cx="${x + 5.5}" cy="${y - 40.4}" r="1" fill="#4cd964"/>`
      + line(x - 7, y - 42, x - 10, y - 50, '#cfd8dc', 1.8) + line(x + 7, y - 42, x + 10, y - 50, '#cfd8dc', 1.8) + wifiMark(x, y - 47, .95, '#ffd36b'),
    /* 4G/5G: hall with a lattice base-station mast, sector panels and signal waves */
    mobile: (x, y, g) => {
      const top = y - 16 - 10, h = 46, w0 = 7, w1 = 1.3, wi = (k) => w0 + (w1 - w0) * k;
      let m = '';
      for (let i = 0; i < 5; i++) { const a = i / 5, b = (i + 1) / 5, ya = top - h * a, yb = top - h * b; m += line(x - wi(a), ya, x + wi(b), yb, '#dbe5e8', 1) + line(x + wi(a), ya, x - wi(b), yb, '#dbe5e8', 1); }
      return cube(x, y, 20, 16) + cols(rq, x, y, 20, 4, 0, 14, '#f4f7f6') + rq(x, y, 20, .38, .62, 0, 8, DARK) + topFace(x, y, 20, 20, 16, '#e6dcc3')
        + `<polygon points="${pts([[x - w0, top], [x - w1, top - h], [x + w1, top - h], [x + w0, top]])}" fill="none" stroke="#dbe5e8" stroke-width="1.5"/>` + m
        + `<rect x="${x - 7}" y="${top - h + 3}" width="3.6" height="9" fill="${g.roof}"/><rect x="${x + 3.4}" y="${top - h + 3}" width="3.6" height="9" fill="${g.roof}"/><circle cx="${x}" cy="${top - h - 2}" r="1.8" fill="#ff5a4f"/>`
        + [1, 2].map((k) => `<path d="M${x + 8 + k * 4},${top - h + 2} A${k * 5},${k * 5} 0 0 1 ${x + 8 + k * 4},${top - h + 12}" fill="none" stroke="#ffd36b" stroke-width="1.4" stroke-linecap="round"/><path d="M${x - 8 - k * 4},${top - h + 2} A${k * 5},${k * 5} 0 0 0 ${x - 8 - k * 4},${top - h + 12}" fill="none" stroke="#ffd36b" stroke-width="1.4" stroke-linecap="round"/>`).join('');
    },
    /* Broadband: long arched hall with a fibre cable reel and an orange fibre running to the door */
    broadband: (x0, y, g) => {
      const x = x0 - 6;
      return box(x, y, 12, 28, 14, 'var(--wall)', 'var(--wall2)') + [0, 1, 2, 3].map((i) => rq(x, y, 28, .08 + i * .22, .24 + i * .22, 3, 11, DARK) + rq(x, y, 28, .08 + i * .22, .24 + i * .22, 11, 12.4, '#cfe3e8')).join('')
        + topFace(x, y, 12, 28, 14, g.roof)
        + `<path d="M${x - 14},${y + 10} C${x - 4},${y + 14} ${x + 4},${y + 6} ${x + 10},${y + 1}" fill="none" stroke="#ffb74d" stroke-width="1.6" stroke-linecap="round"/><circle cx="${x + 10}" cy="${y + 1}" r="2" fill="#ffe08a"/>`
        + `<ellipse cx="${x - 22}" cy="${y + 14}" rx="9" ry="3" fill="var(--shadow)"/><circle cx="${x - 22}" cy="${y + 4}" r="10" fill="${g.roof}"/><circle cx="${x - 22}" cy="${y + 4}" r="7.2" fill="${shade(g.roof, .75)}"/><circle cx="${x - 22}" cy="${y + 4}" r="5.2" fill="none" stroke="#ffb74d" stroke-width="1.4"/><circle cx="${x - 22}" cy="${y + 4}" r="3.3" fill="none" stroke="#ffb74d" stroke-width="1.2"/><circle cx="${x - 22}" cy="${y + 4}" r="1.6" fill="#e9f2f3"/>`;
    },
    /* CSIT: stepped test-lab library with a clipboard / checklist statue */
    csit: (x, y, g) => cube(x, y, 18, 14) + rq(x, y, 18, .36, .64, 0, 8, DARK) + cols(lq, x, y, 18, 3, 3, 11, '#f4f7f6') + topFace(x, y, 18, 18, 14, '#e6dcc3')
      + cube(x, y - 18, 10, 9) + rq(x, y - 18, 10, .2, .8, 2, 6, GLASS) + topFace(x, y - 18, 10, 10, 9, g.roof)
      + cube(x - 30, y + 4, 5, 4, '#cfd9dc', '#b5c2c6') + `<rect x="${x - 37}" y="${y - 18}" width="14" height="18" rx="2" fill="#7a5a34"/><rect x="${x - 35.5}" y="${y - 16}" width="11" height="14" fill="#fff"/><rect x="${x - 33}" y="${y - 19.4}" width="6" height="3.4" rx="1" fill="#9aa7ab"/>`
      + `<polyline points="${x - 34},${y - 10} ${x - 32.2},${y - 8} ${x - 29},${y - 13}" fill="none" stroke="#2fb67c" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/>${line(x - 29, y - 7, x - 26, y - 7, '#b9c7cb', 1.2)}${line(x - 34, y - 5, x - 26, y - 5, '#b9c7cb', 1.2)}`,
    /* Certification: Greek-style temple with a medal and ribbon on the pediment */
    cert: (x, y, g) => cube(x, y, 20, 13) + cols(rq, x, y, 20, 6, 0, 13, '#fbf8ef') + cols(lq, x, y, 20, 4, 0, 13, '#e4ddc8') + topFace(x, y, 20, 20, 13, '#efe6cf')
      + roof(x, y, 21, 13, 9, '#e8dcc0') + `<path d="M${x - 5},${y - 38} L${x - 8},${y - 29} L${x - 3},${y - 31} L${x - 1},${y - 28} Z" fill="#d8403a"/><path d="M${x + 5},${y - 38} L${x + 8},${y - 29} L${x + 3},${y - 31} L${x + 1},${y - 28} Z" fill="#b8312d"/>`
      + `<circle cx="${x}" cy="${y - 41}" r="8" fill="${GOLD}"/><circle cx="${x}" cy="${y - 41}" r="5.8" fill="#ffd66b"/>` + star(x, y - 41, 4.2, '#d08a12'),
    /* Integrations: twin towers linked by a skywalk, with a three-node network on top */
    integrations: (x, y, g) => box(x + 14, y - 3, 9, 9, 26, 'var(--wall)', 'var(--wall2)') + roof(x + 14, y - 3, 9, 26, 8, g.roof) + rq(x + 14, y - 3, 9, .3, .7, 8, 20, GLASS)
      + `<polygon points="${pts([[x - 6, y - 12], [x + 5, y - 17.5], [x + 5, y - 14], [x - 6, y - 8.5]])}" fill="#dbe5e8"/>`
      + box(x - 14, y + 3, 9, 9, 26, 'var(--wall)', 'var(--wall2)') + roof(x - 14, y + 3, 9, 26, 8, g.roof) + rq(x - 14, y + 3, 9, .3, .7, 8, 20, GLASS)
      + line(x - 14, y - 42, x + 14, y - 48, '#9fd8cc', 1.4) + line(x - 14, y - 42, x, y - 56, '#9fd8cc', 1.4) + line(x + 14, y - 48, x, y - 56, '#9fd8cc', 1.4)
      + `<circle cx="${x - 14}" cy="${y - 42}" r="3.6" fill="#ff9d4d"/><circle cx="${x + 14}" cy="${y - 48}" r="3.6" fill="#4aa8ff"/><circle cx="${x}" cy="${y - 56}" r="3.6" fill="#4cd7a0"/>`,
    /* Equipment: industrial hall with a saw-tooth roof, a gear and a booking calendar */
    equipment: (x0, y, g) => {
      const x = x0 - 4;
      return box(x, y, 14, 22, 14, 'var(--wall)', 'var(--wall2)') + rq(x, y, 22, .12, .42, 0, 9, '#8f9fa3') + [0, 1, 2].map((i) => rq(x, y, 22, .52 + i * .15, .62 + i * .15, 4, 10, GLASS)).join('')
        + topFace(x, y, 14, 22, 14, '#cfd9dc') + [.2, .55, .9].map((u) => { const px = x + 22 * u, py = y - 14 - 11 * u; return `<polygon points="${pts([[px - 7, py], [px + 7, py - 9], [px + 7, py]])}" fill="${g.roof}"/>`; }).join('')
        + `<rect x="${x - 3}" y="${y - 44}" width="2.4" height="22" fill="#b9c7cb"/>` + gear(x - 2, y - 46, 7.5, '#ffcf5a')
        + `<rect x="${x - 29}" y="${y - 14}" width="13" height="14" rx="1.5" fill="#fff"/><rect x="${x - 29}" y="${y - 14}" width="13" height="4.4" rx="1.5" fill="#e4503f"/>` + [0, 1, 2].flatMap((r) => [0, 1, 2].map((c) => `<rect x="${x - 27.5 + c * 3.8}" y="${y - 8 + r * 2.8}" width="2.2" height="1.6" fill="#8aa0a5"/>`)).join('');
    },
    /* Lab: observatory-style library (dome with a slit) and a conical flask sculpture */
    lab: (x, y, g) => cube(x, y, 16, 12) + rq(x, y, 16, .36, .64, 0, 8, DARK) + lq(x, y, 16, .25, .75, 4, 9, GLASS) + topFace(x, y, 16, 16, 12, '#e6dcc3')
      + `<ellipse cx="${x}" cy="${y - 20}" rx="14" ry="5.6" fill="var(--wall2)"/><path d="M${x - 14},${y - 20} A14,14 0 0 1 ${x + 14},${y - 20} Z" fill="#e9f1f2"/><path d="M${x},${y - 34} A14,14 0 0 1 ${x + 14},${y - 20} L${x},${y - 20} Z" fill="#cdd9dc"/><path d="M${x + 1},${y - 33.6} L${x + 5},${y - 31} L${x + 5},${y - 21} L${x + 1},${y - 21} Z" fill="${DARK}"/>` + line(x + 3, y - 31, x + 9, y - 39, '#9aa7ab', 3)
      + cube(x + 28, y + 3, 5, 3, '#cfd9dc', '#b5c2c6') + `<path d="M${x + 25},${y - 26} L${x + 31},${y - 26} L${x + 31},${y - 17} L${x + 39},${y - 2} L${x + 17},${y - 2} L${x + 25},${y - 17} Z" fill="rgba(210,242,252,.85)" stroke="#9fd0e0" stroke-width="1"/>`
      + `<path d="M${x + 20},${y - 7} L${x + 36},${y - 7} L${x + 39},${y - 2} L${x + 17},${y - 2} Z" fill="#4cd7a0"/><circle cx="${x + 26}" cy="${y - 11}" r="1.6" fill="#b8f3da"/><circle cx="${x + 31}" cy="${y - 14}" r="1.1" fill="#b8f3da"/>`,
    /* Admin: clock-tower library with a filing cabinet */
    admin: (x, y, g) => cube(x, y, 18, 14) + rq(x, y, 18, .36, .64, 0, 8, DARK) + cols(lq, x, y, 18, 3, 3, 11, '#f4f7f6') + topFace(x, y, 18, 18, 14, '#e6dcc3')
      + box(x, y - 19, 8, 8, 18, 'var(--wall)', 'var(--wall2)') + roof(x, y - 19, 8, 18, 9, g.roof) + `<circle cx="${x + 4}" cy="${y - 33}" r="4.4" fill="#fff" stroke="#8aa0a5" stroke-width=".8"/>${line(x + 4, y - 33, x + 4, y - 36, '#27434a', 1)}${line(x + 4, y - 33, x + 6.4, y - 32, '#27434a', 1)}`
      + box(x + 30, y + 2, 5, 5, 15, '#9db0b6', '#869ba2') + [0, 1, 2].map((i) => rq(x + 30, y + 2, 5, .15, .85, 2 + i * 4.2, 4.6 + i * 4.2, '#c2d0d4')).join('') + [0, 1, 2].map((i) => rq(x + 30, y + 2, 5, .4, .6, 3.2 + i * 4.2, 3.9 + i * 4.2, '#59707a')).join(''),
  };
  /* CPE and Small Cell live in the 4G/5G zone: a little home router and a pole-mounted small cell stand beside its base-station library. */
  const baseStation = BUILD.mobile;
  BUILD.mobile = (x, y, g) => baseStation(x, y, g)
    + cube(x - 34, y + 8, 6, 3, '#f4f7f6', '#cfd9dc') + topFace(x - 34, y + 8, 6, 6, 3, '#fff') + line(x - 36.5, y - 1, x - 39, y - 11, '#eef3f4', 1.6) + line(x - 31.5, y - 1.5, x - 29, y - 11.5, '#eef3f4', 1.6)
    + `<circle cx="${x - 32}" cy="${y + 3.6}" r=".8" fill="#4cd964"/>`
    + `<rect x="${x + 33}" y="${y - 13}" width="2" height="22" fill="#b9c7cb"/><rect x="${x + 28.5}" y="${y - 27}" width="11" height="15" rx="4" fill="#f4f7f6"/><rect x="${x + 28.5}" y="${y - 22}" width="11" height="2.4" fill="#3fcf8e"/>`
    + [1, 2].map((k) => `<path d="M${x + 41 + k * 3},${y - 24} A${k * 4},${k * 4} 0 0 1 ${x + 41 + k * 3},${y - 16}" fill="none" stroke="#ffd36b" stroke-width="1.3" stroke-linecap="round"/>`).join('');
  const LAYOUT = [
    { b: [-4, -14], t: [[-48, 8, .9], [50, 2, .8]], p: [[54, -14, .8]] }, { b: [4, -16], t: [[-50, 4, 1]], p: [[48, 8, .9], [-40, -12, .7]] },
    { b: [-6, -12], t: [[50, -4, .9], [44, 14, .7]], p: [[-52, 6, .9]] }, { b: [2, -14], t: [[-46, 10, .9]], p: [[50, -6, 1]] },
  ];


  /* ---- the zones as islands ---- */
  const THEMES = [{ rim: '#2f9bd4', roof: '#e4673d' }, { rim: '#e0a82e', roof: '#8a72c0' }, { rim: '#e0603f', roof: '#2f78b0' }];  // one per group of GROUPS
  const SLOTS = { wifi: [0, -1], mobile: [1, -1], broadband: [1, 0], csit: [-1, 0], cert: [-1, 1], integrations: [0, 0], equipment: [0, 1], lab: [1, 1], admin: [0, 2] };
  const SHORT = { integrations: 'Jira / TestRail', lab: '實驗室管理' };
  const state = { selected: 'wifi' };
  const GEO = {};         // where each island's library stands, so the visitors keep clear of it
  let showIsland = null;  // set by bind(): selects an island and shows its numbers
  const groupIndex = (id) => Math.max(0, GROUPS.findIndex((g) => g.ids.includes(id)));
  const theme = (id) => ({ ...THEMES[groupIndex(id)] });
  const shortName = (id) => SHORT[id] || META[id].label.replace(' 知識專區', '').replace('知識專區', '').replace('專區', '');
  const todo = (id) => (hub.data[id] && hub.data[id].ok ? hub.data[id].attention.length : 0);
  const ids = () => GROUPS.flatMap((g) => g.ids).filter((id) => SLOTS[id] && hub.data[id]);

  function island(id, cx, cy, index) {
    const g = theme(id), top = hex(1), grass = hex(.84), L = LAYOUT[index % LAYOUT.length], s = hub.data[id], warn = todo(id);
    const side = (a, b, dy, fill) => `<polygon points="${pts([top[a], top[b], [top[b][0], top[b][1] + dy], [top[a][0], top[a][1] + dy]])}" fill="${fill}"/>`;
    let svg = `<ellipse cx="0" cy="${T + 12}" rx="${R * 1.05}" ry="${R * K * 1.1}" fill="var(--shadow)"/>`;
    svg += side(2, 3, T, 'var(--base)') + side(1, 2, T, 'var(--base2)') + side(0, 1, T, 'var(--base3)');
    svg += side(2, 3, 6, g.rim) + side(1, 2, 6, shade(g.rim, .82)) + side(0, 1, 6, shade(g.rim, .66));
    svg += `<polygon points="${pts(top)}" fill="var(--top)"/><polygon points="${pts(top)}" fill="none" stroke="${g.rim}" stroke-width="2.5" stroke-linejoin="round"/><polygon points="${pts(grass)}" fill="var(--grass)"/>`;
    GEO[id] = { bx: L.b[0], by: L.b[1] };
    const things = [{ y: L.b[1], s: `<g transform="translate(${L.b[0]} ${L.b[1]}) scale(.8) translate(${-L.b[0]} ${-L.b[1]})">${BUILD[id](L.b[0], L.b[1], g)}</g>` }];
    L.t.forEach(([x, y, k]) => things.push({ y, s: tree(x, y, k) }));
    L.p.forEach(([x, y, k]) => things.push({ y, s: pine(x, y, k) }));
    svg += things.sort((a, b) => a.y - b.y).map((t) => t.s).join('');
    svg += `<g class="isl-people" data-island="${id}"></g>`;
    const text = shortName(id), w = Math.max(70, [...text].reduce((n, c) => n + (c.charCodeAt(0) > 255 ? 14 : 8), 0) + 28), at = `translate(${cx.toFixed(1)},${cy.toFixed(1)})`, down = s && !s.ok;
    const url = zoneUrl(id);
    const label = `<a class="isl-hit isl-label${down ? ' down' : ''}" href="${esc(url)}" data-id="${id}" aria-label="${esc(META[id].label)}${warn ? `，待處理 ${warn} 項` : ''}" transform="${at}"><g class="isl-lab" transform="translate(0,27)"><rect x="${-w / 2}" y="-13" width="${w}" height="26" rx="13"/><text y="5">${esc(text)}</text></g>`
      + (warn ? `<g class="isl-badge" transform="translate(${w / 2 - 2},17)"><circle r="9"/><text y="4">${warn}</text></g>` : '') + (META[id].live ? `<circle class="isl-live" cx="${-w / 2 + 2}" cy="27" r="4"/>` : '') + '</a>';
    const body = `<a class="isl-hit isl-body${down ? ' down' : ''}" href="${esc(url)}" data-id="${id}" tabindex="-1" aria-hidden="true" transform="${at}"><g class="isl-lift">${svg}</g></a>`;
    return { body, label };
  }

  function scene() {
    const placed = ids().map((id) => { const [q, r] = SLOTS[id]; return { id, cx: 1.5 * R * q * GAP, cy: Math.sqrt(3) * R * (r + q / 2) * K * GAP }; }).sort((a, b) => a.cy - b.cy || a.cx - b.cx);
    const minX = Math.min(...placed.map((p) => p.cx)) - R - 40, maxX = Math.max(...placed.map((p) => p.cx)) + R + 40;
    const minY = Math.min(...placed.map((p) => p.cy)) - 80, maxY = Math.max(...placed.map((p) => p.cy)) + T + R * K + 60;
    const ripples = [[-.55, .5, 150], [.6, -.35, 190], [.1, 1.05, 130]].map(([fx, fy, rx]) => `<ellipse class="isl-ripple" cx="${minX + (maxX - minX) * (.5 + fx / 2)}" cy="${minY + (maxY - minY) * (.5 + fy / 2)}" rx="${rx}" ry="${rx * .28}"/>`).join('');
    const drawn = placed.map((p, i) => island(p.id, p.cx, p.cy, i));
    return `<svg class="isl-scene" viewBox="${minX} ${minY} ${maxX - minX} ${maxY - minY}" preserveAspectRatio="xMidYMid meet" role="group" aria-label="知識專區群島">${ripples}${drawn.map((d) => d.body).join('')}${drawn.map((d) => d.label).join('')}</svg>`;
  }

  function detail(id) {
    const m = META[id], s = hub.data[id], warn = todo(id);
    const stat = (value, name, tone = '') => `<div class="hub-stat ${tone}"><strong>${s.ok ? num(value) : '—'}</strong><small>${name}</small></div>`;
    const latest = !s.ok ? '暫時無法讀取這個專區的資料' : s.latest ? `最新：${esc(s.latest.title)}（${day(s.latest.time)}）` : '近期沒有更新';
    return `<div class="isl-d1"><p class="isl-eyebrow">${esc(GROUPS[groupIndex(id)].label)}</p><h3 id="isl-modal-title">${esc(m.label)} <span class="hub-tag ${m.live ? 'live' : 'demo'}">${m.live ? '即時' : '示範'}</span></h3><p class="isl-tagline">${esc(m.tagline)}</p><p class="hub-latest">${latest}</p><p class="isl-crowd"></p></div>
      <div class="isl-d2"><div class="hub-stats">${stat(s.current, '有效來源檔案')}${stat(s.history, '舊版來源檔案')}${stat(s.week, '本週更新')}${stat(warn, '待處理', s.ok && s.attention.some((a) => a.level === 'warning') ? 'warn' : '')}</div>
      <div class="hub-actions"><a class="primary-button" href="${zoneUrl(id)}">進入專區</a><a class="secondary-button" href="${zoneUrl(id, 'ai')}">直接提問</a></div></div>`;
  }

  /* The markup of the whole block; bind() makes it live once it is in the page. */
  function html() {
    const legend = GROUPS.map((g, i) => `<span><i style="background:${THEMES[i].rim}"></i>${esc(g.label)}</span>`).join('');
    const list = ids().map((id) => `<li><a href="${zoneUrl(id)}"><span class="isl-dot" style="background:${theme(id).rim}"></span><span>${esc(META[id].label)}</span>${todo(id) ? `<em>${todo(id)}</em>` : ''}</a></li>`).join('');  // shown only on narrow screens, where the map is hidden
    if (!hub.data[state.selected]) state.selected = 'wifi';
    return `<div class="isl-stage"><div class="isl-map">${scene()}<div class="isl-legend">${legend}</div></div></div><ul class="isl-list">${list}</ul>`;
  }

  function bind(root) {
    const map = root.querySelector('.isl-map'); if (!map) return;
    let modal = document.getElementById('isl-modal');
    if (!modal) {
      modal = document.createElement('div');
      modal.id = 'isl-modal'; modal.className = 'pp-modal isl-modal'; modal.hidden = true;
      modal.setAttribute('role', 'dialog'); modal.setAttribute('aria-modal', 'true'); modal.setAttribute('aria-labelledby', 'isl-modal-title');
      modal.innerHTML = '<div class="pp-sheet"></div>';
      document.body.appendChild(modal);
      modal.addEventListener('click', (e) => { if (e.target === modal || e.target.closest('[data-close]')) modal.hidden = true; });
      document.addEventListener('keydown', (e) => { if (e.key === 'Escape') modal.hidden = true; });
    }
    const show = (id, visit = false) => {
      if (!hub.data[id]) return;
      state.selected = id;
      map.querySelectorAll('.isl-hit').forEach((n) => n.classList.toggle('on', n.dataset.id === id));
      People.select(id, visit);
    };
    const open = (id) => {
      if (!hub.data[id]) return;
      modal.querySelector('.pp-sheet').innerHTML = `<button type="button" class="pp-x" data-close aria-label="關閉">×</button>${detail(id)}<p class="isl-hint">小提示：在島上快速點兩下，可以直接進入專區。</p>`;
      modal.hidden = false;
      show(id, true);
      modal.querySelector('[data-close]').focus();
    };
    const hot = (e, on) => { const a = e.target.closest && e.target.closest('.isl-hit'); if (a) map.querySelectorAll(`.isl-hit[data-id="${a.dataset.id}"]`).forEach((n) => n.classList.toggle('hot', on)); };
    let pending = 0;  // the dialog waits a moment, so that the second click of a double click still lands on the island
    map.addEventListener('click', (e) => { const a = e.target.closest('.isl-hit'); if (!a) return; e.preventDefault(); const id = a.dataset.id; show(id, true); clearTimeout(pending); pending = setTimeout(() => open(id), 260); });
    map.addEventListener('dblclick', (e) => { const a = e.target.closest('.isl-hit'); if (a) { clearTimeout(pending); location.assign(a.getAttribute('href')); } });
    map.addEventListener('keydown', (e) => { const a = e.target.closest('.isl-hit'); if (a && e.key === ' ') { e.preventDefault(); open(a.dataset.id); } });  // Enter follows the link, Space looks at it
    map.addEventListener('focusin', (e) => { const a = e.target.closest && e.target.closest('.isl-label'); if (a) show(a.dataset.id); });
    map.addEventListener('mouseover', (e) => hot(e, true));
    map.addEventListener('mouseout', (e) => hot(e, false));
    showIsland = show;
    show(state.selected);
    People.attach(map);
    pushStats();
  }

  /* The keeper (a frame on the same page) only needs to know which islands have news; the numbers are the ones the page already shows. */
  function pushStats() {
    const frame = document.querySelector('.hub-assistant-frame');
    if (!frame || !frame.contentWindow) return;
    const stats = {};
    ids().forEach((id) => { const s = hub.data[id]; stats[id] = { week: s.ok ? s.week : 0, todo: todo(id) }; });
    frame.contentWindow.postMessage({ type: 'km-keeper-stats', stats }, location.origin);
  }

  /* "Take me there": select the island, bring it into view and make it bounce a few times. */
  function focus(id) {
    if (!showIsland || !SLOTS[id] || !hub.data[id]) return;
    showIsland(id, true);
    const map = document.querySelector('.isl-map'); if (!map) return;
    map.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
    map.querySelectorAll('.isl-hit.pulse').forEach((n) => n.classList.remove('pulse'));
    map.querySelectorAll(`.isl-hit[data-id="${id}"]`).forEach((n) => { void n.getBoundingClientRect(); n.classList.add('pulse'); setTimeout(() => n.classList.remove('pulse'), 2400); });
  }

  window.addEventListener('message', (e) => {
    if (e.origin !== location.origin || !e.data || e.data.type !== 'km-keeper-go' || typeof e.data.zone !== 'string') return;
    focus(e.data.zone);
  });
  document.addEventListener('load', (e) => { if (e.target && e.target.classList && e.target.classList.contains('hub-assistant-frame') && hub.data) pushStats(); }, true);

  return { html, bind, helpers: { esc, hex, shade, geo: (id) => GEO[id] || { bx: 0, by: -14 }, ids, shortName } };
})();

// Home page of the knowledge zones (part 1.6 of 3): visitors, zone badges and animals on the islands.
// DEMO DATA: the people walking on the islands and every score are simulated in the browser (the "me" scores are kept in localStorage); there is no server
// behind it yet. The page says so ("示範資料"), and the real source of the numbers will be the per-account question log of each zone.
// Each zone has one badge with 8 levels (a colour each); the level rises with points from on-topic questions in that zone. Every badge level counts 1
// towards a "badge level total", which unlocks more animals to choose from.
const People = (() => {
  const H = Islands.helpers, NS = 'http://www.w3.org/2000/svg', esc = H.esc, shade = H.shade, ACC = 'var(--green)';
  const TIERS = [
    { n: '灰', c: '#9aa5a8', at: 5 }, { n: '綠', c: '#4cc27a', at: 15 }, { n: '藍', c: '#4aa8ff', at: 35 }, { n: '紫', c: '#a07cf0', at: 70 },
    { n: '紅', c: '#ef5b5b', at: 120 }, { n: '橙', c: '#ff9d3d', at: 200 }, { n: '金', c: '#f2c230', at: 320 }, { n: '彩虹', c: 'url(#km-rainbow)', at: 500 },
  ];
  const ANIMALS = [
    { id: 'cat', name: '小貓', at: 0, color: '#f4a259' }, { id: 'duck', name: '小鴨', at: 0, color: '#f6d55c' }, { id: 'bunny', name: '兔兔', at: 3, color: '#ece6dc' },
    { id: 'fox', name: '狐狸', at: 6, color: '#e8793a' }, { id: 'bear', name: '小熊', at: 10, color: '#a9744f' }, { id: 'deer', name: '小鹿', at: 15, color: '#c99a6b' },
    { id: 'owl', name: '貓頭鷹', at: 22, color: '#8d7b68' }, { id: 'penguin', name: '企鵝', at: 30, color: '#2f4858' }, { id: 'unicorn', name: '獨角獸', at: 45, color: '#f1e6ff' },
    { id: 'dragon', name: '小龍', at: 60, color: '#4cc27a' },
  ];
  const ANIMAL = Object.fromEntries(ANIMALS.map((a) => [a.id, a]));
  const GLYPH = { wifi: '⌁', mobile: '◌', broadband: '≋', csit: '◈', cert: '✦', integrations: '⌕', equipment: '▣', lab: '⚗', admin: '▤' };
  const ADJ = ['好奇', '認真', '悠閒', '機靈', '溫柔', '勤勞', '愛問', '開朗', '安靜', '活潑'];
  const AVATAR = 1.7, STORE = 'km-island-demo', MAX_USERS = 40;
  const REDUCED = window.matchMedia && matchMedia('(prefers-reduced-motion: reduce)').matches;
  const rnd = (a, b) => a + Math.random() * (b - a);
  const pick = (list) => list[Math.floor(Math.random() * list.length)];
  const tierOf = (points) => TIERS.filter((t) => points >= t.at).length;
  const levelSum = (scores) => Object.values(scores).reduce((n, p) => n + tierOf(p), 0);
  const unlocked = (scores) => ANIMALS.filter((a) => levelSum(scores) >= a.at);
  const topTier = (scores) => Math.max(0, ...Object.values(scores).map(tierOf));
  const tierName = (t) => `${TIERS[t - 1].n}徽章`;
  const shortZone = (id) => H.shortName(id);
  const zoneIds = () => H.ids();
  const earned = (scores) => zoneIds().filter((id) => tierOf(scores[id] || 0) > 0).sort((a, b) => tierOf(scores[b]) - tierOf(scores[a]));
  const fakeScores = () => {
    const scores = {};
    zoneIds().sort(() => Math.random() - .5).slice(0, 1 + Math.floor(Math.random() * 6)).forEach((id) => { scores[id] = Math.floor(Math.pow(Math.random(), 2.2) * 520); });
    return scores;
  };
  const DEFAULT_ME = () => ({ scores: { wifi: 38, mobile: 6, cert: 16 }, animal: 'cat' });
  const loadMine = () => {
    try { const v = JSON.parse(localStorage.getItem(STORE) || 'null'); if (v && v.scores && ANIMAL[v.animal]) return v; } catch (_) { /* no storage: use the defaults */ }
    return DEFAULT_ME();
  };
  const saveMine = (m) => { try { localStorage.setItem(STORE, JSON.stringify({ scores: m.scores, animal: m.kind })); } catch (_) { /* not saved */ } };
  const badgeSvg = (tier, glyph, size = 30) => `<svg class="bsvg" width="${size}" height="${Math.round(size * 1.08)}" viewBox="0 0 24 26" aria-hidden="true"><path d="M12 1.5 L21.5 5 V12.5 C21.5 18 17.5 22.5 12 24.5 C6.5 22.5 2.5 18 2.5 12.5 V5 Z" fill="${tier ? TIERS[tier - 1].c : 'none'}" stroke="${tier ? 'rgba(0,0,0,.4)' : 'currentColor'}" stroke-width="1" ${tier ? '' : 'stroke-dasharray="2 2" opacity=".5"'}/>`
    + (tier ? `<path d="M12 4 L19 6.6 V12.4 C19 16.6 16 20 12 21.8 C8 20 5 16.6 5 12.4 V6.6 Z" fill="rgba(255,255,255,.2)"/><text x="12" y="15.2" text-anchor="middle" font-size="9" font-weight="700" fill="#fff" stroke="rgba(0,0,0,.35)" stroke-width=".4">${glyph}</text>` : `<text x="12" y="15.2" text-anchor="middle" font-size="9" fill="currentColor" opacity=".5">${glyph}</text>`) + `</svg>`;
  const ringHtml = (u) => { const t = topTier(u.scores); return (t ? `<ellipse cx="0" cy="1" rx="5.8" ry="2.2" fill="none" stroke="${TIERS[t - 1].c}" stroke-width="1.3"/>` : '') + (u.me ? `<ellipse cx="0" cy="1" rx="8" ry="3" fill="none" stroke="${ACC}" stroke-width="1.2"/>` : ''); };

  /* ---- the animals ---- */
  function figure(u) {
    const k = u.kind, c = u.color, dark = shade(c, .7), light = shade(c, 1.18);
    let ears = '', beak = '', cheek = '', tail = '', behind = '', front = '', eyes = true, feet = dark, belly = light;
    if (k === 'cat' || k === 'fox') ears = [-1, 1].map((s) => `<polygon points="${s * 4},-12 ${s * 2.8},-16.6 ${s * .6},-13.6" fill="${c}"/>`).join('');
    if (k === 'bunny') ears = [-1, 1].map((s) => `<ellipse cx="${s * 2}" cy="-16" rx="1.4" ry="3.6" fill="${c}"/><ellipse cx="${s * 2}" cy="-16" rx=".6" ry="2.4" fill="#f7c6d0"/>`).join('');
    if (k === 'bear') ears = [-1, 1].map((s) => `<circle cx="${s * 3.6}" cy="-13.6" r="1.8" fill="${c}"/>`).join('');
    if (k === 'deer') ears = [-1, 1].map((s) => `<ellipse cx="${s * 4.2}" cy="-12.6" rx="1.6" ry=".9" fill="${c}"/><path d="M${s * 2},-14 L${s * 3},-18 M${s * 2.6},-16.2 L${s * 4.6},-17.4" stroke="#8a6a48" stroke-width=".9" fill="none" stroke-linecap="round"/>`).join('');
    if (k === 'duck') beak = `<polygon points="4.2,-10.4 7.2,-9.4 4.2,-8.4" fill="#ff9d2e"/><path d="M-1,-14.4 Q0,-17 1.4,-14.6" stroke="${dark}" stroke-width=".9" fill="none"/>`;
    if (k === 'fox') { cheek = `<ellipse cx="0" cy="-8.4" rx="3.2" ry="1.8" fill="#fff7ea"/>`; tail = `<ellipse cx="-5" cy="-4" rx="3" ry="1.8" fill="${c}" transform="rotate(-30 -5 -4)"/><circle cx="-7.6" cy="-5.6" r="1" fill="#fff7ea"/>`; }
    if (k === 'bunny') tail = `<circle cx="-4.3" cy="-3.2" r="1.5" fill="#fff"/>`;
    if (k === 'owl') {
      ears = [-1, 1].map((s) => `<polygon points="${s * 3.8},-13.2 ${s * 2.9},-16.8 ${s * .8},-14.2" fill="${c}"/>`).join('');
      behind = [-1, 1].map((s) => `<ellipse cx="${s * 4.2}" cy="-4.6" rx="1.3" ry="3.4" fill="${dark}"/>`).join('');
      eyes = false;
      front = [-1, 1].map((s) => `<circle cx="${s * 1.9}" cy="-10.3" r="2" fill="#fff"/><circle cx="${s * 1.9}" cy="-10.3" r=".9" fill="#1d3238"/>`).join('') + `<polygon points="-.7,-9 .7,-9 0,-7.6" fill="#ff9d2e"/>`;
      feet = '#ff9d2e';
    }
    if (k === 'penguin') {
      belly = '#f5f7f7'; feet = '#ff9d2e';
      behind = [-1, 1].map((s) => `<ellipse cx="${s * 4.3}" cy="-4.6" rx="1.2" ry="3.2" fill="${dark}" transform="rotate(${s * -12} ${s * 4.3} -4.6)"/>`).join('');
      front = `<ellipse cx="0" cy="-9.6" rx="2.6" ry="2.7" fill="#f5f7f7"/><polygon points="-1,-9.6 1,-9.6 0,-8.2" fill="#ff9d2e"/>`;
      eyes = false; front += [-1, 1].map((s) => `<circle cx="${s * 1.4}" cy="-10.6" r=".75" fill="#1d3238"/>`).join('');
    }
    if (k === 'unicorn') {
      ears = [-1, 1].map((s) => `<ellipse cx="${s * 3.6}" cy="-13.4" rx="1.3" ry="1.6" fill="${c}"/>`).join('') + `<polygon points="-.9,-14 0,-19.6 .9,-14" fill="#f2c230"/><line x1="-.7" y1="-16" x2=".7" y2="-15.4" stroke="#fff3b0" stroke-width=".6"/>`;
      behind = `<ellipse cx="-3.6" cy="-9.4" rx="1.5" ry="3.4" fill="#f7a8d8"/>`;
      tail = `<path d="M-4,-4 Q-8,-6 -7,-1.5" stroke="#f7a8d8" stroke-width="1.8" fill="none" stroke-linecap="round"/>`;
    }
    if (k === 'dragon') {
      behind = [-1, 1].map((s) => `<polygon points="${s * 3},-7.4 ${s * 8.6},-12.6 ${s * 5},-3" fill="${shade(c, .78)}"/>`).join('');
      ears = [-1, 1].map((s) => `<polygon points="${s * 2.2},-13.6 ${s * 3.6},-18 ${s * .8},-14.2" fill="#f5e6b3"/>`).join('');
      tail = `<path d="M-4,-3 Q-9,-4 -8.6,-.6" stroke="${c}" stroke-width="2" fill="none" stroke-linecap="round"/><polygon points="-9.6,-1.6 -7.4,-1.6 -8.6,.6" fill="#f5e6b3"/>`;
      belly = '#f5e6b3';
    }
    const bodyFill = k === 'penguin' ? dark : c;
    const head = k === 'penguin' ? dark : c;
    return `<ellipse cx="0" cy="1" rx="4.6" ry="1.5" fill="var(--shadow)"/>${behind}${tail}<ellipse class="ft1" cx="-1.9" cy="-.4" rx="1.6" ry="1" fill="${feet}"/><ellipse class="ft2" cx="1.9" cy="-.4" rx="1.6" ry="1" fill="${feet}"/>`
      + `<ellipse cx="0" cy="-4.6" rx="3.9" ry="4.7" fill="${bodyFill}"/><ellipse cx="0" cy="-3.6" rx="2.4" ry="3" fill="${belly}"/>${ears}<circle cx="0" cy="-10" r="4.5" fill="${head}"/>${cheek}`
      + (eyes ? `<circle cx="-1.7" cy="-10.5" r=".75" fill="#1d3238"/><circle cx="1.7" cy="-10.5" r=".75" fill="#1d3238"/>` : '') + beak + front;
  }

  /* ---- walking: each person is a small animal that wanders on the free ground of the island they are in ---- */
  const walkArea = H.hex(.8);
  const inPoly = (x, y, poly) => { let inside = false; for (let i = 0, j = poly.length - 1; i < poly.length; j = i++) { const [xi, yi] = poly[i], [xj, yj] = poly[j]; if ((yi > y) !== (yj > y) && x < (xj - xi) * (y - yi) / (yj - yi) + xi) inside = !inside; } return inside; };
  /* free ground: inside the island, in front of the library (not behind or in it) and above the name label */
  const walkable = (id, x, y) => { const g = H.geo(id); return inPoly(x, y, walkArea) && y > -30 && y < 9 && !(Math.abs(x - g.bx) < 38 && y < g.by + 9); };
  const sample = (id) => { for (let i = 0; i < 60; i++) { const x = rnd(-64, 64), y = rnd(-28, 8); if (walkable(id, x, y)) return { x, y }; } return { x: H.geo(id).bx + 44, y: 0 }; };
  const clearPath = (id, a, b) => { for (let k = 1; k <= 8; k++) if (!walkable(id, a.x + (b.x - a.x) * k / 8, a.y + (b.y - a.y) * k / 8)) return false; return true; };

  const users = [];
  let seq = 0, scene = null, selected = 'wifi', started = false, wired = false, meTab = 'badges', toastTimer = 0, last = 0, sortAt = 0;
  let tipEl, meEl, cardEl, toastEl;
  const layer = (id) => scene && scene.querySelector(`.isl-people[data-island="${id}"]`);
  const nameFor = (kind) => { for (let i = 0; i < 20; i++) { const n = pick(ADJ) + '的' + ANIMAL[kind].name; if (!users.some((u) => u.name === n)) return n; } return pick(ADJ) + '的' + ANIMAL[kind].name + (seq % 90 + 10); };
  const place = (u) => u.el.setAttribute('transform', `translate(${u.pos.x.toFixed(1)},${u.pos.y.toFixed(1)})`);

  function spawn(island, opts = {}) {
    const where = layer(island); if (!where) return null;
    const scores = opts.scores || fakeScores(), kind = opts.kind || pick(unlocked(scores)).id;
    const u = { id: ++seq, name: opts.name || nameFor(kind), kind, color: ANIMAL[kind].color, scores, island, speed: rnd(9, 15), wait: rnd(0, 3), me: !!opts.me, phase: rnd(0, 6), pos: sample(island), target: null };
    u.el = document.createElementNS(NS, 'g');
    u.el.setAttribute('class', 'av' + (u.me ? ' me' : ''));
    u.el.dataset.uid = u.id;
    u.el.innerHTML = `<g class="fig pop"><ellipse class="hitbox" cx="0" cy="-12" rx="13" ry="22"/><g transform="scale(${AVATAR})">${ringHtml(u)}</g><g class="walk" transform="scale(${AVATAR})">${figure(u)}</g>${u.me ? `<g transform="translate(0,-37) scale(1.3)"><rect x="-6" y="-6" width="12" height="9" rx="4" fill="${ACC}"/><text y="1.8" text-anchor="middle" font-size="6" font-weight="700" fill="#04202a">你</text></g>` : ''}</g>`;
    const fig = u.el.querySelector('.fig');
    fig.addEventListener('animationend', (e) => { if (e.animationName === 'kmPop') fig.classList.remove('pop'); });  // a node that is moved in the DOM must not replay its entrance
    where.appendChild(u.el);
    users.push(u);
    place(u);
    return u;
  }
  function leave(u) { const fig = u.el.querySelector('.fig'); fig.classList.remove('pop'); fig.classList.add('out'); users.splice(users.indexOf(u), 1); setTimeout(() => u.el.remove(), 380); count(); }
  function moveTo(u, island) {
    if (!layer(island)) return;
    const fig = u.el.querySelector('.fig'); fig.classList.remove('pop'); fig.classList.add('out');
    setTimeout(() => {
      const where = layer(island); if (!where) return;
      u.island = island; u.pos = sample(island); u.target = null; where.appendChild(u.el); place(u);
      fig.classList.remove('out'); void fig.getBoundingClientRect(); fig.classList.add('pop'); count();
    }, 340);
  }

  function tick(now) {
    const dt = Math.min(.1, (now - last) / 1000); last = now;
    if (scene && scene.isConnected && !document.hidden) {
      for (const u of users) {
        if (REDUCED) break;
        if (u.hover) { u.walking = false; continue; }   // standing still while the pointer is on them, so a click lands
        if (u.wait > 0) { u.wait -= dt; u.walking = false; }
        else {
          if (!u.target) {
            for (let i = 0; i < 8 && !u.target; i++) { const t = sample(u.island); if (clearPath(u.island, u.pos, t)) u.target = t; }
            if (!u.target) { u.wait = rnd(1, 3); continue; }
          }
          const dx = u.target.x - u.pos.x, dy = u.target.y - u.pos.y, d = Math.hypot(dx, dy), step = u.speed * dt;
          if (d <= step) { u.pos = u.target; u.target = null; u.wait = rnd(1.5, 6); u.walking = false; }
          else { u.pos = { x: u.pos.x + dx / d * step, y: u.pos.y + dy / d * step }; u.walking = true; if (Math.abs(dx) > .5) u.face = dx < 0 ? -1 : 1; }
          place(u);
        }
        const walk = u.el.querySelector('.walk'), t = now / 1000 + u.phase;
        walk.setAttribute('transform', `scale(${(u.face || 1) * AVATAR},${AVATAR}) translate(0,${u.walking ? (-Math.abs(Math.sin(t * 9)) * 1.4).toFixed(2) : 0})`);
        const f1 = walk.querySelector('.ft1'), f2 = walk.querySelector('.ft2');
        if (u.walking && f1 && f2) { f1.setAttribute('cy', (-.4 - Math.max(0, Math.sin(t * 9)) * 1.3).toFixed(2)); f2.setAttribute('cy', (-.4 - Math.max(0, -Math.sin(t * 9)) * 1.3).toFixed(2)); }
      }
      if (now - sortAt > 400) {  // paint the ones further back first; only touch the DOM when the order really changed
        sortAt = now;
        const yOf = new Map(users.map((u) => [u.el, u.pos.y]));
        scene.querySelectorAll('.isl-people').forEach((g) => { const cur = [...g.children], want = cur.slice().sort((a, b) => (yOf.get(a) || 0) - (yOf.get(b) || 0)); if (want.some((n, i) => n !== cur[i])) want.forEach((n) => g.appendChild(n)); });
      }
    }
    requestAnimationFrame(tick);
  }

  /* simulated comings and goings, as the real page would see them when it polls the server */
  function churn() {
    const others = users.filter((u) => !u.me), r = Math.random();
    if (!document.hidden && scene && scene.isConnected) {
      if (r < .34 && others.length > 3) leave(pick(others));
      else if (r < .68 && users.length < MAX_USERS) { spawn(pick(WEIGHTS())); count(); }
      else if (others.length) moveTo(pick(others), pick(zoneIds()));
    }
    setTimeout(churn, rnd(5000, 12000));
  }
  const WEIGHTS = () => { const ids = zoneIds(); return ids.concat(ids.filter((id) => id === 'wifi' || id === 'mobile'), ['wifi']); };

  /* ---- who is where: the corner pill and the line in the island's side panel ---- */
  function count() {
    const pill = document.getElementById('pp-online'); if (pill) pill.textContent = `${users.length} 人在線（示範）`;
    const crowd = document.querySelector('.isl-crowd'); if (!crowd) return;
    const here = users.filter((u) => u.island === selected);
    crowd.innerHTML = here.length ? `島上現在有 <strong>${here.length}</strong> 人：${here.map((u) => esc(u.me ? '你' : u.name)).join('、')}` : '島上目前沒有人';
  }

  /* ---- badge wall, animal picker, and the card that opens when a person is clicked ---- */
  const meUser = () => users.find((u) => u.me);
  const animalSvg = (id, size = 64) => `<svg width="${size}" height="${Math.round(size * 1.15)}" viewBox="-12 -23 24 27" aria-hidden="true">${figure({ kind: id, color: ANIMAL[id].color, scores: {} })}</svg>`;
  function toast(text) { toastEl.textContent = text; toastEl.hidden = false; clearTimeout(toastTimer); toastTimer = setTimeout(() => { toastEl.hidden = true; }, 3800); }

  function renderMe() {
    const m = meUser(); if (!m) return;
    const sc = m.scores, total = levelSum(sc), have = earned(sc).length;
    const rows = zoneIds().map((id) => {
      const p = sc[id] || 0, t = tierOf(p), next = TIERS[t], prev = t ? TIERS[t - 1].at : 0, pct = next ? Math.round((p - prev) / (next.at - prev) * 100) : 100;
      return `<li class="pp-brow"><span class="pp-bi">${badgeSvg(t, GLYPH[id] || '◇', 36)}</span><div><div class="pp-bline"><strong>${esc(shortZone(id))}</strong><span>${t ? `${tierName(t)}・Lv.${t}` : '尚未取得徽章'}</span></div>
        <div class="pp-bar"><i style="width:${pct}%;background:${t ? (TIERS[t - 1].c.startsWith('url') ? 'linear-gradient(90deg,#ff5b5b,#ffc83d,#4cd7a0,#4aa8ff,#b57cff)' : TIERS[t - 1].c) : ACC}"></i></div>
        <small>${p} 分${next ? `・再 ${next.at - p} 分升為${tierName(t + 1)}（${next.at} 分）` : '・已達最高等級'}</small></div></li>`;
    }).join('');
    const animals = ANIMALS.map((a) => {
      const ok = total >= a.at, on = m.kind === a.id;
      return `<li class="pp-acard${ok ? '' : ' locked'}${on ? ' on' : ''}"><div class="pp-apic">${animalSvg(a.id, 58)}</div><strong>${a.name}</strong>
        ${ok ? `<button type="button" class="pp-btn small" data-pick="${a.id}" ${on ? 'disabled' : ''}>${on ? '使用中' : '選擇'}</button>` : `<small>徽章等級合計 ${a.at}<br>（目前 ${total}）</small>`}</li>`;
    }).join('');
    meEl.querySelector('.pp-sheet').innerHTML = `<button type="button" class="pp-x" data-close aria-label="關閉">×</button><h2 id="pp-me-title">我的徽章與動物</h2>
      <p class="pp-sum">已取得 <strong>${have}</strong> 枚徽章・徽章等級合計 <strong>${total}</strong>（每個專區的徽章每升一級計 1）</p>
      <div class="pp-tabs" role="tablist"><button type="button" role="tab" data-tab="badges" aria-selected="${meTab === 'badges'}">徽章</button><button type="button" role="tab" data-tab="animals" aria-selected="${meTab === 'animals'}">動物</button></div>
      ${meTab === 'badges' ? `<ul class="pp-list">${rows}</ul>` : `<p class="pp-note">徽章等級合計越高，解鎖越多動物，可以自由選擇要使用哪一隻。</p><ul class="pp-agrid">${animals}</ul>`}
      <div class="pp-sim"><span>示範資料・加分工具：</span><select id="pp-sim-zone" aria-label="模擬提問的專區">${zoneIds().map((id) => `<option value="${id}">${esc(shortZone(id))}</option>`).join('')}</select>
        <button type="button" class="pp-btn small" data-add="1">＋1 分（一次符合主題的提問）</button><button type="button" class="pp-btn small" data-add="10">＋10 分</button><button type="button" class="pp-btn small" data-reset>重設</button></div>`;
  }
  function openMe(tab) { if (tab) meTab = tab; renderMe(); meEl.hidden = false; meEl.querySelector('[data-close]').focus(); }
  function refreshMeAvatar() {
    const m = meUser(); if (!m) return;
    m.el.querySelector('.walk').innerHTML = figure(m);
    m.el.querySelector('.fig > g').innerHTML = ringHtml(m);
  }
  function addPoints(zone, n) {
    const m = meUser(), before = m.scores[zone] || 0, t0 = tierOf(before), total0 = levelSum(m.scores);
    m.scores[zone] = before + n; saveMine(m);
    const t1 = tierOf(m.scores[zone]), total1 = levelSum(m.scores), fresh = ANIMALS.filter((a) => a.at > total0 && a.at <= total1), lines = [];
    if (t1 > t0) lines.push(`${shortZone(zone)}專區升為${tierName(t1)}（Lv.${t1}）`);
    if (fresh.length) lines.push(`解鎖新動物：${fresh.map((a) => a.name).join('、')}`);
    if (lines.length) toast(lines.join('　'));
    refreshMeAvatar(); renderMe(); count();
  }
  function openCard(u, x, y) {
    const list = earned(u.scores), total = levelSum(u.scores);
    cardEl.innerHTML = `<button type="button" class="pp-x" data-close aria-label="關閉">×</button><div class="pp-chead"><div class="pp-apic">${animalSvg(u.kind, 44)}</div><div><strong>${esc(u.me ? '你' : u.name)}</strong><small>${ANIMAL[u.kind].name}・在${esc(shortZone(u.island))}</small></div></div>
      <p class="pp-csum">${list.length ? `已取得 ${list.length} 枚徽章・徽章等級合計 ${total}` : '還沒有取得徽章'}（示範資料）</p>
      <ul class="pp-clist">${list.map((id) => { const t = tierOf(u.scores[id]); return `<li>${badgeSvg(t, GLYPH[id] || '◇', 26)}<span>${esc(shortZone(id))}</span><em>${tierName(t)}${u.me ? `・${u.scores[id]} 分` : ''}</em></li>`; }).join('')}</ul>
      ${u.me ? '<button type="button" class="pp-btn small" data-open-me>管理我的徽章與動物</button>' : ''}`;
    cardEl.hidden = false;
    const r = cardEl.getBoundingClientRect();
    cardEl.style.left = `${Math.max(8, Math.min(x + 14, innerWidth - r.width - 8))}px`;
    cardEl.style.top = `${Math.max(8, Math.min(y - 20, innerHeight - r.height - 8))}px`;
  }

  /* the pieces that live outside the map (modal, card, tip, toast) exist once; the map itself is drawn again on every refresh */
  function ensureUi() {
    if (meEl) return;
    const box = document.createElement('div');
    box.innerHTML = `<svg width="0" height="0" style="position:absolute" aria-hidden="true"><defs><linearGradient id="km-rainbow" x1="0" x2="1" y1="0" y2="1"><stop offset="0" stop-color="#ff5b5b"/><stop offset=".25" stop-color="#ffc83d"/><stop offset=".5" stop-color="#4cd7a0"/><stop offset=".75" stop-color="#4aa8ff"/><stop offset="1" stop-color="#b57cff"/></linearGradient></defs></svg>
      <div id="pp-tip" class="pp-tip" hidden></div><div id="pp-me" class="pp-modal" hidden role="dialog" aria-modal="true" aria-labelledby="pp-me-title"><div class="pp-sheet"></div></div>
      <div id="pp-card" class="pp-card" hidden role="dialog" aria-label="人物徽章"></div><div id="pp-toast" class="pp-toast" role="status" hidden></div>`;
    document.body.append(...box.children);
    tipEl = document.getElementById('pp-tip'); meEl = document.getElementById('pp-me'); cardEl = document.getElementById('pp-card'); toastEl = document.getElementById('pp-toast');
    const closeMe = () => { meEl.hidden = true; };
    meEl.addEventListener('click', (e) => {
      if (e.target === meEl || e.target.closest('[data-close]')) return closeMe();
      const tab = e.target.closest('[data-tab]'); if (tab) { meTab = tab.dataset.tab; return renderMe(); }
      const choose = e.target.closest('[data-pick]');
      if (choose) { const m = meUser(); m.kind = choose.dataset.pick; m.color = ANIMAL[m.kind].color; saveMine(m); refreshMeAvatar(); renderMe(); return toast(`現在使用：${ANIMAL[m.kind].name}`); }
      const add = e.target.closest('[data-add]'); if (add) return addPoints(document.getElementById('pp-sim-zone').value, Number(add.dataset.add));
      if (e.target.closest('[data-reset]')) { const m = meUser(), d = DEFAULT_ME(); m.scores = d.scores; m.kind = d.animal; m.color = ANIMAL[m.kind].color; saveMine(m); refreshMeAvatar(); renderMe(); }
    });
    cardEl.addEventListener('click', (e) => { if (e.target.closest('[data-close]')) cardEl.hidden = true; if (e.target.closest('[data-open-me]')) { cardEl.hidden = true; openMe('badges'); } });
    document.addEventListener('mousedown', (e) => { if (!cardEl.hidden && !cardEl.contains(e.target) && !(e.target.closest && e.target.closest('.av'))) cardEl.hidden = true; });
    document.addEventListener('keydown', (e) => { if (e.key === 'Escape') { cardEl.hidden = true; closeMe(); } });
  }

  /* called by Islands.bind() each time the map is drawn */
  function attach(map) {
    scene = map.querySelector('.isl-scene'); if (!scene) return;
    ensureUi();
    const bar = document.createElement('div');
    bar.className = 'pp-toolbar';
    bar.innerHTML = '<span class="pp-pill" title="示範資料：人物與分數都是模擬的"><i></i><span id="pp-online"></span></span><button type="button" class="pp-btn small" data-pp="me">我的徽章與動物</button><button type="button" class="pp-btn small" data-pp="hide" aria-pressed="true">隱藏人物</button>';
    map.appendChild(bar);
    bar.addEventListener('click', (e) => {
      const b = e.target.closest('[data-pp]'); if (!b) return;
      if (b.dataset.pp === 'me') return openMe('badges');
      const off = scene.classList.toggle('nopeople'); b.setAttribute('aria-pressed', String(!off)); b.textContent = off ? '顯示人物' : '隱藏人物';
    });
    scene.addEventListener('mousemove', (e) => {
      const av = e.target.closest && e.target.closest('.av');
      if (!av) { tipEl.hidden = true; return; }
      const u = users.find((x) => String(x.id) === av.dataset.uid); if (!u) return;
      tipEl.textContent = `${u.me ? '你' : u.name}・${shortZone(u.island)}`;
      tipEl.hidden = false; tipEl.style.left = `${e.clientX + 12}px`; tipEl.style.top = `${e.clientY - 28}px`;
    });
    scene.addEventListener('mouseleave', () => { tipEl.hidden = true; });
    const hover = (e, on) => { const av = e.target.closest && e.target.closest('.av'); const u = av && users.find((x) => String(x.id) === av.dataset.uid); if (u) u.hover = on; };
    scene.addEventListener('mouseover', (e) => hover(e, true));
    scene.addEventListener('mouseout', (e) => hover(e, false));
    scene.addEventListener('click', (e) => {   // capture phase: a click on a person opens the card instead of selecting the island
      const av = e.target.closest && e.target.closest('.av'); if (!av) return;
      e.preventDefault(); e.stopImmediatePropagation();
      const u = users.find((x) => String(x.id) === av.dataset.uid); if (u) openCard(u, e.clientX, e.clientY);
    }, true);
    if (!started) {
      started = true;
      const mine = loadMine(), target = Math.max(0, Math.min(MAX_USERS, Number(new URLSearchParams(location.search).get('users') ?? 11)));
      spawn(layer('wifi') ? 'wifi' : zoneIds()[0], { me: true, name: '你', scores: mine.scores, kind: mine.animal });
      for (let i = 0; i < target - 1; i++) spawn(pick(WEIGHTS()));
      last = performance.now();
      requestAnimationFrame(tick);
      setTimeout(churn, 6000);
    } else {
      users.forEach((u) => { const where = layer(u.island) || layer('wifi'); if (where) { if (u.island !== where.dataset.island) { u.island = where.dataset.island; u.pos = sample(u.island); } where.appendChild(u.el); } });
    }
    count();
  }

  /* an island was selected: remember it for the "who is here" line; a click (not a hover or a refresh) also walks "you" over there */
  function select(id, visit) {
    selected = id;
    if (visit) { const me = meUser(); if (me && me.island !== id) moveTo(me, id); }
    count();
  }

  return { attach, select };
})();

// Home page of the knowledge zones (part 2 of 2): the page itself.
const $ = (selector) => document.querySelector(selector);
const esc = (value) => String(value ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const num = (value) => Number(value || 0).toLocaleString('zh-TW');
const day = (time) => (time ? new Date(time).toLocaleDateString('zh-TW', { month: 'numeric', day: 'numeric' }) : '');
const label = (id) => META[id].label;
const EVENT = { new_document: ['新增', ''], superseded: ['被新版取代', 'warn'], removed: ['已移除', 'gone'] };
const hub = { data: null, tab: 'digest' };
function navItem(id) {
  return `<a class="nav-item" href="${zoneUrl(id)}"><span class="nav-icon" aria-hidden="true">${META[id].icon}</span><span>${esc(label(id))}</span></a>`;
}
function renderNav() {
  $('#primary-nav').innerHTML = `<section class="nav-group"><p class="nav-label">知識中樞</p><a class="nav-item active" href="/hub/" aria-current="page"><span class="nav-icon" aria-hidden="true">◈</span><span>首頁總覽</span></a></section>`
    + GROUPS.map((g) => `<section class="nav-group"><p class="nav-label">${g.label}</p>${g.ids.map(navItem).join('')}</section>`).join('')
    + '<section class="nav-group"><p class="nav-label">資料瀏覽</p><a class="nav-item" href="/legacy/"><span class="nav-icon" aria-hidden="true">▤</span><span>舊資料專區瀏覽（測試）</span></a></section>';
}

const attentionRow = (a) => `<a class="attention-task ${esc(a.level)}" href="${zoneUrl(a.zone)}"><span><strong>${esc(label(a.zone))}・${esc(a.title)}</strong><small>${esc(a.detail)}</small></span><span class="attention-go" aria-hidden="true">›</span></a>`;
function panel(title, body, hint = '') { return `<section class="panel hub-section"><div class="panel-heading"><div><h2>${title}</h2>${hint ? `<span>${hint}</span>` : ''}</div></div>${body}</section>`; }

function renderPage() {
  const all = Object.values(hub.data);
  const sum = (key) => all.reduce((n, s) => n + (s.ok ? s[key] : 0), 0);
  const attention = all.flatMap((s) => s.attention).sort((a, b) => (b.level === 'warning') - (a.level === 'warning'));
  const recent = all.flatMap((s) => s.recent).sort((a, b) => String(b.date).localeCompare(String(a.date))).slice(0, 10);
  $('#hub-islands').innerHTML = Islands.html();
  $('#hub-body').innerHTML = '';
  Islands.bind($('#hub-islands'));
  $('#zone-status').textContent = `${GROUPS.flatMap((g) => g.ids).filter((id) => hub.data[id]).length} 個專區`;  // the zones listed in the navigation, not every key of the data
  $('#page-updated').textContent = new Date().toLocaleString('zh-TW', { hour12: false });
}

const feedCard = (meta, title, text) => `<article class="feed-card"><div class="feed-meta">${meta}</div><h3>${esc(title)}</h3>${text ? `<p>${esc(text)}</p>` : ''}</article>`;
function renderFeed() {
  const body = $('#feed-body'); if (!body || !hub.data) return;
  document.querySelectorAll('[data-feed-tab]').forEach((b) => { const on = b.dataset.feedTab === hub.tab; b.classList.toggle('active', on); b.setAttribute('aria-selected', String(on)); });
  const all = Object.values(hub.data);
  if (hub.tab === 'digest') {
    const items = all.flatMap((s) => s.items).sort((a, b) => b.time - a.time).slice(0, 14);
    const highlights = all.flatMap((s) => s.highlights.slice(0, 1).map((h) => `${label(s.id)}：${h}`)).slice(0, 6);
    body.innerHTML = (highlights.length ? `<div class="feed-card"><div class="feed-section">各專區本週重點</div><ul class="feed-highlights">${highlights.map((h) => `<li>${esc(h)}</li>`).join('')}</ul></div>` : '')
      + items.map((i) => feedCard(`<span class="feed-badge">${esc(label(i.zone))}</span><span>${esc(i.source || '')}</span><span>${day(i.time)}</span>${i.older ? '<span class="feed-badge warn">較早</span>' : ''}`, i.title, i.summary)).join('')
      + '<p class="feed-note">週報由各專區彙整；WiFi 專區為即時資料，其餘專區為示範資料。</p>';
  } else {
    const events = all.flatMap((s) => s.events).sort((a, b) => b.time - a.time).slice(0, 16);
    body.innerHTML = events.map((e) => { const [name, tone] = EVENT[e.type] || [e.type, '']; return feedCard(`<span class="feed-badge ${tone}">${name}</span><span class="feed-badge">${esc(label(e.zone))}</span><span>${day(e.time)}</span>`, e.title, [e.role, e.version].filter(Boolean).join(' · ')); }).join('') || '<p class="feed-empty">各專區近期沒有文件變動。</p>';
  }
  $('#feed-stamp').textContent = `彙整時間 ${new Date().toLocaleString('zh-TW', { hour12: false })}`;
}
function initFeed() {
  $('#feed-column').innerHTML = '<div class="feed-head"><div><span class="feed-kicker">Hub Watch</span><h2>跨專區動態</h2></div><button id="feed-refresh" class="feed-refresh" type="button">重新整理</button></div><div class="feed-tabs" role="tablist" aria-label="動態類型"><button type="button" role="tab" data-feed-tab="digest">每週週報</button><button type="button" role="tab" data-feed-tab="updates">文件更新</button></div><div id="feed-body" class="feed-body" aria-live="polite"><p class="feed-empty">讀取中…</p></div><p id="feed-stamp" class="feed-stamp"></p>';
  document.querySelectorAll('[data-feed-tab]').forEach((b) => b.addEventListener('click', () => { hub.tab = b.dataset.feedTab; renderFeed(); }));
  $('#feed-refresh').addEventListener('click', refresh);
}
async function refresh() {
  try { hub.data = await loadAll(); renderPage(); renderFeed(); }
  catch (error) { $('#hub-metrics').innerHTML = ''; $('#hub-islands').innerHTML = ''; $('#hub-body').innerHTML = `<div class="error-card" role="alert"><strong>載入失敗</strong><p>${esc(error.message)}</p></div>`; }
  $('#app').setAttribute('aria-busy', 'false');
}
renderNav(); initFeed();
$('#nav-toggle').addEventListener('click', () => { const open = $('#primary-nav').classList.toggle('open'); $('#nav-toggle').setAttribute('aria-expanded', String(open)); });
$('#refresh-page').addEventListener('click', async (event) => { event.currentTarget.classList.add('is-loading'); event.currentTarget.disabled = true; await refresh(); event.currentTarget.classList.remove('is-loading'); event.currentTarget.disabled = false; });
refresh();
setInterval(refresh, 10 * 60 * 1000);
})();
