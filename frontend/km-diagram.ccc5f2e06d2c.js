/* Diagrams in assistant answers. The model never draws with text characters: it describes the picture as JSON in a ```diagram block and this
   file draws it (same look every time, readable on dark and light pages, scales with the answer box). Everything from the model is escaped;
   anything that does not validate returns null so the caller keeps its plain code block. Types: "spectrum" (resource layout over a frequency
   axis) and "flow" (steps with arrows). Tables stay ordinary Markdown tables. */
(function () {
  'use strict';
  const ESC = { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' };
  const esc = (v) => String(v == null ? '' : v).replace(/[&<>"']/g, (c) => ESC[c]);
  // The Markdown renderer has already escaped the block's text; undo that once to read the JSON, escape again when drawing.
  const unescape = (t) => t.replace(/&quot;/g, '"').replace(/&#39;/g, "'").replace(/&lt;/g, '<').replace(/&gt;/g, '>').replace(/&amp;/g, '&');
  const int = (v) => (Number.isFinite(Number(v)) ? Math.round(Number(v)) : NaN);
  const text = (v, max) => String(v == null ? '' : v).slice(0, max);
  const GROUPS = 5;

  const CSS = `
.kmd{margin:14px 0;padding:14px 16px;border:1px solid var(--line,rgba(127,255,227,.22));border-radius:14px;background:var(--kmd-bg,rgba(4,26,33,.55))}
.kmd-title{margin:0 0 10px;font-weight:700;font-size:.9rem}
.kmd-row{display:grid;grid-template-columns:64px minmax(0,1fr);gap:4px 12px;align-items:center;margin:8px 0}
.kmd-label{font-weight:700;font-size:.82rem}
.kmd-track{display:grid;gap:3px;min-height:34px;padding:3px;border-radius:9px;background:var(--kmd-track,rgba(127,255,227,.07))}
.kmd-block{display:flex;align-items:center;justify-content:center;min-width:0;padding:0 4px;border-radius:6px;font-size:.72rem;font-weight:700;line-height:1.2;text-align:center;overflow:hidden;color:#04222a}
.kmd-g0{background:#2dd4bf}.kmd-g1{background:#60a5fa}.kmd-g2{background:#fbbf24}.kmd-g3{background:#c4b5fd}.kmd-g4{background:#fb7185}
.kmd-note{grid-column:2;font-size:.76rem;opacity:.8}
.kmd-axis{display:flex;justify-content:space-between;margin:8px 0 0 76px;font-size:.72rem;opacity:.7}
.kmd-legend{display:flex;flex-wrap:wrap;gap:6px 16px;margin:10px 0 0;font-size:.76rem}
.kmd-legend span::before{content:"";display:inline-block;width:12px;height:12px;margin-right:6px;border-radius:3px;vertical-align:-2px;background:currentColor}
.kmd-legend .kmd-g0::before{background:#2dd4bf}.kmd-legend .kmd-g1::before{background:#60a5fa}.kmd-legend .kmd-g2::before{background:#fbbf24}.kmd-legend .kmd-g3::before{background:#c4b5fd}.kmd-legend .kmd-g4::before{background:#fb7185}
.kmd-foot{margin:10px 0 0;font-size:.7rem;opacity:.65}
.kmd-flow{display:flex;flex-wrap:wrap;align-items:stretch;gap:8px}
.kmd-step{display:flex;flex-direction:column;gap:2px;min-width:110px;max-width:220px;padding:8px 12px;border:1px solid var(--line,rgba(127,255,227,.35));border-radius:10px;background:var(--kmd-track,rgba(127,255,227,.08));font-size:.82rem}
.kmd-step b{font-size:.84rem}.kmd-step small{opacity:.75}
.kmd-arrow{align-self:center;font-weight:700;opacity:.7}
@media (max-width:560px){.kmd-row{grid-template-columns:minmax(0,1fr)}.kmd-note{grid-column:1}.kmd-axis{margin-left:0}}`;

  function spectrum(spec) {
    const rows = Array.isArray(spec.rows) ? spec.rows.slice(0, 8) : [];
    if (!rows.length) return null;
    let n = 0;
    const out = [];
    for (const row of rows) {
      const blocks = (Array.isArray(row.blocks) ? row.blocks : []).slice(0, 40).map((b) => ({ from: int(b.from), to: int(b.to), group: int(b.group), text: text(b.text, 24) }));
      for (const b of blocks) {
        if (!Number.isInteger(b.from) || !Number.isInteger(b.to) || b.from < 0 || b.to <= b.from || b.to > 64) return null;
        n = Math.max(n, b.to);
      }
      out.push({ label: text(row.label, 16), note: text(row.note, 80), blocks });
    }
    if (!n) return null;
    n = Math.max(n, int(spec.width) > 0 && int(spec.width) <= 64 ? int(spec.width) : 0);
    const body = out.map((row) => `<div class="kmd-row"><span class="kmd-label">${esc(row.label)}</span><div class="kmd-track" style="grid-template-columns:repeat(${n},minmax(0,1fr))">`
      + row.blocks.map((b, i) => `<span class="kmd-block kmd-g${(Number.isInteger(b.group) && b.group >= 0 ? b.group : i) % GROUPS}" style="grid-column:${b.from + 1} / ${b.to + 1}">${esc(b.text)}</span>`).join('')
      + `</div>${row.note ? `<span class="kmd-note">${esc(row.note)}</span>` : ''}</div>`).join('');
    const legend = (Array.isArray(spec.legend) ? spec.legend : []).slice(0, GROUPS).map((l) => `<span class="kmd-g${(int(l.group) >= 0 ? int(l.group) : 0) % GROUPS}">${esc(text(l.text, 30))}</span>`).join('');
    const axis = spec.axis ? `<div class="kmd-axis"><span>${esc(text(spec.axis.low || '低', 20))}</span><span>${esc(text(spec.axis.label || '', 30))}</span><span>${esc(text(spec.axis.high || '高', 20))}</span></div>` : '';
    return { body: body + axis + (legend ? `<div class="kmd-legend">${legend}</div>` : '') };
  }

  function flow(spec) {
    const steps = (Array.isArray(spec.steps) ? spec.steps : []).slice(0, 10);
    if (steps.length < 2) return null;
    const parts = steps.map((s) => { const o = typeof s === 'string' ? { text: s } : s || {}; return `<div class="kmd-step"><b>${esc(text(o.text, 40))}</b>${o.note ? `<small>${esc(text(o.note, 80))}</small>` : ''}</div>`; });
    return { body: `<div class="kmd-flow">${parts.join('<span class="kmd-arrow" aria-hidden="true">→</span>')}</div>` };
  }

  function html(source) {
    let spec;
    try { spec = JSON.parse(unescape(String(source || '')).trim()); } catch (e) { return null; }
    if (!spec || typeof spec !== 'object') return null;
    const drawn = spec.type === 'spectrum' ? spectrum(spec) : spec.type === 'flow' ? flow(spec) : null;
    if (!drawn) return null;
    if (!document.getElementById('kmd-style')) { const s = document.createElement('style'); s.id = 'kmd-style'; s.textContent = CSS; document.head.appendChild(s); }
    return `<figure class="kmd">${spec.title ? `<figcaption class="kmd-title">${esc(text(spec.title, 60))}</figcaption>` : ''}${drawn.body}<p class="kmd-foot">概念示意圖，由 AI 依回答內容繪製，非原文圖片。</p></figure>`;
  }
  window.KMDiagram = { html };
})();
