// Home page of the knowledge zones (part 2 of 2): the page itself.
const $ = (selector) => document.querySelector(selector);
const esc = (value) => String(value ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const num = (value) => Number(value || 0).toLocaleString('zh-TW');
const day = (time) => (time ? new Date(time).toLocaleDateString('zh-TW', { month: 'numeric', day: 'numeric' }) : '');
const label = (id) => META[id].label;
const EVENT = { new_document: ['新增', ''], superseded: ['被新版取代', 'warn'], removed: ['已移除', 'gone'] };
const hub = { data: null, zone: 'all', more: {} };
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
  return `<article class="hub-card" data-zone="${id}"><div class="hub-card-head"><span class="hub-icon" aria-hidden="true">${m.icon}</span><div><h3>${esc(m.label)}</h3><p>${esc(m.tagline)}</p></div><span class="hub-tag ${m.live ? 'live' : 'demo'}">${m.live ? '即時' : '示範'}</span></div>
    <div class="hub-stats">${stat(s.current, '有效來源檔案')}${stat(s.history, '舊版來源檔案')}${stat(s.week, '本週更新')}${stat(warn, '待處理', s.attention.some((a) => a.level === 'warning') ? 'warn' : '')}</div>
    <p class="hub-latest">${latest}</p>
    <div class="hub-actions"><a class="primary-button" href="${zoneUrl(id)}">進入專區</a><a class="secondary-button" href="${zoneUrl(id, 'ai')}">直接提問</a></div></article>`;
}
function panel(title, body, hint = '') { return `<section class="panel hub-section"><div class="panel-heading"><div><h2>${title}</h2>${hint ? `<span>${hint}</span>` : ''}</div></div>${body}</section>`; }

function renderPage() {
  const all = Object.values(hub.data);
  const sum = (key) => all.reduce((n, s) => n + (s.ok ? s[key] : 0), 0);
  $('#zone-status').textContent = `${all.length} 個專區`;
  $('#page-updated').textContent = new Date().toLocaleString('zh-TW', { hour12: false });
}

const feedCard = (meta, title, text) => `<article class="feed-card"><div class="feed-meta">${meta}</div><h3>${esc(title)}</h3>${text ? `<p>${esc(text)}</p>` : ''}</article>`;
const SHOW = { few: 5, many: 14 };
const more = (key, total) => (total > SHOW.few ? `<button class="hub-news-more" type="button" data-more="${key}">${hub.more[key] ? '收合' : `顯示更多（還有 ${total - SHOW.few} 則）`}</button>` : '');
const shortZone = (id) => label(id).replace(' 知識專區', '').replace('知識專區', '').replace('專區', '');
function renderFeed() {
  const digest = $('#hub-news-digest'), docs = $('#hub-news-docs'); if (!digest || !docs || !hub.data) return;
  const all = Object.values(hub.data), mine = (s) => hub.zone === 'all' || s.id === hub.zone;
  $('#hub-news-zones').innerHTML = [['all', '全部專區']].concat(all.map((s) => [s.id, shortZone(s.id)]))
    .map(([id, name]) => `<button type="button" data-zone="${id}" aria-pressed="${hub.zone === id}" class="${hub.zone === id ? 'on' : ''}">${esc(name)}</button>`).join('');
  const items = all.filter(mine).flatMap((s) => s.items).sort((a, b) => b.time - a.time).slice(0, SHOW.many);
  const highlights = all.filter(mine).flatMap((s) => s.highlights.slice(0, 1).map((h) => `${label(s.id)}：${h}`)).slice(0, 6);
  const shownItems = hub.more.digest ? items : items.slice(0, SHOW.few);
  digest.innerHTML = (highlights.length ? `<div class="feed-card"><div class="feed-section">各專區本週重點</div><ul class="feed-highlights">${highlights.map((h) => `<li>${esc(h)}</li>`).join('')}</ul></div>` : '')
    + shownItems.map((i) => feedCard(`<span class="feed-badge">${esc(label(i.zone))}</span><span>${esc(i.source || '')}</span><span>${day(i.time)}</span>${i.older ? '<span class="feed-badge warn">較早</span>' : ''}`, i.title, i.summary)).join('')
    + more('digest', items.length) + (items.length || highlights.length ? '' : '<p class="feed-empty">這個專區近期沒有更新消息。</p>')
    + '<p class="feed-note">WiFi 專區為每日 08:00 更新的即時資料，其餘專區為示範資料。</p>';
  const events = all.filter(mine).flatMap((s) => s.events).sort((a, b) => b.time - a.time).slice(0, SHOW.many);
  const shownEvents = hub.more.docs ? events : events.slice(0, SHOW.few);
  docs.innerHTML = shownEvents.map((e) => { const [name, tone] = EVENT[e.type] || [e.type, '']; return feedCard(`<span class="feed-badge ${tone}">${name}</span><span class="feed-badge">${esc(label(e.zone))}</span><span>${day(e.time)}</span>`, e.title, [e.role, e.version].filter(Boolean).join(' · ')); }).join('')
    + more('docs', events.length) + (events.length ? '' : '<p class="feed-empty">這個專區近期沒有文件變動。</p>');
  $('#hub-news-stamp').textContent = `彙整時間 ${new Date().toLocaleString('zh-TW', { hour12: false })}`;
}
function initFeed() {
  $('#feed-refresh').addEventListener('click', refresh);
  $('#hub-news-zones').addEventListener('click', (e) => { const b = e.target.closest('[data-zone]'); if (b) { hub.zone = b.dataset.zone; renderFeed(); } });
  $('.hub-news').addEventListener('click', (e) => { const b = e.target.closest('[data-more]'); if (b) { hub.more[b.dataset.more] = !hub.more[b.dataset.more]; renderFeed(); } });
}

/* The all-zones assistant is a guide: it says which zone a question belongs to and takes the user there. It never answers what is inside a zone
   (/api/keeper/route only returns zones and a pointer; the experts of each zone answer the content). */
const plain = (text) => String(text || '')   // the guide's texts talk about "islands"; this page talks about zones
  .replace(/座島/g, '個專區').replace(/的島/g, '的專區').replace(/各島/g, '各專區').replace(/這些島/g, '這些專區').replace(/島上的專家/g, '該專區的專家')
  .replace(/不同的島（專區）/g, '不同的專區').replace(/島主/g, '導覽助理');
function initAsk() {
  const panel = $('#hub-ask-panel'), log = $('#hub-ask-log'), input = $('#hub-ask-input'), form = $('#hub-ask-form');
  let busy = false;
  const stats = () => { const out = {}; Object.values(hub.data || {}).forEach((s) => { out[s.id] = { week: s.ok ? s.week : 0, todo: s.attention ? s.attention.length : 0 }; }); return out; };
  const add = (cls, html) => { const div = document.createElement('div'); div.className = `hub-msg ${cls}`; div.innerHTML = html; log.appendChild(div); log.scrollTop = log.scrollHeight; return div; };
  const zoneCard = (z, question) => `<div class="hub-guide-card"><div class="hub-guide-title">${esc(z.name)}${z.simulated ? ' <span class="hub-guide-sim">示範資料</span>' : ''}</div><div class="hub-guide-why">${esc(plain(z.reason))}</div>
    <div class="hub-guide-actions">${question ? `<a href="${esc(z.url)}?q=${encodeURIComponent(question.slice(0, 300))}#/ai">帶著問題進入</a>` : `<a href="${esc(z.url)}#/overview">進入專區</a>`}</div></div>`;
  function render(res, question) {
    const asking = res.intent === 'route' || res.mode === 'index';
    let html = `<div>${esc(plain(res.answer))}</div>` + (res.zones || []).map((z) => zoneCard(z, asking ? question : '')).join('');
    if (!(res.zones || []).length && (res.all_zones || []).length) html += '<div class="hub-guide-all">' + res.all_zones.map((z) => `<button type="button" title="${esc(plain(z.reason || ''))}" data-go="${esc(z.id)}">${esc(z.name.replace('知識專區', '').replace('專區', ''))}</button>`).join('') + '</div>';
    if (res.mode === 'keyword') html += '<div class="hub-guide-note">判斷服務暫時無法使用，這是用關鍵字比對的結果，可能不夠精準。</div>';
    return html;
  }
  /* "take me there": bring the zone's card into view and make it flash */
  function goTo(id) {
    const card = document.querySelector(`.hub-card[data-zone="${id}"]`); if (!card) { location.assign(zoneUrl(id)); return; }
    card.scrollIntoView({ behavior: 'smooth', block: 'center' });
    card.classList.remove('pulse'); void card.offsetWidth; card.classList.add('pulse'); setTimeout(() => card.classList.remove('pulse'), 2600);
  }
  async function ask(question) {
    if (busy) return;
    busy = true; panel.hidden = false;
    add('me', esc(question));
    const waiting = add('bot', '正在找該去哪個專區…');
    const controller = new AbortController(), timer = setTimeout(() => controller.abort(), 35000);
    try {
      const response = await fetch('/api/keeper/route', { method: 'POST', credentials: 'same-origin', signal: controller.signal, headers: { 'Content-Type': 'application/json', Accept: 'application/json' }, body: JSON.stringify({ question, stats: stats() }) });
      if (response.status === 401) waiting.textContent = '登入已過期，請重新整理頁面後再問。';
      else if (response.status === 429) waiting.textContent = '問得太快了，請稍等一下再問。';
      else if (!response.ok) throw new Error(`HTTP ${response.status}`);
      else waiting.innerHTML = render(await response.json(), question);
    } catch (error) { waiting.textContent = error.name === 'AbortError' ? '等太久了，請再問一次。' : '導覽服務暫時無法使用，請直接從下方選擇專區。'; }
    finally { clearTimeout(timer); busy = false; log.scrollTop = log.scrollHeight; }
  }
  form.addEventListener('submit', (e) => { e.preventDefault(); const q = input.value.trim(); if (!q) { input.focus(); return; } input.value = ''; ask(q); });
  document.querySelectorAll('[data-ask]').forEach((b) => b.addEventListener('click', () => ask(b.dataset.ask)));
  log.addEventListener('click', (e) => { const b = e.target.closest('[data-go]'); if (b) goTo(b.dataset.go); });
  $('#hub-ask-close').addEventListener('click', () => { panel.hidden = true; });
  $('#hub-ask-clear').addEventListener('click', () => { log.innerHTML = ''; panel.hidden = true; });
}
async function refresh() {
  try { hub.data = await loadAll(); renderPage(); renderFeed(); }
  catch (error) { $('#hub-body').innerHTML = `<div class="error-card" role="alert"><strong>載入失敗</strong><p>${esc(error.message)}</p></div>`; }
  $('#app').setAttribute('aria-busy', 'false');
}
/* "What people are asking": a hand-kept list (edit here). Each item opens its zone's assistant with the question already typed in (not sent). */
const FAQ = [
  { zone: 'wifi', q: 'MRU、RRU 與 Wi-Fi 8 DRU 的資源配置方式如何比較？' },
  { zone: 'wifi', q: 'ELR 的規格重點是什麼？' },
  { zone: 'wifi', q: 'Wi-Fi 8 的 NPCA 是什麼？適用什麼情境？' },
  { zone: 'cert', q: 'Wi-Fi 認證要準備什麼？' },
  { zone: 'equipment', q: '設備預約的借用規範是什麼？' },
  { zone: 'mobile', q: '5G NR Handover 的測試案例有哪些？' },
].filter((item) => typeof META !== 'undefined' && META[item.zone]);
function initFaq() {
  const box = $('#hub-faq-list'); if (!box) return;
  box.innerHTML = FAQ.map((item) => `<a class="hub-faq-item" href="${META[item.zone].url}?q=${encodeURIComponent(item.q)}#/ai"><span class="hub-faq-zone">${esc(shortZone(item.zone))}</span><span class="hub-faq-q">${esc(item.q)}</span></a>`).join('');
}
renderNav(); initFeed(); initAsk(); initFaq();
$('#nav-toggle').addEventListener('click', () => { const open = $('#primary-nav').classList.toggle('open'); $('#nav-toggle').setAttribute('aria-expanded', String(open)); });
$('#refresh-page').addEventListener('click', async (event) => { event.currentTarget.classList.add('is-loading'); event.currentTarget.disabled = true; await refresh(); event.currentTarget.classList.remove('is-loading'); event.currentTarget.disabled = false; });
refresh();
setInterval(refresh, 10 * 60 * 1000);
