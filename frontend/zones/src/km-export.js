// Export an assistant answer as a file. One script for every page that has an assistant (WiFi zone, demo zones, hub chat).
// It watches the conversation, adds an "匯出" bar under each finished answer, and walks the user through: choose → outline → file.
// Nothing is generated before the user confirms the outline. Pages without the capability (or without the service) never show it.
(() => {
  'use strict';
  const API = '/api/export';
  const FORMATS = [['pptx', '簡報', 'PPTX'], ['docx', '文件', 'DOCX'], ['xlsx', '表格', 'XLSX'], ['md', 'Markdown', 'MD'], ['csv', '資料', 'CSV'], ['html', '網頁', 'HTML']];
  const text = (el) => String(el ? el.innerText || el.textContent || '' : '').replace(/\s+/g, ' ').trim();
  const esc = (v) => String(v ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));

  // Rendered answer → plain text that keeps headings, list items and table rows.
  function toText(root) {
    let out = '';
    const walk = (n) => {
      if (n.nodeType === 3) { out += n.nodeValue; return; }
      if (n.nodeType !== 1) return;
      const tag = n.tagName;
      if (['SCRIPT', 'STYLE', 'BUTTON'].includes(tag) || n.hasAttribute('data-km-export-bar')) return;
      if (tag === 'TABLE') {
        out += '\n';
        n.querySelectorAll('tr').forEach((tr) => { out += '| ' + [...tr.children].map((c) => text(c)).join(' | ') + ' |\n'; });
        out += '\n'; return;
      }
      if (/^H[1-6]$/.test(tag)) out += '\n\n' + '#'.repeat(Number(tag[1])) + ' ';
      if (tag === 'LI') out += '\n- ';
      if (tag === 'BR') out += '\n';
      n.childNodes.forEach(walk);
      if (/^(P|DIV|UL|OL|H[1-6]|BLOCKQUOTE|PRE)$/.test(tag)) out += '\n';
    };
    walk(root);
    return out.replace(/[ \t]+\n/g, '\n').replace(/\n{3,}/g, '\n\n').trim().slice(0, 19000);
  }

  // How each page lays out its conversation. `answers` finds finished answers; the rest read what the export needs from around one.
  const ADAPTERS = [
    {   // WiFi zone and the demo zones (same page code)
      root: '#conversation', settle: 400,
      answers: (root) => [...root.querySelectorAll('.message.assistant.markdown')],
      body: (el) => el,
      after: (el) => { let last = el; while (last.nextElementSibling && !last.nextElementSibling.classList.contains('message')) last = last.nextElementSibling; return last; },
      question: (el) => { let p = el.previousElementSibling; while (p && !p.classList.contains('user')) p = p.previousElementSibling; if (!p) return ''; const c = p.cloneNode(true); c.querySelectorAll('.message-files').forEach((x) => x.remove()); return text(c); },
      sources: (el) => { const found = []; let s = el.nextElementSibling; while (s && !s.classList.contains('message')) { s.querySelectorAll?.('.citation-list li').forEach((li) => found.push(text(li).slice(0, 300))); if (s.matches?.('.citation-list')) s.querySelectorAll('li').forEach((li) => found.push(text(li).slice(0, 300))); s = s.nextElementSibling; } return [...new Set(found)].slice(0, 30); },
    },
    {   // OpenClaw chat (the hub assistant and the old CSIT chat)
      root: '#chatMessages', settle: 1500, inside: true,
      answers: (root) => [...root.querySelectorAll('.message.bot')].slice(1).filter((m) => text(m.querySelector('.message-bubble')).length >= 40),
      body: (el) => el.querySelector('.message-bubble'),
      after: (el) => el.querySelector('.message-content') || el,
      question: (el) => { let p = el.previousElementSibling; while (p && !p.classList.contains('user')) p = p.previousElementSibling; return p ? text(p.querySelector('.message-bubble')) : ''; },
      sources: () => [],
    },
  ];

  const CSS = `
.kmx-bar{display:flex;align-items:center;gap:10px;margin:10px 0 2px;font:13px/1.4 system-ui,'Microsoft JhengHei',sans-serif}
.kmx-open{cursor:pointer;border:1px solid #2aa6a0;background:rgba(42,166,160,.12);color:#7fffe3;border-radius:8px;padding:5px 12px;font:inherit}
.kmx-open:hover{background:rgba(42,166,160,.25)}
.kmx-back{position:fixed;inset:0;z-index:2147483000;background:rgba(2,10,14,.72);display:grid;place-items:center;padding:16px}
.kmx-dlg{width:min(640px,100%);max-height:90vh;overflow:auto;background:#0b2530;color:#e6f3f5;border:1px solid #2b5560;border-radius:14px;padding:20px;font:14px/1.6 system-ui,'Microsoft JhengHei',sans-serif;box-shadow:0 20px 60px rgba(0,0,0,.5)}
.kmx-dlg h2{margin:0 0 4px;font-size:18px;color:#f2ffff}.kmx-dlg p{margin:6px 0;color:#a9c5ca}.kmx-dlg label{display:block;margin:12px 0 4px;color:#cfe6ea}
.kmx-chips{display:flex;flex-wrap:wrap;gap:8px}
.kmx-chip{cursor:pointer;border:1px solid #2b5560;background:#0f3340;color:#e6f3f5;border-radius:999px;padding:6px 14px;font:inherit}
.kmx-chip[aria-pressed=true]{border-color:#7fffe3;background:#14505a;color:#fff}
.kmx-dlg textarea,.kmx-dlg input[type=text]{width:100%;box-sizing:border-box;background:#06161d;color:#e6f3f5;border:1px solid #2b5560;border-radius:8px;padding:8px 10px;font:inherit}
.kmx-dlg textarea{min-height:76px;resize:vertical}
.kmx-row{display:flex;gap:8px;justify-content:flex-end;margin-top:18px;flex-wrap:wrap}
.kmx-btn{cursor:pointer;border:1px solid #2b5560;background:#0f3340;color:#e6f3f5;border-radius:8px;padding:7px 16px;font:inherit}
.kmx-btn.primary{background:#1f8a8a;border-color:#2aa6a0;color:#fff}.kmx-btn:disabled{opacity:.5;cursor:default}
.kmx-sec{display:grid;grid-template-columns:auto 1fr auto;gap:8px;align-items:center;margin:6px 0}
.kmx-sec small{color:#8fb0b6}
.kmx-err{color:#ffb4a8;margin-top:10px}.kmx-note{font-size:12px;color:#8fb0b6}
.kmx-dl{display:inline-block;margin-top:10px;padding:8px 18px;border-radius:8px;background:#1f8a8a;color:#fff;text-decoration:none}`;

  let config = null;
  async function loadConfig() {
    if (config) return config;
    try {
      const r = await fetch(`${API}/config`, { credentials: 'same-origin', headers: { Accept: 'application/json' } });
      config = r.ok ? await r.json() : { enabled: false };
    } catch (_) { config = { enabled: false }; }
    return config;
  }
  async function call(path, body) {
    const r = await fetch(`${API}${path}`, { method: 'POST', credentials: 'same-origin', headers: { 'Content-Type': 'application/json', 'x-km-export': '1' }, body: JSON.stringify(body) });
    const data = await r.json().catch(() => ({}));
    if (!r.ok) throw new Error(typeof data.detail === 'string' ? data.detail : `匯出失敗（HTTP ${r.status}）`);
    return data;
  }

  function open(context) {
    const back = document.createElement('div');
    back.className = 'kmx-back';
    back.innerHTML = '<div class="kmx-dlg" role="dialog" aria-modal="true" aria-labelledby="kmx-title" tabindex="-1"></div>';
    const dlg = back.firstChild;
    const state = { format: null, request: '', spec: null, busy: false };
    const close = () => { back.remove(); document.removeEventListener('keydown', onKey, true); context.button.focus(); };
    const onKey = (e) => { if (e.key === 'Escape' && !state.busy) { e.stopPropagation(); close(); } };
    document.addEventListener('keydown', onKey, true);
    back.addEventListener('mousedown', (e) => { if (e.target === back && !state.busy) close(); });
    const show = (html) => { dlg.innerHTML = html; dlg.focus(); };
    const fail = (message) => { const box = dlg.querySelector('.kmx-err') || dlg.appendChild(Object.assign(document.createElement('p'), { className: 'kmx-err', role: 'alert' })); box.textContent = message; };

    function stepChoose() {
      show(`<h2 id="kmx-title">匯出這則回答</h2><p>選擇想要的檔案格式，或直接用文字描述需求。按下「產生大綱」之前不會產生任何檔案。</p>
        <label>檔案格式</label><div class="kmx-chips">${FORMATS.map(([id, name, ext]) => `<button type="button" class="kmx-chip" data-f="${id}" aria-pressed="${state.format === id}">${name} <small>${ext}</small></button>`).join('')}<button type="button" class="kmx-chip" data-f="" aria-pressed="${state.format === null}">讓助理建議</button></div>
        <label for="kmx-req">你希望怎麼整理？（選填）</label><textarea id="kmx-req" maxlength="1000" placeholder="例如：做成 5 頁簡報給主管看；只列重點與數值；比較表格要放前面">${esc(state.request)}</textarea>
        <p class="kmx-note">產生大綱會使用語言模型額度；內容只會依這則回答與其來源整理，不會加入新的資料。</p>
        <div class="kmx-row"><button type="button" class="kmx-btn" data-a="cancel">取消</button><button type="button" class="kmx-btn primary" data-a="plan">產生大綱</button></div>`);
      dlg.querySelectorAll('.kmx-chip').forEach((b) => b.addEventListener('click', () => { state.format = b.dataset.f || null; dlg.querySelectorAll('.kmx-chip').forEach((x) => x.setAttribute('aria-pressed', String(x === b))); }));
      dlg.querySelector('[data-a=cancel]').addEventListener('click', close);
      dlg.querySelector('[data-a=plan]').addEventListener('click', async (e) => {
        state.request = dlg.querySelector('#kmx-req').value; state.busy = true; e.target.disabled = true; e.target.textContent = '整理中…';
        try {
          const payload = { question: context.question(), answer: context.answer(), sources: context.sources(), request: state.request };
          if (state.format) payload.format = state.format;
          state.spec = (await call('/plan', payload)).spec; state.busy = false; stepOutline();
        } catch (err) { state.busy = false; e.target.disabled = false; e.target.textContent = '產生大綱'; fail(err.message); }
      });
    }

    function stepOutline() {
      const s = state.spec;
      show(`<h2 id="kmx-title">確認大綱</h2><p>檢查標題與章節；取消勾選的章節不會放進檔案。確認後才會產生檔案。</p>
        <label for="kmx-t">標題</label><input id="kmx-t" type="text" maxlength="200" value="${esc(s.title)}">
        <label for="kmx-f">格式</label><select id="kmx-f" class="kmx-chip">${FORMATS.map(([id, name, ext]) => `<option value="${id}"${id === s.format ? ' selected' : ''}>${name} ${ext}</option>`).join('')}</select>
        <label>章節（${s.sections.length}）</label>${s.sections.map((sec, i) => `<div class="kmx-sec"><input type="checkbox" checked aria-label="包含此章節" data-i="${i}"><input type="text" maxlength="200" data-h="${i}" value="${esc(sec.heading)}" placeholder="（無標題）"><small>${sec.bullets.length + sec.paragraphs.length} 段${sec.table && sec.table.rows.length ? `・表格 ${sec.table.rows.length} 列` : ''}</small></div>`).join('')}
        <div class="kmx-row"><button type="button" class="kmx-btn" data-a="back">上一步</button><button type="button" class="kmx-btn primary" data-a="build">產生檔案</button></div>`);
      dlg.querySelector('[data-a=back]').addEventListener('click', stepChoose);
      dlg.querySelector('[data-a=build]').addEventListener('click', async (e) => {
        const keep = [...dlg.querySelectorAll('input[type=checkbox]')].filter((c) => c.checked).map((c) => Number(c.dataset.i));
        if (!keep.length) { fail('至少要保留一個章節。'); return; }
        const spec = { ...s, title: dlg.querySelector('#kmx-t').value.trim() || s.title, format: dlg.querySelector('#kmx-f').value,
          sections: keep.map((i) => ({ ...s.sections[i], heading: dlg.querySelector(`[data-h="${i}"]`).value.trim() })) };
        state.busy = true; e.target.disabled = true; e.target.textContent = '產生中…';
        try { stepDone(await call('/build', { spec })); state.busy = false; }
        catch (err) { state.busy = false; e.target.disabled = false; e.target.textContent = '產生檔案'; fail(err.message); }
      });
    }

    function stepDone(file) {
      const minutes = Math.max(1, Math.round((file.expires_in || 3600) / 60));
      show(`<h2 id="kmx-title">檔案已產生</h2><p>${esc(file.name)}（${Math.max(1, Math.round(file.bytes / 1024))} KB）</p>
        <a class="kmx-dl" href="${API}/files/${encodeURIComponent(file.file_id)}" download="${esc(file.name)}">下載檔案</a>
        <p class="kmx-note">檔案由 AI 依回答整理，使用前請對照來源。下載連結約 ${minutes} 分鐘後失效。</p>
        <div class="kmx-row"><button type="button" class="kmx-btn" data-a="close">關閉</button></div>`);
      dlg.querySelector('[data-a=close]').addEventListener('click', close);
    }

    document.body.appendChild(back);
    stepChoose();
  }

  function decorate(adapter, root) {
    for (const el of adapter.answers(root)) {
      if (el.dataset.kmExported) continue;
      el.dataset.kmExported = '1';
      const bar = document.createElement('div');
      bar.className = 'kmx-bar'; bar.setAttribute('data-km-export-bar', '');
      bar.innerHTML = '<button type="button" class="kmx-open" aria-haspopup="dialog">匯出為檔案</button>';
      const button = bar.firstChild;
      button.addEventListener('click', () => open({ button, answer: () => toText(adapter.body(el)), question: () => adapter.question(el).slice(0, 2000), sources: () => adapter.sources(el) }));
      const anchor = adapter.after(el);
      if (adapter.inside) anchor.appendChild(bar); else anchor.after(bar);
    }
  }

  async function start() {
    if (!(await loadConfig()).enabled) return;
    const style = document.createElement('style'); style.textContent = CSS; document.head.appendChild(style);
    const timers = new Map();
    const scan = () => ADAPTERS.forEach((adapter) => {
      const root = document.querySelector(adapter.root); if (!root) return;
      clearTimeout(timers.get(adapter));
      timers.set(adapter, setTimeout(() => decorate(adapter, root), adapter.settle));  // an answer that is still being written is left alone until it stops changing
    });
    new MutationObserver(scan).observe(document.body, { childList: true, subtree: true, characterData: true });
    scan();
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', start); else start();
})();
