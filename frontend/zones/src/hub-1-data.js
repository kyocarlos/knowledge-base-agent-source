// Home page of the knowledge zones (part 1 of 2): which zones exist, and what each one reports. scripts/build_zone_demo.js joins the parts into one script.
// WiFi is read from its real API; the other zones are summarised from the sample data in zones-data.js.
const ZONES = window.KM_ZONES || {};
const DAY = 86400000;
const GROUPS = [
  { label: '技術類', ids: ['wifi', 'mobile', 'cpe', 'smallcell', 'broadband'] },
  { label: '測試與認證類', ids: ['csit', 'cert', 'integrations'] },
  { label: '資源與管理類', ids: ['equipment', 'lab', 'admin'] },
];
const META = {
  wifi: { label: 'WiFi 知識專區', icon: '⌁', tagline: 'Wi-Fi 8／802.11bn 規格與 WFA 文件問答', url: '/wifi8/', live: true },
  mobile: { icon: '◌', tagline: '3GPP 規範與 LTE／5G NR 技術文件' },
  cpe: { icon: '◍', tagline: 'CPE 機種規格、韌體測試與業者規範' },
  smallcell: { icon: '◎', tagline: 'Small Cell 部署、OAM 與 O-RAN 互通' },
  broadband: { icon: '≋', tagline: 'PON／Cable 技術與 Broadband Forum 規範' },
  csit: { icon: '◈', tagline: 'CSIT 測試報告、申請單與測試計畫' },
  cert: { icon: '✦', tagline: 'Wi-Fi、藍牙、GCF、PTCRB 認證與法規' },
  integrations: { icon: '⌕', tagline: 'Confluence、Jira、TestRail 整合查詢' },
  equipment: { icon: '▣', tagline: '設備資訊、預約規範與校驗' },
  lab: { icon: '⚗', tagline: '實驗室規劃、建置與測試環境' },
  admin: { icon: '▤', tagline: '週報、工時、人事行政與請款' },
};
Object.keys(ZONES).forEach((id) => { META[id] = Object.assign({ label: ZONES[id].label, url: `/zones/${id}/`, live: false }, META[id]); });
const zoneUrl = (id, route = 'overview') => `${META[id].url}#/${route}`;

function summarizeSample(id) {
  const z = ZONES[id]; const fam = z.families;
  let history = 0; fam.forEach((f) => { history += f[5].split('|').length - 1; });
  const stamp = (days) => Date.now() - days * DAY;
  const events = (z.updates || []).map(([type, days, i]) => ({ zone: id, type, time: stamp(days), title: fam[i][1], publisher: fam[i][4], role: fam[i][3], version: fam[i][5].split('|')[0].split('@')[0] }));
  const items = (z.digest?.items || []).map(([source, days, title, summary, older]) => ({ zone: id, source, time: stamp(days), title, summary, older }));
  const recent = fam.map((f) => ({ zone: id, title: f[1], publisher: f[4], role: f[3], date: f[5].split('|')[0].split('@')[1] }));
  return { id, ok: true, current: fam.length, history, events, items, recent, highlights: z.digest?.highlights || [], attention: (z.attention || []).map(([level, title, detail]) => ({ zone: id, level, title, detail })) };
}

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
async function loadAll() {
  const wifi = summarizeWifi();
  const out = {}; Object.keys(ZONES).forEach((id) => { out[id] = summarizeSample(id); });
  out.wifi = await wifi;
  Object.values(out).forEach((s) => { s.week = s.events.filter((e) => Date.now() - e.time <= 7 * DAY).length; s.latest = s.events.slice().sort((a, b) => b.time - a.time)[0] || null; });
  return out;
}
