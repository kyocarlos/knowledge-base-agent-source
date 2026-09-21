<template>
  <section class="report-page">
    <header class="page-header">
      <div><h1>測試報告數據</h1><p>查看已發布 TestRun 的摘要、時間曲線、版本與來源。</p></div>
      <button class="secondary" @click="loadRuns" :disabled="loading">重新整理</button>
    </header>

    <div class="scope-card">
      <label>Project scope <input v-model="project" placeholder="例如 KM-CI" @keyup.enter="loadRuns" /></label>
      <label>Role
        <select v-model="role"><option value="report-reader">report-reader</option><option value="report-admin">report-admin</option></select>
      </label>
      <label>Reviewer token <input v-model="token" type="password" placeholder="Bearer token" autocomplete="off" /></label>
      <button @click="loadRuns">載入報告</button>
    </div>
    <p v-if="error" class="message error">{{ error }}</p>

    <div class="layout">
      <aside class="runs-card">
        <h2>已發布報告</h2>
        <button v-for="run in runs" :key="`${run.run_id}:${run.document_version}`"
                class="run-item" :class="{ selected: selected?.run_id === run.run_id && selected?.document_version === run.document_version }"
                @click="selectRun(run)">
          <strong>{{ run.run_id }}</strong><span>{{ run.project_code }} · {{ run.document_version }}</span>
          <small>{{ run.dut_model }} · {{ run.overall_verdict }}</small>
        </button>
        <p v-if="!loading && !runs.length" class="empty">沒有可查看的已發布報告</p>
      </aside>

      <main v-if="selected" class="detail-card">
        <div class="detail-header"><div><h2>{{ selected.run_id }}</h2><p>{{ selected.project_code }} · {{ selected.document_version }}</p></div><span class="published">published / current</span></div>
        <dl class="provenance"><div><dt>來源檔案</dt><dd>{{ selected.source_file_name }}</dd></div><div><dt>SHA-256</dt><dd>{{ selected.source_file_sha256 }}</dd></div><div><dt>時間</dt><dd>{{ selected.started_at }} → {{ selected.finished_at }}</dd></div></dl>

        <h3>摘要</h3>
        <table><thead><tr><th>Case</th><th>Metric</th><th>Unit</th><th>Min</th><th>Avg</th><th>Max</th><th>Samples</th></tr></thead>
          <tbody><tr v-for="item in summary" :key="`${item.case_id}:${item.metric_name}:${item.unit}`"><td>{{ item.case_id }}</td><td>{{ item.metric_name }}</td><td>{{ item.unit }}</td><td>{{ item.min_value }}</td><td>{{ item.avg_value }}</td><td>{{ item.max_value }}</td><td>{{ item.sample_count }}</td></tr></tbody>
        </table>
        <h3>時間曲線</h3>
        <label class="metric-select">Metric <select v-model="metric" @change="loadSamples"><option v-for="name in metricNames" :key="name" :value="name">{{ name }}</option></select></label>
        <svg class="chart" viewBox="0 0 800 220" role="img" aria-label="metric time series chart"><polyline v-if="polyline" :points="polyline" fill="none" stroke="#1f8db8" stroke-width="3" /><line x1="40" y1="190" x2="780" y2="190" stroke="#b9c8d8" /><text x="42" y="210">{{ samples[0]?.observed_at || '' }}</text><text x="600" y="210">{{ samples[samples.length - 1]?.observed_at || '' }}</text></svg>
        <p class="chart-meta">{{ samples.length }} samples · 單位 {{ samples[0]?.unit || '-' }} · 查詢結果來自 TimescaleDB</p>
      </main>
    </div>
  </section>
</template>

<script setup>
import { computed, ref } from 'vue'

const project = ref('')
const role = ref('report-reader')
const token = ref('')
const runs = ref([]); const selected = ref(null); const summary = ref([]); const samples = ref([]); const metric = ref(''); const loading = ref(false); const error = ref('')
const headers = () => ({ 'X-KM-Project': project.value.trim(), 'X-KM-Role': role.value, ...(token.value ? { Authorization: `Bearer ${token.value}` } : {}) })
const metricNames = computed(() => [...new Set(summary.value.map(item => item.metric_name))])
const polyline = computed(() => {
  if (!samples.value.length) return ''
  const values = samples.value.map(item => Number(item.value)); const min = Math.min(...values); const max = Math.max(...values); const range = max - min || 1
  return values.map((value, index) => `${40 + (740 * index / Math.max(1, values.length - 1))},${190 - (150 * (value - min) / range)}`).join(' ')
})
async function body(response) { try { const value = await response.json(); return value.detail || JSON.stringify(value) } catch { return `HTTP ${response.status}` } }
async function loadRuns() {
  if (!project.value.trim()) { error.value = '請輸入 Project scope'; return }
  loading.value = true; error.value = ''
  try { const response = await fetch('/api/v1/reports/timeseries/runs?limit=50', { headers: headers(), cache: 'no-store' }); if (!response.ok) throw new Error(await body(response)); runs.value = (await response.json()).items || []; if (runs.value.length) await selectRun(runs.value[0]); else { selected.value = null; summary.value = []; samples.value = [] } } catch (cause) { error.value = cause.message || String(cause) } finally { loading.value = false }
}
async function selectRun(run) { selected.value = run; error.value = ''; const query = `version=${encodeURIComponent(run.document_version)}`; try { const response = await fetch(`/api/v1/reports/${encodeURIComponent(run.run_id)}/timeseries/summary?${query}`, { headers: headers(), cache: 'no-store' }); if (!response.ok) throw new Error(await body(response)); summary.value = (await response.json()).items || []; metric.value = metricNames.value[0] || ''; await loadSamples() } catch (cause) { error.value = cause.message || String(cause) } }
async function loadSamples() { if (!selected.value || !metric.value) { samples.value = []; return }; const query = new URLSearchParams({ version: selected.value.document_version, metric: metric.value, limit: '5000' }); try { const response = await fetch(`/api/v1/reports/${encodeURIComponent(selected.value.run_id)}/timeseries/samples?${query}`, { headers: headers(), cache: 'no-store' }); if (!response.ok) throw new Error(await body(response)); samples.value = (await response.json()).items || [] } catch (cause) { error.value = cause.message || String(cause) } }
</script>

<style scoped>
.report-page{max-width:1500px;margin:0 auto;padding:32px}.page-header,.scope-card,.detail-header{display:flex;align-items:center;justify-content:space-between;gap:18px}.page-header{margin-bottom:22px}.page-header h1{font-size:28px}.page-header p,.detail-header p{color:var(--text-secondary)}.scope-card,.runs-card,.detail-card{background:#fff;border:1px solid var(--border);border-radius:var(--radius-lg);box-shadow:var(--shadow);padding:18px}.scope-card{justify-content:flex-start;margin-bottom:18px}.scope-card label,.metric-select{display:flex;align-items:center;gap:8px}.scope-card input,.scope-card select,.metric-select select{padding:9px;border:1px solid var(--border-strong);border-radius:8px}.scope-card button,.page-header button{border:0;border-radius:8px;padding:9px 14px;background:var(--primary-light);color:#fff;cursor:pointer}.secondary{background:#e7eef6!important;color:var(--primary)!important}.message{padding:12px;border-radius:8px;margin:12px 0}.error{background:#feecec;color:var(--error)}.layout{display:grid;grid-template-columns:300px 1fr;gap:18px}.runs-card h2,.detail-card h2{margin-bottom:14px}.run-item{display:block;width:100%;text-align:left;background:#f7fafc;border:1px solid var(--border);border-radius:8px;padding:12px;margin:8px 0;cursor:pointer;color:var(--text-primary)}.run-item span,.run-item small{display:block;color:var(--text-secondary);margin-top:3px}.run-item.selected{border-color:var(--accent);background:#e9f7fb}.empty{color:var(--text-muted);padding:20px 0}.published{color:var(--success);font-weight:700}.provenance{display:grid;grid-template-columns:repeat(3,1fr);gap:12px;background:var(--bg-surface);padding:14px;border-radius:8px;margin:18px 0}.provenance dt{font-size:12px;color:var(--text-muted)}.provenance dd{overflow-wrap:anywhere;font-size:13px}.detail-card h3{margin:22px 0 10px}table{width:100%;border-collapse:collapse}th,td{padding:10px;border-bottom:1px solid var(--border);text-align:left}.chart{width:100%;height:230px;background:#f8fbfe;border:1px solid var(--border);border-radius:8px;margin-top:12px}.chart-meta{color:var(--text-secondary);font-size:13px}@media(max-width:900px){.layout{grid-template-columns:1fr}.provenance{grid-template-columns:1fr}.scope-card,.page-header{align-items:stretch;flex-direction:column}}
</style>
