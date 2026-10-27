// Home page of the knowledge zones (part 2 of 2): the page itself.
const $ = (selector) => document.querySelector(selector);
const esc = (value) => String(value ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const num = (value) => Number(value || 0).toLocaleString('zh-TW');
const day = (time) => (time ? new Date(time).toLocaleDateString('zh-TW', { month: 'numeric', day: 'numeric' }) : '');
const label = (id) => META[id].label;
const EVENT = { new_document: ['新增', ''], superseded: ['被新版取代', 'warn'], removed: ['已移除', 'gone'] };
const hub = { data: null, tab: 'digest' };

function renderNav() {
  $('#primary-nav').innerHTML = `<section class="nav-group"><p class="nav-label">知識中樞</p><a class="nav-item active" href="/hub/" aria-current="page"><span class="nav-icon" aria-hidden="true">◈</span><span>首頁總覽</span></a></section>`
    + GROUPS.map((g) => `<section class="nav-group"><p class="nav-label">${g.label}</p>${g.ids.map((id) => `<a class="nav-item" href="${zoneUrl(id)}"><span class="nav-icon" aria-hidden="true">${META[id].icon}</span><span>${esc(label(id))}</span></a>`).join('')}</section>`).join('');
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
  $('#page-content').innerHTML = `
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
  catch (error) { $('#page-content').innerHTML = `<div class="error-card" role="alert"><strong>載入失敗</strong><p>${esc(error.message)}</p></div>`; }
  $('#app').setAttribute('aria-busy', 'false');
}
renderNav(); initFeed();
$('#nav-toggle').addEventListener('click', () => { const open = $('#primary-nav').classList.toggle('open'); $('#nav-toggle').setAttribute('aria-expanded', String(open)); });
$('#refresh-page').addEventListener('click', async (event) => { event.currentTarget.classList.add('is-loading'); event.currentTarget.disabled = true; await refresh(); event.currentTarget.classList.remove('is-loading'); event.currentTarget.disabled = false; });
refresh();
setInterval(refresh, 10 * 60 * 1000);
