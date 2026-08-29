/**
 * 管理 API 服務
 */

const API_BASE_URL = (import.meta.env.VITE_API_BASE_URL || '').replace(/\/$/, '')

/**
 * 取得 Neo4j 圖譜統計
 */
export async function getGraphStats() {
  const response = await fetch(`${API_BASE_URL}/admin/graph-stats`)
  if (!response.ok) throw new Error(`HTTP ${response.status}`)
  return response.json()
}

/**
 * 清除所有快取
 */
export async function clearAllCache() {
  const response = await fetch(`${API_BASE_URL}/admin/cache`, {
    method: 'DELETE'
  })
  if (!response.ok) throw new Error(`HTTP ${response.status}`)
  return response.json()
}

/**
 * 重新整理 Schema
 */
export async function refreshSchema() {
  const response = await fetch(`${API_BASE_URL}/admin/schema/refresh`, {
    method: 'POST'
  })
  if (!response.ok) throw new Error(`HTTP ${response.status}`)
  return response.json()
}

/**
 * 取得系統日誌
 */
export async function getLogs(lines = 100) {
  const response = await fetch(`${API_BASE_URL}/admin/logs?lines=${lines}`)
  if (!response.ok) throw new Error(`HTTP ${response.status}`)
  return response.json()
}

/**
 * 取得 Celery Beat 排程設定
 */
export async function getBeatSchedule() {
  const response = await fetch(`${API_BASE_URL}/admin/beat-schedule`)
  if (!response.ok) throw new Error(`HTTP ${response.status}`)
  return response.json()
}

/**
 * 更新 Celery Beat 排程設定
 */
export async function updateBeatSchedule(data) {
  const response = await fetch(`${API_BASE_URL}/admin/beat-schedule`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data)
  })
  if (!response.ok) throw new Error(`HTTP ${response.status}`)
  return response.json()
}

/**
 * 手動觸發一次掃描
 */
export async function triggerBeatSchedule() {
  const response = await fetch(`${API_BASE_URL}/admin/beat-schedule/trigger`, {
    method: 'POST'
  })
  if (!response.ok) throw new Error(`HTTP ${response.status}`)
  return response.json()
}

/**
 * 取得 Chunk Viewer 文件清單
 */
export async function getChunkDocuments() {
  const response = await fetch(`${API_BASE_URL}/admin/chunk-documents`)
  if (!response.ok) throw new Error(`HTTP ${response.status}`)
  return response.json()
}

/**
 * 取得指定文件的 chunk 明細
 */
export async function getChunkDocumentChunks(docName) {
  const response = await fetch(`${API_BASE_URL}/admin/chunk-documents/${encodeURIComponent(docName)}/chunks`)
  if (!response.ok) throw new Error(`HTTP ${response.status}`)
  return response.json()
}

/**
 * 取得指定文件的版本歷史
 */
export async function getChunkDocumentVersions(docName) {
  const response = await fetch(`${API_BASE_URL}/admin/chunk-documents/${encodeURIComponent(docName)}/versions`)
  if (!response.ok) throw new Error(`HTTP ${response.status}`)
  return response.json()
}

/**
 * 取得上傳攝入任務狀態
 */
export async function getUploadTaskStatus(taskId) {
  const response = await fetch(`${API_BASE_URL}/api/upload/tasks/${encodeURIComponent(taskId)}`)
  if (!response.ok) throw new Error(`HTTP ${response.status}`)
  return response.json()
}

/**
 * 修改指定 chunk 文字並重新攝入
 */
export async function updateChunkDocumentChunk(docName, chunkId, content) {
  const response = await fetch(`${API_BASE_URL}/admin/chunk-documents/${encodeURIComponent(docName)}/chunks/${encodeURIComponent(chunkId)}/edit`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ content })
  })
  if (!response.ok) throw new Error(`HTTP ${response.status}`)
  return response.json()
}

/**
 * 回復指定文件的歷史版本
 */
export async function restoreChunkDocumentVersion(docName, versionId) {
  const response = await fetch(`${API_BASE_URL}/admin/chunk-documents/${encodeURIComponent(docName)}/versions/${encodeURIComponent(versionId)}/restore`, {
    method: 'POST'
  })
  if (!response.ok) throw new Error(`HTTP ${response.status}`)
  return response.json()
}

/**
 * 取得 chunk 資產檔案 URL
 */
export function getChunkAssetUrl(assetPath) {
  if (!assetPath) return ''
  const normalized = String(assetPath).replace(/^asset:\/\//, '').replace(/^\/+/, '')
  return `${API_BASE_URL}/admin/chunk-assets/${normalized}`
}
