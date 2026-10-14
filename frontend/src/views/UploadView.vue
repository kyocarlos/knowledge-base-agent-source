<template>
  <div class="upload-page">
    <!-- 頁面標題區 -->
    <div class="page-header">
      <div class="header-content">
        <h1 class="page-title">檔案上傳</h1>
        <p class="page-desc">上傳文件並依類別轉換，4G/5G 與 WiFi 走完整攝入流程，Lab / Project / Automation 只寫入向量資料庫</p>
      </div>
    </div>

    <!-- 上傳卡片 -->
    <div class="upload-card">
      <div class="upload-zone" @dragover.prevent @drop.prevent="handleDrop">
        <input
          type="file"
          ref="fileInput"
          @change="handleFileSelect"
          accept=".pdf,.docx,.xlsx,.pptx,.txt,.md,.html,.csv,.json,.xml,.epub,.msg,.png,.jpg,.jpeg,.gif"
          style="display: none"
        />

        <div class="zone-content" @click="triggerFileInput">
          <div class="zone-icon">
            <svg width="40" height="40" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5">
              <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/>
              <polyline points="17,8 12,3 7,8"/>
              <line x1="12" y1="3" x2="12" y2="15"/>
            </svg>
          </div>
          <div class="zone-text">
            <span class="zone-primary">點擊或拖曳檔案到此處</span>
            <span class="zone-secondary">支援 PDF、Word、Excel、PowerPoint、Markdown 等格式</span>
          </div>
        </div>

        <div v-if="selectedFile" class="selected-file">
          <div class="file-icon-wrapper">
            <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
              <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/>
              <polyline points="14,2 14,8 20,8"/>
            </svg>
          </div>
          <div class="file-details">
            <span class="file-name">{{ selectedFile.name }}</span>
            <span class="file-size">{{ formatSize(selectedFile.size) }}</span>
          </div>
          <button class="file-remove" @click.stop="clearFile">
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
              <line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/>
            </svg>
          </button>
        </div>
      </div>

      <!-- 選項區 -->
      <div v-if="selectedFile" class="options-section">
        <div class="option-group">
          <label class="checkbox-label" @click="autoIngest = !autoIngest">
            <div :class="['checkbox', { checked: autoIngest }]">
              <svg v-if="autoIngest" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3">
                <polyline points="20,6 9,17 4,12"/>
              </svg>
            </div>
            <div class="checkbox-text">
              <span class="checkbox-title">轉換後自動攝入知識庫</span>
              <span class="checkbox-desc">4G/5G 與 WiFi 會同步寫入 Neo4j 與 QDrant；Lab / Project / Automation 只寫入 QDrant</span>
            </div>
          </label>
        </div>

        <!-- 萃取模式 -->
        <div v-if="autoIngest" class="extraction-section">
          <label class="section-label">選擇攝入類別</label>
          <div class="extraction-modes">
            <label
              v-for="mode in extractionModes"
              :key="mode.id"
              :class="['extraction-option', { active: selectedMode === mode.id }]"
            >
              <input type="radio" v-model="selectedMode" :value="mode.id" style="display:none" />
              <div class="mode-icon" v-html="mode.icon"></div>
              <div class="mode-info">
                <span class="mode-name">{{ mode.name }}</span>
                <span class="mode-desc">{{ mode.description }}</span>
              </div>
              <div class="mode-check" v-if="selectedMode === mode.id">
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3">
                  <polyline points="20,6 9,17 4,12"/>
                </svg>
              </div>
            </label>
          </div>
        </div>

        <!-- 上傳按鈕 -->
        <div class="action-section">
          <button
            class="upload-submit-btn"
            @click="uploadFile"
            :disabled="isUploading"
          >
            <span v-if="!isUploading" class="btn-content">
              <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/>
                <polyline points="17,8 12,3 7,8"/>
                <line x1="12" y1="3" x2="12" y2="15"/>
              </svg>
              上傳並{{ autoIngest ? '攝入知識庫' : '轉換' }}
            </span>
            <span v-else class="btn-content">
              <span class="btn-spinner"></span>
              處理中...
            </span>
          </button>
        </div>
      </div>
    </div>

    <!-- 結果顯示 -->
    <div v-if="result" :class="['result-card', result.status]">
      <div class="result-header">
        <div class="result-status">
          <div :class="['status-icon', result.status]">
            <svg v-if="result.status === 'success'" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5">
              <polyline points="20,6 9,17 4,12"/>
            </svg>
            <svg v-else width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5">
              <line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/>
            </svg>
          </div>
          <div class="status-text">
            <span class="status-title">{{ resultStatusTitle(result.status) }}</span>
            <span class="status-file" v-if="result.file_name">{{ result.file_name }}</span>
          </div>
        </div>
        <button class="result-close" @click="result = null">
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/>
          </svg>
        </button>
      </div>

      <div v-if="result.status === 'success' || result.status === 'submitted'" class="result-body">
        <div class="result-grid">
          <div class="result-item" v-if="result.converted_path">
            <span class="result-label">轉換檔案</span>
            <span class="result-value">{{ result.converted_path }}</span>
          </div>
          <div class="result-item" v-if="result.task_id">
            <span class="result-label">任務 ID</span>
            <span class="result-value">{{ result.task_id }}</span>
          </div>
          <div class="result-item">
            <span class="result-label">知識庫攝入</span>
            <span :class="['result-badge', result.status === 'submitted' ? 'neutral' : (result.ingested ? 'success' : 'neutral')]">
              {{ result.status === 'submitted' ? '已加入佇列' : (result.ingested ? '已攝入' : '未攝入') }}
            </span>
          </div>
          <div class="result-item" v-if="result.extraction_mode_name">
            <span class="result-label">萃取模式</span>
            <span class="result-value">{{ result.extraction_mode_name }}</span>
          </div>
          <div class="result-item" v-if="result.queue_position">
            <span class="result-label">排隊位置</span>
            <span class="result-value">{{ result.queue_position }}</span>
          </div>
        </div>

        <div v-if="result.content" class="content-preview">
          <div class="preview-header">
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
              <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/>
              <polyline points="14,2 14,8 20,8"/>
            </svg>
            <span>Markdown 預覽</span>
          </div>
          <pre class="preview-content">{{ result.content }}</pre>
        </div>
      </div>

      <div v-else class="result-body error-body">
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <circle cx="12" cy="12" r="10"/><path d="M12 8v4M12 16h.01"/>
        </svg>
        <div class="error-message">
          <span>{{ result.error }}</span>
          <span v-if="result.response_status" class="error-status">HTTP {{ result.response_status }}</span>
        </div>
        <pre v-if="result.response_preview" class="error-preview">{{ result.response_preview }}</pre>
      </div>
    </div>

    <!-- 攝入任務列表 -->
    <div v-if="ingestTasks.length" class="tasks-card">
      <div class="tasks-header">
        <div class="tasks-title">
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <path d="M12 20v-6M6 20V10M18 20V4"/>
          </svg>
          <h3>攝入任務</h3>
          <span class="file-count-badge">{{ ingestTasks.length }}</span>
        </div>
        <div class="tasks-actions">
          <button class="refresh-btn" @click="refreshIngestTasks">
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
              <polyline points="23,4 23,10 17,10"/>
              <path d="M20.49 15a9 9 0 1 1-2.12-9.36L23 10"/>
            </svg>
            更新狀態
          </button>
          <button
            class="clear-history-btn"
            :disabled="!hasHistoricalTasks || isClearingHistory"
            @click="clearHistory"
          >
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
              <path d="M3 6h18"/>
              <path d="M8 6V4h8v2"/>
              <path d="M6 6l1 14h10l1-14"/>
              <path d="M10 11v5"/>
              <path d="M14 11v5"/>
            </svg>
            {{ isClearingHistory ? '清除中...' : '清除紀錄' }}
          </button>
        </div>
      </div>

      <div v-if="taskNotice" class="task-notice">
        {{ taskNotice }}
      </div>

      <div class="task-list">
        <div v-for="task in ingestTasks" :key="task.task_id" :class="['task-item', task.status]">
          <div class="task-main">
            <div class="task-name-row">
              <span class="task-file-name">{{ task.file_name }}</span>
              <span :class="['task-status-badge', task.status]">{{ task.status_text || taskStatusText(task.status) }}</span>
            </div>
            <div class="task-step">{{ task.step || task.message || '等待背景任務處理' }}</div>
            <div v-if="task.status === 'queued' && task.queue_position" class="task-queue">
              排隊位置：{{ task.queue_position }}
            </div>
            <div v-if="task.error" class="task-error">{{ task.error }}</div>
            <div class="task-progress">
              <div class="task-progress-bar" :style="{ width: `${task.progress || 0}%` }"></div>
            </div>
          </div>
          <div class="task-percent">{{ task.progress || 0 }}%</div>
        </div>
      </div>
    </div>

    <!-- 已上傳檔案列表 -->
    <div class="files-card">
      <div class="files-header">
        <div class="files-title">
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z"/>
          </svg>
          <h3>已上傳檔案</h3>
          <span class="file-count-badge" v-if="files.length">{{ files.length }}</span>
        </div>
        <button class="refresh-btn" @click="refreshFiles">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <polyline points="23,4 23,10 17,10"/>
            <path d="M20.49 15a9 9 0 1 1-2.12-9.36L23 10"/>
          </svg>
          重新整理
        </button>
      </div>

      <div v-if="files.length === 0" class="files-empty">
        <svg width="36" height="36" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5">
          <path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z"/>
        </svg>
        <span>尚無上傳的檔案</span>
      </div>

      <div v-else class="files-list">
        <div v-for="file in files" :key="file.path" class="file-item">
          <div class="file-type-icon">
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
              <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/>
              <polyline points="14,2 14,8 20,8"/>
            </svg>
          </div>
          <div class="file-info">
            <span class="file-name">{{ file.path || file.name }}</span>
            <span class="file-meta">{{ formatSize(file.size) }}</span>
          </div>
          <div class="file-badge">
            <span class="ingest-badge">已攝入</span>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, onUnmounted, computed } from 'vue'
import { clearUploadTaskHistory } from '../services/api'

const fileInput = ref(null)
const selectedFile = ref(null)
const isUploading = ref(false)
const autoIngest = ref(true)
const result = ref(null)
const files = ref([])
const selectedMode = ref('4g5g')
const ingestTasks = ref([])
const isClearingHistory = ref(false)
const taskNotice = ref('')
let taskPollTimer = null

const extractionModes = [
  {
    id: '4g5g',
    name: '4G/5G 電信設備',
    description: '維持原有攝入原則：LLM 萃取 + Neo4j + QDrant',
    icon: '<svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M5 12.55a11 11 0 0 1 14.08 0M8.53 16.11a6 6 0 0 1 6.95 0M12 20h.01"/></svg>'
  },
  {
    id: 'wifi',
    name: 'WiFi 設備',
    description: '維持原有攝入原則：LLM 萃取 + Neo4j + QDrant',
    icon: '<svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M5 12.55a11 11 0 0 1 14.08 0M1.42 9a16 16 0 0 1 21.16 0M8.53 16.11a6 6 0 0 1 6.95 0M12 20h.01"/></svg>'
  },
  {
    id: 'lab',
    name: 'Lab 管理',
    description: 'Chunk 後直接寫入 QDrant，不寫入 Neo4j',
    icon: '<svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M9 3H5a2 2 0 0 0-2 2v4m6-6h10a2 2 0 0 1 2 2v4M9 3v18m0 0h10a2 2 0 0 0 2-2v-4M9 21H5a2 2 0 0 1-2-2v-4m0 0h18"/></svg>'
  },
  {
    id: 'project',
    name: 'Project 專案',
    description: 'Chunk 後直接寫入 QDrant，不寫入 Neo4j',
    icon: '<svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M2 3h6a4 4 0 0 1 4 4v14a3 3 0 0 0-3-3H2zM22 3h-6a4 4 0 0 0-4 4v14a3 3 0 0 1 3-3h7z"/></svg>'
  },
  {
    id: 'automation',
    name: 'Automation 自動化',
    description: 'Chunk 後直接寫入 QDrant，不寫入 Neo4j',
    icon: '<svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1 0 2.83 2 2 0 0 1-2.83 0l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-2 2 2 2 0 0 1-2-2v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83 0 2 2 0 0 1 0-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1-2-2 2 2 0 0 1 2-2h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 0-2.83 2 2 0 0 1 2.83 0l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 2-2 2 2 0 0 1 2 2v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 0 2 2 0 0 1 0 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 2 2 2 2 0 0 1-2 2h-.09a1.65 1.65 0 0 0-1.51 1z"/></svg>'
  }
]

function triggerFileInput() {
  fileInput.value.click()
}

function handleFileSelect(event) {
  const file = event.target.files[0]
  if (file) {
    selectedFile.value = file
    result.value = null
  }
}

function handleDrop(event) {
  const file = event.dataTransfer.files[0]
  if (file) {
    selectedFile.value = file
    result.value = null
  }
}

function clearFile() {
  selectedFile.value = null
  if (fileInput.value) fileInput.value.value = ''
}

async function uploadFile() {
  if (!selectedFile.value) return

  isUploading.value = true
  result.value = null

  try {
    const formData = new FormData()
    formData.append('file', selectedFile.value)

    let endpoint = autoIngest.value ? '/api/upload/ingest' : '/api/upload'

    if (autoIngest.value) {
      endpoint += `?extraction_mode=${selectedMode.value}`
    }

    const response = await fetch(endpoint, {
      method: 'POST',
      body: formData
    })

    const bodyText = await response.text()
    let parsedBody = null

    if (bodyText) {
      try {
        parsedBody = JSON.parse(bodyText)
      } catch (parseError) {
        parsedBody = {
          status: 'failed',
          error: `伺服器回應不是 JSON：${response.status} ${response.statusText}`,
          response_preview: bodyText.slice(0, 1000)
        }
      }
    } else {
      parsedBody = {
        status: 'failed',
        error: `伺服器回應空白：${response.status} ${response.statusText}`
      }
    }

    if (!response.ok) {
      result.value = {
        status: 'failed',
        file_name: selectedFile.value.name,
        error: parsedBody?.error || `HTTP ${response.status} ${response.statusText}`,
        response_status: response.status,
        response_preview: parsedBody?.response_preview || bodyText.slice(0, 1000)
      }
      return
    }

    result.value = parsedBody

    if (result.value.status === 'success') {
      refreshFiles()
    } else if (result.value.status === 'submitted') {
      await refreshIngestTasks()
      startTaskPolling()
      clearFile()
    }
  } catch (e) {
    result.value = {
      status: 'failed',
      error: e.message || '上傳失敗'
    }
  } finally {
    isUploading.value = false
  }
}

async function refreshFiles() {
  try {
    const response = await fetch('/api/files')
    const data = await response.json()
    files.value = data.files || []
  } catch (e) {
    console.error('取得檔案列表失敗:', e)
  }
}

function mergeTaskSections(data) {
  const merged = [...(data.active || []), ...(data.queued || []), ...(data.recent || [])]
  const seen = new Set()
  return merged.filter(task => {
    if (!task?.task_id || seen.has(task.task_id)) return false
    seen.add(task.task_id)
    return true
  })
}

const hasHistoricalTasks = computed(() =>
  ingestTasks.value.some(task => ['completed', 'failed'].includes(task.status))
)

async function refreshIngestTasks() {
  try {
    const response = await fetch('/api/upload/tasks?limit=30')
    if (!response.ok) return
    const data = await response.json()
    ingestTasks.value = mergeTaskSections(data)

    const hasRunningTasks = ingestTasks.value.some(task => !['completed', 'failed'].includes(task.status))
    if (hasRunningTasks) {
      startTaskPolling()
    } else {
      stopTaskPolling()
      refreshFiles()
    }
  } catch (e) {
    console.error('取得攝入任務失敗:', e)
  }
}

async function clearHistory() {
  if (!hasHistoricalTasks.value || isClearingHistory.value) return
  const confirmed = window.confirm('要清除所有已完成與失敗的攝入紀錄嗎？這不會影響進行中的任務。')
  if (!confirmed) return

  isClearingHistory.value = true
  taskNotice.value = ''

  try {
    const result = await clearUploadTaskHistory()
    await refreshIngestTasks()
    taskNotice.value = `已清除 ${result.deleted_count || 0} 筆歷史紀錄`
    setTimeout(() => {
      if (taskNotice.value === `已清除 ${result.deleted_count || 0} 筆歷史紀錄`) {
        taskNotice.value = ''
      }
    }, 3000)
  } catch (e) {
    taskNotice.value = `清除失敗：${e.message || '未知錯誤'}`
  } finally {
    isClearingHistory.value = false
  }
}

function startTaskPolling() {
  if (taskPollTimer) return
  taskPollTimer = setInterval(refreshIngestTasks, 3000)
}

function stopTaskPolling() {
  if (taskPollTimer) {
    clearInterval(taskPollTimer)
    taskPollTimer = null
  }
}

function taskStatusText(status) {
  const mapping = {
    queued: '等待中',
    upload_saved: '檔案已接收',
    converting: '轉換中',
    converted: '轉換完成',
    extracting: 'LLM 萃取中',
    writing_neo4j: '寫入 Neo4j',
    writing_qdrant: '寫入 QDrant',
    refreshing_index: '更新索引',
    completed: '攝入完成',
    failed: '攝入失敗'
  }
  return mapping[status] || status || '未知'
}

function resultStatusTitle(status) {
  if (status === 'success') return '上傳成功'
  if (status === 'submitted') return '已提交攝入'
  return '上傳失敗'
}

function formatSize(bytes) {
  if (bytes < 1024) return bytes + ' B'
  if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + ' KB'
  return (bytes / (1024 * 1024)).toFixed(1) + ' MB'
}

// 初始載入
refreshFiles()
refreshIngestTasks()

onUnmounted(() => {
  stopTaskPolling()
})
</script>

<style scoped>
.upload-page {
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
.upload-card,
.result-card,
.tasks-card,
.files-card {
  background: var(--bg-card);
  border-radius: var(--radius-lg);
  box-shadow: var(--shadow);
  border: 1px solid rgba(184, 200, 216, 0.9);
  position: relative;
  overflow: hidden;
}

.upload-card::before,
.result-card::before,
.tasks-card::before,
.files-card::before {
  content: '';
  position: absolute;
  inset: 0 auto auto 0;
  width: 100%;
  height: 4px;
  background: linear-gradient(90deg, var(--primary), var(--accent-light));
}

/* === Upload Card === */
.upload-card {
  overflow: hidden;
  background: linear-gradient(180deg, rgba(255,255,255,0.98), rgba(248, 251, 254, 0.98));
}

.upload-zone {
  padding: 40px 32px;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 20px;
  border-bottom: 1px solid rgba(184, 200, 216, 0.8);
  cursor: pointer;
  transition: background 0.2s;
}

.upload-zone:hover {
  background: linear-gradient(180deg, rgba(247, 250, 252, 0.98), rgba(241, 246, 252, 0.98));
}

.zone-content {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 14px;
  text-align: center;
}

.zone-icon {
  width: 72px;
  height: 72px;
  background: linear-gradient(135deg, rgba(20, 58, 102, 0.1) 0%, rgba(31, 141, 184, 0.14) 100%);
  border-radius: 16px;
  display: flex;
  align-items: center;
  justify-content: center;
  color: var(--primary);
}

.zone-primary {
  font-size: 1em;
  font-weight: 600;
  color: var(--text-primary);
  display: block;
}

.zone-secondary {
  font-size: 0.82em;
  color: var(--text-muted);
  display: block;
  margin-top: 4px;
}

/* === Selected File === */
.selected-file {
  display: flex;
  align-items: center;
  gap: 12px;
  width: 100%;
  max-width: 480px;
  padding: 12px 16px;
  background: linear-gradient(180deg, rgba(247, 250, 252, 0.98), rgba(241, 246, 252, 0.98));
  border: 1px solid rgba(184, 200, 216, 0.8);
  border-radius: var(--radius);
}

.file-icon-wrapper {
  width: 38px;
  height: 38px;
  background: linear-gradient(135deg, rgba(20, 58, 102, 0.1), rgba(31, 141, 184, 0.12));
  border-radius: 8px;
  display: flex;
  align-items: center;
  justify-content: center;
  color: var(--primary);
  flex-shrink: 0;
}

.file-details {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
}

.file-name {
  font-weight: 600;
  font-size: 0.9em;
  color: var(--text-primary);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.file-size {
  font-size: 0.78em;
  color: var(--text-muted);
}

.file-remove {
  width: 28px;
  height: 28px;
  background: none;
  border: none;
  border-radius: 6px;
  cursor: pointer;
  color: var(--text-muted);
  display: flex;
  align-items: center;
  justify-content: center;
  transition: all 0.2s;
}

.file-remove:hover {
  background: rgba(239, 68, 68, 0.1);
  color: #ef4444;
}

/* === Options Section === */
.options-section {
  padding: 24px 32px;
  display: flex;
  flex-direction: column;
  gap: 20px;
}

.section-label {
  display: block;
  font-size: 0.78em;
  font-weight: 600;
  color: var(--text-muted);
  text-transform: uppercase;
  letter-spacing: 0.06em;
  margin-bottom: 10px;
}

/* === Checkbox === */
.checkbox-label {
  display: flex;
  align-items: flex-start;
  gap: 12px;
  cursor: pointer;
  padding: 14px 16px;
  background: linear-gradient(180deg, rgba(247, 250, 252, 0.98), rgba(241, 246, 252, 0.98));
  border: 1px solid rgba(184, 200, 216, 0.8);
  border-radius: var(--radius);
  transition: all 0.2s;
}

.checkbox-label:hover {
  border-color: var(--accent);
}

.checkbox {
  width: 20px;
  height: 20px;
  border: 2px solid var(--border);
  border-radius: 5px;
  display: flex;
  align-items: center;
  justify-content: center;
  transition: all 0.2s;
  flex-shrink: 0;
  margin-top: 1px;
}

.checkbox.checked {
  background: linear-gradient(135deg, var(--primary), var(--primary-light));
  border-color: var(--primary);
  color: white;
}

.checkbox-text {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.checkbox-title {
  font-weight: 600;
  font-size: 0.9em;
  color: var(--text-primary);
}

.checkbox-desc {
  font-size: 0.8em;
  color: var(--text-secondary);
}

/* === Extraction Modes === */
.extraction-modes {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.extraction-option {
  display: flex;
  align-items: center;
  gap: 14px;
  padding: 14px 16px;
  border: 1px solid rgba(184, 200, 216, 0.9);
  border-radius: var(--radius);
  cursor: pointer;
  transition: all 0.2s;
  background: linear-gradient(180deg, rgba(255,255,255,0.98), rgba(244, 249, 253, 0.96));
  box-shadow: inset 0 1px 0 rgba(255,255,255,0.72);
}

.extraction-option:hover {
  border-color: rgba(31, 141, 184, 0.65);
  transform: translateY(-1px);
}

.extraction-option.active {
  border-color: rgba(20, 58, 102, 0.9);
  background: linear-gradient(135deg, rgba(20, 58, 102, 0.08), rgba(31, 141, 184, 0.06));
}

.mode-icon {
  width: 40px;
  height: 40px;
  background: linear-gradient(135deg, rgba(20, 58, 102, 0.1), rgba(31, 141, 184, 0.12));
  border-radius: 10px;
  display: flex;
  align-items: center;
  justify-content: center;
  color: var(--primary);
  flex-shrink: 0;
}

.extraction-option.active .mode-icon {
  background: rgba(20, 58, 102, 0.12);
  color: var(--primary);
}

.mode-info {
  flex: 1;
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.mode-name {
  font-weight: 600;
  font-size: 0.9em;
  color: var(--text-primary);
}

.mode-desc {
  font-size: 0.78em;
  color: var(--text-secondary);
}

.mode-check {
  width: 22px;
  height: 22px;
  background: linear-gradient(135deg, var(--primary), var(--primary-light));
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  color: white;
}

/* === Upload Submit Button === */
.action-section {
  padding-top: 4px;
}

.upload-submit-btn {
  width: 100%;
  padding: 14px;
  background: linear-gradient(135deg, var(--primary) 0%, var(--primary-light) 55%, var(--accent) 100%);
  color: white;
  border: none;
  border-radius: var(--radius);
  font-size: 0.95em;
  font-weight: 600;
  cursor: pointer;
  transition: all 0.2s;
}

.upload-submit-btn:hover:not(:disabled) {
  background: linear-gradient(135deg, #112b4c 0%, #1e4f8f 55%, #157395 100%);
  transform: translateY(-1px);
  box-shadow: 0 10px 24px -14px rgba(20, 58, 102, 0.6);
}

.upload-submit-btn:disabled {
  background: #cbd5e1;
  cursor: not-allowed;
  transform: none;
  box-shadow: none;
}

.btn-content {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
}

.btn-spinner {
  width: 16px;
  height: 16px;
  border: 2px solid rgba(255,255,255,0.3);
  border-top-color: white;
  border-radius: 50%;
  animation: spin 0.8s linear infinite;
}

@keyframes spin {
  to { transform: rotate(360deg); }
}

/* === Result Card === */
.result-card {
  overflow: hidden;
  border-radius: var(--radius-lg);
}

.result-card.success {
  border-color: rgba(20, 131, 93, 0.3);
  background: linear-gradient(135deg, rgba(20, 131, 93, 0.03) 0%, transparent 100%);
}

.result-card.failed {
  border-color: rgba(193, 54, 58, 0.3);
  background: linear-gradient(135deg, rgba(193, 54, 58, 0.03) 0%, transparent 100%);
}

.result-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 16px 20px;
  border-bottom: 1px solid var(--border);
}

.result-status {
  display: flex;
  align-items: center;
  gap: 12px;
}

.status-icon {
  width: 36px;
  height: 36px;
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
}

.status-icon.success {
  background: #d1fae5;
  color: #14835d;
}

.status-icon.failed {
  background: #fee2e2;
  color: #c1363a;
}

.status-title {
  font-weight: 600;
  font-size: 0.95em;
  color: var(--text-primary);
  display: block;
}

.status-file {
  font-size: 0.8em;
  color: var(--text-muted);
  display: block;
  margin-top: 2px;
}

.result-close {
  width: 30px;
  height: 30px;
  background: none;
  border: none;
  border-radius: 6px;
  cursor: pointer;
  color: var(--text-muted);
  display: flex;
  align-items: center;
  justify-content: center;
  transition: all 0.2s;
}

.result-close:hover {
  background: linear-gradient(180deg, rgba(247, 250, 252, 0.96), rgba(241, 246, 252, 0.98));
  color: var(--text-primary);
}

.result-body {
  padding: 20px;
}

.result-grid {
  display: flex;
  gap: 24px;
  flex-wrap: wrap;
}

.result-item {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.result-label {
  font-size: 0.72em;
  color: var(--text-muted);
  text-transform: uppercase;
  letter-spacing: 0.04em;
}

.result-value {
  font-size: 0.88em;
  font-weight: 500;
  color: var(--text-primary);
}

.result-badge {
  font-size: 0.78em;
  font-weight: 600;
  padding: 2px 8px;
  border-radius: 4px;
  align-self: flex-start;
}

.result-badge.success {
  background: #d1fae5;
  color: #059669;
}

.result-badge.neutral {
  background: var(--bg-page);
  color: var(--text-secondary);
}

.content-preview {
  margin-top: 16px;
  border: 1px solid rgba(184, 200, 216, 0.8);
  border-radius: var(--radius);
  overflow: hidden;
}

.preview-header {
  display: flex;
  align-items: center;
  gap: 7px;
  padding: 10px 14px;
  background: linear-gradient(180deg, rgba(247, 250, 252, 0.96), rgba(241, 246, 252, 0.98));
  border-bottom: 1px solid rgba(184, 200, 216, 0.8);
  font-size: 0.8em;
  font-weight: 600;
  color: var(--text-secondary);
}

.preview-content {
  padding: 14px;
  font-size: 0.82em;
  color: var(--text-secondary);
  line-height: 1.6;
  max-height: 240px;
  overflow-y: auto;
  background: linear-gradient(180deg, rgba(250, 252, 255, 0.98), rgba(243, 248, 252, 0.98));
  margin: 0;
}

.error-body {
  display: flex;
  align-items: flex-start;
  gap: 10px;
  color: #dc2626;
  font-size: 0.9em;
}

.error-message {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.error-status {
  color: var(--text-muted);
  font-size: 0.82em;
}

.error-preview {
  margin: 0;
  padding: 10px 12px;
  border-radius: 6px;
  border: 1px solid rgba(184, 200, 216, 0.8);
  background: linear-gradient(180deg, rgba(250, 252, 255, 0.98), rgba(243, 248, 252, 0.98));
  color: var(--text-secondary);
  font-size: 0.8em;
  line-height: 1.5;
  white-space: pre-wrap;
  word-break: break-word;
}

/* === Ingest Tasks Card === */
.tasks-card {
  overflow: hidden;
}

.tasks-header,
.files-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 16px 20px;
  border-bottom: 1px solid var(--border);
}

.task-list {
  display: flex;
  flex-direction: column;
  gap: 12px;
  padding: 16px 20px 20px;
}

.task-item {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  padding: 14px 16px;
  border: 1px solid var(--border);
  border-radius: var(--radius);
  background: linear-gradient(180deg, rgba(255,255,255,0.98), rgba(248,251,254,0.98));
}

.task-item.failed {
  border-color: rgba(193, 54, 58, 0.35);
  background: #fff5f5;
}

.task-item.completed {
  border-color: rgba(20, 131, 93, 0.35);
  background: #f0fdf4;
}

.task-main {
  flex: 1;
  min-width: 0;
}

.task-name-row {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
}

.task-file-name {
  color: var(--text-primary);
  font-weight: 600;
  font-size: 0.92em;
  word-break: break-all;
}

.task-status-badge {
  font-size: 0.72em;
  font-weight: 700;
  padding: 2px 8px;
  border-radius: 999px;
  background: #e0f2fe;
  color: #0369a1;
}

.task-status-badge.queued {
  background: #fef3c7;
  color: #92400e;
}

.task-status-badge.completed {
  background: #d1fae5;
  color: #047857;
}

.task-status-badge.failed {
  background: #fee2e2;
  color: #b91c1c;
}

.task-step,
.task-queue {
  margin-top: 4px;
  color: var(--text-secondary);
  font-size: 0.82em;
}

.task-error {
  margin-top: 6px;
  color: var(--error);
  font-size: 0.82em;
  word-break: break-word;
}

.task-progress {
  margin-top: 10px;
  height: 7px;
  border-radius: 999px;
  overflow: hidden;
  background: #e5edf6;
}

.task-progress-bar {
  height: 100%;
  border-radius: inherit;
  background: linear-gradient(90deg, var(--primary-light), var(--accent-light));
  transition: width 0.3s ease;
}

.task-percent {
  color: var(--text-secondary);
  font-weight: 700;
  min-width: 44px;
  text-align: right;
}

.tasks-title,
.files-title {
  display: flex;
  align-items: center;
  gap: 9px;
  color: var(--text-secondary);
}

.tasks-actions {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
  justify-content: flex-end;
}

.files-title h3 {
  font-size: 0.9em;
  font-weight: 600;
  color: var(--text-primary);
}

.file-count-badge {
  padding: 1px 7px;
  background: linear-gradient(135deg, var(--primary), var(--primary-light));
  color: white;
  border-radius: 10px;
  font-size: 0.72em;
  font-weight: 600;
}

.refresh-btn {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 6px 12px;
  background: linear-gradient(180deg, rgba(247, 250, 252, 0.96), rgba(241, 246, 252, 0.98));
  border: 1px solid rgba(184, 200, 216, 0.8);
  border-radius: 6px;
  cursor: pointer;
  font-size: 0.82em;
  font-weight: 500;
  color: var(--text-secondary);
  transition: all 0.2s;
}

.refresh-btn:hover {
  background: white;
  border-color: rgba(31, 141, 184, 0.6);
  color: var(--accent);
}

.clear-history-btn {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 6px 12px;
  background: linear-gradient(180deg, #fff7f7, #fff0f0);
  border: 1px solid rgba(239, 68, 68, 0.18);
  border-radius: 6px;
  cursor: pointer;
  font-size: 0.82em;
  font-weight: 600;
  color: #b91c1c;
  transition: all 0.2s;
}

.clear-history-btn:hover:not(:disabled) {
  background: #fff;
  border-color: rgba(239, 68, 68, 0.42);
  color: #991b1b;
}

.clear-history-btn:disabled {
  opacity: 0.55;
  cursor: not-allowed;
}

.task-notice {
  margin: 0 20px 6px;
  padding: 10px 12px;
  border: 1px solid rgba(31, 141, 184, 0.25);
  border-radius: var(--radius);
  background: rgba(31, 141, 184, 0.06);
  color: var(--text-primary);
  font-size: 0.84em;
}

.files-empty {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 10px;
  padding: 40px;
  color: var(--text-muted);
  font-size: 0.88em;
}

.files-list {
  display: flex;
  flex-direction: column;
}

.file-item {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 14px 20px;
  border-bottom: 1px solid var(--border);
  transition: background 0.15s;
}

.file-item:last-child {
  border-bottom: none;
}

.file-item:hover {
  background: linear-gradient(180deg, rgba(247, 250, 252, 0.96), rgba(241, 246, 252, 0.98));
}

.file-type-icon {
  width: 36px;
  height: 36px;
  background: linear-gradient(135deg, rgba(20, 58, 102, 0.08), rgba(31, 141, 184, 0.1));
  border-radius: 8px;
  display: flex;
  align-items: center;
  justify-content: center;
  color: var(--primary);
  flex-shrink: 0;
}

.file-info {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
}

.file-name {
  font-weight: 500;
  font-size: 0.88em;
  color: var(--text-primary);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.file-meta {
  font-size: 0.75em;
  color: var(--text-muted);
}

.file-badge {
  flex-shrink: 0;
}

.ingest-badge {
  padding: 2px 8px;
  background: #d1fae5;
  color: #14835d;
  border-radius: 4px;
  font-size: 0.72em;
  font-weight: 600;
}
</style>
