(() => {
  'use strict';

  const navGroups = [
    { label: 'Knowledge zone', items: [
      ['overview', '◈', '總覽', true], ['documents', '▤', '文件瀏覽', true], ['ai', '♙', 'AI Agent', true],
    ]},
    { label: 'Operations', items: [
      ['jobs', '◷', '匯入與進度', true], ['research', '⌕', '研究主題', false], ['wfa-downloads', '⇩', 'WFA 下載', false],
      ['web-collection', '◎', '網頁收集', false], ['review', '✓', '內容審核', false],
    ]},
    { label: 'Administration', items: [['ai-usage', '◌', 'AI 用量', false], ['settings', '⚙', '設定', false]] },
  ];
  const routeInfo = {
    overview: ['總覽', '即時資料集、分類與版本狀態'],
    documents: ['文件瀏覽', '查詢目前版本、歷史版本與文件段落'],
    ai: ['WiFi AI Agent', '使用現有 WiFi Agent 進行可追溯問答'],
    jobs: ['匯入與工作進度', '檢視匯入工作，有權限帳號可上傳匯出包'],
    research: ['研究主題', '建立與管理 WiFi 研究主題'],
    'wfa-downloads': ['WFA 下載', '管理 Wi-Fi Alliance 文件來源'],
    'web-collection': ['網頁收集', '收集、清理與追蹤網頁資料'],
    review: ['內容審核', '審核文件與知識內容'],
    'ai-usage': ['AI 用量', '查看 Agent 用量與執行狀態'],
    settings: ['設定', '調整 WiFi 知識專區設定'],
  };
  const state = { route: 'overview', overview: null, documentPage: 1, conversation: [], agentTask: null, renderToken: 0 };
  const $ = (selector) => document.querySelector(selector);
  const content = $('#page-content');
  const escapeHtml = (value) => String(value ?? '').replace(/[&<>"']/g, (char) => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[char]));
  const number = (value) => Number(value || 0).toLocaleString('zh-TW');
  const formatTime = (value) => value ? new Date(value).toLocaleString('zh-TW', { hour12: false }) : '—';
  // The in-page route (#/ai …) never reaches the server, so it is kept in this tab while the user logs in again;
  // login.html stores it too when /wifi8/#/… was opened without a session.
  const RETURN_ROUTE_KEY = 'km.wifi8.returnRoute';
  const LOADED_SCRIPT = (document.currentScript?.src.match(/wifi8\.[0-9a-f]{12}\.js/) || [''])[0];

  async function api(path, options = {}) {
    const response = await fetch(path, { credentials: 'same-origin', ...options, headers: { Accept: 'application/json', ...(options.headers || {}) } });
    if (response.status === 401) {
      try { sessionStorage.setItem(RETURN_ROUTE_KEY, location.hash); } catch (_) { /* storage may be unavailable */ }
      location.assign('/login.html?next=%2Fwifi8%2F');
      throw new Error('登入已過期');
    }
    let payload = null;
    try { payload = await response.json(); } catch (_) { /* response can be empty */ }
    if (!response.ok) throw new Error(payload?.detail || `請求失敗 (${response.status})`);
    return payload;
  }

  function renderNav() {
    $('#primary-nav').innerHTML = navGroups.map((group) => `<section class="nav-group"><p class="nav-label">${group.label}</p>${group.items.map(([id, icon, label, ready]) => `<a class="nav-item${id === state.route ? ' active' : ''}${ready ? '' : ' pending'}" href="#/${id}" ${id === state.route ? 'aria-current="page"' : ''}><span class="nav-icon" aria-hidden="true">${icon}</span><span>${label}</span>${ready ? '' : '<small>待移植</small>'}</a>`).join('')}</section>`).join('');
  }

  function setHeader(route) {
    const [title, subtitle] = routeInfo[route];
    $('#page-section').textContent = `WiFi knowledge zone / ${subtitle}`;
    $('#page-title').textContent = title;
    $('#page-updated').textContent = new Date().toLocaleString('zh-TW', { hour12: false });
    document.title = `${title} · WiFi 知識專區`;
  }

  function fail(error) { content.innerHTML = `<div class="error-card" role="alert"><strong>載入失敗</strong><p>${escapeHtml(error.message)}</p></div>`; }
  function panel(title, body, hint = '') { return `<section class="panel"><div class="panel-heading"><div><h2>${title}</h2>${hint ? `<span>${hint}</span>` : ''}</div></div>${body}</section>`; }
  function statusClass(status) { return /fail|error/i.test(status || '') ? 'failed' : /complete|success|ready/i.test(status || '') ? '' : 'active'; }

  function healthItem(icon, name, status, detail, tone = '') {
    return `<div class="health-item"><span class="health-icon">${icon}</span><div class="health-copy"><h3>${name}</h3><span class="health-state ${tone}">${escapeHtml(status)}</span><small>${escapeHtml(detail || '')}</small></div></div>`;
  }
  // Classification statistics like the original Wi-Fi8 KM System: every document (history versions included) grouped by the category of its
  // publishing organisation; names and descriptions come from the server (src/wifi8/categories.json), the current versions are shown next to the total.
  function classificationRows(stats = {}, counts = {}) {
    const rows = stats.rows || []; const total = Number(stats.total || 0);
    const excluded = Object.entries(counts.excluded || {});
    const note = excluded.length ? `<p class="results-meta classification-note">另有 ${escapeHtml(excluded.map(([reason, n]) => `${number(n)} 份（${reason}）`).join('、'))} 依匯入政策未匯入，不在以上合計內。</p>` : '';
    return `<div class="classification-total"><span>合計</span><strong>${number(total)}</strong></div><div class="category-list">${rows.map((row) => `<div class="category-row classification-row">
      <div class="category-name"><span>${escapeHtml(row.label)}</span><small>${escapeHtml(row.description || '')}</small></div>
      <div class="classification-bar"><progress class="category-bar" max="${Math.max(1, total)}" value="${Number(row.total || 0)}" aria-label="${escapeHtml(row.label)} 占比 ${Number(row.share || 0).toFixed(1)}%"></progress><small>目前版本 ${number(row.current)}・歷史版本 ${number(row.history)}</small></div>
      <div class="category-value"><strong>${number(row.total)}</strong><span>${Number(row.share || 0).toFixed(1)}%</span></div></div>`).join('') || '<p class="empty">尚無分類資料</p>'}</div>${note}`;
  }
  function overviewCards(data, counts) {
    const excluded = Object.values(counts.excluded || {}).reduce((sum, n) => sum + Number(n || 0), 0);
    const cards = [
      ['▤', '知識庫文件', counts.documents, `目前版本 ${number(counts.current_documents)}／歷史版本 ${number(counts.superseded_documents)}`],
      ['◈', '問答與研究採用文件', data.qna_documents, 'AI 問答與研究共用的預設範圍'],
      ['⌕', '檢索單位', counts.chunks || counts.retrieval_units, `可用 ${number(counts.chunks_ready)}／處理中 ${number(counts.chunks_pending)}`],
      ['⊘', '依政策未匯入', excluded, excluded ? '機密屬性不符，不進入 KM' : '沒有被排除的文件'],
    ];
    return `<div class="metric-grid">${cards.map(([icon, label, value, note]) => `<div class="metric"><span class="metric-icon">${icon}</span><div class="metric-copy"><span>${label}</span><strong>${number(value)}</strong><small>${escapeHtml(note)}</small></div></div>`).join('')}</div>`;
  }
  // Things that need a person's attention, computed by the server from the import and the zone's switches (src/wifi8/overview.py).
  function attentionPanel(items = []) {
    const body = items.length
      ? `<div class="attention-list">${items.map((item) => `<a class="attention-task ${escapeHtml(item.level)}" href="#/${escapeHtml(item.route)}"><span><strong>${escapeHtml(item.title)}</strong><small>${escapeHtml(item.detail)}</small></span><span class="attention-go" aria-hidden="true">›</span></a>`).join('')}</div>`
      : '<div class="alert-row success"><strong>目前沒有待處理事項</strong>匯入、版本關係與自動檢查都正常。</div>';
    return `<div class="overview-grid single">${panel('待處理事項', body, items.length ? `${items.length} 項` : '一切正常')}</div>`;
  }
  function categoryRows(items = []) {
    const max = Math.max(1, ...items.map((item) => Number(item[1] || 0)));
    return `<div class="category-list">${items.slice(0, 12).map(([name, count]) => `<div class="category-row"><span class="category-name" title="${escapeHtml(name)}">${escapeHtml(name)}</span><progress class="category-bar" max="${max}" value="${Number(count || 0)}"></progress><span class="category-value">${number(count)}</span></div>`).join('') || '<div class="empty">尚無分類資料</div>'}</div>`;
  }

  async function renderOverview(token) {
    const data = state.overview = await api('/api/wifi8/overview');
    if (token !== state.renderToken) return;
    const counts = data.counts || {};
    const current = data.current || {};
    const job = data.active_job;
    $('#zone-status').textContent = `${number(counts.documents)} 份文件`;
    content.innerHTML = `
      <section class="health-panel"><div class="section-intro"><div><span class="health-icon">⌑</span><div><h2>系統狀態</h2><p>目前資料版本與匯入進度</p></div></div><span class="inline-note">LIVE API</span></div>
        <div class="health-grid">${healthItem('◈','資料集','可用', current.package_id || current.version || current.import_id || '目前版本')}${healthItem('▤','文件','已索引',`${number(counts.current_documents)} 目前 / ${number(counts.superseded_documents)} 歷史`)}${healthItem('⌕','檢索單位','已就緒',`${number(counts.chunks || counts.retrieval_units)} 個`)}${healthItem('⇩','匯入工作',job ? (job.status || '執行中') : '無進行中工作',job?.job_id || '穩定',job ? 'warning' : '')}</div></section>
      ${attentionPanel(data.attention)}
      <div class="overview-grid">${panel('分類統計', classificationRows(data.by_category, counts), '依來源機構類別統計（全部文件）')}${panel('文件概況', overviewCards(data, counts), '來自目前匯入版本')}</div>
      <div class="overview-grid">${panel('發布者', categoryRows(data.by_publisher), '目前版本')}${panel('文件角色', categoryRows(data.by_document_role), '目前版本')}</div>
      <div class="overview-grid single">${panel('主題', `<div class="topic-list">${(data.top_topics || []).map(([name,count]) => `<span class="topic">${escapeHtml(name)} · ${number(count)}</span>`).join('') || '<span class="empty">尚無主題</span>'}</div>`, '目前版本')}</div>
      ${processingPanel(data, counts)}`;
  }

  // What the import did with the data (Patty item 1): text status, excluded documents, chunk state, metadata coverage, failures.
  function processingPanel(data, counts) {
    const p = data.processing || {};
    const excluded = Object.entries(counts.excluded || {});
    const names = { indexed: '已建立全文', not_indexed: '未建立全文（圖片檔，由圖片轉文字進入檢索）' };
    const rows = [
      ['已排除（不匯入）', excluded.length ? excluded.map(([reason, n]) => `${escapeHtml(reason)}：${number(n)} 份`).join('、') : '無'],
      ...(p.text_status || []).map(([name, n]) => [`文字狀態：${escapeHtml(names[name] || name)}`, `${number(n)} 份`]),
      ['檢索單位', `${number(counts.chunks_ready)} 個可用／${number(counts.chunks_pending)} 個處理中`],
      ['匯入失敗紀錄', p.failed_jobs ? `${number(p.failed_jobs)} 筆（最近：${escapeHtml((p.latest_failure?.error || '').slice(0, 80))}）` : '無'],
    ];
    const coverage = (p.metadata_coverage || []).map((m) => `<div class="detail-field"><small>${escapeHtml(m.label)}</small><strong>${m.total ? Math.round(m.present / m.total * 100) : 0}%</strong><small>${number(m.present)} / ${number(m.total)} 份有值</small></div>`).join('');
    return panel('資料處理狀態', `<div class="detail-grid">${rows.map(([label, value]) => `<div class="detail-field"><small>${label}</small><strong>${value}</strong></div>`).join('')}</div><h3>metadata 覆蓋率</h3><div class="detail-grid">${coverage}</div>`, '清理、檢索單位、metadata 與失敗');
  }

  function documentFilters() {
    return `<form id="document-filters" class="filters"><label>關鍵字<input name="query" maxlength="200" placeholder="ELR、NPCA、WFA ID…"></label><label>發布者<select name="publisher"><option value="">全部</option></select></label><label>文件角色<select name="document_role"><option value="">全部</option></select></label><button class="primary-button" type="submit">查詢</button><label class="checkbox-label"><input name="include_history" type="checkbox">包含歷史版本</label></form>`;
  }
  async function loadDocuments(page = 1, token = state.renderToken) {
    const form = $('#document-filters');
    const params = new URLSearchParams(new FormData(form));
    params.set('page', page); params.set('page_size', '20');
    const data = await api(`/api/wifi8/documents?${params}`);
    if (token !== state.renderToken || state.route !== 'documents') return;
    state.documentPage = page;
    if (form.publisher.options.length === 1) (data.facets?.publishers || []).forEach(([value,count]) => form.publisher.add(new Option(`${value} (${count})`, value)));
    if (form.document_role.options.length === 1) (data.facets?.document_roles || []).forEach(([value,count]) => form.document_role.add(new Option(`${value} (${count})`, value)));
    const pages = Math.max(1, Math.ceil(data.total / data.page_size));
    $('#document-results').innerHTML = `<p class="results-meta">共 ${number(data.total)} 份，第 ${page} / ${pages} 頁</p><div class="table-wrap"><table><thead><tr><th style="width:42%">文件</th><th>發布者</th><th>角色</th><th>版本</th><th></th></tr></thead><tbody>${data.documents.map((doc) => `<tr><td><span class="document-title" title="${escapeHtml(doc.title)}">${escapeHtml(doc.title)}</span><span class="document-sub">${escapeHtml(doc.wfa_document_id || doc.revision_id)}</span></td><td>${escapeHtml(doc.publisher || '—')}</td><td>${escapeHtml(doc.document_role || '—')}</td><td><span class="tag ${doc.analysis_eligible ? '' : 'history'}">${doc.analysis_eligible ? '目前' : '歷史'}</span></td><td><button class="table-button" data-document="${escapeHtml(doc.revision_id)}">詳情</button></td></tr>`).join('') || '<tr><td colspan="5" class="empty">找不到符合條件的文件</td></tr>'}</tbody></table></div><div class="pagination"><button class="secondary-button" data-page="${page-1}" ${page <= 1 ? 'disabled' : ''}>上一頁</button><button class="secondary-button" data-page="${page+1}" ${page >= pages ? 'disabled' : ''}>下一頁</button></div>`;
  }
  // Search hits and agent citations carry the document title in `source`.
  const hitTitle = (hit) => hit.source || hit.title || hit.document_title || hit.revision_id || '未命名文件';
  const matchedLabels = { fulltext: '全文', vector: '語意' };
  function hitMeta(hit) {
    return [
      hit.location_label, hit.publisher, hit.wfa_document_id ? `WFA ${hit.wfa_document_id}` : '',
      hit.analysis_eligible === false ? '歷史版本' : '',
      (hit.matched_by || []).map((name) => matchedLabels[name] || name).join('＋'),
      hit.score != null ? Number(hit.score).toFixed(4) : '',
    ].filter(Boolean).join(' · ');
  }
  // Tables extracted as rows come with a Markdown display text (display_text); figures show the image with the
  // text it was turned into; other chunks stay plain text.
  function chunkBody(item, text) {
    const image = item && item.image;
    if (image && /^[0-9a-f]{64}$/.test(image.id || '')) {
      return `<figure class="chunk-image"><a href="/api/wifi8/images/${image.id}" target="_blank" rel="noopener"><img src="/api/wifi8/images/${image.id}" alt="${escapeHtml(item.location_label || '文件圖片')}" loading="lazy"></a><figcaption>${escapeHtml(text)}</figcaption></figure>`;
    }
    return item && item.display_text ? `<div class="markdown chunk-table">${renderMarkdown(item.display_text)}</div>` : `<p>${escapeHtml(text)}</p>`;
  }
  async function runHybridSearch() {
    const input = $('#hybrid-query');
    const target = $('#hybrid-results');
    if (!input.value.trim()) return;
    target.innerHTML = '<div class="loading-card">正在執行 BM25 + 向量混合檢索…</div>';
    try {
      const data = await api('/api/wifi8/search', { method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({ query:input.value.trim(), top_k:10, include_history:$('#hybrid-history').checked }) });
      const hits = data.results || data.hits || [];
      target.innerHTML = `<p class="results-meta">${escapeHtml(data.policy || '混合檢索')} · ${hits.length} 筆</p><div class="search-results">${hits.map((hit) => `<article class="search-hit"><h3 title="${escapeHtml(hit.revision_id)}">${escapeHtml(hitTitle(hit))}</h3>${chunkBody(hit, hit.content || hit.text || hit.snippet || '')}<small>${escapeHtml(hitMeta(hit))}</small></article>`).join('') || '<div class="empty">沒有檢索結果</div>'}</div>`;
    } catch (error) { target.innerHTML = `<div class="error-card">${escapeHtml(error.message)}</div>`; }
  }
  async function renderDocuments(token) {
    content.innerHTML = `${panel('文件篩選', documentFilters(), '預設只顯示目前版本')}<section id="document-results" class="panel" style="margin-top:16px"><div class="loading-card">正在載入文件…</div></section>${panel('混合檢索', `<div class="filters"><label>查詢<input id="hybrid-query" maxlength="500" placeholder="輸入中文短詞、縮寫或 WFA ID"></label><label class="checkbox-label"><input id="hybrid-history" type="checkbox">包含歷史版本</label><button id="hybrid-submit" class="primary-button" type="button">開始檢索</button></div><div id="hybrid-results"></div>`, 'BM25 + vector RRF')}`;
    $('#document-filters').addEventListener('submit', (event) => { event.preventDefault(); loadDocuments(1).catch(fail); });
    $('#document-results').addEventListener('click', (event) => { const id = event.target.dataset.document; const page = Number(event.target.dataset.page); if (id) showDocument(id); if (page > 0) loadDocuments(page).catch(fail); });
    $('#hybrid-submit').addEventListener('click', runHybridSearch);
    await loadDocuments(1, token);
  }

  // Figures are numbered after the text, so they get their own section instead of waiting behind the text pages.
  function figureSection(figures) {
    const items = (figures && figures.chunks) || [];
    if (!items.length) return '';
    const more = figures.total > items.length ? `<p class="results-meta">顯示前 ${number(items.length)} 張，共 ${number(figures.total)} 張；其餘可用混合檢索找到</p>` : '';
    return `<h3>文件圖片（${number(figures.total)}）</h3>${more}${items.map((chunk) => `<article class="chunk"><small>#${chunk.chunk_index} · ${escapeHtml(chunk.location_label || '')}</small>${chunkBody(chunk, chunk.content)}</article>`).join('')}`;
  }
  async function showDocument(revisionId) {
    const dialog = $('#document-dialog');
    $('#document-dialog-body').innerHTML = '<div class="loading-card">正在載入文件…</div>'; dialog.showModal();
    try {
      const [detail, chunks, figures] = await Promise.all([api(`/api/wifi8/documents/${encodeURIComponent(revisionId)}`), api(`/api/wifi8/documents/${encodeURIComponent(revisionId)}/chunks?count=8`), api(`/api/wifi8/documents/${encodeURIComponent(revisionId)}/chunks?figures=true&count=12`)]);
      const doc = detail.document || {};
      $('#document-dialog-title').textContent = doc.title || '文件詳情';
      $('#document-dialog-body').innerHTML = `<div class="detail-grid">${[['Revision ID',doc.revision_id],['WFA ID',doc.wfa_document_id],['發布者',doc.publisher],['文件角色',doc.document_role],['日期',doc.document_date],['狀態',doc.analysis_eligible ? '目前版本' : '歷史版本']].map(([label,value]) => `<div class="detail-field"><small>${label}</small><strong>${escapeHtml(value || '—')}</strong></div>`).join('')}</div><h3>版本關係</h3><div class="topic-list">${(detail.versions || []).map((version) => `<span class="topic">${escapeHtml(version.version_label || version.wfa_revision || version.revision_id)}${version.analysis_eligible ? ' · 目前' : ''}</span>`).join('') || '<span class="empty">無其他版本</span>'}</div><h3>來源段落</h3>${(chunks.chunks || []).map((chunk) => `<article class="chunk"><small>#${chunk.chunk_index} · ${escapeHtml(chunk.location_label || '')}</small>${chunkBody(chunk, chunk.content)}</article>`).join('') || '<div class="empty">無可顯示段落</div>'}${figureSection(figures)}`;
    } catch (error) { $('#document-dialog-body').innerHTML = `<div class="error-card">${escapeHtml(error.message)}</div>`; }
  }

  // Minimal Markdown for agent answers. The text is HTML-escaped before any rule runs,
  // so only the tags generated here reach the page (no raw HTML, no links).
  function inlineMarkdown(text) {
    return text.split(/(`[^`\n]+`)/).map((part, index) => index % 2
      ? `<code>${part.slice(1, -1)}</code>`
      : part.replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
        .replace(/(^|[^*\w])\*(?!\s)([^*\n]+?)\*(?!\w)/g, '$1<em>$2</em>')
        .replace(/\[(S\d+)\]/g, '<span class="cite-ref">[$1]</span>')
        .replace(/\[(G\d+)\]/g, '<span class="cite-ref graph-ref" title="知識圖譜關聯（LLM 抽取，未逐句驗證）">[$1]</span>')).join('');
  }
  const markdownList = /^\s*([-*+]|\d+[.)])\s+(.*)$/;
  const markdownBlock = /^\s*(```|#{1,6}\s|[-*+]\s|\d+[.)]\s|&gt;|\|)/;
  const tableRow = (line) => /^\s*\|.*\|\s*$/.test(line);
  const tableCells = (line) => line.trim().replace(/^\||\|$/g, '').split('|').map((cell) => inlineMarkdown(cell.trim()));
  function renderMarkdown(source) {
    const lines = escapeHtml(source).replace(/\r\n?/g, '\n').split('\n');
    const html = [];
    let i = 0;
    while (i < lines.length) {
      const line = lines[i];
      let match;
      if (!line.trim()) { i += 1; continue; }
      if (/^\s*```/.test(line)) {
        const code = [];
        for (i += 1; i < lines.length && !/^\s*```/.test(lines[i]); i += 1) code.push(lines[i]);
        i += 1; html.push(`<pre><code>${code.join('\n')}</code></pre>`); continue;
      }
      if ((match = line.match(/^\s*(#{1,6})\s+(.*)$/))) {
        const level = Math.min(match[1].length + 2, 6);
        html.push(`<h${level}>${inlineMarkdown(match[2])}</h${level}>`); i += 1; continue;
      }
      if (/^\s*([-*_])(\s*\1){2,}\s*$/.test(line)) { html.push('<hr>'); i += 1; continue; }
      if (tableRow(line) && /^\s*\|?\s*:?-{3,}/.test(lines[i + 1] || '')) {
        const head = tableCells(line); const rows = [];
        for (i += 2; i < lines.length && tableRow(lines[i]); i += 1) rows.push(tableCells(lines[i]));
        html.push(`<div class="md-table"><table><thead><tr>${head.map((cell) => `<th>${cell}</th>`).join('')}</tr></thead><tbody>${rows.map((row) => `<tr>${row.map((cell) => `<td>${cell}</td>`).join('')}</tr>`).join('')}</tbody></table></div>`);
        continue;
      }
      if ((match = line.match(markdownList))) {
        const ordered = /\d/.test(match[1]); const items = [];
        const start = ordered ? parseInt(match[1], 10) : 1;
        while (i < lines.length && (match = lines[i].match(markdownList)) && /\d/.test(match[1]) === ordered) {
          items.push(inlineMarkdown(match[2])); i += 1;
          let next = i; while (next < lines.length && !lines[next].trim()) next += 1;  // loose list: blank lines between items
          if (next < lines.length && (match = lines[next].match(markdownList)) && /\d/.test(match[1]) === ordered) i = next;
        }
        const tag = ordered ? 'ol' : 'ul';
        html.push(`<${tag}${ordered && start !== 1 ? ` start="${start}"` : ''}>${items.map((item) => `<li>${item}</li>`).join('')}</${tag}>`); continue;
      }
      if (/^\s*&gt;/.test(line)) {
        const quote = [];
        for (; i < lines.length && /^\s*&gt;/.test(lines[i]); i += 1) quote.push(lines[i].replace(/^\s*&gt;\s?/, ''));
        html.push(`<blockquote>${inlineMarkdown(quote.join('<br>'))}</blockquote>`); continue;
      }
      const paragraph = [];
      do { paragraph.push(lines[i]); i += 1; } while (i < lines.length && lines[i].trim() && !markdownBlock.test(lines[i]));
      html.push(`<p>${inlineMarkdown(paragraph.join('<br>'))}</p>`);
    }
    return html.join('');
  }
  function citationItem(item, index) {
    if (typeof item !== 'object' || item === null) return `<li><strong>[${index + 1}]</strong> ${escapeHtml(item)}</li>`;
    const meta = [item.publisher, item.wfa_document_id ? `WFA ${item.wfa_document_id}` : '', item.analysis_eligible === false ? '歷史版本' : ''].filter(Boolean).join(' · ');
    const image = item.image && /^[0-9a-f]{64}$/.test(item.image.id || '') ? item.image : null;
    // Where in the document the cited text is (page / slide / figure): shown prominently, figures get a badge and
    // a thumbnail that opens the image, so an answer read from a figure can be checked against it.
    // Several chunks of one page / slide are told apart by their position there ("第 3 頁・第 1/2 段").
    const part = item.part && item.part.total > 1 ? `・第 ${Number(item.part.index)}/${Number(item.part.total)} 段` : '';
    const place = item.location_label ? `<span class="citation-place">${escapeHtml(item.location_label)}${part}</span>` : '';
    const badge = image ? '<span class="citation-badge">圖片</span>' : '';
    const thumb = image ? `<a class="citation-thumb" href="/api/wifi8/images/${image.id}" target="_blank" rel="noopener" title="開啟原圖"><img src="/api/wifi8/images/${image.id}" alt="${escapeHtml(item.location_label || '引用圖片')}" loading="lazy"></a>` : '';
    return `<li class="${image ? 'citation-figure' : ''}">${thumb}<div><strong>[${escapeHtml(item.ref || index + 1)}]</strong> <span title="${escapeHtml(item.revision_id)}">${escapeHtml(hitTitle(item))}</span><div class="citation-meta">${badge}${place}${meta ? `<small>${escapeHtml(meta)}</small>` : ''}</div></div></li>`;
  }
  // Grounding check computed by the worker against the full text of the cited chunks (absent on older answers).
  const groundingReasons = { no_source: '未附來源', value_not_found: '數值在資料中找不到', value_other_source: '數值出現在其他引用', value_not_in_cited: '數值不在引用的段落', source_name_mismatch: '引用的不是題目指名的文件', low_similarity: '與原文相似度低' };
  function groundingChip(label, text, tone) { return `<span class="g-chip ${tone}"><small>${label}</small>${escapeHtml(text)}</span>`; }
  function groundingPanel(grounding) {
    if (!grounding) return '';
    if (grounding.error) return '<p class="grounding-note">依據檢核未完成，請以引用原文為準。</p>';
    const s = grounding.summary || {};
    if (!s.claims) return '';
    const sim = s.similarity || {};
    const flagged = grounding.flagged || [];
    const supported = (s.claims_cited || 0) + (s.claims_tool_data || 0);
    const found = (s.values_verified || 0) + (s.values_other_source || 0) + (s.values_tool_data || 0);
    const chips = [
      groundingChip('有依據的句子', `${supported}/${s.claims}${s.claims_tool_data ? `（${s.claims_tool_data} 句依工具資料）` : ''}`, supported === s.claims ? 'ok' : supported / s.claims >= 0.8 ? 'warn' : 'bad'),
      s.values ? groundingChip('數值核對', `${found}/${s.values} 可在資料中找到${s.values_not_found ? `，${s.values_not_found} 找不到` : ''}`, s.values_not_found ? 'bad' : 'ok') : groundingChip('數值核對', '無數值', 'ok'),
      s.similarity_enabled && (sim.high || sim.medium || sim.low) ? groundingChip('原文相似度', `高 ${sim.high || 0}・中 ${sim.medium || 0}・低 ${sim.low || 0}`, sim.low ? 'warn' : 'ok') : '',
      s.sources && s.sources.total ? groundingChip('引用來源', `${s.sources.wfa} 份 WFA・${s.sources.current}/${s.sources.total} 份目前版本`, s.sources.current === s.sources.total ? 'ok' : 'warn') : '',
    ].join('');
    const items = flagged.map((f) => `<li><p>${escapeHtml(f.text)}${(f.refs || []).length ? ` <span class="cite-ref">[${escapeHtml(f.refs.join('][')) }]</span>` : ''}</p><div>${(f.reasons || []).map((r) => `<span class="g-reason ${r}">${escapeHtml(groundingReasons[r] || r)}</span>`).join('')}${(f.values || []).map((v) => `<code class="${v.status}" title="${v.status === 'not_found' ? '在 Agent 取得的資料中找不到' : v.status === 'not_in_cited' ? '不在本句引用的段落' : '出現在其他引用，不在本句引用的段落'}">${escapeHtml(v.value)}</code>`).join('')}${(f.names || []).map((n) => `<code class="not_in_cited" title="本句提到的文件，引用的段落不是這份文件">${escapeHtml(n)}</code>`).join('')}${f.similarity != null && (f.reasons || []).includes('low_similarity') ? `<small>相似度 ${Number(f.similarity).toFixed(2)}</small>` : ''}</div></li>`).join('');
    return `<section class="grounding" aria-label="依據檢核"><div class="grounding-head"><strong>依據檢核</strong><div class="g-chips">${chips}</div></div><p class="grounding-note">由程式比對 Agent 取得的原文段落與文件資料：檢查每句是否有引用，以及數字、版本、型號是否真的出現在資料中${s.similarity_enabled ? '；相似度只代表用詞接近程度，不代表內容正確' : ''}。這是輔助檢核，不保證內容正確。</p>${flagged.length ? `<details><summary>需留意的句子（${flagged.length}）</summary><ul class="g-flags">${items}</ul></details>` : '<p class="grounding-note ok">所有句子都有依據，數值皆可在資料中找到。</p>'}</section>`;
  }
  // Extension of an answer: related knowledge (graph/documents), labelled general knowledge, follow-up questions. Only present when the zone enables it.
  function graphCitationItem(item) {
    const kind = item.kind === 'topic' ? '主題' : '文件';
    const detail = [item.document_role, item.publisher, item.lifecycle].filter(Boolean).join('・');
    return `<li><strong>[${escapeHtml(item.ref)}]</strong> ${kind}：${escapeHtml(item.title || item.key)}${detail ? `<small>${escapeHtml(detail)}</small>` : ''}</li>`;
  }
  function extensionPanel(value) {
    const ext = value.extension; if (!ext) return '';
    const graph = (value.graph_citations || []).map(graphCitationItem).join('');
    const parts = [
      ext.related ? `<section class="ext-section"><h4>相關主題與文件<small>來自專區文件與知識圖譜（圖譜關聯由 LLM 抽取，未逐句驗證）</small></h4><div class="markdown">${renderMarkdown(ext.related)}</div>${graph ? `<ul class="citation-list graph-list">${graph}</ul>` : ''}</section>` : '',
      ext.general ? `<section class="ext-section ext-general"><h4>一般知識補充<small>模型的一般知識，未經專區文件驗證</small></h4><div class="markdown">${renderMarkdown(ext.general)}</div></section>` : '',
      (ext.followups || []).length ? `<section class="ext-section"><h4>你可能還想問</h4><div class="followups">${ext.followups.map((q) => `<button type="button" class="followup" data-question="${escapeHtml(q)}">${escapeHtml(q)}</button>`).join('')}</div></section>` : '',
    ].filter(Boolean).join('');
    return parts ? `<div class="extension" aria-label="延伸知識"><strong class="ext-title">延伸知識</strong>${parts}</div>` : '';
  }
  function agentOutput(value) {
    const answer = value.answer_main || value.answer || value.result || value.message || '未回傳回答';
    const citations = value.citations || value.sources || [];
    const trace = value.steps || value.tool_steps || value.trace || [];
    return `<div class="message assistant markdown">${renderMarkdown(answer)}</div>${extensionPanel(value)}${groundingPanel(value.grounding)}<ul class="citation-list">${citations.map(citationItem).join('')}</ul><details><summary>Agent 工具步驟與停止原因</summary><ul class="trace-list">${trace.map((item) => `<li>${escapeHtml(typeof item === 'string' ? item : item.tool || item.name || JSON.stringify(item))}</li>`).join('') || '<li>無工具步驟</li>'}</ul><p class="results-meta">${escapeHtml(value.stop_reason || value.status || '')}</p></details>`;
  }
  async function pollAgent(taskId) {
    for (let attempt = 0; attempt < 120; attempt += 1) {
      const result = await api(`/api/wifi8/agent/${encodeURIComponent(taskId)}`);
      if (result.status !== 'pending' && result.status !== 'submitted') return result;
      await new Promise((resolve) => setTimeout(resolve, 1500));
    }
    throw new Error('Agent 等待逾時，請稍後重試');
  }
  async function askAgent() {
    const input = $('#agent-question'); const question = input.value.trim(); if (!question) return;
    const button = $('#agent-submit'); button.disabled = true;
    $('#conversation').insertAdjacentHTML('beforeend', `<div class="message user">${escapeHtml(question)}</div><div id="agent-wait" class="message assistant">正在調用 WiFi Agent…</div>`);
    input.value = '';
    try {
      const submitted = await api('/api/wifi8/agent', { method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({ question, history:state.conversation.slice(-12) }) });
      const result = await pollAgent(submitted.task_id); $('#agent-wait').outerHTML = agentOutput(result);
      state.conversation.push({role:'user',content:question},{role:'assistant',content:result.answer_main || result.answer || result.result || ''});
    } catch (error) { $('#agent-wait').outerHTML = `<div class="message error">${escapeHtml(error.message)}</div>`; }
    finally { button.disabled = false; }
  }
  async function renderAgent() {
    content.innerHTML = `<div class="ai-layout">${panel('AI research assistant', `<div id="conversation" class="conversation"><div class="message assistant">我會使用 WiFi 專區的文件與版本關係回答，並保留引用與工具步驟。</div></div><label>問題<textarea id="agent-question" maxlength="2000" placeholder="例如：ELR 的規格重點是什麼？"></textarea></label><div class="ai-actions"><small class="results-meta">回答以目前匯入資料為準</small><button id="agent-submit" class="primary-button" type="button">送出問題</button></div>`)}${panel('可追溯輸出', '<p>每次回答會同時顯示：</p><ul><li>引用文件</li><li>Agent 工具步驟</li><li>停止原因與錯誤狀態</li></ul>', 'EXISTING KM PIPELINE')}</div>`;
    $('#agent-submit').addEventListener('click', askAgent);
    // A suggested follow-up fills the question box; the user decides whether to send it.
    $('#conversation').addEventListener('click', (event) => {
      const button = event.target.closest('.followup'); if (!button) return;
      const input = $('#agent-question'); input.value = button.dataset.question || ''; input.focus();
    });
  }

  function imageProgress(job) {
    const images = job.images;
    if (!images || !images.distinct) return '';
    const finished = Number(images.described || 0) + Number(images.empty || 0) + Number(images.failed || 0);
    return `<div class="job-meta">圖片轉文字 ${number(finished)} / ${number(images.distinct)}（有內容 ${number(images.described || 0)}、無內容 ${number(images.empty || 0)}、失敗 ${number(images.failed || 0)}）</div>`;
  }
  function jobRow(job) {
    const total = Number(job.total || job.total_chunks || job.progress?.total || 0); const done = Number(job.completed || job.ready || job.progress?.completed || 0); const value = total ? Math.round(done / total * 100) : (/complete|success/.test(job.status || '') ? 100 : 0);
    return `<li class="job-item"><div class="job-head"><strong>${escapeHtml(job.job_id || '匯入工作')}</strong><span class="status-badge ${statusClass(job.status)}">${escapeHtml(job.status || '未知')}</span></div><div class="job-meta">${escapeHtml(job.stage || '')} ${done || total ? `· ${number(done)} / ${number(total)}` : ''} · ${formatTime(job.updated_at || job.created_at)}</div>${imageProgress(job)}${job.message ? `<p class="job-meta">${escapeHtml(job.message)}</p>` : ''}${job.error ? `<p class="error-card">${escapeHtml(job.error)}</p>` : ''}<progress max="100" value="${value}"></progress></li>`;
  }
  // Automatic quality check after a data update: the switch is a file in this zone (see src/wifi8/autocheck.py); the host's watcher reads it.
  function autoCheckPanel(info) {
    const on = info.enabled !== false; const can = info.can_change === true;
    const locked = can ? '' : '<p id="auto-check-locked" class="results-meta" role="note">您的帳號尚未獲得這個開關的授權，只能查看目前狀態。需要使用時，請聯絡 KM 管理員，在「帳號與資料區授權管理」頁授權。</p>';
    const last = info.last_check ? `${formatTime(info.last_check.at)}（${escapeHtml(info.last_check.status || '—')}；資料版本 ${escapeHtml(info.last_check.package_id || '—')}）` : '尚無資料更新後的檢查紀錄';
    const alive = info.last_poll_at ? formatTime(info.last_poll_at) : '尚未回報';
    const warn = info.watcher_overdue ? `<p class="auto-check-warn" role="alert">監看程式超過 ${Number(info.interval_minutes || 5) * 3} 分鐘沒有回報，開關仍會記住，但目前不會自動檢查，請通知開發者。</p>` : '';
    const body = `<div class="auto-check-row"><label class="switch${can ? '' : ' is-locked'}"><input id="auto-check-toggle" type="checkbox" role="switch" ${on ? 'checked' : ''} ${can ? '' : 'disabled'} aria-describedby="auto-check-note"><span class="switch-track" aria-hidden="true"></span><span id="auto-check-state">${on ? '已開啟' : '已關閉'}</span></label>
      <p id="auto-check-note" class="results-meta">新資料匯入完成後，系統每 ${Number(info.interval_minutes || 5)} 分鐘確認一次，發現資料更新就自動做品質檢查（檢索、回答、可信度），有問題會通知開發者。關閉後不再自動檢查，重新開啟時會補檢查關閉期間的資料更新；每日與每週的排程檢查不受影響。</p></div>
      ${locked}${warn}<dl class="auto-check-status"><dt>最近輪詢</dt><dd>${escapeHtml(alive)}</dd><dt>目前監看的資料版本</dt><dd>${escapeHtml(info.watching?.package_id || '—')}</dd><dt>最近一次資料更新檢查</dt><dd>${last}</dd><dt>開關最後變更</dt><dd>${info.changed_at ? `${escapeHtml(info.changed_by || '—')}，${formatTime(info.changed_at)}` : '尚未變更（預設開啟）'}</dd></dl>
      <p id="auto-check-message" class="results-meta" role="status" aria-live="polite"></p>`;
    return panel('資料更新後自動檢查', body, on ? '已開啟' : '已關閉');
  }
  function bindAutoCheck(host) {
    const toggle = $('#auto-check-toggle');
    if (!toggle || toggle.disabled) return;
    toggle.addEventListener('change', async () => {
      const wanted = toggle.checked; const message = $('#auto-check-message'); toggle.disabled = true; message.textContent = '正在儲存…';
      try {
        const info = await api('/api/wifi8/auto-check', { method: 'POST', headers: { 'x-km-wifi8-setting': '1', 'Content-Type': 'application/json' }, body: JSON.stringify({ enabled: wanted }) });
        host.innerHTML = autoCheckPanel(info); bindAutoCheck(host); $('#auto-check-message').textContent = wanted ? '已開啟自動檢查。' : '已關閉自動檢查。';
      } catch (error) {
        toggle.checked = !wanted; toggle.disabled = false; message.textContent = `儲存失敗：${error.message}`;
        try { host.innerHTML = autoCheckPanel(await api('/api/wifi8/auto-check')); bindAutoCheck(host); $('#auto-check-message').textContent = `儲存失敗：${error.message}`; } catch (_) { /* keep the message */ }
      }
    });
  }
  // When the zone's scheduled quality check runs: everybody sees the time, only an account that a KM Control admin authorised for this zone
  // can change it. The page mirrors can_change from GET /api/wifi8/quality-schedule; the server checks again on every change.
  // The time is picked on a 24-hour clock with two selects (a time input would show AM/PM on some systems); minutes are offered in
  // steps of 5, the interval at which the host looks whether a check is due.
  function qualitySchedulePanel(info) {
    const can = info.can_change === true;
    const [hour, minute] = String(info.time || '03:30').split(':');
    const hours = Array.from({ length: 24 }, (_, h) => String(h).padStart(2, '0'));
    const minutes = Array.from({ length: 12 }, (_, i) => String(i * 5).padStart(2, '0'));
    if (!minutes.includes(minute)) { minutes.push(minute); minutes.sort(); }
    const options = (list, current) => list.map((v) => `<option value="${v}"${v === current ? ' selected' : ''}>${v}</option>`).join('');
    const clock = info.timezone === 'Asia/Taipei' ? '台北時間' : escapeHtml(info.timezone || '');
    const dis = can ? '' : 'disabled';
    const locked = can ? '' : '<p id="quality-schedule-locked" class="results-meta" role="note">您的帳號尚未獲得這個設定的授權，只能查看目前時間。需要更改時，請聯絡 KM 管理員，在「帳號與資料區授權管理」頁授權。</p>';
    const body = `<p id="quality-schedule-note" class="results-meta">每天在這個時間為這個資料區執行品質檢查：檢索與回答可信度；每週日另外加跑 Agent 回答檢查（會把題庫逐題問 Agent，使用語言模型，較久）。檢查跑完一律通知 Telegram，不論通過、警示、失敗或無法執行。預設 03:30。</p>
      <div class="summary-time-row" role="group" aria-label="品質檢查時間（24 小時制）"><span>每天</span>
        <select id="quality-schedule-hour" aria-label="時（00 到 23）" ${dis}>${options(hours, hour)}</select><span aria-hidden="true">:</span>
        <select id="quality-schedule-minute" aria-label="分" ${dis}>${options(minutes, minute)}</select>
        <span class="results-meta">24 小時制・${clock}</span>
        <button id="quality-schedule-save" class="secondary-button" type="button" disabled>儲存時間</button></div>
      ${locked}<dl class="auto-check-status"><dt>目前設定</dt><dd>每天 ${escapeHtml(info.time || '03:30')}（${clock}）</dd><dt>最後變更</dt><dd>${info.changed_at ? `${escapeHtml(info.changed_by || '—')}，${formatTime(info.changed_at)}` : '尚未變更（使用預設時間）'}</dd></dl>
      <p id="quality-schedule-message" class="results-meta" role="status" aria-live="polite"></p>`;
    return panel('品質檢查排程', body, `每天 ${escapeHtml(info.time || '03:30')}`);
  }
  function bindQualitySchedule(host) {
    const hour = $('#quality-schedule-hour'); const minute = $('#quality-schedule-minute'); const save = $('#quality-schedule-save');
    if (!hour || hour.disabled) return;
    const initial = `${hour.value}:${minute.value}`; const picked = () => `${hour.value}:${minute.value}`;
    const sync = () => { save.disabled = picked() === initial; };
    hour.addEventListener('change', sync); minute.addEventListener('change', sync);
    save.addEventListener('click', async () => {
      const message = $('#quality-schedule-message'); const controls = [hour, minute, save]; controls.forEach((c) => { c.disabled = true; }); message.textContent = '正在儲存…';
      try {
        const info = await api('/api/wifi8/quality-schedule', { method: 'POST', headers: { 'x-km-wifi8-setting': '1', 'Content-Type': 'application/json' }, body: JSON.stringify({ time: picked() }) });
        host.innerHTML = qualitySchedulePanel(info); bindQualitySchedule(host); $('#quality-schedule-message').textContent = `已儲存：每天 ${info.time} 執行品質檢查，跑完會通知 Telegram。`;
      } catch (error) {
        try { host.innerHTML = qualitySchedulePanel(await api('/api/wifi8/quality-schedule')); bindQualitySchedule(host); $('#quality-schedule-message').textContent = `儲存失敗：${error.message}`; }
        catch (_) { controls.forEach((c) => { c.disabled = false; }); message.textContent = `儲存失敗：${error.message}`; }
      }
    });
  }
  async function renderJobs(token) {
    const data = await api('/api/wifi8/jobs');
    if (token !== state.renderToken) return;
    let upload = '';
    try { const status = await api('/api/wifi8/status'); if (status.upload_enabled) upload = `<div class="upload-box"><form id="upload-form" class="upload-row"><label>Wi-Fi8 匯出包 (.zip)<input name="file" type="file" accept=".zip" required></label><button class="primary-button" type="submit">上傳並匯入</button></form><p id="upload-status" class="results-meta">匯入完成前不會切換目前版本。</p></div>`; } catch (_) { /* jobs remain readable */ }
    let autoCheck = '<div id="auto-check-host"></div>';
    try { autoCheck = `<div id="auto-check-host">${autoCheckPanel(await api('/api/wifi8/auto-check'))}</div>`; } catch (_) { /* the jobs stay readable without the switch */ }
    let qualitySchedule = '<div id="quality-schedule-host"></div>';
    try { qualitySchedule = `<div id="quality-schedule-host">${qualitySchedulePanel(await api('/api/wifi8/quality-schedule'))}</div>`; } catch (_) { /* the jobs stay readable without it */ }
    content.innerHTML = panel('匯入工作', `${upload}<ul class="job-list">${(data.jobs || []).map(jobRow).join('') || '<li class="empty">尚無匯入工作</li>'}</ul>`, `${(data.jobs || []).length} 筆近期工作`) + autoCheck + qualitySchedule;
    if ($('#auto-check-host')?.firstElementChild) bindAutoCheck($('#auto-check-host'));
    if ($('#quality-schedule-host')?.firstElementChild) bindQualitySchedule($('#quality-schedule-host'));
    $('#upload-form')?.addEventListener('submit', async (event) => { event.preventDefault(); const message = $('#upload-status'); message.textContent = '正在上傳…'; try { const result = await api('/api/wifi8/packages', { method:'POST', headers:{'x-km-wifi8-import':'1'}, body:new FormData(event.target) }); message.textContent = `已送出 ${result.job_id}`; setTimeout(() => renderRoute(), 1000); } catch (error) { message.textContent = error.message; } });
  }

  function renderPlaceholder(route) {
    const [title, description] = routeInfo[route];
    content.innerHTML = `<section class="placeholder-card"><div><span class="placeholder-icon">⌘</span><h2>${title}</h2><p>${description}</p><p>這個頁面已保留完整導覽與版型，功能尚未從參考站移植。</p><span class="mode-badge">功能待移植</span></div></section>`;
  }
  async function renderRoute() {
    const token = ++state.renderToken;
    const candidate = (location.hash.replace(/^#\//, '').split('/')[0] || 'overview');
    state.route = routeInfo[candidate] ? candidate : 'overview'; renderNav(); setHeader(state.route); content.innerHTML = '<div class="loading-card">正在載入…</div>'; $('#app').setAttribute('aria-busy','true');
    try {
      if (state.route === 'overview') await renderOverview(token); else if (state.route === 'documents') await renderDocuments(token); else if (state.route === 'ai') await renderAgent(); else if (state.route === 'jobs') await renderJobs(token); else renderPlaceholder(state.route);
    } catch (error) { fail(error); }
    finally { $('#app').setAttribute('aria-busy','false'); content.focus({preventScroll:true}); $('#primary-nav').classList.remove('open'); $('#nav-toggle').setAttribute('aria-expanded','false'); }
  }

  $('#nav-toggle').addEventListener('click', () => { const open = $('#primary-nav').classList.toggle('open'); $('#nav-toggle').setAttribute('aria-expanded', String(open)); });
  $('#refresh-page').addEventListener('click', async (event) => { event.currentTarget.classList.add('is-loading'); event.currentTarget.disabled = true; await renderRoute(); event.currentTarget.classList.remove('is-loading'); event.currentTarget.disabled = false; });
  $('#close-dialog').addEventListener('click', () => $('#document-dialog').close());
  window.addEventListener('hashchange', renderRoute);

  // A tab opened before a deploy keeps running the old code; tell the user when the server serves another build.
  async function checkForUpdate() {
    if (!LOADED_SCRIPT || $('#update-banner')) return;
    try {
      const response = await fetch('/wifi8/', { cache: 'no-store', credentials: 'same-origin', redirect: 'manual' });
      const current = response.ok ? ((await response.text()).match(/wifi8\.[0-9a-f]{12}\.js/) || [''])[0] : '';
      if (!current || current === LOADED_SCRIPT) return;
      const banner = document.createElement('div');
      banner.id = 'update-banner'; banner.className = 'update-banner'; banner.setAttribute('role', 'status');
      banner.innerHTML = '<span>WiFi 專區已更新，請重新整理以使用最新版本。</span><button type="button" class="primary-button">重新整理</button>';
      banner.querySelector('button').addEventListener('click', () => location.reload());
      document.body.prepend(banner);
    } catch (_) { /* offline or logged out: check again later */ }
  }
  setInterval(checkForUpdate, 5 * 60 * 1000);
  document.addEventListener('visibilitychange', () => { if (document.visibilityState === 'visible') checkForUpdate(); });

  let returnRoute = null;
  try { returnRoute = sessionStorage.getItem(RETURN_ROUTE_KEY); sessionStorage.removeItem(RETURN_ROUTE_KEY); } catch (_) { /* no storage */ }
  if (!location.hash) location.replace(returnRoute && /^#\/[\w-]+/.test(returnRoute) && routeInfo[returnRoute.slice(2).split('/')[0]] ? returnRoute : '#/overview'); else renderRoute();
})();
