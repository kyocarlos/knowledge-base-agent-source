<template>
  <div class="chunk-viewer-page">
    <div class="page-header">
      <div>
        <h1 class="page-title">Chunk 檢視</h1>
        <p class="page-desc">查看文件被切成哪些 chunk，並對照原圖資產與文字內容。</p>
      </div>
      <div class="header-actions">
        <button class="refresh-btn" @click="reloadDocuments" :disabled="loadingDocs">
          重新整理文件
        </button>
      </div>
    </div>

    <div class="upload-card">
      <div class="upload-card-header">
        <div>
          <h2>上傳並攝入</h2>
          <p>直接選擇文件，上傳後會進入知識庫，完成後可立即在下方查看 chunk 與原圖引用。</p>
        </div>
      </div>

      <div class="upload-controls">
        <input
          ref="fileInput"
          type="file"
          class="hidden-file-input"
          :accept="acceptedTypes"
          @change="handleFileSelect"
        />
        <button class="primary-btn" @click="triggerFileInput">
          選擇文件
        </button>
        <div v-if="selectedFile" class="selected-file">
          <span class="selected-name">{{ selectedFile.name }}</span>
          <button class="clear-btn" @click="clearSelectedFile">清除</button>
        </div>
        <div v-else class="selected-file placeholder">
          尚未選擇文件
        </div>
      </div>

      <div class="upload-controls">
        <label class="mode-label">
          攝入模式
          <select v-model="uploadMode" class="mode-select">
            <option value="4g5g">4G/5G</option>
            <option value="wifi">WiFi</option>
            <option value="lab">Lab</option>
            <option value="project">Project</option>
            <option value="automation">Automation</option>
            <option value="report">Report</option>
            <option value="simple">Simple</option>
          </select>
        </label>
        <button class="primary-btn" @click="uploadSelectedFile" :disabled="uploading || !selectedFile">
          {{ uploading ? '上傳中...' : '上傳並攝入' }}
        </button>
      </div>

      <div v-if="uploadMessage" class="upload-message" :class="uploadMessageType">
        {{ uploadMessage }}
      </div>
      <pre v-if="uploadPreview" class="upload-preview">{{ uploadPreview }}</pre>
    </div>

    <div class="viewer-layout">
      <aside class="doc-panel">
        <div class="panel-header">
          <h2>文件清單</h2>
          <span class="panel-count">{{ filteredDocuments.length }}</span>
        </div>
        <input
          v-model="docFilter"
          class="search-input"
          type="text"
          placeholder="搜尋文件名稱"
        />
        <div v-if="loadingDocs" class="empty-state">載入文件中...</div>
        <div v-else class="doc-list">
          <button
            v-for="doc in filteredDocuments"
            :key="doc.doc_name"
            class="doc-item"
            :class="{ active: selectedDocName === doc.doc_name }"
            @click="selectDocument(doc.doc_name)"
          >
            <div class="doc-name">{{ doc.doc_name }}</div>
            <div class="doc-meta">
              <span>{{ doc.chunk_count }} chunks</span>
              <span v-if="doc.source_ext">{{ doc.source_ext }}</span>
            </div>
            <div v-if="doc.section_titles?.length" class="doc-sections">
              {{ doc.section_titles.slice(0, 2).join(' / ') }}
            </div>
          </button>
        </div>
      </aside>

      <main class="chunk-panel">
        <div class="panel-header">
          <div>
            <h2>{{ selectedDocName || '請先選擇文件' }}</h2>
            <p class="panel-subtitle">
              {{ selectedDocInfo?.source_path || '選擇左側文件後可檢視 chunk 文字與原圖引用。' }}
            </p>
          </div>
          <button class="refresh-btn" @click="reloadChunks" :disabled="loadingChunks || !selectedDocName">
            重新整理 chunk
          </button>
        </div>

        <div v-if="!selectedDocName" class="empty-state large">
          請先從左側選擇一份文件
        </div>

        <div v-else-if="loadingChunks" class="empty-state large">載入 chunk 中...</div>

        <div v-else class="chunk-content">
          <div class="chunk-summary">
            <div class="summary-item">
              <span class="summary-label">Chunk 數</span>
              <span class="summary-value">{{ chunks.length }}</span>
            </div>
            <div class="summary-item">
              <span class="summary-label">原圖引用</span>
              <span class="summary-value">{{ totalImageRefs }}</span>
            </div>
          </div>

          <div class="version-card">
            <div class="version-header">
              <div>
                <h3>修改歷史</h3>
                <p>每次儲存前都會先備份來源檔，必要時可直接回復上一版。</p>
              </div>
              <button class="refresh-btn" @click="reloadVersions" :disabled="loadingVersions || !selectedDocName">
                重新整理版本
              </button>
            </div>
            <div v-if="loadingVersions" class="empty-state compact">載入版本中...</div>
            <div v-else-if="versions.length === 0" class="empty-state compact">目前尚無修改歷史</div>
            <div v-else class="version-list">
              <div v-for="version in versions" :key="version.version_id" class="version-item">
                <div class="version-info">
                  <div class="version-id">{{ version.version_id }}</div>
                  <div class="version-meta">
                    <span>{{ version.created_at }}</span>
                    <span v-if="version.reason">{{ version.reason }}</span>
                    <span v-if="version.chunk_index !== undefined">chunk #{{ version.chunk_index }}</span>
                  </div>
                  <div class="version-preview" v-if="version.old_content_preview">
                    {{ version.old_content_preview.slice(0, 160) }}
                  </div>
                </div>
                <button class="secondary-btn" @click="restoreVersion(version.version_id)" :disabled="restoringVersion">
                  回復
                </button>
              </div>
            </div>
          </div>

          <div v-if="chunkActionMessage" class="upload-message" :class="chunkActionType">
            {{ chunkActionMessage }}
          </div>

          <div v-if="chunks.length === 0" class="empty-state large">
            這份文件目前沒有 chunk 資料
          </div>

          <div v-else class="chunk-list">
            <section
              v-for="chunk in chunks"
              :key="chunk.id"
              class="chunk-card"
            >
              <div class="chunk-card-header">
                <div>
                  <div class="chunk-title">Chunk #{{ chunk.chunk_index }}</div>
                  <div class="chunk-subtitle">
                    <span v-if="chunk.section_title">{{ chunk.section_title }}</span>
                    <span v-if="chunk.source_path">{{ chunk.source_path }}</span>
                  </div>
                </div>
                <div class="chunk-actions">
                  <div class="chunk-badges">
                    <span class="badge" v-if="chunk.image_refs?.length">{{ chunk.image_refs.length }} 張圖</span>
                    <span class="badge muted" v-else>無原圖引用</span>
                  </div>
                  <button
                    v-if="editingChunkId !== chunk.id"
                    class="secondary-btn"
                    @click="startEditChunk(chunk)"
                  >
                    編輯
                  </button>
                  <div v-else class="chunk-edit-actions">
                    <button class="secondary-btn" @click="cancelEditChunk">取消</button>
                    <button class="primary-btn compact" @click="saveChunkEdit" :disabled="savingChunk">
                      {{ savingChunk ? '儲存中...' : '儲存並重攝入' }}
                    </button>
                  </div>
                </div>
              </div>

              <div class="chunk-body">
                <div class="chunk-text-block">
                  <div class="chunk-section-header">
                    <div class="chunk-section-label">Chunk 文字</div>
                    <div class="chunk-view-toggle">
                      <button
                        class="toggle-btn"
                        :class="{ active: chunkViewMode === 'beautified' }"
                        @click="chunkViewMode = 'beautified'"
                      >
                        美化版
                      </button>
                      <button
                        class="toggle-btn"
                        :class="{ active: chunkViewMode === 'raw' }"
                        @click="chunkViewMode = 'raw'"
                      >
                        原始版
                      </button>
                    </div>
                  </div>
                  <textarea
                    v-if="editingChunkId === chunk.id"
                    v-model="draftChunkContent"
                    class="chunk-editor"
                    spellcheck="false"
                  />
                  <div
                    v-else-if="chunkViewMode === 'beautified'"
                    class="chunk-rendered markdown-body"
                    v-html="renderChunkHtml(chunk)"
                  />
                  <pre v-else class="chunk-text">{{ sanitizeChunkContent(chunk.content) }}</pre>
                </div>

                <div class="chunk-image-block" v-if="chunk.image_refs?.length">
                  <div class="chunk-section-label">原圖</div>
                  <div class="image-grid">
                    <a
                      v-for="ref in chunk.image_refs"
                      :key="ref"
                      class="image-card"
                      :href="getChunkAssetUrl(ref)"
                      target="_blank"
                      rel="noreferrer"
                    >
                      <img :src="getChunkAssetUrl(ref)" :alt="ref" />
                      <span>{{ ref }}</span>
                    </a>
                  </div>
                </div>
              </div>
            </section>
          </div>
        </div>
      </main>
    </div>
  </div>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import { marked } from 'marked'
import {
  getChunkAssetUrl,
  getChunkDocumentChunks,
  getChunkDocumentVersions,
  getChunkDocuments,
  getUploadTaskStatus,
  restoreChunkDocumentVersion,
  updateChunkDocumentChunk
} from '../services/admin'

const fileInput = ref(null)
const selectedFile = ref(null)
const uploadMode = ref('report')
const uploading = ref(false)
const uploadMessage = ref('')
const uploadMessageType = ref('info')
const uploadPreview = ref('')
const acceptedTypes = '.pdf,.docx,.xlsx,.pptx,.txt,.md,.html,.csv,.json,.xml,.epub,.msg,.png,.jpg,.jpeg,.gif'
const documents = ref([])
const selectedDocName = ref('')
const selectedDocInfo = ref(null)
const chunks = ref([])
const loadingDocs = ref(false)
const loadingChunks = ref(false)
const loadingVersions = ref(false)
const versions = ref([])
const docFilter = ref('')
const editingChunkId = ref('')
const draftChunkContent = ref('')
const savingChunk = ref(false)
const restoringVersion = ref(false)
const chunkActionMessage = ref('')
const chunkActionType = ref('info')
const chunkViewMode = ref('beautified')

const filteredDocuments = computed(() => {
  const keyword = docFilter.value.trim().toLowerCase()
  if (!keyword) return documents.value
  return documents.value.filter((doc) => {
    return (doc.doc_name || '').toLowerCase().includes(keyword)
  })
})

const totalImageRefs = computed(() => {
  return chunks.value.reduce((total, chunk) => total + (chunk.image_refs?.length || 0), 0)
})

function triggerFileInput() {
  if (fileInput.value) {
    fileInput.value.click()
  }
}

function handleFileSelect(event) {
  const file = event.target.files?.[0]
  if (!file) return
  selectedFile.value = file
  uploadMessage.value = ''
}

function clearSelectedFile() {
  selectedFile.value = null
  if (fileInput.value) {
    fileInput.value.value = ''
  }
}

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms))
}

function sanitizeChunkContent(content) {
  if (!content) return ''
  return String(content)
    .replace(/!\[[^\]]*\]\(data:image\/[^)]+\)/gi, '')
    .replace(/<img[^>]+src=["']data:image\/[^"']+["'][^>]*>/gi, '')
    .replace(/data:image\/[a-zA-Z0-9.+-]+;base64,[A-Za-z0-9+/=\s]+/gi, '')
    .replace(/\n{3,}/g, '\n\n')
    .trim()
}

function renderChunkHtml(chunk) {
  const sanitized = sanitizeChunkContent(chunk?.content || '')
  if (!sanitized) return '<div class="chunk-empty">沒有可顯示的內容</div>'
  try {
    return marked.parse(sanitized, { gfm: true, breaks: false })
  } catch {
    return `<pre class="chunk-text">${sanitized}</pre>`
  }
}

async function reloadDocuments() {
  loadingDocs.value = true
  try {
    const data = await getChunkDocuments()
    documents.value = data.documents || []
    if (!selectedDocName.value && documents.value.length > 0) {
      await selectDocument(documents.value[0].doc_name)
    } else if (selectedDocName.value) {
      const matched = documents.value.find((doc) => doc.doc_name === selectedDocName.value)
      selectedDocInfo.value = matched || null
    }
  } finally {
    loadingDocs.value = false
  }
}

async function selectDocument(docName) {
  if (!docName) return
  selectedDocName.value = docName
  selectedDocInfo.value = documents.value.find((doc) => doc.doc_name === docName) || null
  cancelEditChunk()
  chunkActionMessage.value = ''
  await Promise.all([reloadChunks(), reloadVersions()])
}

async function reloadChunks() {
  if (!selectedDocName.value) return
  loadingChunks.value = true
  try {
    const data = await getChunkDocumentChunks(selectedDocName.value)
    chunks.value = data.chunks || []
  } finally {
    loadingChunks.value = false
  }
}

async function reloadVersions() {
  if (!selectedDocName.value) return
  loadingVersions.value = true
  try {
    const data = await getChunkDocumentVersions(selectedDocName.value)
    versions.value = data.versions || []
  } finally {
    loadingVersions.value = false
  }
}

async function pollUploadTask(taskId) {
  const maxAttempts = 180
  let attempts = 0

  while (attempts < maxAttempts) {
    const state = await getUploadTaskStatus(taskId)

    if (state?.status === 'completed') {
      return state
    }

    if (state?.status === 'failed') {
      throw new Error(state.error || '攝入任務失敗')
    }

    uploadMessageType.value = 'info'
    uploadMessage.value = state?.status === 'queued'
      ? `攝入任務已提交，排隊中（${state.queue_position || 0}）...`
      : '攝入任務處理中...'
    await sleep(1000)
    attempts++
  }

  throw new Error('攝入任務逾時，請稍後再試')
}

function startEditChunk(chunk) {
  editingChunkId.value = chunk.id
  draftChunkContent.value = chunk.content || ''
  chunkActionMessage.value = ''
}

function cancelEditChunk() {
  editingChunkId.value = ''
  draftChunkContent.value = ''
}

async function saveChunkEdit() {
  if (!selectedDocName.value || !editingChunkId.value) return
  savingChunk.value = true
  chunkActionMessage.value = ''
  chunkActionType.value = 'info'
  try {
    const result = await updateChunkDocumentChunk(
      selectedDocName.value,
      editingChunkId.value,
      draftChunkContent.value
    )
    chunkActionType.value = result.status === 'success' ? 'success' : 'error'
    chunkActionMessage.value = result.status === 'success'
      ? `已儲存修改，並重新攝入完成。備份版本：${result.backup?.version_id || 'unknown'}`
      : `儲存完成，但重新攝入結果為：${result.status || 'unknown'}`
    if (result.status === 'success') {
      window.alert(`已完成儲存並重新攝入。\n備份版本：${result.backup?.version_id || 'unknown'}`)
    }
    cancelEditChunk()
    await reloadDocuments()
    await reloadChunks()
    await reloadVersions()
  } catch (e) {
    chunkActionType.value = 'error'
    chunkActionMessage.value = `儲存失敗：${e.message || '未知錯誤'}`
  } finally {
    savingChunk.value = false
  }
}

async function restoreVersion(versionId) {
  if (!selectedDocName.value || !versionId) return
  if (!window.confirm(`要回復版本 ${versionId} 嗎？這會重新攝入文件。`)) return
  restoringVersion.value = true
  chunkActionMessage.value = ''
  chunkActionType.value = 'info'
  try {
    const result = await restoreChunkDocumentVersion(selectedDocName.value, versionId)
    chunkActionType.value = result.status === 'success' ? 'success' : 'error'
    chunkActionMessage.value = result.status === 'success'
      ? `已回復版本 ${versionId}，並重新攝入完成。`
      : `回復完成，但重新攝入結果為：${result.status || 'unknown'}`
    if (result.status === 'success') {
      window.alert(`已完成回復版本 ${versionId} 並重新攝入。`)
    }
    cancelEditChunk()
    await reloadDocuments()
    await reloadChunks()
    await reloadVersions()
  } catch (e) {
    chunkActionType.value = 'error'
    chunkActionMessage.value = `回復失敗：${e.message || '未知錯誤'}`
  } finally {
    restoringVersion.value = false
  }
}

async function uploadSelectedFile() {
  if (!selectedFile.value) return
  uploading.value = true
  uploadMessage.value = ''
  uploadMessageType.value = 'info'
  uploadPreview.value = ''

  try {
    const formData = new FormData()
    formData.append('file', selectedFile.value)

    const response = await fetch(`/api/upload/ingest?extraction_mode=${encodeURIComponent(uploadMode.value)}`, {
      method: 'POST',
      body: formData
    })

    const bodyText = await response.text()
    let parsedBody = null

    if (bodyText) {
      try {
        parsedBody = JSON.parse(bodyText)
      } catch {
        parsedBody = {
          status: 'failed',
          error: `伺服器回應不是 JSON：${response.status} ${response.statusText}`,
          response_preview: bodyText.slice(0, 1500)
        }
      }
    } else {
      parsedBody = {
        status: 'failed',
        error: `伺服器回應空白：${response.status} ${response.statusText}`
      }
    }

    if (!response.ok) {
      uploadMessageType.value = 'error'
      uploadMessage.value = parsedBody?.error || `HTTP ${response.status} ${response.statusText}`
      uploadPreview.value = parsedBody?.response_preview || bodyText.slice(0, 1500)
      return
    }

    const data = parsedBody || {}
    uploadMessageType.value = 'success'
    uploadMessage.value = data.status === 'submitted'
      ? `已提交攝入任務：${data.file_name || selectedFile.value.name}`
      : `上傳成功：${data.file_name || selectedFile.value.name}`
    uploadPreview.value = ''

    if (data.status === 'submitted' && data.task_id) {
      const state = await pollUploadTask(data.task_id)
      uploadMessageType.value = 'success'
      uploadMessage.value = `已完成攝入：${data.file_name || selectedFile.value.name}`
      window.alert(`已完成攝入：${data.file_name || selectedFile.value.name}`)
      if (state?.status === 'completed') {
        await reloadDocuments()
      }
    } else {
      window.alert(`上傳並攝入完成：${data.file_name || selectedFile.value.name}`)
    }

    clearSelectedFile()
    await reloadDocuments()
  } catch (e) {
    uploadMessageType.value = 'error'
    uploadMessage.value = `上傳失敗：${e.message || '未知錯誤'}`
    uploadPreview.value = ''
  } finally {
    uploading.value = false
  }
}

onMounted(async () => {
  await reloadDocuments()
})
</script>

<style scoped>
.chunk-viewer-page {
  display: flex;
  flex-direction: column;
  gap: 20px;
}

.page-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 16px;
}

.page-title {
  font-size: 1.6rem;
  font-weight: 700;
}

.page-desc {
  color: var(--text-secondary);
  margin-top: 6px;
}

.upload-card {
  background: var(--bg-card);
  border: 1px solid var(--border);
  border-radius: var(--radius-lg);
  box-shadow: var(--shadow-sm);
  padding: 16px;
  display: flex;
  flex-direction: column;
  gap: 14px;
}

.upload-card-header h2 {
  font-size: 1rem;
  margin: 0;
}

.upload-card-header p {
  color: var(--text-secondary);
  margin-top: 4px;
  font-size: 0.9rem;
}

.upload-controls {
  display: flex;
  align-items: center;
  gap: 12px;
  flex-wrap: wrap;
}

.hidden-file-input {
  display: none;
}

.selected-file {
  display: inline-flex;
  align-items: center;
  gap: 10px;
  padding: 10px 12px;
  border: 1px solid var(--border);
  border-radius: 12px;
  background: var(--bg-surface);
}

.selected-file.placeholder {
  color: var(--text-secondary);
}

.selected-name {
  font-weight: 600;
  word-break: break-all;
}

.mode-label {
  display: inline-flex;
  align-items: center;
  gap: 10px;
  font-weight: 600;
}

.mode-select {
  min-width: 160px;
  border: 1px solid var(--border);
  border-radius: 10px;
  padding: 8px 10px;
  background: white;
}

.upload-message {
  border-radius: 12px;
  padding: 10px 12px;
  font-size: 0.92rem;
}

.upload-message.info {
  background: rgba(31, 141, 184, 0.08);
  color: var(--accent);
}

.upload-message.success {
  background: rgba(20, 131, 93, 0.08);
  color: var(--success);
}

.upload-message.error {
  background: rgba(193, 54, 58, 0.08);
  color: var(--error);
}

.upload-preview {
  margin: 0;
  padding: 12px;
  border-radius: 12px;
  background: #f8fafc;
  border: 1px solid var(--border);
  color: var(--text-secondary);
  font-size: 0.82rem;
  white-space: pre-wrap;
  word-break: break-word;
  max-height: 240px;
  overflow: auto;
}

.viewer-layout {
  display: grid;
  grid-template-columns: 320px 1fr;
  gap: 16px;
  min-height: 72vh;
}

.doc-panel,
.chunk-panel {
  background: var(--bg-card);
  border: 1px solid var(--border);
  border-radius: var(--radius-lg);
  box-shadow: var(--shadow-sm);
  display: flex;
  flex-direction: column;
  min-height: 0;
}

.doc-panel {
  padding: 16px;
}

.chunk-panel {
  padding: 16px;
}

.panel-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 12px;
  margin-bottom: 12px;
}

.panel-header h2 {
  font-size: 1.05rem;
  margin: 0;
}

.panel-subtitle {
  color: var(--text-secondary);
  font-size: 0.9rem;
  margin-top: 4px;
  word-break: break-all;
}

.panel-count {
  background: rgba(31, 141, 184, 0.1);
  color: var(--accent);
  padding: 4px 10px;
  border-radius: 999px;
  font-size: 0.85rem;
  font-weight: 600;
}

.search-input {
  width: 100%;
  border: 1px solid var(--border);
  border-radius: 10px;
  padding: 10px 12px;
  margin-bottom: 12px;
  background: var(--bg-surface);
}

.doc-list {
  display: flex;
  flex-direction: column;
  gap: 10px;
  overflow: auto;
  min-height: 0;
}

.doc-item {
  text-align: left;
  border: 1px solid var(--border);
  background: var(--bg-surface);
  border-radius: 12px;
  padding: 12px;
  cursor: pointer;
}

.doc-item.active {
  border-color: var(--accent);
  box-shadow: 0 0 0 1px rgba(31, 141, 184, 0.15);
}

.doc-name {
  font-weight: 700;
  margin-bottom: 6px;
}

.doc-meta,
.doc-sections {
  color: var(--text-secondary);
  font-size: 0.85rem;
}

.doc-meta {
  display: flex;
  gap: 12px;
  flex-wrap: wrap;
}

.empty-state {
  display: flex;
  align-items: center;
  justify-content: center;
  min-height: 120px;
  color: var(--text-secondary);
  border: 1px dashed var(--border);
  border-radius: 12px;
  background: var(--bg-surface);
}

.empty-state.large {
  min-height: 280px;
}

.chunk-content {
  display: flex;
  flex-direction: column;
  gap: 16px;
  min-height: 0;
}

.chunk-summary {
  display: flex;
  gap: 12px;
}

.summary-item {
  min-width: 140px;
  padding: 12px 14px;
  border: 1px solid var(--border);
  border-radius: 12px;
  background: var(--bg-surface);
}

.summary-label {
  display: block;
  color: var(--text-secondary);
  font-size: 0.85rem;
}

.summary-value {
  display: block;
  margin-top: 6px;
  font-size: 1.1rem;
  font-weight: 700;
}

.version-card {
  border: 1px solid var(--border);
  border-radius: 14px;
  background: var(--bg-surface);
  padding: 14px;
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.version-header {
  display: flex;
  justify-content: space-between;
  gap: 12px;
  align-items: center;
}

.version-header h3 {
  margin: 0;
  font-size: 0.98rem;
}

.version-header p {
  margin-top: 4px;
  color: var(--text-secondary);
  font-size: 0.84rem;
}

.empty-state.compact {
  min-height: 72px;
}

.version-list {
  display: flex;
  flex-direction: column;
  gap: 10px;
  max-height: 220px;
  overflow: auto;
}

.version-item {
  display: flex;
  justify-content: space-between;
  gap: 12px;
  border: 1px solid var(--border);
  border-radius: 12px;
  background: white;
  padding: 10px 12px;
}

.version-info {
  min-width: 0;
  flex: 1;
}

.version-id {
  font-weight: 700;
  font-size: 0.9rem;
  word-break: break-all;
}

.version-meta {
  display: flex;
  flex-wrap: wrap;
  gap: 8px 12px;
  margin-top: 4px;
  color: var(--text-secondary);
  font-size: 0.8rem;
}

.version-preview {
  margin-top: 8px;
  color: var(--text-secondary);
  font-size: 0.82rem;
  line-height: 1.45;
  white-space: pre-wrap;
  word-break: break-word;
}

.chunk-list {
  display: flex;
  flex-direction: column;
  gap: 16px;
  overflow: auto;
  min-height: 0;
}

.chunk-card {
  border: 1px solid var(--border);
  border-radius: 14px;
  padding: 16px;
  background: linear-gradient(180deg, rgba(255,255,255,0.95), rgba(248,251,254,0.98));
}

.chunk-card-header {
  display: flex;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 14px;
}

.chunk-title {
  font-weight: 700;
  font-size: 1rem;
}

.chunk-subtitle {
  margin-top: 4px;
  color: var(--text-secondary);
  font-size: 0.85rem;
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.chunk-badges {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
}

.chunk-actions {
  display: flex;
  gap: 10px;
  align-items: flex-start;
  flex-wrap: wrap;
  justify-content: flex-end;
}

.chunk-edit-actions {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
}

.badge {
  padding: 5px 10px;
  border-radius: 999px;
  background: rgba(20, 131, 93, 0.1);
  color: var(--success);
  font-size: 0.82rem;
  font-weight: 600;
}

.badge.muted {
  background: rgba(134, 148, 166, 0.12);
  color: var(--text-secondary);
}

.chunk-body {
  display: grid;
  grid-template-columns: 1.1fr 0.9fr;
  gap: 14px;
}

.chunk-text-block,
.chunk-image-block {
  min-width: 0;
}

.chunk-view-toggle {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 4px;
  border: 1px solid var(--border);
  border-radius: 999px;
  background: var(--bg-surface);
}

.toggle-btn {
  border: 0;
  border-radius: 999px;
  padding: 6px 12px;
  background: transparent;
  color: var(--text-secondary);
  font-size: 0.82rem;
  cursor: pointer;
  transition: all 0.18s ease;
}

.toggle-btn.active {
  background: var(--accent);
  color: #fff;
  box-shadow: var(--shadow-sm);
}

.chunk-section-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 10px;
}

.chunk-section-label {
  font-size: 0.82rem;
  font-weight: 700;
  color: var(--accent);
  margin-bottom: 0;
}

.chunk-text {
  white-space: pre-wrap;
  word-break: break-word;
  font-family: ui-monospace, SFMono-Regular, SF Mono, Consolas, monospace;
  font-size: 0.84rem;
  line-height: 1.55;
  background: #f9fbfd;
  border: 1px solid var(--border);
  border-radius: 12px;
  padding: 12px;
  max-height: 420px;
  overflow: auto;
}

.chunk-rendered {
  line-height: 1.8;
  color: var(--text-primary);
  font-size: 0.96em;
  background: #fff;
  border: 1px solid var(--border);
  border-radius: 12px;
  padding: 16px;
  max-height: 520px;
  overflow: auto;
}

.chunk-rendered :deep(h1),
.chunk-rendered :deep(h2),
.chunk-rendered :deep(h3),
.chunk-rendered :deep(h4),
.chunk-rendered :deep(h5) {
  margin: 16px 0 10px;
  line-height: 1.35;
  color: var(--text-primary);
}

.chunk-rendered :deep(p) {
  margin: 0 0 10px;
}

.chunk-rendered :deep(ul),
.chunk-rendered :deep(ol) {
  margin: 0 0 12px 20px;
  padding: 0;
}

.chunk-rendered :deep(li) {
  margin: 4px 0;
}

.chunk-rendered :deep(table) {
  width: 100%;
  border-collapse: collapse;
  margin: 16px 0;
  font-size: 0.9em;
}

.chunk-rendered :deep(th),
.chunk-rendered :deep(td) {
  border: 1px solid var(--border);
  padding: 10px 12px;
  vertical-align: top;
}

.chunk-rendered :deep(th) {
  background: #f5f7fb;
  font-weight: 600;
  text-align: left;
}

.chunk-rendered :deep(tr:nth-child(even)) {
  background: #f9fbfd;
}

.chunk-rendered :deep(code) {
  background: #f0f4f8;
  padding: 2px 6px;
  border-radius: 4px;
  font-family: monospace;
}

.chunk-rendered :deep(pre) {
  background: #0f172a;
  color: #e2e8f0;
  padding: 14px;
  border-radius: 10px;
  overflow: auto;
}

.chunk-rendered :deep(blockquote) {
  margin: 12px 0;
  padding: 12px 14px;
  border-left: 4px solid var(--accent);
  background: rgba(31, 141, 184, 0.08);
  color: var(--text-secondary);
}

.chunk-rendered :deep(img) {
  max-width: 100%;
  height: auto;
  border-radius: 10px;
  border: 1px solid var(--border);
  background: #fff;
}

.chunk-rendered :deep(hr) {
  border: 0;
  border-top: 1px solid var(--border);
  margin: 16px 0;
}

.chunk-empty {
  color: var(--text-secondary);
  font-style: italic;
}

.chunk-editor {
  width: 100%;
  min-height: 260px;
  resize: vertical;
  white-space: pre-wrap;
  word-break: break-word;
  font-family: ui-monospace, SFMono-Regular, SF Mono, Consolas, monospace;
  font-size: 0.84rem;
  line-height: 1.55;
  background: #f9fbfd;
  border: 1px solid var(--border);
  border-radius: 12px;
  padding: 12px;
}

.image-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(180px, 1fr));
  gap: 12px;
}

.image-card {
  display: flex;
  flex-direction: column;
  gap: 8px;
  border: 1px solid var(--border);
  border-radius: 12px;
  padding: 10px;
  background: var(--bg-surface);
  text-decoration: none;
  color: inherit;
}

.image-card img {
  width: 100%;
  aspect-ratio: 1 / 1;
  object-fit: contain;
  background: white;
  border-radius: 10px;
  border: 1px solid var(--border);
}

.image-card span {
  font-size: 0.78rem;
  color: var(--text-secondary);
  word-break: break-all;
}

.refresh-btn {
  border: 1px solid var(--border);
  background: white;
  border-radius: 10px;
  padding: 8px 12px;
  cursor: pointer;
}

.secondary-btn {
  border: 1px solid var(--border);
  background: white;
  border-radius: 10px;
  padding: 8px 12px;
  cursor: pointer;
}

.primary-btn.compact {
  padding: 8px 12px;
}

@media (max-width: 1100px) {
  .viewer-layout {
    grid-template-columns: 1fr;
  }

  .chunk-body {
    grid-template-columns: 1fr;
  }

  .version-header,
  .chunk-card-header {
    flex-direction: column;
    align-items: stretch;
  }

  .chunk-actions {
    justify-content: flex-start;
  }
}
</style>
