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
  const state = { route: 'overview', overview: null, documentPage: 1, conversation: [], agentTask: null };
  const $ = (selector) => document.querySelector(selector);
  const content = $('#page-content');
  const escapeHtml = (value) => String(value ?? '').replace(/[&<>"']/g, (char) => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[char]));
  const number = (value) => Number(value || 0).toLocaleString('zh-TW');
  const formatTime = (value) => value ? new Date(value).toLocaleString('zh-TW', { hour12: false }) : '—';

  async function api(path, options = {}) {
    const response = await fetch(path, { credentials: 'same-origin', ...options, headers: { Accept: 'application/json', ...(options.headers || {}) } });
    if (response.status === 401) {
      location.assign(`/login.html?next=${encodeURIComponent('/wifi8/' + location.hash)}`);
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
  function categoryRows(items = []) {
    const max = Math.max(1, ...items.map((item) => Number(item[1] || 0)));
    return `<div class="category-list">${items.slice(0, 12).map(([name, count]) => `<div class="category-row"><span class="category-name" title="${escapeHtml(name)}">${escapeHtml(name)}</span><progress class="category-bar" max="${max}" value="${Number(count || 0)}"></progress><span class="category-value">${number(count)}</span></div>`).join('') || '<div class="empty">尚無分類資料</div>'}</div>`;
  }

  async function renderOverview() {
    const data = state.overview = await api('/api/wifi8/overview');
    const counts = data.counts || {};
    const current = data.current || {};
    const job = data.active_job;
    $('#zone-status').textContent = `${number(counts.documents)} 份文件`;
    content.innerHTML = `
      <section class="health-panel"><div class="section-intro"><div><span class="health-icon">⌑</span><div><h2>系統狀態</h2><p>目前資料版本與匯入進度</p></div></div><span class="inline-note">LIVE API</span></div>
        <div class="health-grid">${healthItem('◈','資料集','可用', current.package_id || current.version || current.import_id || '目前版本')}${healthItem('▤','文件','已索引',`${number(counts.current_documents)} 目前 / ${number(counts.superseded_documents)} 歷史`)}${healthItem('⌕','檢索單位','已就緒',`${number(counts.chunks || counts.retrieval_units)} 個`)}${healthItem('⇩','匯入工作',job ? (job.status || '執行中') : '無進行中工作',job?.job_id || '穩定',job ? 'warning' : '')}</div></section>
      <div class="overview-grid">${panel('內容統計', `<div class="metric-grid">${[['▤','全部文件',counts.documents],['◈','目前版本',counts.current_documents],['◷','歷史版本',counts.superseded_documents],['⌕','檢索單位',counts.chunks || counts.retrieval_units]].map(([icon,label,value]) => `<div class="metric"><span class="metric-icon">${icon}</span><div class="metric-copy"><span>${label}</span><strong>${number(value)}</strong><small>來自目前匯入版本</small></div></div>`).join('')}</div>`, '僅顯示真實匯入統計')}${panel('發布者', categoryRows(data.by_publisher), '目前版本')}</div>
      <div class="overview-grid">${panel('文件角色', categoryRows(data.by_document_role))}${panel('主題', `<div class="topic-list">${(data.top_topics || []).map(([name,count]) => `<span class="topic">${escapeHtml(name)} · ${number(count)}</span>`).join('') || '<span class="empty">尚無主題</span>'}</div>`)}</div>`;
  }

  function documentFilters() {
    return `<form id="document-filters" class="filters"><label>關鍵字<input name="query" maxlength="200" placeholder="ELR、NPCA、WFA ID…"></label><label>發布者<select name="publisher"><option value="">全部</option></select></label><label>文件角色<select name="document_role"><option value="">全部</option></select></label><button class="primary-button" type="submit">查詢</button><label class="checkbox-label"><input name="include_history" type="checkbox">包含歷史版本</label></form>`;
  }
  async function loadDocuments(page = 1) {
    const form = $('#document-filters');
    const params = new URLSearchParams(new FormData(form));
    params.set('page', page); params.set('page_size', '20');
    const data = await api(`/api/wifi8/documents?${params}`);
    state.documentPage = page;
    if (form.publisher.options.length === 1) (data.facets?.publishers || []).forEach(([value,count]) => form.publisher.add(new Option(`${value} (${count})`, value)));
    if (form.document_role.options.length === 1) (data.facets?.document_roles || []).forEach(([value,count]) => form.document_role.add(new Option(`${value} (${count})`, value)));
    const pages = Math.max(1, Math.ceil(data.total / data.page_size));
    $('#document-results').innerHTML = `<p class="results-meta">共 ${number(data.total)} 份，第 ${page} / ${pages} 頁</p><div class="table-wrap"><table><thead><tr><th style="width:42%">文件</th><th>發布者</th><th>角色</th><th>版本</th><th></th></tr></thead><tbody>${data.documents.map((doc) => `<tr><td><span class="document-title" title="${escapeHtml(doc.title)}">${escapeHtml(doc.title)}</span><span class="document-sub">${escapeHtml(doc.wfa_document_id || doc.revision_id)}</span></td><td>${escapeHtml(doc.publisher || '—')}</td><td>${escapeHtml(doc.document_role || '—')}</td><td><span class="tag ${doc.analysis_eligible ? '' : 'history'}">${doc.analysis_eligible ? '目前' : '歷史'}</span></td><td><button class="table-button" data-document="${escapeHtml(doc.revision_id)}">詳情</button></td></tr>`).join('') || '<tr><td colspan="5" class="empty">找不到符合條件的文件</td></tr>'}</tbody></table></div><div class="pagination"><button class="secondary-button" data-page="${page-1}" ${page <= 1 ? 'disabled' : ''}>上一頁</button><button class="secondary-button" data-page="${page+1}" ${page >= pages ? 'disabled' : ''}>下一頁</button></div>`;
  }
  async function runHybridSearch() {
    const input = $('#hybrid-query');
    const target = $('#hybrid-results');
    if (!input.value.trim()) return;
    target.innerHTML = '<div class="loading-card">正在執行 BM25 + 向量混合檢索…</div>';
    try {
      const data = await api('/api/wifi8/search', { method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({ query:input.value.trim(), top_k:10, include_history:$('#hybrid-history').checked }) });
      const hits = data.results || data.hits || [];
      target.innerHTML = `<p class="results-meta">${escapeHtml(data.policy || '混合檢索')} · ${hits.length} 筆</p><div class="search-results">${hits.map((hit) => `<article class="search-hit"><h3>${escapeHtml(hit.title || hit.document_title || hit.revision_id)}</h3><p>${escapeHtml(hit.content || hit.text || hit.snippet || '')}</p><small>${escapeHtml(hit.location_label || hit.publisher || '')}${hit.score != null ? ` · ${Number(hit.score).toFixed(4)}` : ''}</small></article>`).join('') || '<div class="empty">沒有檢索結果</div>'}</div>`;
    } catch (error) { target.innerHTML = `<div class="error-card">${escapeHtml(error.message)}</div>`; }
  }
  async function renderDocuments() {
    content.innerHTML = `${panel('文件篩選', documentFilters(), '預設只顯示目前版本')}<section id="document-results" class="panel" style="margin-top:16px"><div class="loading-card">正在載入文件…</div></section>${panel('混合檢索', `<div class="filters"><label>查詢<input id="hybrid-query" maxlength="500" placeholder="輸入中文短詞、縮寫或 WFA ID"></label><label class="checkbox-label"><input id="hybrid-history" type="checkbox">包含歷史版本</label><button id="hybrid-submit" class="primary-button" type="button">開始檢索</button></div><div id="hybrid-results"></div>`, 'BM25 + vector RRF')}`;
    $('#document-filters').addEventListener('submit', (event) => { event.preventDefault(); loadDocuments(1).catch(fail); });
    $('#document-results').addEventListener('click', (event) => { const id = event.target.dataset.document; const page = Number(event.target.dataset.page); if (id) showDocument(id); if (page > 0) loadDocuments(page).catch(fail); });
    $('#hybrid-submit').addEventListener('click', runHybridSearch);
    await loadDocuments();
  }

  async function showDocument(revisionId) {
    const dialog = $('#document-dialog');
    $('#document-dialog-body').innerHTML = '<div class="loading-card">正在載入文件…</div>'; dialog.showModal();
    try {
      const [detail, chunks] = await Promise.all([api(`/api/wifi8/documents/${encodeURIComponent(revisionId)}`), api(`/api/wifi8/documents/${encodeURIComponent(revisionId)}/chunks?count=8`)]);
      const doc = detail.document || {};
      $('#document-dialog-title').textContent = doc.title || '文件詳情';
      $('#document-dialog-body').innerHTML = `<div class="detail-grid">${[['Revision ID',doc.revision_id],['WFA ID',doc.wfa_document_id],['發布者',doc.publisher],['文件角色',doc.document_role],['日期',doc.document_date],['狀態',doc.analysis_eligible ? '目前版本' : '歷史版本']].map(([label,value]) => `<div class="detail-field"><small>${label}</small><strong>${escapeHtml(value || '—')}</strong></div>`).join('')}</div><h3>版本關係</h3><div class="topic-list">${(detail.versions || []).map((version) => `<span class="topic">${escapeHtml(version.version_label || version.wfa_revision || version.revision_id)}${version.analysis_eligible ? ' · 目前' : ''}</span>`).join('') || '<span class="empty">無其他版本</span>'}</div><h3>來源段落</h3>${(chunks.chunks || []).map((chunk) => `<article class="chunk"><small>#${chunk.chunk_index} · ${escapeHtml(chunk.location_label || '')}</small><p>${escapeHtml(chunk.content)}</p></article>`).join('') || '<div class="empty">無可顯示段落</div>'}`;
    } catch (error) { $('#document-dialog-body').innerHTML = `<div class="error-card">${escapeHtml(error.message)}</div>`; }
  }

  function agentOutput(value) {
    const answer = value.answer || value.result || value.message || '未回傳回答';
    const citations = value.citations || value.sources || [];
    const trace = value.steps || value.tool_steps || value.trace || [];
    return `<div class="message assistant">${escapeHtml(answer)}</div><ul class="citation-list">${citations.map((item,index) => `<li><strong>[${index+1}]</strong> ${escapeHtml(item.title || item.document_title || item.revision_id || item)}</li>`).join('')}</ul><details><summary>Agent 工具步驟與停止原因</summary><ul class="trace-list">${trace.map((item) => `<li>${escapeHtml(typeof item === 'string' ? item : item.tool || item.name || JSON.stringify(item))}</li>`).join('') || '<li>無工具步驟</li>'}</ul><p class="results-meta">${escapeHtml(value.stop_reason || value.status || '')}</p></details>`;
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
      state.conversation.push({role:'user',content:question},{role:'assistant',content:result.answer || result.result || ''});
    } catch (error) { $('#agent-wait').outerHTML = `<div class="message error">${escapeHtml(error.message)}</div>`; }
    finally { button.disabled = false; }
  }
  async function renderAgent() {
    content.innerHTML = `<div class="ai-layout">${panel('AI research assistant', `<div id="conversation" class="conversation"><div class="message assistant">我會使用 WiFi 專區的文件與版本關係回答，並保留引用與工具步驟。</div></div><label>問題<textarea id="agent-question" maxlength="2000" placeholder="例如：ELR 的規格重點是什麼？"></textarea></label><div class="ai-actions"><small class="results-meta">回答以目前匯入資料為準</small><button id="agent-submit" class="primary-button" type="button">送出問題</button></div>`)}${panel('可追溯輸出', '<p>每次回答會同時顯示：</p><ul><li>引用文件</li><li>Agent 工具步驟</li><li>停止原因與錯誤狀態</li></ul>', 'EXISTING KM PIPELINE')}</div>`;
    $('#agent-submit').addEventListener('click', askAgent);
  }

  function jobRow(job) {
    const total = Number(job.total || job.total_chunks || job.progress?.total || 0); const done = Number(job.completed || job.ready || job.progress?.completed || 0); const value = total ? Math.round(done / total * 100) : (/complete|success/.test(job.status || '') ? 100 : 0);
    return `<li class="job-item"><div class="job-head"><strong>${escapeHtml(job.job_id || '匯入工作')}</strong><span class="status-badge ${statusClass(job.status)}">${escapeHtml(job.status || '未知')}</span></div><div class="job-meta">${escapeHtml(job.stage || '')} ${done || total ? `· ${number(done)} / ${number(total)}` : ''} · ${formatTime(job.updated_at || job.created_at)}</div>${job.error ? `<p class="error-card">${escapeHtml(job.error)}</p>` : ''}<progress max="100" value="${value}"></progress></li>`;
  }
  async function renderJobs() {
    const data = await api('/api/wifi8/jobs');
    let upload = '';
    try { const status = await api('/api/wifi8/status'); if (status.upload_enabled) upload = `<div class="upload-box"><form id="upload-form" class="upload-row"><label>Wi-Fi8 匯出包 (.zip)<input name="file" type="file" accept=".zip" required></label><button class="primary-button" type="submit">上傳並匯入</button></form><p id="upload-status" class="results-meta">匯入完成前不會切換目前版本。</p></div>`; } catch (_) { /* jobs remain readable */ }
    content.innerHTML = panel('匯入工作', `${upload}<ul class="job-list">${(data.jobs || []).map(jobRow).join('') || '<li class="empty">尚無匯入工作</li>'}</ul>`, `${(data.jobs || []).length} 筆近期工作`);
    $('#upload-form')?.addEventListener('submit', async (event) => { event.preventDefault(); const message = $('#upload-status'); message.textContent = '正在上傳…'; try { const result = await api('/api/wifi8/packages', { method:'POST', headers:{'x-km-wifi8-import':'1'}, body:new FormData(event.target) }); message.textContent = `已送出 ${result.job_id}`; setTimeout(() => renderRoute(), 1000); } catch (error) { message.textContent = error.message; } });
  }

  function renderPlaceholder(route) {
    const [title, description] = routeInfo[route];
    content.innerHTML = `<section class="placeholder-card"><div><span class="placeholder-icon">⌘</span><h2>${title}</h2><p>${description}</p><p>這個頁面已保留完整導覽與版型，功能尚未從參考站移植。</p><span class="mode-badge">功能待移植</span></div></section>`;
  }
  async function renderRoute() {
    const candidate = (location.hash.replace(/^#\//, '').split('/')[0] || 'overview');
    state.route = routeInfo[candidate] ? candidate : 'overview'; renderNav(); setHeader(state.route); content.innerHTML = '<div class="loading-card">正在載入…</div>'; $('#app').setAttribute('aria-busy','true');
    try {
      if (state.route === 'overview') await renderOverview(); else if (state.route === 'documents') await renderDocuments(); else if (state.route === 'ai') await renderAgent(); else if (state.route === 'jobs') await renderJobs(); else renderPlaceholder(state.route);
    } catch (error) { fail(error); }
    finally { $('#app').setAttribute('aria-busy','false'); content.focus({preventScroll:true}); $('#primary-nav').classList.remove('open'); $('#nav-toggle').setAttribute('aria-expanded','false'); }
  }

  $('#nav-toggle').addEventListener('click', () => { const open = $('#primary-nav').classList.toggle('open'); $('#nav-toggle').setAttribute('aria-expanded', String(open)); });
  $('#refresh-page').addEventListener('click', async (event) => { event.currentTarget.classList.add('is-loading'); event.currentTarget.disabled = true; await renderRoute(); event.currentTarget.classList.remove('is-loading'); event.currentTarget.disabled = false; });
  $('#close-dialog').addEventListener('click', () => $('#document-dialog').close());
  window.addEventListener('hashchange', renderRoute);
  if (!location.hash) location.replace('#/overview'); else renderRoute();
})();
