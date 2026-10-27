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
