(() => {
'use strict';
// Home page of the knowledge zones (part 1 of 2): which zones exist, and what each one reports. scripts/build_zone_demo.js joins the parts into one script.
// WiFi is read from its real API; the other zones are summarised from the sample data in zones-data.js.
const ZONES = window.KM_ZONES || {};
const DAY = 86400000;
const GROUPS = [
  { label: '技術類', ids: ['wifi', 'mobile', 'cpe', 'smallcell', 'broadband', 'technical'] },
  { label: '測試與認證類', ids: ['csit', 'cert', 'integrations'] },
  { label: '資源與管理類', ids: ['equipment', 'lab', 'admin'] },
];
const META = {
  wifi: { label: 'WiFi 知識專區', icon: '⌁', tagline: 'Wi-Fi 8／802.11bn 規格與 WFA 文件問答', url: '/wifi8/', live: true },
  mobile: { icon: '◌', tagline: '3GPP 規範與 LTE／5G NR 技術文件' },
  cpe: { icon: '◍', tagline: 'CPE 機種規格、韌體測試與業者規範' },
  smallcell: { icon: '◎', tagline: 'Small Cell 部署、OAM 與 O-RAN 互通' },
  broadband: { icon: '≋', tagline: 'PON／Cable 技術與 Broadband Forum 規範' },
  technical: { icon: '⌬', tagline: '研討會講義、設計文件與除錯經驗' },
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

// Home page of the knowledge zones (part 2 of 2): the page itself.
const $ = (selector) => document.querySelector(selector);
const esc = (value) => String(value ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const num = (value) => Number(value || 0).toLocaleString('zh-TW');
const day = (time) => (time ? new Date(time).toLocaleDateString('zh-TW', { month: 'numeric', day: 'numeric' }) : '');
const label = (id) => META[id].label;
const EVENT = { new_document: ['新增', ''], superseded: ['被新版取代', 'warn'], removed: ['已移除', 'gone'] };
const hub = { data: null, tab: 'digest' };
// CPE 與 Smallcell 歸在 4G/5G 知識專區底下（與原本的選單一致）
const SUB_OF = { cpe: 'mobile', smallcell: 'mobile' };

// 有子專區的項目（4G/5G）：第一次點擊先展開子專區，再點一次才進入該專區。
function navItem(id, children) {
  const sub = SUB_OF[id]; const icon = sub ? '›' : META[id].icon;
  const link = `<a class="nav-item${sub ? ' nav-sub' : ''}${children.length ? ' nav-parent' : ''}" href="${zoneUrl(id)}"${children.length ? ' aria-expanded="false"' : ''}><span class="nav-icon" aria-hidden="true">${icon}</span><span>${esc(label(id))}</span>${children.length ? '<span class="nav-caret" aria-hidden="true">▸</span>' : ''}</a>`;
  return children.length ? `${link}<div class="nav-subs" hidden>${children.map((c) => navItem(c, [])).join('')}</div>` : link;
}
function renderNav() {
  $('#primary-nav').innerHTML = `<section class="nav-group"><p class="nav-label">知識中樞</p><a class="nav-item active" href="/hub/" aria-current="page"><span class="nav-icon" aria-hidden="true">◈</span><span>首頁總覽</span></a></section>`
    + GROUPS.map((g) => `<section class="nav-group"><p class="nav-label">${g.label}</p>${g.ids.filter((id) => !SUB_OF[id]).map((id) => navItem(id, g.ids.filter((c) => SUB_OF[c] === id))).join('')}</section>`).join('');
  document.querySelectorAll('.nav-parent').forEach((parent) => parent.addEventListener('click', (event) => {
    const subs = parent.nextElementSibling;
    if (!subs.hidden) return;  // 已展開：照連結進入該專區
    event.preventDefault(); subs.hidden = false; parent.setAttribute('aria-expanded', 'true'); parent.querySelector('.nav-caret').textContent = '▾';
  }));
}

function card(id, s) {
  const m = META[id]; const warn = s.attention.length;
  const stat = (value, name, tone = '') => `<div class="hub-stat ${tone}"><strong>${s.ok ? num(value) : '—'}</strong><small>${name}</small></div>`;
  const latest = !s.ok ? '暫時無法讀取這個專區的資料' : s.latest ? `最新：${esc(s.latest.title)}（${day(s.latest.time)}）` : '近期沒有更新';
  return `<article class="hub-card"><div class="hub-card-head"><span class="hub-icon" aria-hidden="true">${m.icon}</span><div><h3>${esc(m.label)}</h3><p>${esc(m.tagline)}</p></div><span class="hub-tag ${m.live ? 'live' : 'demo'}">${m.live ? '即時' : '示範'}</span></div>
    <div class="hub-stats">${stat(s.current, '目前版本')}${stat(s.history, '歷史版本')}${stat(s.week, '本週更新')}${stat(warn, '待處理', s.attention.some((a) => a.level === 'warning') ? 'warn' : '')}</div>
    <p class="hub-latest">${latest}</p>
    <div class="hub-actions"><a class="primary-button" href="${zoneUrl(id)}">進入專區</a><a class="secondary-button" href="${zoneUrl(id, 'ai')}">直接提問</a></div></article>`;
}
const attentionRow = (a) => `<a class="attention-task ${esc(a.level)}" href="${zoneUrl(a.zone)}"><span><strong>${esc(label(a.zone))}・${esc(a.title)}</strong><small>${esc(a.detail)}</small></span><span class="attention-go" aria-hidden="true">›</span></a>`;
function panel(title, body, hint = '') { return `<section class="panel hub-section"><div class="panel-heading"><div><h2>${title}</h2>${hint ? `<span>${hint}</span>` : ''}</div></div>${body}</section>`; }

function renderPage() {
  const all = Object.values(hub.data);
  const sum = (key) => all.reduce((n, s) => n + (s.ok ? s[key] : 0), 0);
  const attention = all.flatMap((s) => s.attention).sort((a, b) => (b.level === 'warning') - (a.level === 'warning'));
  const metrics = [['▦', '知識專區', all.length, `${all.filter((s) => s.ok).length} 個專區資料可用`], ['▤', '目前版本文件', sum('current'), `另有 ${num(sum('history'))} 份歷史版本`], ['⌁', '本週更新', sum('week'), '近 7 天各專區的文件變動'], ['⚑', '待處理事項', attention.length, `${attention.filter((a) => a.level === 'warning').length} 項需要留意`]];
  const recent = all.flatMap((s) => s.recent).sort((a, b) => String(b.date).localeCompare(String(a.date))).slice(0, 10);
  $('#hub-body').innerHTML = `
    <div class="panel hub-section hub-summary"><div class="metric-grid hub-metrics">${metrics.map(([icon, name, value, note]) => `<div class="metric"><span class="metric-icon">${icon}</span><div class="metric-copy"><span>${name}</span><strong>${num(value)}</strong><small>${esc(note)}</small></div></div>`).join('')}</div></div>
    ${GROUPS.map((g) => panel(g.label, `<div class="hub-grid">${g.ids.map((id) => card(id, hub.data[id])).join('')}</div>`, `${g.ids.length} 個專區`)).join('')}
    ${panel('待處理事項', attention.length ? `<div class="attention-list">${attention.slice(0, 6).map(attentionRow).join('')}</div>${attention.length > 6 ? `<details class="hub-more"><summary>顯示其餘 ${attention.length - 6} 項</summary><div class="attention-list">${attention.slice(6).map(attentionRow).join('')}</div></details>` : ''}` : '<div class="alert-row success"><strong>目前沒有待處理事項</strong>各專區狀態正常。</div>', `${attention.length} 項，彙整自各專區，需留意的排在前面`)}
    ${panel('近期更新的文件', `<div class="table-wrap"><table><thead><tr><th style="width:44%">文件</th><th>專區</th><th>發布者</th><th>角色</th><th>日期</th></tr></thead><tbody>${recent.map((d) => `<tr><td><span class="document-title" title="${esc(d.title)}">${esc(d.title)}</span></td><td><a class="hub-link" href="${zoneUrl(d.zone, 'documents')}">${esc(label(d.zone))}</a></td><td>${esc(d.publisher || '—')}</td><td>${esc(d.role || '—')}</td><td>${esc(d.date || '—')}</td></tr>`).join('') || '<tr><td colspan="5" class="empty">目前沒有文件</td></tr>'}</tbody></table></div>`, '依文件日期，跨專區')}`;
  $('#zone-status').textContent = `${all.length} 個專區`;
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
  catch (error) { $('#hub-body').innerHTML = `<div class="error-card" role="alert"><strong>載入失敗</strong><p>${esc(error.message)}</p></div>`; }
  $('#app').setAttribute('aria-busy', 'false');
}
renderNav(); initFeed();
$('#nav-toggle').addEventListener('click', () => { const open = $('#primary-nav').classList.toggle('open'); $('#nav-toggle').setAttribute('aria-expanded', String(open)); });
$('#refresh-page').addEventListener('click', async (event) => { event.currentTarget.classList.add('is-loading'); event.currentTarget.disabled = true; await refresh(); event.currentTarget.classList.remove('is-loading'); event.currentTarget.disabled = false; });
refresh();
setInterval(refresh, 10 * 60 * 1000);
})();
