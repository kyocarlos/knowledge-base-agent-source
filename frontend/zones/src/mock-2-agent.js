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
