<template>
  <div class="search-page">
    <!-- 頁面標題區 -->
    <div class="page-header">
      <div class="header-content">
        <h1 class="page-title">智慧搜尋</h1>
        <p class="page-desc">支援 GraphRAG + RAG 混合架構，多種模式精準回答</p>
      </div>
    </div>

    <!-- 搜尋卡片 -->
    <div class="search-card">
      <!-- 搜尋模式選擇 -->
      <div class="mode-section">
        <label class="section-label">選擇搜尋模式</label>
        
        <!-- 類別下拉選單 -->
        <div class="category-section">
          <label class="category-label">選擇類別</label>
          <select v-model="selectedCategory" class="category-select">
            <option value="">全部類別</option>
            <option v-for="cat in categories" :key="cat.value" :value="cat.value">
              {{ cat.label }}
            </option>
          </select>
        </div>
        
        <div class="mode-grid">
          <button
            v-for="mode in modes"
            :key="mode.value"
            :class="['mode-btn', { active: selectedMode === mode.value }]"
            @click="selectedMode = mode.value"
          >
            <span class="mode-icon" v-html="mode.icon"></span>
            <span class="mode-label">{{ mode.label }}</span>
            <span class="mode-desc">{{ mode.shortDesc }}</span>
          </button>
        </div>
        <div class="mode-detail">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <circle cx="12" cy="12" r="10"/><path d="M12 16v-4M12 8h.01"/>
          </svg>
          <span>{{ currentModeDesc }}</span>
        </div>
      </div>

      <!-- 搜尋輸入區 -->
      <div class="input-section">
        <div class="search-input-wrapper">
          <svg class="search-icon" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <circle cx="11" cy="11" r="8"/><path d="m21 21-4.35-4.35"/>
          </svg>
          <textarea
            v-model="query"
            placeholder="輸入您的問題，例如：SCU7000 設備的規格為何？散熱系統的狀況如何？"
            rows="3"
            @keydown.enter.ctrl="handleSearch"
          ></textarea>
          <button class="search-btn" @click="handleSearch" :disabled="isSearching || !query.trim()">
            <span v-if="!isSearching">搜尋</span>
            <span v-else class="loading-text">
              <span class="spinner"></span>
              處理中
            </span>
          </button>
        </div>
      </div>
    </div>

    <!-- 類別權重卡片 -->
    <div v-if="analysisLoading || categoryAnalysis" class="analysis-card">
      <div class="analysis-header">
        <div class="analysis-title-block">
          <h3>類別權重</h3>
          <p>依問題關鍵字、相關文件與 boost 詞彙加權</p>
        </div>
        <div class="analysis-summary" v-if="categoryAnalysis && categoryAnalysis.top_category">
          <span class="summary-label">最高相關</span>
          <span class="summary-value">{{ categoryAnalysis.top_category }}</span>
          <span class="summary-score">{{ categoryAnalysis.normalized_scores?.[categoryAnalysis.top_category] ?? 0 }}%</span>
          <span class="summary-confidence" v-if="categoryAnalysis.confidence !== undefined">
            信心 {{ categoryAnalysis.confidence }}%
          </span>
        </div>
      </div>

      <div v-if="analysisLoading" class="analysis-loading">
        <div class="analysis-spinner"></div>
        <span>分析類別權重中...</span>
      </div>

      <div v-else class="analysis-list">
        <div
          v-for="item in categoryWeightRows"
          :key="item.key"
          class="analysis-row"
          :class="{ active: item.isTop }"
        >
          <div class="analysis-row-head">
            <div class="analysis-name">
              <span class="analysis-dot" :class="item.themeClass"></span>
              <span>{{ item.label }}</span>
            </div>
            <div class="analysis-metrics">
              <span class="analysis-score">{{ item.score }}%</span>
              <span class="analysis-docs">{{ item.docCount }} files</span>
            </div>
          </div>
          <div class="analysis-track">
            <div
              class="analysis-fill"
              :class="item.themeClass"
              :style="{ width: item.score + '%' }"
            ></div>
          </div>
          <div v-if="item.previewDocs.length" class="analysis-preview">
            {{ item.previewDocs.join(' · ') }}
          </div>
        </div>
      </div>
    </div>

    <!-- 任務狀態 -->
    <div v-if="isSearching && taskId" class="task-card">
      <div class="task-header">
        <div class="task-spinner"></div>
        <span>任務處理中</span>
      </div>
      <div class="task-info">
        <span>任務ID: <code>{{ taskId }}</code></span>
      </div>
    </div>

    <!-- 錯誤訊息 -->
    <div v-if="error" class="error-card">
      <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
        <circle cx="12" cy="12" r="10"/><path d="M12 8v4M12 16h.01"/>
      </svg>
      <span>{{ error }}</span>
    </div>

    <!-- 搜尋結果 -->
    <div v-if="answer" class="result-card">
      <div class="result-header">
        <div class="result-meta">
          <span class="result-badge" :class="displayMode.toLowerCase()">{{ displayMode }} 模式</span>
          <span class="result-time" v-if="taskId && !fromCache">任務 ID: {{ taskId }}</span>
          <span class="cache-badge" v-if="fromCache">快取命中</span>
        </div>
      </div>

      <!-- 答案區 -->
      <div class="answer-section">
        <div class="section-header">
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/>
          </svg>
          <h3>回答結果</h3>
        </div>
        <div class="answer-content" v-html="formattedAnswer"></div>
      </div>

      <!-- 來源區 -->
      <div v-if="sources && sources.length" class="sources-section">
        <div class="section-header">
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14,2 14,8 20,8"/>
          </svg>
          <h3>來源文件</h3>
          <span class="source-count">{{ sources.length }} 個相關文件</span>
        </div>
        <div class="sources-list">
          <div v-for="(src, idx) in sources" :key="idx" class="source-item">
            <div class="source-icon">
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14,2 14,8 20,8"/>
              </svg>
            </div>
            <div class="source-info">
              <span class="source-name">{{ src.source || '來源 ' + (idx + 1) }}</span>
              <span class="source-score" v-if="src.mode !== 'graph'">相似度 {{ ((src.score || 0) * 100).toFixed(1) }}%</span>
            </div>
            <div class="source-preview">{{ src.content?.substring(0, 120) }}...</div>
          </div>
        </div>
      </div>
    </div>

    <!-- 系統資訊折疊面板 -->
    <div class="system-card">
      <button @click="showStats = !showStats" class="system-toggle">
        <div class="toggle-left">
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <rect x="2" y="3" width="20" height="14" rx="2" ry="2"/><line x1="8" y1="21" x2="16" y2="21"/><line x1="12" y1="17" x2="12" y2="21"/>
          </svg>
          <span>系統狀態</span>
        </div>
        <svg :class="['toggle-icon', { open: showStats }]" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <polyline points="6 9 12 15 18 9"/>
        </svg>
      </button>
      <div v-if="showStats && stats" class="stats-content">
        <div class="stats-grid">
          <div class="stat-item">
            <span class="stat-label">Workers</span>
            <span class="stat-value">{{ stats.active_workers }}</span>
          </div>
          <div class="stat-item">
            <span class="stat-label">快取</span>
            <span :class="['stat-badge', stats.cache_enabled ? 'on' : 'off']">
              {{ stats.cache_enabled ? '開啟' : '關閉' }}
            </span>
          </div>
          <div class="stat-item" v-if="stats.queue_size !== undefined">
            <span class="stat-label">佇列</span>
            <span class="stat-value">{{ stats.queue_size }}</span>
          </div>
        </div>
      </div>
      <button v-if="!stats && !showStats" @click="fetchStats" class="system-check-btn">
        檢視系統狀態
      </button>
    </div>
  </div>
</template>

<script setup>
import { ref, computed } from 'vue'
import { marked } from 'marked'
import { searchApi, analyzeQuestionApi, getTaskStatus, getSystemStats } from '../services/api'

const modes = [
  {
    value: 'auto',
    label: 'Auto',
    shortDesc: '自動判斷',
    icon: '<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 2L2 7l10 5 10-5-10-5zM2 17l10 5 10-5M2 12l10 5 10-5"/></svg>',
    desc: '系統自動判斷最佳搜尋模式，適合不確定使用哪種模式時'
  },
  {
    value: 'basic',
    label: 'Basic',
    shortDesc: '關鍵字搜尋',
    icon: '<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="11" cy="11" r="8"/><path d="m21 21-4.35-4.35"/></svg>',
    desc: 'Neo4j 關鍵字搜尋，適用於簡單事實查詢'
  },
  {
    value: 'vector',
    label: 'Vector',
    shortDesc: '語意搜尋',
    icon: '<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 2a10 10 0 1 0 10 10H12V2z"/><path d="M12 2a10 10 0 0 1 10 10"/></svg>',
    desc: '語意向量搜尋，適用於語義相似查詢'
  },
  {
    value: 'deep',
    label: 'Deep',
    shortDesc: '圖譜推理',
    icon: '<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="3"/><path d="M12 1v4M12 19v4M4.22 4.22l2.83 2.83M16.95 16.95l2.83 2.83M1 12h4M19 12h4M4.22 19.78l2.83-2.83M16.95 7.05l2.83-2.83"/></svg>',
    desc: '知識圖譜推理，適用於複雜多跳問題'
  },
  {
    value: 'hybrid',
    label: 'Hybrid',
    shortDesc: '混合搜尋',
    icon: '<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M8 6h13M8 12h13M8 18h13M3 6h.01M3 12h.01M3 18h.01"/></svg>',
    desc: '混合搜尋（向量+圖譜），適用於全面回答'
  }
]

const query = ref('')
const selectedMode = ref('auto')
const selectedCategory = ref('')

const categories = [
  { value: '4g5g', label: '4G/5G' },
  { value: 'report', label: 'Report' },
  { value: 'wifi', label: 'WiFi' },
  { value: 'lab', label: 'Lab管理' },
  { value: 'project', label: 'Project' },
  { value: 'automation', label: 'Automation' }
]
const isSearching = ref(false)
const taskId = ref(null)
const answer = ref('')
const sources = ref([])
const error = ref('')
const fromCache = ref(false)
const stats = ref(null)
const showStats = ref(false)
const hybridBusy = ref(false)
const hybridMessage = ref('')
const categoryAnalysis = ref(null)
const analysisLoading = ref(false)
const analysisRequestId = ref(0)

const currentModeDesc = computed(() => {
  const mode = modes.find(m => m.value === selectedMode.value)
  return mode ? mode.desc : ''
})

const displayMode = computed(() => {
  const map = { basic: 'Basic', deep: 'Deep', vector: 'Vector', hybrid: 'Hybrid', auto: 'Auto' }
  return map[selectedMode.value] || selectedMode.value
})

const formattedAnswer = computed(() => {
  if (!answer.value) return ''
  // 使用 marked 將 Markdown 轉換為 HTML（包含表格）
  return marked.parse(answer.value)
})

const categoryWeightRows = computed(() => {
  const normalized = categoryAnalysis.value?.normalized_scores || {}
  const relatedDocs = categoryAnalysis.value?.related_docs || {}
  const topCategory = categoryAnalysis.value?.top_category || ''

  return categories.map((cat) => {
    const apiLabel = cat.label
    const score = normalized[apiLabel] ?? 0
    const docs = relatedDocs[apiLabel] || []
    return {
      key: cat.value,
      label: cat.label,
      score,
      docCount: docs.length,
      previewDocs: docs.slice(0, 2),
      themeClass: `cat-${cat.value}`,
      isTop: apiLabel === topCategory
    }
  })
})

async function checkHybridStatus() {
  try {
    const res = await fetch('/hybrid-status')
    const data = await res.json()
    hybridBusy.value = data.is_busy
    hybridMessage.value = data.message || ''
    return data
  } catch (e) {
    return null
  }
}

async function handleSearch() {
  if (!query.value.trim()) {
    error.value = '請輸入搜尋內容'
    return
  }

  // Hybrid 模式檢查
  if (selectedMode.value === 'hybrid') {
    await checkHybridStatus()
    if (hybridBusy.value) {
      error.value = hybridMessage.value || '目前忙碌，請稍候'
      return
    }
  }

  error.value = ''
  answer.value = ''
  sources.value = []
  fromCache.value = false
  categoryAnalysis.value = null
  analysisLoading.value = true

  const requestId = analysisRequestId.value + 1
  analysisRequestId.value = requestId

  analyzeQuestionApi(query.value)
    .then((analysis) => {
      if (analysisRequestId.value === requestId) {
        categoryAnalysis.value = analysis
      }
    })
    .catch(() => {
      if (analysisRequestId.value === requestId) {
        categoryAnalysis.value = null
      }
    })
    .finally(() => {
      if (analysisRequestId.value === requestId) {
        analysisLoading.value = false
      }
    })

  try {
    isSearching.value = true
    const response = await searchApi(query.value, selectedMode.value)
    taskId.value = response.task_id

    if (response.status === 'completed') {
      answer.value = response.answer || response.message
      fromCache.value = true
      isSearching.value = false
      return
    }

    await pollTaskStatus(response.task_id)
  } catch (e) {
    error.value = e.message || '搜尋請求失敗'
    isSearching.value = false
    analysisLoading.value = false
  }
}

async function pollTaskStatus(id) {
  const maxAttempts = 120
  let attempts = 0

  while (attempts < maxAttempts) {
    try {
      const status = await getTaskStatus(id)

      if (status.status === 'completed') {
        answer.value = status.answer || ''
        sources.value = status.sources || []
        isSearching.value = false
        return
      }

      if (status.status === 'failed') {
        error.value = status.error || '任務執行失敗'
        isSearching.value = false
        return
      }

      await new Promise(r => setTimeout(r, 1000))
      attempts++

    } catch (e) {
      await new Promise(r => setTimeout(r, 2000))
      attempts += 2
    }
  }

  error.value = '任務處理逾時'
  isSearching.value = false
}

async function fetchStats() {
  try {
    showStats.value = true
    stats.value = await getSystemStats()
  } catch (e) {
    error.value = '無法取得系統狀態'
  }
}
</script>

<style scoped>
.search-page {
  display: flex;
  flex-direction: column;
  gap: 20px;
}

/* === Page Header === */
.page-header {
  margin-bottom: 8px;
  padding: 18px 20px;
  border-radius: var(--radius-lg);
  background: linear-gradient(135deg, rgba(11, 36, 64, 0.98), rgba(20, 58, 102, 0.92) 48%, rgba(31, 141, 184, 0.9));
  color: white;
  box-shadow: var(--shadow-lg);
  position: relative;
  overflow: hidden;
}

.page-header::after {
  content: '';
  position: absolute;
  inset: 0;
  background: linear-gradient(90deg, transparent 0%, rgba(255,255,255,0.08) 50%, transparent 100%);
  pointer-events: none;
}

.page-title {
  font-size: 1.6em;
  font-weight: 700;
  color: #fff;
  letter-spacing: -0.02em;
}

.page-desc {
  color: rgba(255,255,255,0.78);
  font-size: 0.92em;
  margin-top: 4px;
}

/* === Cards === */
.search-card,
.result-card,
.task-card,
.error-card,
.system-card {
  background: var(--bg-card);
  border-radius: var(--radius-lg);
  box-shadow: var(--shadow);
  border: 1px solid rgba(184, 200, 216, 0.9);
  position: relative;
  overflow: hidden;
}

/* === Search Card === */
.search-card {
  padding: 28px;
  background: linear-gradient(180deg, rgba(255,255,255,0.98), rgba(248, 251, 254, 0.98));
}

.mode-section {
  margin-bottom: 24px;
}

.section-label {
  display: block;
  font-size: 0.8em;
  font-weight: 600;
  color: var(--text-muted);
  text-transform: uppercase;
  letter-spacing: 0.06em;
  margin-bottom: 12px;
}

/* 類別下拉選單 */
.category-section {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 16px;
  padding: 12px 16px;
  background: linear-gradient(180deg, rgba(247, 250, 252, 0.98), rgba(241, 246, 252, 0.98));
  border: 1px solid rgba(184, 200, 216, 0.8);
  border-radius: var(--radius);
}

.category-label {
  font-size: 0.9em;
  font-weight: 600;
  color: var(--text-primary);
  white-space: nowrap;
}

.category-select {
  flex: 1;
  padding: 8px 12px;
  font-size: 0.95em;
  border: 1px solid var(--border);
  border-radius: 6px;
  background: white;
  color: var(--text-primary);
  cursor: pointer;
  transition: all 0.2s;
}

.category-select:hover {
  border-color: var(--primary);
}

.category-select:focus {
  outline: none;
  border-color: var(--primary);
  box-shadow: 0 0 0 3px rgba(0, 217, 255, 0.1);
}

.mode-grid {
  display: grid;
  grid-template-columns: repeat(5, 1fr);
  gap: 10px;
  margin-bottom: 14px;
}

.mode-btn {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 6px;
  padding: 14px 8px;
  border: 1px solid rgba(184, 200, 216, 0.95);
  background: linear-gradient(180deg, rgba(255,255,255,0.98), rgba(244, 249, 253, 0.96));
  border-radius: var(--radius);
  cursor: pointer;
  transition: all 0.2s;
  text-align: center;
  box-shadow: inset 0 1px 0 rgba(255,255,255,0.72);
}

.mode-btn:hover {
  border-color: rgba(31, 141, 184, 0.65);
  background: linear-gradient(180deg, rgba(244, 251, 255, 1), rgba(236, 244, 251, 0.96));
  transform: translateY(-1px);
}

.mode-btn.active {
  border-color: rgba(20, 58, 102, 0.9);
  background: linear-gradient(135deg, rgba(20, 58, 102, 0.08), rgba(31, 141, 184, 0.06));
  box-shadow: 0 10px 24px -18px rgba(20, 58, 102, 0.55);
}

.mode-icon {
  color: var(--text-secondary);
  display: flex;
}

.mode-btn.active .mode-icon {
  color: var(--primary);
}

.mode-label {
  font-size: 0.88em;
  font-weight: 600;
  color: var(--text-primary);
}

.mode-desc {
  font-size: 0.72em;
  color: var(--text-muted);
  display: none;
}

.mode-detail {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 0.82em;
  color: var(--text-secondary);
  padding: 10px 14px;
  background: linear-gradient(180deg, rgba(247, 250, 252, 0.98), rgba(241, 246, 252, 0.98));
  border-radius: 8px;
  border: 1px solid rgba(184, 200, 216, 0.6);
}

.mode-detail svg {
  flex-shrink: 0;
  opacity: 0.5;
}

/* === Input Section === */
.input-section {
  border-top: 1px solid var(--border);
  padding-top: 24px;
}

.search-input-wrapper {
  display: flex;
  align-items: flex-start;
  gap: 12px;
  background: linear-gradient(180deg, rgba(247, 250, 252, 0.98), rgba(255,255,255,0.98));
  border: 1px solid rgba(184, 200, 216, 0.95);
  border-radius: var(--radius);
  padding: 12px 16px;
  transition: border-color 0.2s, box-shadow 0.2s;
  box-shadow: inset 0 1px 0 rgba(255,255,255,0.8);
}

.search-input-wrapper:focus-within {
  border-color: rgba(31, 141, 184, 0.8);
  box-shadow: 0 0 0 4px rgba(31, 141, 184, 0.08);
}

.search-icon {
  color: var(--text-muted);
  margin-top: 10px;
  flex-shrink: 0;
}

.search-input-wrapper textarea {
  flex: 1;
  border: none;
  background: transparent;
  font-size: 1em;
  font-family: inherit;
  color: var(--text-primary);
  resize: none;
  outline: none;
  line-height: 1.6;
}

.search-input-wrapper textarea::placeholder {
  color: var(--text-muted);
}

.search-btn {
  padding: 10px 28px;
  background: linear-gradient(135deg, var(--primary) 0%, var(--primary-light) 55%, var(--accent) 100%);
  color: white;
  border: none;
  border-radius: 8px;
  font-size: 0.92em;
  font-weight: 600;
  cursor: pointer;
  transition: all 0.2s;
  white-space: nowrap;
  display: flex;
  align-items: center;
  gap: 8px;
  align-self: center;
}

.search-btn:hover:not(:disabled) {
  background: linear-gradient(135deg, #112b4c 0%, #1e4f8f 55%, #157395 100%);
  transform: translateY(-1px);
  box-shadow: 0 10px 24px -14px rgba(20, 58, 102, 0.6);
}

.search-btn:disabled {
  background: #cbd5e1;
  cursor: not-allowed;
  transform: none;
  box-shadow: none;
}

.loading-text {
  display: flex;
  align-items: center;
  gap: 8px;
}

.spinner {
  width: 14px;
  height: 14px;
  border: 2px solid rgba(255,255,255,0.3);
  border-top-color: white;
  border-radius: 50%;
  animation: spin 0.8s linear infinite;
}

@keyframes spin {
  to { transform: rotate(360deg); }
}

/* === Analysis Card === */
.analysis-card {
  background: var(--bg-card);
  border-radius: var(--radius-lg);
  box-shadow: var(--shadow);
  border: 1px solid rgba(184, 200, 216, 0.9);
  padding: 22px 24px;
  position: relative;
  overflow: hidden;
}

.analysis-card::before,
.result-card::before,
.task-card::before,
.error-card::before,
.system-card::before {
  content: '';
  position: absolute;
  inset: 0 auto auto 0;
  width: 100%;
  height: 4px;
  background: linear-gradient(90deg, var(--primary), var(--accent-light));
}

.analysis-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
  margin-bottom: 18px;
}

.analysis-title-block h3 {
  font-size: 1em;
  font-weight: 700;
  color: var(--text-primary);
}

.analysis-title-block p {
  margin-top: 4px;
  font-size: 0.84em;
  color: var(--text-secondary);
}

.analysis-summary {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  justify-content: flex-end;
  gap: 8px;
  text-align: right;
}

.summary-label,
.summary-value,
.summary-score,
.summary-confidence {
  display: inline-flex;
  align-items: center;
  min-height: 28px;
  padding: 0 10px;
  border-radius: 999px;
  font-size: 0.8em;
  font-weight: 600;
}

.summary-label {
  background: rgba(20, 58, 102, 0.08);
  color: var(--primary);
}

.summary-value {
  background: rgba(31, 141, 184, 0.12);
  color: var(--accent);
}

.summary-score {
  background: rgba(16, 185, 129, 0.12);
  color: var(--success);
}

.summary-confidence {
  background: rgba(245, 158, 11, 0.12);
  color: #b45309;
}

.analysis-loading {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 14px 0 4px;
  color: var(--text-secondary);
  font-size: 0.9em;
}

.analysis-spinner {
  width: 16px;
  height: 16px;
  border: 2px solid rgba(14, 165, 233, 0.18);
  border-top-color: var(--accent);
  border-radius: 50%;
  animation: spin 0.8s linear infinite;
}

.analysis-list {
  display: flex;
  flex-direction: column;
  gap: 14px;
}

.analysis-row {
  padding: 14px 16px;
  border: 1px solid rgba(184, 200, 216, 0.8);
  border-radius: var(--radius);
  background: linear-gradient(180deg, rgba(250, 252, 255, 0.96), rgba(243, 248, 252, 0.98));
}

.analysis-row.active {
  border-color: rgba(20, 58, 102, 0.4);
  background: linear-gradient(135deg, rgba(20, 58, 102, 0.08) 0%, rgba(31, 141, 184, 0.06) 100%);
}

.analysis-row-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 10px;
}

.analysis-name {
  display: flex;
  align-items: center;
  gap: 10px;
  min-width: 0;
  font-size: 0.92em;
  font-weight: 600;
  color: var(--text-primary);
}

.analysis-dot {
  width: 10px;
  height: 10px;
  border-radius: 50%;
  flex-shrink: 0;
}

.analysis-metrics {
  display: flex;
  align-items: baseline;
  gap: 10px;
  flex-shrink: 0;
}

.analysis-score {
  font-size: 0.98em;
  font-weight: 700;
  color: var(--text-primary);
}

.analysis-docs {
  font-size: 0.75em;
  color: var(--text-muted);
}

.analysis-track {
  height: 10px;
  border-radius: 999px;
  background: rgba(148, 163, 184, 0.16);
  overflow: hidden;
}

.analysis-fill {
  height: 100%;
  border-radius: inherit;
  transition: width 0.25s ease;
}

.analysis-preview {
  margin-top: 8px;
  font-size: 0.76em;
  color: var(--text-secondary);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.analysis-fill.cat-4g5g,
.analysis-dot.cat-4g5g {
  background: linear-gradient(90deg, #1d4ed8, #38bdf8);
}

.analysis-fill.cat-report,
.analysis-dot.cat-report {
  background: linear-gradient(90deg, #7c3aed, #c084fc);
}

.analysis-fill.cat-wifi,
.analysis-dot.cat-wifi {
  background: linear-gradient(90deg, #0f766e, #14b8a6);
}

.analysis-fill.cat-lab,
.analysis-dot.cat-lab {
  background: linear-gradient(90deg, #b45309, #f59e0b);
}

.analysis-fill.cat-project,
.analysis-dot.cat-project {
  background: linear-gradient(90deg, #0f766e, #10b981);
}

.analysis-fill.cat-automation,
.analysis-dot.cat-automation {
  background: linear-gradient(90deg, #475569, #94a3b8);
}

/* === Task Card === */
.task-card {
  padding: 20px 24px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  background: linear-gradient(135deg, rgba(20, 58, 102, 0.05) 0%, rgba(31, 141, 184, 0.05) 100%);
  border-color: rgba(20, 58, 102, 0.18);
}

.task-header {
  display: flex;
  align-items: center;
  gap: 12px;
  font-weight: 500;
  color: var(--primary);
}

.task-spinner {
  width: 18px;
  height: 18px;
  border: 2px solid rgba(14, 165, 233, 0.2);
  border-top-color: var(--accent);
  border-radius: 50%;
  animation: spin 0.8s linear infinite;
}

.task-info {
  font-size: 0.82em;
  color: var(--text-muted);
}

.task-info code {
  background: rgba(0,0,0,0.05);
  padding: 2px 6px;
  border-radius: 4px;
  font-size: 0.9em;
}

/* === Error Card === */
.error-card {
  padding: 16px 20px;
  background: rgba(239, 68, 68, 0.05);
  border: 1px solid rgba(239, 68, 68, 0.2);
  border-radius: var(--radius);
  color: #b91c1c;
  display: flex;
  align-items: center;
  gap: 10px;
  font-size: 0.92em;
}

/* === Result Card === */
.result-card {
  overflow: hidden;
}

.result-header {
  padding: 16px 24px;
  border-bottom: 1px solid var(--border);
  background: linear-gradient(135deg, rgba(20, 58, 102, 0.04) 0%, transparent 100%);
}

.result-meta {
  display: flex;
  align-items: center;
  gap: 12px;
}

.result-badge {
  padding: 3px 10px;
  border-radius: 20px;
  font-size: 0.78em;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.04em;
}

.result-badge.basic { background: #dbeafe; color: #1d4ed8; }
.result-badge.deep { background: #ede9fe; color: #7c3aed; }
.result-badge.vector { background: #d1fae5; color: #0f766e; }
.result-badge.hybrid { background: #e0f2fe; color: #0369a1; }
.result-badge.auto { background: #e2e8f0; color: #334155; }

.cache-badge {
  padding: 2px 8px;
  background: #fef3c7;
  color: #92400e;
  border-radius: 4px;
  font-size: 0.72em;
  font-weight: 600;
}

.result-time {
  font-size: 0.78em;
  color: var(--text-muted);
}

/* === Answer Section === */
.answer-section {
  padding: 24px;
  border-bottom: 1px solid var(--border);
}

.section-header {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 14px;
  color: var(--text-secondary);
}

.section-header h3 {
  font-size: 0.88em;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.04em;
}

.answer-content {
  line-height: 1.8;
  color: var(--text-primary);
  font-size: 0.96em;
}

/* Markdown 表格樣式 */
.answer-content table {
  width: 100%;
  border-collapse: collapse;
  margin: 16px 0;
  font-size: 0.9em;
}
.answer-content th {
  background: var(--bg-secondary, #f5f5f5);
  font-weight: 600;
  text-align: left;
}
.answer-content th, .answer-content td {
  border: 1px solid var(--border-color, #ddd);
  padding: 10px 12px;
}
.answer-content tr:nth-child(even) {
  background: var(--bg-hover, #f9f9f9);
}
.answer-content code {
  background: var(--bg-secondary, #f0f0f0);
  padding: 2px 6px;
  border-radius: 3px;
  font-family: monospace;
}

/* === Sources Section === */
.sources-section {
  padding: 24px;
}

.source-count {
  margin-left: auto;
  font-size: 0.78em;
  color: var(--text-muted);
  font-weight: 400;
  text-transform: none;
  letter-spacing: 0;
}

.sources-list {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.source-item {
  display: flex;
  align-items: flex-start;
  gap: 12px;
  padding: 14px 16px;
  background: linear-gradient(180deg, rgba(247, 250, 252, 0.96), rgba(241, 246, 252, 0.98));
  border-radius: var(--radius);
  border: 1px solid rgba(184, 200, 216, 0.7);
}

.source-icon {
  width: 30px;
  height: 30px;
  background: linear-gradient(135deg, rgba(20, 58, 102, 0.1), rgba(31, 141, 184, 0.12));
  border-radius: 6px;
  display: flex;
  align-items: center;
  justify-content: center;
  color: var(--primary);
  flex-shrink: 0;
}

.source-info {
  display: flex;
  flex-direction: column;
  min-width: 140px;
}

.source-name {
  font-weight: 600;
  font-size: 0.88em;
  color: var(--text-primary);
}

.source-score {
  font-size: 0.75em;
  color: var(--success);
  font-weight: 500;
}

.source-preview {
  flex: 1;
  font-size: 0.82em;
  color: var(--text-secondary);
  line-height: 1.5;
  overflow: hidden;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
}

/* === System Card === */
.system-card {
  overflow: hidden;
}

.system-toggle {
  width: 100%;
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 16px 20px;
  background: none;
  border: none;
  cursor: pointer;
  font-size: 0.9em;
  font-weight: 500;
  color: var(--text-secondary);
  transition: background 0.2s;
}

.system-toggle:hover {
  background: linear-gradient(180deg, rgba(247, 250, 252, 0.96), rgba(241, 246, 252, 0.98));
}

.toggle-left {
  display: flex;
  align-items: center;
  gap: 8px;
}

.toggle-icon {
  transition: transform 0.2s;
}

.toggle-icon.open {
  transform: rotate(180deg);
}

.stats-content {
  padding: 0 20px 18px;
}

.stats-grid {
  display: flex;
  gap: 24px;
  padding: 14px 18px;
  background: linear-gradient(180deg, rgba(247, 250, 252, 0.96), rgba(241, 246, 252, 0.98));
  border-radius: var(--radius);
}

.stat-item {
  display: flex;
  flex-direction: column;
  gap: 3px;
}

.stat-label {
  font-size: 0.72em;
  color: var(--text-muted);
  text-transform: uppercase;
  letter-spacing: 0.04em;
}

.stat-value {
  font-size: 1.1em;
  font-weight: 700;
  color: var(--text-primary);
}

.stat-badge {
  font-size: 0.82em;
  font-weight: 600;
  padding: 2px 8px;
  border-radius: 4px;
  align-self: flex-start;
}

.stat-badge.on {
  background: #d1fae5;
  color: #059669;
}

.stat-badge.off {
  background: #fee2e2;
  color: #dc2626;
}

.system-check-btn {
  width: 100%;
  padding: 12px;
  background: none;
  border: none;
  border-top: 1px solid var(--border);
  cursor: pointer;
  color: var(--text-muted);
  font-size: 0.85em;
  transition: all 0.2s;
}

.system-check-btn:hover {
  background: var(--bg-page);
  color: var(--text-primary);
}

/* === Responsive === */
@media (max-width: 900px) {
  .mode-grid {
    grid-template-columns: repeat(3, 1fr);
  }
}

@media (max-width: 600px) {
  .mode-grid {
    grid-template-columns: repeat(2, 1fr);
  }

  .search-input-wrapper {
    flex-direction: column;
  }

  .search-btn {
    width: 100%;
    justify-content: center;
  }
}
</style>
