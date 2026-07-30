<template>
  <div class="admin-page">
    <!-- 頁面標題區 -->
    <div class="page-header">
      <div class="header-content">
        <h1 class="page-title">系統管理</h1>
        <p class="page-desc">監控知識圖譜狀態、管理快取與系統資源</p>
      </div>
    </div>

    <!-- 狀態卡片列 -->
    <div class="stats-row">
      <div class="stat-card">
        <div class="stat-icon blue">
          <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <circle cx="12" cy="12" r="10"/><path d="M12 6v6l4 2"/>
          </svg>
        </div>
        <div class="stat-info">
          <span class="stat-value">{{ stats?.active_workers ?? '-' }}</span>
          <span class="stat-label">Workers</span>
        </div>
      </div>
      <div class="stat-card">
        <div class="stat-icon" :class="stats?.cache_enabled ? 'green' : 'red'">
          <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <path d="M22 12h-4l-3 9L9 3l-3 9H2"/>
          </svg>
        </div>
        <div class="stat-info">
          <span class="stat-value">{{ stats?.cache_enabled ? '開啟' : '關閉' }}</span>
          <span class="stat-label">快取</span>
        </div>
      </div>
      <div class="stat-card">
        <div class="stat-icon" :class="graphStats ? 'green' : 'gray'">
          <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <circle cx="12" cy="12" r="3"/><path d="M12 1v4M12 19v4M4.22 4.22l2.83 2.83M16.95 16.95l2.83 2.83M1 12h4M19 12h4M4.22 19.78l2.83-2.83M16.95 7.05l2.83-2.83"/>
          </svg>
        </div>
        <div class="stat-info">
          <span class="stat-value">{{ graphStats ? formatNodeCount(graphStats.nodes) : '-' }}</span>
          <span class="stat-label">Neo4j 節點</span>
        </div>
      </div>
      <div class="stat-card">
        <div class="stat-icon" :class="vectorStats?.points_count ? 'green' : 'gray'">
          <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <path d="M21 16V8a2 2 0 0 0-1-1.73l-7-4a2 2 0 0 0-2 0l-7 4A2 2 0 0 0 3 8v8a2 2 0 0 0 1 1.73l7 4a2 2 0 0 0 2 0l7-4A2 2 0 0 0 21 16z"/>
          </svg>
        </div>
        <div class="stat-info">
          <span class="stat-value">{{ vectorStats?.points_count ?? '0' }}</span>
          <span class="stat-label">QDrant 向量</span>
        </div>
      </div>
    </div>

    <!-- 功能卡片 -->
    <div class="admin-grid">
      <!-- Neo4j 圖資料庫 -->
      <div class="admin-card">
        <div class="card-header">
          <div class="card-title">
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
              <circle cx="12" cy="12" r="3"/><path d="M12 1v4M12 19v4M4.22 4.22l2.83 2.83M16.95 16.95l2.83 2.83M1 12h4M19 12h4M4.22 19.78l2.83-2.83M16.95 7.05l2.83-2.83"/>
            </svg>
            <h3>Neo4j 圖資料庫</h3>
          </div>
          <button class="refresh-btn" @click="fetchGraphStats">
            <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
              <polyline points="23,4 23,10 17,10"/><path d="M20.49 15a9 9 0 1 1-2.12-9.36L23 10"/>
            </svg>
            重新整理
          </button>
        </div>
        <div class="card-body">
          <div v-if="!graphStats" class="empty-state">
            <span>載入中...</span>
          </div>
          <div v-else class="db-details">
            <div class="detail-section">
              <h4 class="detail-title">節點統計</h4>
              <div class="detail-row" v-for="(count, type) in graphStats.nodes" :key="type">
                <span class="detail-label">{{ type }}</span>
                <span class="detail-value">{{ count }}</span>
              </div>
            </div>
            <div class="detail-section" v-if="graphStats.relationships">
              <h4 class="detail-title">關係統計</h4>
              <div class="detail-row" v-for="(count, type) in graphStats.relationships" :key="type">
                <span class="detail-label">{{ type }}</span>
                <span class="detail-value">{{ count }}</span>
              </div>
            </div>
          </div>
        </div>
      </div>

      <!-- QDrant 向量資料庫 -->
      <div class="admin-card">
        <div class="card-header">
          <div class="card-title">
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
              <path d="M21 16V8a2 2 0 0 0-1-1.73l-7-4a2 2 0 0 0-2 0l-7 4A2 2 0 0 0 3 8v8a2 2 0 0 0 1 1.73l7 4a2 2 0 0 0 2 0l7-4A2 2 0 0 0 21 16z"/>
            </svg>
            <h3>QDrant 向量資料庫</h3>
          </div>
          <button class="refresh-btn" @click="fetchVectorStats">
            <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
              <polyline points="23,4 23,10 17,10"/><path d="M20.49 15a9 9 0 1 1-2.12-9.36L23 10"/>
            </svg>
            重新整理
          </button>
        </div>
        <div class="card-body">
          <div v-if="!vectorStats" class="empty-state">
            <span>載入中...</span>
          </div>
          <div v-else class="db-details">
            <div class="detail-section">
              <h4 class="detail-title">Collection: knowledge_base</h4>
              <div class="detail-row">
                <span class="detail-label">狀態</span>
                <span class="detail-value" :class="vectorStats.status === 'green' ? 'green' : 'orange'">
                  {{ vectorStats.status }}
                </span>
              </div>
              <div class="detail-row">
                <span class="detail-label">向量數量</span>
                <span class="detail-value">{{ vectorStats.vectors_count ?? 0 }}</span>
              </div>
              <div class="detail-row">
                <span class="detail-label">Points 總數</span>
                <span class="detail-value">{{ vectorStats.points_count ?? 0 }}</span>
              </div>
              <div class="detail-row" v-if="vectorStats.optimizer_status">
                <span class="detail-label">優化器</span>
                <span class="detail-value">{{ vectorStats.optimizer_status }}</span>
              </div>
            </div>
          </div>
        </div>
      </div>

      <!-- 快取管理 -->
      <div class="admin-card">
        <div class="card-header">
          <div class="card-title">
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
              <path d="M22 12h-4l-3 9L9 3l-3 9H2"/>
            </svg>
            <h3>快取管理</h3>
          </div>
        </div>
        <div class="card-body">
          <p class="cache-info">快取可加速相同查詢的回應速度。清除後需重新生成答案。</p>
          <button class="danger-btn" @click="clearCache">
            <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
              <polyline points="3,6 5,6 21,6"/><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/>
            </svg>
            清除所有快取
          </button>
        </div>
      </div>

      <!-- 定時自動攝入 -->
      <div class="admin-card">
        <div class="card-header">
          <div class="card-title">
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
              <circle cx="12" cy="12" r="10"/><path d="M12 6v6l4 2"/>
            </svg>
            <h3>定時自動攝入</h3>
          </div>
        </div>
        <div class="card-body">
          <div class="beat-config">
            <div class="beat-status">
              <span class="beat-label">狀態</span>
              <span class="beat-value" :class="beatEnabled ? 'green' : 'red'">
                {{ beatEnabled ? '已啟用' : '已停用' }}
              </span>
            </div>

            <div class="beat-interval">
              <label class="beat-label">執行間隔（分鐘）</label>
              <input type="number" v-model.number="beatInterval" min="1" max="60" class="beat-input" />
            </div>

            <div class="beat-folder">
              <span class="beat-label">監控資料夾</span>
              <span class="beat-value folder-path">{{ beatWatchFolder }}</span>
            </div>
            <div class="beat-actions">
              <button class="primary-btn" @click="toggleBeat" :disabled="savingBeat">
                {{ beatEnabled ? '停用' : '啟用' }}自動攝入
              </button>
              <button class="secondary-btn" @click="saveBeatSettings">
                儲存設定
              </button>
              <button class="secondary-btn" @click="triggerScan">
                立即執行一次
              </button>
            </div>
            <div class="type-rules">
              <h4 class="type-rules-title">📁 檔案命名規則</h4>
              <p class="type-rules-desc">自動攝入會根據檔案名稱自動判斷萃取模式：</p>
              <div class="type-list">
                <div class="type-item"><span class="type-badge type1">type1</span> 4G/5G 電信設備</div>
                <div class="type-item"><span class="type-badge type2">type2</span> WiFi 設備</div>
                <div class="type-item"><span class="type-badge type3">type3</span> Lab 管理</div>
                <div class="type-item"><span class="type-badge type4">type4</span> Project 專案</div>
                <div class="type-item"><span class="type-badge type5">type5</span> Automation 自動化</div>
                <div class="type-item"><span class="type-badge type6">SIT-TR-SC</span> Report 測試報告</div>
              </div>
              <p class="type-example">範例：<code>SIT-TR-SC-NR-Throughput.xlsx</code> → 自動使用 Report 模式</p>
            </div>
          </div>
        </div>
      </div>

      <!-- 即時日誌 -->
      <div class="admin-card log-card">
        <div class="card-header">
          <div class="card-title">
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
              <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14,2 14,8 20,8"/><line x1="16" y1="13" x2="8" y2="13"/><line x1="16" y1="17" x2="8" y2="17"/><polyline points="10,9 9,9 8,9"/>
            </svg>
            <h3>系統日誌</h3>
          </div>
          <div class="log-actions">
            <button class="refresh-btn" @click="fetchLogs">
              <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <polyline points="23,4 23,10 17,10"/><path d="M20.49 15a9 9 0 1 1-2.12-9.36L23 10"/>
              </svg>
              重新整理
            </button>
            <button class="clear-btn" @click="clearLogs">
              清除
            </button>
          </div>
        </div>
        <div class="card-body log-body">
          <div class="log-container" ref="logContainer">
            <div v-if="logs.length === 0" class="log-empty">
              尚無日誌記錄
            </div>
            <div v-else class="log-list">
              <div 
                v-for="(log, index) in logs" 
                :key="index" 
                class="log-entry"
                :class="'log-' + log.level.toLowerCase()"
              >
                <span class="log-time">{{ log.timestamp }}</span>
                <span class="log-level">{{ log.level }}</span>
                <span class="log-source">[{{ log.source }}]</span>
                <span class="log-message">{{ log.message }}</span>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted, nextTick } from 'vue'
import { getSystemStats } from '../services/api'
import { getGraphStats, clearAllCache, getBeatSchedule, updateBeatSchedule, triggerBeatSchedule } from '../services/admin'

const graphStats = ref(null)
const vectorStats = ref(null)
const stats = ref(null)
const beatEnabled = ref(false)
const beatInterval = ref(5)
const beatWatchFolder = ref('')
const savingBeat = ref(false)
const logs = ref([])
const logContainer = ref(null)
let logSource = null

async function fetchGraphStats() {
  try {
    graphStats.value = await getGraphStats()
  } catch (e) {
    console.error('取得圖譜失敗:', e)
  }
}

async function fetchVectorStats() {
  try {
    const response = await fetch('/admin/vector-stats')
    vectorStats.value = await response.json()
  } catch (e) {
    console.error('取得向量統計失敗:', e)
  }
}

async function clearCache() {
  if (confirm('確定要清除所有快取嗎？')) {
    try {
      await clearAllCache()
      alert('快取已清除')
    } catch (e) {
      alert('清除失敗: ' + e.message)
    }
  }
}

async function fetchBeatSchedule() {
  try {
    const config = await getBeatSchedule()
    beatEnabled.value = config.enabled
    beatInterval.value = config.interval_minutes
    beatWatchFolder.value = config.watch_folder
  } catch (e) {
    console.error('取得排程設定失敗:', e)
  }
}

async function toggleBeat() {
  if (confirm(beatEnabled.value ? '確定要停用自動攝入？' : '確定要啟用自動攝入？')) {
    try {
      savingBeat.value = true
      const newEnabled = !beatEnabled.value
      await updateBeatSchedule({
        enabled: newEnabled,
        interval_minutes: beatInterval.value
      })
      beatEnabled.value = newEnabled
      alert(newEnabled ? `自動攝入已啟用（每 ${beatInterval.value} 分鐘執行）` : '自動攝入已停用')
    } catch (e) {
      alert('操作失敗: ' + e.message)
    } finally {
      savingBeat.value = false
    }
  }
}

async function saveBeatSettings() {
  try {
    savingBeat.value = true
    await updateBeatSchedule({
      enabled: beatEnabled.value,
      interval_minutes: beatInterval.value
    })
    alert(`設定已儲存（每 ${beatInterval.value} 分鐘執行）`)
  } catch (e) {
    alert('儲存失敗: ' + e.message)
  } finally {
    savingBeat.value = false
  }
}

async function triggerScan() {
  if (confirm('確定要立即執行一次掃描？')) {
    try {
      await triggerBeatSchedule()
      alert('掃描任務已提交，請在執行歷史中查看結果')
    } catch (e) {
      alert('執行失敗: ' + e.message)
    }
  }
}

async function fetchLogs() {
  try {
    const response = await fetch('/admin/logs?lines=200')
    const data = await response.json()
    logs.value = data.logs || []
    // 滾動到最新
    nextTick(() => {
      if (logContainer.value) {
        logContainer.value.scrollTop = logContainer.value.scrollHeight
      }
    })
  } catch (e) {
    console.error('取得日誌失敗:', e)
  }
}

async function clearLogs() {
  if (confirm('確定要清除所有日誌？')) {
    try {
      await fetch('/admin/logs', { method: 'DELETE' })
      logs.value = []
    } catch (e) {
      console.error('清除日誌失敗:', e)
    }
  }
}

function connectLogStream() {
  // 使用 EventSource 連接 SSE
  if (typeof EventSource !== 'undefined') {
    logSource = new EventSource('/admin/logs/stream')
    logSource.onmessage = (event) => {
      try {
        const newLogs = JSON.parse(event.data)
        logs.value = newLogs
        // 自動滾動
        nextTick(() => {
          if (logContainer.value) {
            logContainer.value.scrollTop = logContainer.value.scrollHeight
          }
        })
      } catch (e) {
        console.error('解析日誌失敗:', e)
      }
    }
    logSource.onerror = () => {
      console.error('日誌串流連線錯誤')
      // 斷開後嘗試重新連接
      setTimeout(connectLogStream, 5000)
    }
  }
}

function formatStats(obj) {
  if (!obj) return '-'
  return Object.entries(obj)
    .map(([k, v]) => `${k}: ${v}`)
    .join(', ')
}

function formatNodeCount(obj) {
  if (!obj) return '-'
  if (typeof obj === 'object') {
    const total = Object.values(obj).reduce((a, b) => a + b, 0)
    return total.toLocaleString()
  }
  return obj.toLocaleString()
}

onMounted(async () => {
  await fetchGraphStats()
  await fetchVectorStats()
  try {
    stats.value = await getSystemStats()
  } catch (e) {
    console.error('取得系統狀態失敗:', e)
  }
  await fetchBeatSchedule()
  
  // 取得初始日誌
  await fetchLogs()
  
  // 連接日誌串流
  connectLogStream()
})
</script>

<style scoped>
.admin-page {
  display: flex;
  flex-direction: column;
  gap: 24px;
}

/* === Page Header === */
.page-header {
  margin-bottom: 8px;
}

.page-title {
  font-size: 1.6em;
  font-weight: 700;
  color: var(--text-primary);
  letter-spacing: -0.02em;
}

.page-desc {
  color: var(--text-secondary);
  font-size: 0.92em;
  margin-top: 4px;
}

/* === Stats Row === */
.stats-row {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 16px;
}

.stat-card {
  background: var(--bg-card);
  border: 1px solid var(--border);
  border-radius: var(--radius-lg);
  padding: 20px;
  display: flex;
  align-items: center;
  gap: 16px;
  box-shadow: var(--shadow-sm);
}

.stat-icon {
  width: 48px;
  height: 48px;
  border-radius: 12px;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
}

.stat-icon.blue { background: rgba(14, 165, 233, 0.1); color: var(--accent); }
.stat-icon.green { background: rgba(16, 185, 129, 0.1); color: var(--success); }
.stat-icon.red { background: rgba(239, 68, 68, 0.1); color: var(--error); }
.stat-icon.gray { background: var(--bg-page); color: var(--text-muted); }

.stat-info {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.stat-value {
  font-size: 1.4em;
  font-weight: 700;
  color: var(--text-primary);
  line-height: 1;
}

.stat-label {
  font-size: 0.78em;
  color: var(--text-muted);
  text-transform: uppercase;
  letter-spacing: 0.04em;
  margin-top: 4px;
}

/* === Admin Grid === */
.admin-grid {
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: 20px;
}

.admin-card {
  background: var(--bg-card);
  border: 1px solid var(--border);
  border-radius: var(--radius-lg);
  box-shadow: var(--shadow-sm);
  overflow: hidden;
}

.card-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 16px 20px;
  border-bottom: 1px solid var(--border);
}

.card-title {
  display: flex;
  align-items: center;
  gap: 9px;
  color: var(--text-secondary);
}

.card-title h3 {
  font-size: 0.9em;
  font-weight: 600;
  color: var(--text-primary);
}

.refresh-btn {
  display: flex;
  align-items: center;
  gap: 5px;
  padding: 5px 10px;
  background: var(--bg-page);
  border: 1px solid var(--border);
  border-radius: 6px;
  cursor: pointer;
  font-size: 0.78em;
  font-weight: 500;
  color: var(--text-secondary);
  transition: all 0.2s;
}

.refresh-btn:hover {
  border-color: var(--accent);
  color: var(--accent);
}

.card-body {
  padding: 20px;
}

.empty-state {
  text-align: center;
  color: var(--text-muted);
  font-size: 0.88em;
  padding: 20px;
}

/* === Database Details === */
.db-details {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.detail-section {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.detail-title {
  font-size: 0.78em;
  font-weight: 600;
  color: var(--text-secondary);
  text-transform: uppercase;
  letter-spacing: 0.04em;
  padding-bottom: 6px;
  border-bottom: 1px solid var(--border);
}

.detail-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 8px 12px;
  background: var(--bg-page);
  border-radius: 6px;
}

.detail-row .detail-label {
  font-size: 0.85em;
  color: var(--text-secondary);
}

.detail-row .detail-value {
  font-size: 0.92em;
  font-weight: 600;
  color: var(--text-primary);
}

.detail-row .detail-value.green { color: var(--success); }
.detail-row .detail-value.orange { color: #f59e0b; }

.graph-details {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.detail-row {
  display: flex;
  flex-direction: column;
  gap: 3px;
  padding: 10px 14px;
  background: var(--bg-page);
  border-radius: 8px;
}

.detail-label {
  font-size: 0.72em;
  color: var(--text-muted);
  text-transform: uppercase;
  letter-spacing: 0.04em;
}

.detail-value {
  font-size: 0.88em;
  color: var(--text-primary);
  font-weight: 500;
}

.cache-info {
  font-size: 0.85em;
  color: var(--text-secondary);
  line-height: 1.6;
  margin-bottom: 16px;
}

.danger-btn {
  display: flex;
  align-items: center;
  gap: 7px;
  padding: 10px 18px;
  background: rgba(239, 68, 68, 0.08);
  border: 1px solid rgba(239, 68, 68, 0.2);
  border-radius: 8px;
  color: #dc2626;
  font-size: 0.88em;
  font-weight: 600;
  cursor: pointer;
  transition: all 0.2s;
}

.danger-btn:hover {
  background: rgba(239, 68, 68, 0.12);
  border-color: rgba(239, 68, 68, 0.3);
}

/* === Beat Schedule === */
.beat-config {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.beat-status,
.beat-interval,
.beat-folder {
  display: flex;
  flex-direction: column;
  gap: 4px;
  padding: 12px 14px;
  background: var(--bg-page);
  border-radius: 8px;
}


.beat-label {
  font-size: 0.72em;
  color: var(--text-muted);
  text-transform: uppercase;
  letter-spacing: 0.04em;
}

.beat-value {
  font-size: 0.92em;
  color: var(--text-primary);
  font-weight: 600;
}

.beat-value.green { color: var(--success); }
.beat-value.red { color: var(--error); }
.beat-value.folder-path {
  font-family: monospace;
  font-size: 0.85em;
  word-break: break-all;
}

.beat-input {
  padding: 10px 14px;
  border: 1px solid var(--border);
  border-radius: 6px;
  font-size: 0.95em;
  background: var(--bg-card);
  color: var(--text-primary);
  width: 150px;
}

.beat-input:focus {
  outline: none;
  border-color: var(--accent);
}

.beat-actions {
  display: flex;
  gap: 10px;
  margin-top: 8px;
}

.primary-btn {
  padding: 10px 18px;
  background: var(--accent);
  border: none;
  border-radius: 8px;
  color: white;
  font-size: 0.88em;
  font-weight: 600;
  cursor: pointer;
  transition: all 0.2s;
}

.primary-btn:hover {
  opacity: 0.9;
}

.primary-btn:disabled {
  opacity: 0.6;
  cursor: not-allowed;
}

/* === Type Rules === */
.type-rules {
  margin-top: 16px;
  padding: 14px;
  background: rgba(59, 130, 246, 0.08);
  border: 1px solid rgba(59, 130, 246, 0.2);
  border-radius: 8px;
}

.type-rules-title {
  font-size: 0.85em;
  font-weight: 600;
  color: var(--accent);
  margin-bottom: 8px;
}

.type-rules-desc {
  font-size: 0.8em;
  color: var(--text-secondary);
  margin-bottom: 10px;
}

.type-list {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-bottom: 10px;
}

.type-item {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 0.8em;
  color: var(--text-secondary);
}

.type-badge {
  padding: 2px 8px;
  border-radius: 4px;
  font-size: 0.75em;
  font-weight: 600;
  font-family: monospace;
}

.type-badge.type1 { background: rgba(34, 197, 94, 0.2); color: #22c55e; }
.type-badge.type2 { background: rgba(59, 130, 246, 0.2); color: #3b82f6; }
.type-badge.type3 { background: rgba(168, 85, 247, 0.2); color: #a855f7; }
.type-badge.type4 { background: rgba(249, 115, 22, 0.2); color: #f97316; }
.type-badge.type5 { background: rgba(236, 72, 153, 0.2); color: #ec4899; }
.type-badge.type6 { background: rgba(124, 58, 237, 0.2); color: #7c3aed; }

.type-example {
  font-size: 0.78em;
  color: var(--text-muted);
  margin: 0;
}

.type-example code {
  background: var(--bg-page);
  padding: 2px 6px;
  border-radius: 4px;
  font-family: monospace;
}

.secondary-btn {
  padding: 10px 18px;
  background: var(--bg-page);
  border: 1px solid var(--border);
  border-radius: 8px;
  color: var(--text-primary);
  font-size: 0.88em;
  font-weight: 500;
  cursor: pointer;
  transition: all 0.2s;
}

.secondary-btn:hover {
  border-color: var(--accent);
  color: var(--accent);
}

/* === Responsive === */
@media (max-width: 900px) {
  .stats-row {
    grid-template-columns: repeat(2, 1fr);
  }
  .admin-grid {
    grid-template-columns: 1fr;
  }
}

@media (max-width: 600px) {
  .stats-row {
    grid-template-columns: 1fr;
  }
}

/* === Log Viewer === */
.log-card {
  grid-column: span 2;
}

.log-actions {
  display: flex;
  gap: 8px;
}

.clear-btn {
  display: flex;
  align-items: center;
  gap: 5px;
  padding: 5px 10px;
  background: rgba(239, 68, 68, 0.08);
  border: 1px solid rgba(239, 68, 68, 0.2);
  border-radius: 6px;
  cursor: pointer;
  font-size: 0.78em;
  font-weight: 500;
  color: #dc2626;
  transition: all 0.2s;
}

.clear-btn:hover {
  background: rgba(239, 68, 68, 0.12);
  border-color: rgba(239, 68, 68, 0.3);
}

.log-body {
  padding: 0;
}

.log-container {
  max-height: 400px;
  overflow-y: auto;
  font-family: 'Consolas', 'Courier New', monospace;
  font-size: 0.82em;
  background: #0d1117;
  border-radius: 8px;
}

.log-empty {
  padding: 40px;
  text-align: center;
  color: var(--text-muted);
}

.log-list {
  padding: 8px;
}

.log-entry {
  display: flex;
  align-items: flex-start;
  gap: 8px;
  padding: 6px 10px;
  border-radius: 4px;
  margin-bottom: 2px;
  background: rgba(255, 255, 255, 0.02);
}

.log-entry:hover {
  background: rgba(255, 255, 255, 0.05);
}

.log-time {
  color: #6e7681;
  flex-shrink: 0;
}

.log-level {
  font-weight: 600;
  flex-shrink: 0;
  padding: 1px 6px;
  border-radius: 4px;
  font-size: 0.75em;
}

.log-info .log-level { background: rgba(56, 139, 253, 0.2); color: #58a6ff; }
.log-warning .log-level { background: rgba(210, 153, 34, 0.2); color: #d29922; }
.log-error .log-level { background: rgba(239, 68, 68, 0.2); color: #f85149; }

.log-source {
  color: #8b949e;
  flex-shrink: 0;
}

.log-message {
  color: #c9d1d9;
  word-break: break-word;
}

.log-info .log-message { color: #c9d1d9; }
.log-warning .log-message { color: #e3b341; }
.log-error .log-message { color: #f85149; }
</style>
