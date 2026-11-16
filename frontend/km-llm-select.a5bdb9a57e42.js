/* Model menu for the guide (/hub/) and the zone assistants (/zones/<zone>/).
 *
 * Loads the models this zone allows (GET /api/llm/profiles?zone=), puts a menu next to the send button, and adds the chosen id as "llm" to the question
 * (POST /api/keeper/route, POST /api/wifi8/agent which the zone pages rewrite to /api/zones/<zone>/agent). The server decides what the id means and whether
 * the zone may use it; this script never sends a model name, URL or key. With the default model chosen nothing is added, so the request is unchanged.
 *
 * It does not touch the page's own scripts: it waits for the page to draw its question box, mounts the menu there, and wraps window.fetch.
 * Not used on /wifi8/ (the tool-calling agent has no model choice yet) or on the demo admin page.
 */
(() => {
  'use strict';
  if (window.__kmLlmSelect) return;
  window.__kmLlmSelect = true;

  const path = location.pathname;
  const zone = /^\/hub\/?/.test(path) ? 'hub' : ((path.match(/^\/zones\/([a-z0-9_-]+)\//) || [])[1] || '');
  if (!zone || zone === 'admin') return;

  const STORE = 'km.llm.profile';
  const ACK = 'km.llm.ack.';
  const state = { profiles: [], defaultId: 'auto', current: 'auto', loaded: false };
  const seenTasks = new Set();

  const read = (key) => { try { return window.localStorage.getItem(key); } catch (_) { return null; } };
  const write = (key, value) => { try { window.localStorage.setItem(key, value); } catch (_) { /* private mode: the choice lasts for this page only */ } };
  const find = (id) => state.profiles.find((p) => p.id === id);
  const usable = (id) => { const p = find(id); return !!(p && p.available); };
  const explicit = () => state.loaded && state.current && state.current !== state.defaultId && usable(state.current);

  // ---- style (the pages' dark theme; plain select so the site's own select styling applies)
  const style = document.createElement('style');
  style.textContent = `
    .km-llm { display: inline-flex; align-items: center; gap: .45rem; font-size: .85rem; margin: 0 .5rem; vertical-align: middle; }
    .km-llm > span { opacity: .75; white-space: nowrap; }
    .km-llm select { min-height: 40px; max-width: 15rem; padding: 0 .6rem; border-radius: 8px; }
    .km-llm-note { display: block; font-size: .78rem; opacity: .7; margin-top: .25rem; }
    .km-llm-tag { font-size: .76rem; opacity: .6; margin-top: .4rem; }
    @media (max-width: 640px) { .km-llm { margin: .4rem 0; } .km-llm select { max-width: 100%; } }`;
  document.head.appendChild(style);

  // ---- the menu
  const fmtPoints = (n) => (Math.round(n * 10) / 10).toString();

  // KM's own running total for this model's account, never the provider's official balance (there is no balance API for ModaOne).
  function usageText(usage, short) {
    if (!usage) return '';
    if (typeof usage.pointsRemaining === 'number') {
      return short ? '剩餘約 ' + fmtPoints(usage.pointsRemaining) + ' 點' : '剩餘約 ' + fmtPoints(usage.pointsRemaining) + ' 點（核發 ' + fmtPoints(usage.grantedPoints) + ' 點）';
    }
    return 'KM 已用約 ' + fmtPoints(usage.pointsUsed) + ' 點';
  }

  function optionText(p) {
    let text = p.label;
    if (p.experimental) text += ' · 實驗';
    if (p.usage) text += '（' + usageText(p.usage, true) + '）';
    if (!p.available) text += ' — 不可用';
    else if (p.degraded) text += ' — 最近失敗';
    return text;
  }

  function render(box) {
    const select = box.querySelector('select');
    select.textContent = '';
    for (const p of state.profiles) {
      const option = document.createElement('option');
      option.value = p.id;
      option.textContent = optionText(p);
      option.disabled = !p.available;
      option.title = p.available ? p.description || '' : p.reason || '';
      select.appendChild(option);
    }
    select.value = state.current;
    const note = box.querySelector('.km-llm-note');
    const p = find(state.current);
    const lines = [];
    if (p && p.experimental && p.external) lines.push('使用此模型時，問題與搜尋到的文件節錄會送到外部算力平台。');
    if (p && p.usage) lines.push(usageText(p.usage, false) + '（KM 自行估算，非官方數字，實際以政府算力平台通知為準）。');
    note.textContent = lines.join('');
    note.hidden = lines.length === 0;
  }

  function makeBox() {
    const box = document.createElement('label');
    box.className = 'km-llm';
    box.innerHTML = '<span>模型</span><select aria-label="回答使用的模型"></select><span class="km-llm-note" hidden></span>';
    box.querySelector('.km-llm-note').className = 'km-llm-note';
    box.querySelector('select').addEventListener('change', (event) => {
      const id = event.target.value;
      const p = find(id);
      if (p && p.experimental && p.external && read(ACK + id) !== '1') {
        const ok = window.confirm('選擇「' + p.label + '」後，你的問題與搜尋到的文件節錄會送到外部算力平台（政府算力中心）處理。確定要使用嗎？');
        if (!ok) { event.target.value = state.current; return; }
        write(ACK + id, '1');
      }
      state.current = id;
      write(STORE, id);
      document.querySelectorAll('.km-llm').forEach(render);
    });
    return box;
  }

  function mount() {
    if (!state.loaded || state.profiles.filter((p) => p.available).length < 2) return;   // nothing to choose: the page stays as it is
    let host = null, before = null;
    if (zone === 'hub') {
      const form = document.getElementById('hub-ask-form');
      if (form && !form.querySelector('.km-llm')) { host = form; before = form.querySelector('button[type=submit], .primary-button'); }
    } else {
      const submit = document.getElementById('agent-submit');
      const bar = submit && submit.parentElement;
      if (bar && !bar.querySelector('.km-llm')) { host = bar; before = document.getElementById('agent-new') || submit; }
    }
    if (!host) return;
    const box = makeBox();
    host.insertBefore(box, before);
    render(box);
  }

  async function load() {
    try {
      const response = await realFetch('/api/llm/profiles?zone=' + encodeURIComponent(zone), { credentials: 'same-origin', headers: { Accept: 'application/json' } });
      if (!response.ok) return;
      const data = await response.json();
      state.profiles = Array.isArray(data.profiles) ? data.profiles : [];
      state.defaultId = data.default || 'auto';
      const stored = read(STORE);
      state.current = stored && usable(stored) ? stored : state.defaultId;       // a choice this zone does not allow falls back to the default
      state.loaded = true;
      document.querySelectorAll('.km-llm').forEach(render);
      mount();
    } catch (_) { /* no menu: the assistant works as before */ }
  }

  // ---- the question requests
  const realFetch = window.fetch.bind(window);
  const asks = (url, method) => method === 'POST' && (/\/api\/keeper\/route(\?|$)/.test(url) || /\/api\/zones\/[^/]+\/agent(\?|$)/.test(url) ||
    (zone !== 'hub' && /\/api\/wifi8\/agent(\?|$)/.test(url)));
  const result = (url, method) => method === 'GET' && /\/api\/(zones\/[^/]+|wifi8)\/agent\/[^/?]+(\?|$)/.test(url);

  function tag(container, llm, key) {
    if (!llm || (key && seenTasks.has(key))) return;
    if (key) seenTasks.add(key);
    window.setTimeout(() => {
      const root = typeof container === 'string' ? document.querySelector(container) : container;
      if (!root) return;
      const items = zone === 'hub' ? [...root.children] : [...root.querySelectorAll('.message.assistant')].filter((el) => el.id !== 'agent-wait' && !el.classList.contains('restored-note'));
      const last = items[items.length - 1];
      if (!last || last.querySelector('.km-llm-tag')) return;
      const el = document.createElement('div');
      el.className = 'km-llm-tag';
      const name = llm.label || llm.profile;
      el.textContent = llm.failed ? '回答模型：' + name + '（這次沒有回應，以上是關鍵字比對的結果；可改選「自動」再問一次）' : '回答模型：' + name;
      last.appendChild(el);
    }, 600);
  }

  window.fetch = async function (input, init) {
    const url = typeof input === 'string' ? input : (input && input.url) || '';
    const method = String((init && init.method) || (input && input.method) || 'GET').toUpperCase();
    let nextInit = init;
    const ask = asks(url, method);
    if (ask && explicit() && init && typeof init.body === 'string') {
      try {
        const body = JSON.parse(init.body);
        body.llm = state.current;
        nextInit = { ...init, body: JSON.stringify(body) };
      } catch (_) { /* not JSON: leave it */ }
    }
    const response = await realFetch(input, nextInit);
    try {
      if (ask && !response.ok) {
        const data = await response.clone().json().catch(() => null);
        const detail = data && data.detail;
        if (detail && typeof detail === 'object' && detail.message) {            // the pages show detail as text
          if (['expired', 'zone_blocked', 'unknown_profile', 'unavailable', 'not_supported'].includes(detail.code)) { state.current = state.defaultId; write(STORE, state.defaultId); load(); }
          return new Response(JSON.stringify({ detail: detail.message, code: detail.code }), { status: response.status, headers: { 'Content-Type': 'application/json' } });
        }
      } else if (ask && response.ok && zone === 'hub') {
        const data = await response.clone().json().catch(() => null);
        if (data && data.llm) { tag('#hub-ask-log', data.llm); load(); }   // reload so a ModaOne option's usage figure stays current
      } else if (response.ok && result(url, method)) {
        const data = await response.clone().json().catch(() => null);
        if (data && data.status === 'completed' && data.llm) { tag('#conversation', data.llm, data.task_id || url); load(); }
      }
    } catch (_) { /* never break the page's own request */ }
    return response;
  };

  // The pages draw their question box with script (and again when the tab changes): mount whenever it appears.
  const observer = new MutationObserver(() => mount());
  const start = () => { observer.observe(document.body, { childList: true, subtree: true }); load(); };
  if (document.body) start(); else document.addEventListener('DOMContentLoaded', start);
})();
