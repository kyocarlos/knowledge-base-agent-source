(() => {
'use strict';
// Demo back end for the other knowledge zones (part 1 of 2; scripts/build_zone_demo.js joins the parts into one script).
// The zone pages are built from the WiFi zone page and call the same /api/wifi8/* paths; the code here answers those calls in the browser from the
// sample data in zones-data.js, so no server, model or real document is involved.
const ZONES = window.KM_ZONES || {};
const zoneId = document.documentElement.dataset.zone;
const Z = window.KM_ZONE_CONFIG = Object.assign({ id: zoneId }, ZONES[zoneId]);
if (!ZONES[zoneId]) throw new Error(`unknown zone ${zoneId}`);

const DAY = 86400000;
const ago = (days, hour = 9) => { const d = new Date(Date.now() - days * DAY); d.setHours(hour, 0, 0, 0); return d.toISOString(); };
const lastMonday = () => { const d = new Date(); d.setHours(8, 0, 0, 0); d.setDate(d.getDate() - ((d.getDay() + 6) % 7)); if (d > new Date()) d.setDate(d.getDate() - 7); return d; };
const isoWeek = (d) => { const t = new Date(Date.UTC(d.getFullYear(), d.getMonth(), d.getDate())); const day = t.getUTCDay() || 7; t.setUTCDate(t.getUTCDate() + 4 - day); const y = new Date(Date.UTC(t.getUTCFullYear(), 0, 1)); return `${t.getUTCFullYear()}-W${String(Math.ceil(((t - y) / DAY + 1) / 7)).padStart(2, '0')}`; };

// Every family is one document with its versions; the first version is the current one.
const docs = []; const families = [];
Z.families.forEach((f, familyIndex) => {
  const [code, title, cat, role, publisher, versions, summary, points, table] = f;
  const family = { code, title, cat, role, publisher, summary, points, table, versions: [] };
  versions.split('|').forEach((v, i) => {
    const [label, date] = v.split('@');
    const doc = { revision_id: `${code}-${label}`, wfa_document_id: code, title, publisher, document_role: role, document_date: date, version_label: label, analysis_eligible: i === 0, cat, family: familyIndex };
    doc.chunks = [
      { chunk_index: 1, location_label: '第 1 頁・摘要', content: summary },
      { chunk_index: 2, location_label: '第 2 頁・重點', content: points.join('；') + '。' },
      ...(table ? [{ chunk_index: 3, location_label: '第 3 頁・表 1', content: table.replace(/[|\-:\n]+/g, ' ').trim(), display_text: table }] : []),
    ];
    family.versions.push(doc); docs.push(doc);
  });
  families.push(family);
});
const current = docs.filter((d) => d.analysis_eligible);
const chunkTotal = docs.reduce((n, d) => n + d.chunks.length, 0);

// Text matching: Chinese by character pairs, other text by words.
const grams = (text) => { const s = String(text || '').toLowerCase(); const out = new Set(s.match(/[a-z0-9][a-z0-9.\-_/]+/g) || []); const han = s.replace(/[^一-鿿]/g, ''); for (let i = 0; i < han.length - 1; i += 1) out.add(han.slice(i, i + 2)); return out; };
const score = (queryGrams, text) => { const g = grams(text); let n = 0; queryGrams.forEach((q) => { if (g.has(q)) n += q.length > 2 ? 2 : 1; }); return n; };
const rank = (query, pool) => { const q = grams(query); return pool.map((d) => ({ d, s: score(q, `${d.title} ${d.wfa_document_id} ${d.chunks.map((c) => c.content).join(' ')}`) + score(q, d.title) })).filter((x) => x.s > 0).sort((a, b) => b.s - a.s); };
const cite = (d, chunk, ref) => ({ ref, source: d.title, revision_id: d.revision_id, location_label: chunk.location_label, publisher: d.publisher, wfa_document_id: d.wfa_document_id, analysis_eligible: d.analysis_eligible });
const docView = (d) => ({ revision_id: d.revision_id, wfa_document_id: d.wfa_document_id, title: d.title, publisher: d.publisher, document_role: d.document_role, document_date: d.document_date, version_label: d.version_label, analysis_eligible: d.analysis_eligible });
const tally = (list, key) => { const m = new Map(); list.forEach((x) => m.set(x[key], (m.get(x[key]) || 0) + 1)); return [...m].sort((a, b) => b[1] - a[1]); };

function overview() {
  const total = docs.length;
  const rows = Z.cats.map(([label, description]) => { const all = docs.filter((d) => d.cat === label); const cur = all.filter((d) => d.analysis_eligible).length; return { label, description, total: all.length, current: cur, history: all.length - cur, share: total ? all.length / total * 100 : 0 }; }).filter((r) => r.total);
  return {
    counts: { documents: total, current_documents: current.length, superseded_documents: total - current.length, chunks: chunkTotal, chunks_ready: chunkTotal, chunks_pending: 0, excluded: {} },
    current: { package_id: Z.package }, active_job: null, qna_documents: current.length,
    attention: (Z.attention || []).map(([level, title, detail]) => ({ level, title, detail })),
    by_category: { total, rows }, by_publisher: tally(current, 'publisher'), by_document_role: tally(current, 'document_role'), top_topics: Z.topics,
    processing: { text_status: [['indexed', total]], failed_jobs: 0, latest_failure: null,
      metadata_coverage: [['發布者', total], ['文件角色', total], ['文件日期', total - 1], ['版本標示', Math.max(1, Math.round(total * 0.92))], ['文件編號', total]].map(([label, present]) => ({ label, total, present })) },
  };
}
function listDocuments(params) {
  const q = (params.get('query') || '').trim(); const publisher = params.get('publisher'); const role = params.get('document_role');
  const history = params.get('include_history') === 'on' || params.get('include_history') === 'true';
  let pool = history ? docs : current;
  const facets = { publishers: tally(pool, 'publisher'), document_roles: tally(pool, 'document_role') };
  if (publisher) pool = pool.filter((d) => d.publisher === publisher);
  if (role) pool = pool.filter((d) => d.document_role === role);
  if (q) pool = rank(q, pool).map((h) => h.d);
  else pool = pool.slice().sort((a, b) => String(b.document_date).localeCompare(String(a.document_date)));
  const size = Number(params.get('page_size')) || 20; const page = Number(params.get('page')) || 1;
  return { total: pool.length, page, page_size: size, documents: pool.slice((page - 1) * size, page * size).map(docView), facets };
}
const findDoc = (revision) => docs.find((d) => d.revision_id === revision);
function search(body) {
  const pool = body.include_history ? docs : current; const q = grams(body.query);
  const results = [];
  pool.forEach((d) => d.chunks.forEach((c) => { const s = score(q, c.content) + score(q, d.title) * 0.5; if (s > 0) results.push({ s, d, c }); }));
  results.sort((a, b) => b.s - a.s);
  const top = results.slice(0, body.top_k || 10); const best = top[0] ? top[0].s : 1;
  return { policy: 'BM25 + vector RRF', results: top.map(({ s, d, c }) => ({ ...docView(d), source: d.title, content: c.content, ...(c.display_text ? { display_text: c.display_text } : {}), location_label: c.location_label, chunk_index: c.chunk_index, matched_by: s > best * 0.7 ? ['fulltext', 'vector'] : ['vector'], score: 0.0164 * (s / best) + 0.0009 })) };
}

function feed() {
  const D = Z.digest || {}; const monday = lastMonday();
  const items = (D.items || []).map(([source, days, title, summary, older]) => ({ source_name: source, published: ago(days), title, summary, ...(older ? { older: true } : {}) }));
  const events = (Z.updates || []).map(([type, days, fam]) => { const f = families[fam]; const d = f.versions[0]; return { type, at: ago(days), title: f.title, publisher: f.publisher, document_role: f.role, version_label: d.version_label, revision_id: d.revision_id }; });
  const recent = current.slice().sort((a, b) => String(b.document_date).localeCompare(String(a.document_date))).slice(0, 8).map(docView);
  return {
    digest: { week: isoWeek(monday), generated_at: monday.toISOString(), highlights: D.highlights || [], timeline: D.timeline || null, items,
      sources: (D.sources || []).map((name) => ({ name, status: 'ok' })), note: D.note || '週報內容為示範資料，來源與摘要皆為模擬。' },
    updates: { events, recent },
  };
}

// Demo back end, part 2 of 2: the assistant (answers composed from the zone's sample documents), attached files, routing and the fetch hook.
const tasks = new Map(); const userFiles = []; let fileSeq = 0;
const qaMatch = (question) => { const q = grams(question); let best = null; (Z.qa || []).forEach((item) => { const s = score(q, item.q) / Math.max(4, grams(item.q).size); if (!best || s > best.s) best = { s, item }; }); return best && best.s >= 0.45 ? best.item : null; };

function compose(question, fileIds) {
  const files = userFiles.filter((f) => fileIds.includes(f.file_id));
  const wantsHistory = /歷史|舊版|前一版/.test(question);
  const curated = qaMatch(question);
  const cites = [];
  const refOf = (d, chunk) => { const found = cites.find((c) => c.revision_id === d.revision_id && c.location_label === chunk.location_label); if (found) return found.ref; const ref = `S${cites.length + 1}`; cites.push(cite(d, chunk, ref)); return ref; };
  let answer; let hitDocs = [];
  if (curated) {
    answer = curated.a.replace(/\{(\d+)(?::(\d))?\}/g, (m, fam, chunkNo) => { const d = families[Number(fam)].versions[0]; return `[${refOf(d, d.chunks[Number(chunkNo || 0)] || d.chunks[0])}]`; });
    hitDocs = (curated.a.match(/\{(\d+)/g) || []).map((m) => families[Number(m.slice(1))].versions[0]);
  } else {
    const seen = new Set();
    const hits = rank(question, wantsHistory ? docs : current).filter((h) => !seen.has(h.d.family) && seen.add(h.d.family)).slice(0, 3);
    hitDocs = hits.map((h) => h.d);
    if (!hits.length || hits[0].s < 3) {
      answer = `${Z.label}目前匯入的文件裡，找不到足以回答「${question.slice(0, 40)}」的依據，所以我不推測答案。\n\n可以試試：\n${(Z.qa || []).slice(0, 3).map((x) => `- ${x.q}`).join('\n')}`;
    } else {
      answer = `根據${Z.label}的文件，與你的問題最相關的內容如下：\n\n${hits.map(({ d }) => { const c = d.chunks[0]; return `- **${d.title}**（${d.version_label}${d.analysis_eligible ? '' : '，歷史版本'}）：${c.content} [${refOf(d, c)}]`; }).join('\n')}\n\n重點整理：\n${hits.slice(0, 2).map(({ d }) => `- ${families[d.family].points[0]} [${refOf(d, d.chunks[1])}]`).join('\n')}`;
    }
  }
  if (files.length) {
    const f = files[0]; const ref = `S${cites.length + 1}`;
    cites.push({ ref, source: f.name, revision_id: f.file_id, location_label: '上傳檔案', publisher: '使用者上傳', analysis_eligible: true });
    const peek = f.text ? f.text.replace(/\s+/g, ' ').slice(0, 90) : '';
    if (/比較|差異|對照|不同|一致/.test(question) && hitDocs[0]) {
      const d = hitDocs[0];
      answer += `\n\n**與你上傳的「${f.name}」比較**\n\n| 項目 | 你的檔案 | ${Z.label}文件 |\n| --- | --- | --- |\n| 內容來源 | ${f.name} [${ref}] | ${d.title}（${d.version_label}） |\n| 主題 | ${peek ? `${peek}…` : '已讀取檔案內容'} | ${d.chunks[0].content.slice(0, 40)}… |\n| 判讀 | 請對照上列內容 | 以專區文件為準 |`;
    } else {
      answer += `\n\n另外，依你上傳的「${f.name}」${peek ? `（開頭：${peek}…）` : ''}補充如上，該檔案只用於這次對話，不屬於專區文件。 [${ref}]`;
    }
  }
  const claims = Math.max(2, (answer.match(/\[S\d+/g) || []).length + 1);
  const sourceDocs = cites.filter((c) => c.publisher !== '使用者上傳');
  return {
    status: 'completed', question, answer_main: answer, citations: cites, stop_reason: 'end_turn（完成）',
    trace: [{ tool: 'search_documents' }, { tool: 'read_chunks' }, ...(files.length ? [{ tool: 'search_user_files' }] : []), { tool: 'check_grounding' }],
    grounding: { summary: { claims, claims_cited: claims, claims_tool_data: 0, values: sourceDocs.length ? 2 : 0, values_verified: sourceDocs.length ? 2 : 0, values_not_found: 0, similarity_enabled: false, sources: { wfa: sourceDocs.length, current: sourceDocs.filter((c) => c.analysis_eligible).length, total: sourceDocs.length } }, flagged: [] },
    extension: { related: hitDocs.length ? `相關文件：${[...new Set(hitDocs.map((d) => d.title))].slice(0, 3).join('、')}` : '', followups: (Z.qa || []).filter((x) => x.q !== (curated && curated.q)).slice(0, 3).map((x) => x.q) },
  };
}
function submit(body) {
  const taskId = (self.crypto && crypto.randomUUID) ? crypto.randomUUID() : `${Date.now()}-${Math.random().toString(16).slice(2)}`;
  const result = compose(String(body.question || ''), body.file_ids || []);
  const events = [{ t: 500, type: 'tool', label: '搜尋專區文件' }, { t: 1300, type: 'tool', label: '讀取引用段落' }];
  if ((body.file_ids || []).length) events.push({ t: 1700, type: 'tool', label: '讀取你上傳的檔案' });
  events.push({ t: 2100, type: 'tool', label: '檢查回答依據' });
  const text = result.answer_main; let at = 2500;
  for (let i = 0; i < text.length; i += 14) { events.push({ t: at, type: 'delta', text: text.slice(i, i + 14) }); at += 45; }
  tasks.set(taskId, { start: Date.now(), events, end: at + 300, result: { task_id: taskId, ...result, elapsed_ms: at + 300 } });
  return { task_id: taskId, status: 'submitted', stream: true, feedback: true };
}
function taskEvents(taskId, after) {
  const task = tasks.get(taskId); if (!task) return null;
  const elapsed = Date.now() - task.start; let end = after;
  while (end < task.events.length && task.events[end].t <= elapsed) end += 1;
  return { events: task.events.slice(after, end).map(({ t, ...e }) => e), next: end, done: end >= task.events.length && elapsed >= task.end };
}
function taskResult(taskId) {
  const task = tasks.get(taskId); if (!task) return null;
  return Date.now() - task.start >= task.end ? task.result : { task_id: taskId, status: 'pending' };
}

// Files attached to a conversation: kept in the page only.
const fileConfig = { enabled: true, ttl_seconds: 7200, max_bytes: 10485760, max_files: 3, extensions: ['.pdf', '.docx', '.xlsx', '.txt', '.md', '.csv', '.png', '.jpg', '.jpeg'] };
async function addFile(body) {
  const file = body && body.get ? body.get('file') : null; if (!file) return [422, { detail: '沒有收到檔案' }];
  if (userFiles.length >= fileConfig.max_files) return [409, { detail: '已達同時附加檔案數量上限' }];
  let text = ''; if (/\.(txt|md|csv)$/i.test(file.name)) { try { text = await file.text(); } catch (_) { text = ''; } }
  fileSeq += 1;
  const record = { file_id: `f${fileSeq}${Math.random().toString(16).slice(2, 10)}`, name: file.name, size: file.size, chunks: Math.max(1, Math.ceil((text.length || file.size / 3) / 800)), text };
  userFiles.push(record); return [200, { file_id: record.file_id, name: record.name, size: record.size, chunks: record.chunks }];
}
const FEEDBACK_REASONS = [{ key: 'wrong_fact', label: '內容有誤' }, { key: 'missing_info', label: '遺漏重點' }, { key: 'bad_citation', label: '引用不對或找不到依據' }, { key: 'unclear', label: '說明不清楚' }, { key: 'too_slow', label: '等太久' }, { key: 'other', label: '其他' }];

async function route(method, url, init) {
  const path = url.pathname.replace('/api/wifi8', ''); const p = url.searchParams;
  const json = () => { try { return JSON.parse(init.body || '{}'); } catch (_) { return {}; } };
  if (path === '/overview') return [200, overview()];
  if (path === '/documents') return [200, listDocuments(p)];
  let m;
  if ((m = path.match(/^\/documents\/([^/]+)\/chunks$/))) {
    const d = findDoc(decodeURIComponent(m[1])); if (!d) return [404, { detail: 'document not found' }];
    if (p.get('figures') === 'true') return [200, { chunks: [], total: 0 }];
    return [200, { chunks: d.chunks.slice(0, Number(p.get('count')) || 8), total: d.chunks.length }];
  }
  if ((m = path.match(/^\/documents\/([^/]+)$/))) {
    const d = findDoc(decodeURIComponent(m[1])); if (!d) return [404, { detail: 'document not found' }];
    return [200, { document: docView(d), versions: families[d.family].versions.map(docView) }];
  }
  if (path === '/search' && method === 'POST') return [200, search(json())];
  if (path === '/feed') return [200, feed()];
  if (path === '/agent' && method === 'POST') return [202, submit(json())];
  if ((m = path.match(/^\/agent\/([^/]+)\/events$/))) { const e = taskEvents(m[1], Number(p.get('after')) || 0); return e ? [200, e] : [404, { detail: 'task not found' }]; }
  if ((m = path.match(/^\/agent\/([^/]+)\/feedback$/))) return [200, { task_id: m[1], rating: json().rating }];
  if ((m = path.match(/^\/agent\/([^/]+)$/))) { const r = taskResult(m[1]); return r ? [200, r] : [404, { detail: 'task not found' }]; }
  if (path === '/agent-feedback/options') return [200, { reasons: FEEDBACK_REASONS }];
  if (path === '/files/config') return [200, fileConfig];
  if (path === '/files' && method === 'POST') return addFile(init.body);
  if (path === '/files') return [200, { files: userFiles.map(({ text, ...f }) => f) }];
  if ((m = path.match(/^\/files\/([^/]+)$/)) && method === 'DELETE') { const i = userFiles.findIndex((f) => f.file_id === decodeURIComponent(m[1])); if (i >= 0) userFiles.splice(i, 1); return [200, { deleted: true }]; }
  return [404, { detail: 'not found' }];
}

const realFetch = window.fetch.bind(window);
window.fetch = async (input, init = {}) => {
  const raw = typeof input === 'string' ? input : input.url; const url = new URL(raw, location.origin);
  if (!url.pathname.startsWith('/api/wifi8/')) return realFetch(input, init);
  await new Promise((resolve) => setTimeout(resolve, 120 + Math.random() * 180));
  const [status, payload] = await route((init.method || 'GET').toUpperCase(), url, init);
  return new Response(JSON.stringify(payload), { status, headers: { 'Content-Type': 'application/json' } });
};
})();
