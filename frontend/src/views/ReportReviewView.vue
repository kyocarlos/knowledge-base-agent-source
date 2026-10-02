<template>
  <section class="review-page">
    <header class="review-header">
      <div><h1>測試報告待審台</h1><p>Anritsu／Amarisoft 報告核准後才會進入正式知識庫。</p></div>
      <button class="secondary" @click="loadReports" :disabled="loading">重新整理</button>
    </header>

    <div class="auth-card">
      <label>Reviewer Token</label>
      <input v-model="token" type="password" autocomplete="off" placeholder="只保存在目前瀏覽器 session" />
      <select v-model="statusFilter" @change="loadReports">
        <option value="pending_review">待審</option><option value="">全部</option>
        <option value="completed">已完成</option><option value="rejected">已退回</option>
        <option value="ingest_failed">攝入失敗</option>
      </select>
      <button @click="saveAndLoad">連線</button>
    </div>

    <p v-if="error" class="message error">{{ error }}</p>
    <p v-if="message" class="message success">{{ message }}</p>

    <div class="table-card">
      <table>
        <thead><tr><th>環境／Run</th><th>專案／DUT</th><th>判定</th><th>狀態</th><th>送出時間</th><th>操作</th></tr></thead>
        <tbody>
          <tr v-for="item in reports" :key="item.submission_id">
            <td><strong>{{ labelEnvironment(item.environment) }}</strong><small>{{ item.run_id }}</small></td>
            <td>{{ item.manifest?.project_code || '-' }}<small>{{ item.manifest?.dut_model || '-' }}</small></td>
            <td><span class="verdict" :class="item.manifest?.overall_verdict">{{ item.manifest?.overall_verdict || '-' }}</span></td>
            <td>{{ statusLabel(item.status) }}</td><td>{{ formatTime(item.created_at) }}</td>
            <td class="actions">
              <button class="secondary" @click="download(item)">下載</button>
              <template v-if="item.status === 'pending_review'">
                <button @click="approve(item)">核准</button><button class="danger" @click="reject(item)">退回</button>
              </template>
            </td>
          </tr>
          <tr v-if="!loading && reports.length === 0"><td colspan="6" class="empty">目前沒有符合條件的報告</td></tr>
        </tbody>
      </table>
    </div>
  </section>
</template>

<script setup>
import { onMounted, ref } from 'vue'

const token = ref(sessionStorage.getItem('kb_report_reviewer_token') || '')
const statusFilter = ref('pending_review')
const reports = ref([])
const loading = ref(false)
const error = ref('')
const message = ref('')

const headers = () => ({ Authorization: `Bearer ${token.value}`, 'Content-Type': 'application/json' })
const detailText = async (response) => { try { const body = await response.json(); return body.detail || JSON.stringify(body) } catch { return `HTTP ${response.status}` } }

async function loadReports() {
  if (!token.value) return
  loading.value = true; error.value = ''; message.value = ''
  try {
    const query = statusFilter.value ? `?status=${encodeURIComponent(statusFilter.value)}` : ''
    const response = await fetch(`/api/admin/v1/report-submissions${query}`, { headers: headers(), cache: 'no-store' })
    if (!response.ok) throw new Error(await detailText(response))
    reports.value = (await response.json()).items || []
  } catch (cause) { error.value = String(cause.message || cause) } finally { loading.value = false }
}

function saveAndLoad() { sessionStorage.setItem('kb_report_reviewer_token', token.value); loadReports() }

async function decide(item, action, comment) {
  error.value = ''; message.value = ''
  const response = await fetch(`/api/admin/v1/report-submissions/${encodeURIComponent(item.submission_id)}/${action}`, {
    method: 'POST', headers: headers(), body: JSON.stringify({ comment })
  })
  if (!response.ok) throw new Error(await detailText(response))
  message.value = action === 'approve' ? `已核准 ${item.run_id}，報告已進入攝入佇列` : `已退回 ${item.run_id}`
  await loadReports()
}

async function approve(item) { if (!confirm(`確定核准 ${item.run_id}？`)) return; try { await decide(item, 'approve', '') } catch (cause) { error.value = cause.message } }
async function reject(item) { const reason = prompt(`請輸入退回 ${item.run_id} 的原因`); if (!reason?.trim()) return; try { await decide(item, 'reject', reason.trim()) } catch (cause) { error.value = cause.message } }
async function download(item) {
  try {
    const response = await fetch(`/api/admin/v1/report-submissions/${encodeURIComponent(item.submission_id)}/download`, { headers: { Authorization: `Bearer ${token.value}` } })
    if (!response.ok) throw new Error(await detailText(response))
    const url = URL.createObjectURL(await response.blob()); const link = document.createElement('a')
    link.href = url; link.download = item.report_name; link.click(); URL.revokeObjectURL(url)
  } catch (cause) { error.value = cause.message }
}

const labelEnvironment = value => value === 'amarisoft' ? 'Amarisoft' : value === 'anritsu' ? 'Anritsu' : value
const statusLabel = value => ({ pending_review: '待審', queued: '排隊中', completed: '已完成', rejected: '已退回', ingest_failed: '攝入失敗' }[value] || value)
const formatTime = value => value ? new Date(value).toLocaleString('zh-TW') : '-'
onMounted(loadReports)
</script>

<style scoped>
.review-page{max-width:1400px;margin:0 auto;padding:32px}.review-header,.auth-card{display:flex;align-items:center;justify-content:space-between;gap:16px}.review-header{margin-bottom:24px}.review-header h1{font-size:28px}.review-header p{color:var(--text-secondary)}.auth-card,.table-card{background:#fff;border:1px solid var(--border);border-radius:var(--radius-lg);box-shadow:var(--shadow);padding:18px;margin-bottom:18px}.auth-card input{flex:1;max-width:520px}.auth-card input,.auth-card select{border:1px solid var(--border-strong);border-radius:8px;padding:10px 12px}button{border:0;border-radius:8px;padding:9px 14px;background:var(--primary-light);color:#fff;cursor:pointer}button.secondary{background:#e7eef6;color:var(--primary)}button.danger{background:var(--error)}button:disabled{opacity:.55}.table-card{overflow:auto;padding:0}table{width:100%;border-collapse:collapse}th,td{padding:14px;text-align:left;border-bottom:1px solid var(--border)}th{background:var(--bg-surface);font-size:13px}td small{display:block;color:var(--text-muted);margin-top:3px}.actions{white-space:nowrap}.actions button{margin-right:6px}.verdict{font-weight:700;text-transform:uppercase}.verdict.pass{color:var(--success)}.verdict.fail,.verdict.error{color:var(--error)}.message{padding:12px;border-radius:8px;margin-bottom:14px}.message.error{background:#feecec;color:var(--error)}.message.success{background:#e8f7f0;color:var(--success)}.empty{text-align:center;color:var(--text-muted);padding:40px}@media(max-width:760px){.review-page{padding:18px}.review-header,.auth-card{align-items:stretch;flex-direction:column}.auth-card input{max-width:none}th:nth-child(2),td:nth-child(2),th:nth-child(5),td:nth-child(5){display:none}}
</style>
