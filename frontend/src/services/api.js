/**
 * API 服務 - 與 FastAPI 後端溝通
 */

const API_BASE_URL = (import.meta.env.VITE_API_BASE_URL || '').replace(/\/$/, '')

/**
 * 取得 OpenClaw Chat runtime 設定
 * @returns {Promise<object>}
 */
export async function getOpenClawChatConfig() {
  const response = await fetch(`${API_BASE_URL}/api/openclaw/chat-config`)

  if (!response.ok) {
    throw new Error(`HTTP ${response.status}: ${response.statusText}`)
  }

  return response.json()
}

/**
 * 提交搜尋任務
 * @param {string} query - 搜尋查詢
 * @param {string} mode - basic / deep / auto
 * @param {object} options - 其他參數，例如 top_k
 * @returns {Promise<{task_id: string, status: string, message: string}>}
 */
export async function searchApi(query, mode = 'auto', options = {}) {
  const response = await fetch(`${API_BASE_URL}/search`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json'
    },
    body: JSON.stringify({ query, mode, ...options })
  })

  if (!response.ok) {
    throw new Error(`HTTP ${response.status}: ${response.statusText}`)
  }

  return response.json()
}

/**
 * 分析問題類別權重
 * @param {string} query - 使用者問題
 * @param {object} options - 可選參數
 * @param {number} options.timeoutMs - 最長等待毫秒數，預設 2500
 * @returns {Promise<{
 *   query: string,
 *   category_scores: Record<string, number>,
 *   normalized_scores: Record<string, number>,
 *   related_docs: Record<string, string[]>,
 *   top_category?: string,
 *   top_score?: number,
 *   confidence?: number
 * }>}
 */
export async function analyzeQuestionApi(query, options = {}) {
  const timeoutMs = Number.isFinite(options.timeoutMs) ? options.timeoutMs : 2500
  const controller = new AbortController()
  const timeoutId = setTimeout(() => controller.abort(), timeoutMs)

  try {
    const response = await fetch(`${API_BASE_URL}/analyze-question`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json'
      },
      body: JSON.stringify({ query }),
      signal: controller.signal
    })

    if (!response.ok) {
      throw new Error(`HTTP ${response.status}: ${response.statusText}`)
    }

    return response.json()
  } finally {
    clearTimeout(timeoutId)
  }
}

/**
 * 查詢任務狀態
 * @param {string} taskId - 任務 ID
 * @returns {Promise<{task_id, status, answer?, sources?, mode?, error?}>}
 */
export async function getTaskStatus(taskId) {
  // 快取命中時 task_id 是 "cached"
  if (taskId === 'cached') {
    return { status: 'completed' }
  }

  const response = await fetch(`${API_BASE_URL}/tasks/${encodeURIComponent(taskId)}?t=${Date.now()}`, {
    cache: 'no-store',
    headers: {
      'Cache-Control': 'no-cache',
      'Pragma': 'no-cache',
      'Expires': '0'
    }
  })

  if (!response.ok) {
    throw new Error(`HTTP ${response.status}: ${response.statusText}`)
  }

  return response.json()
}

/**
 * 取消任務
 * @param {string} taskId - 任務 ID
 */
export async function cancelTask(taskId) {
  const response = await fetch(`${API_BASE_URL}/tasks/${taskId}`, {
    method: 'DELETE'
  })

  if (!response.ok) {
    throw new Error(`HTTP ${response.status}: ${response.statusText}`)
  }

  return response.json()
}

/**
 * 取得系統統計
 * @returns {Promise<{active_workers: number, queued_tasks: number, cache_enabled: boolean}>}
 */
export async function getSystemStats() {
  const response = await fetch(`${API_BASE_URL}/stats`)

  if (!response.ok) {
    throw new Error(`HTTP ${response.status}: ${response.statusText}`)
  }

  return response.json()
}

/**
 * 健康檢查
 */
export async function healthCheck() {
  const response = await fetch(`${API_BASE_URL}/health`)
  return response.ok
}

/**
 * 清除上傳攝入歷史紀錄
 * @returns {Promise<{status: string, deleted_count: number, deleted_task_ids: string[]}>}
 */
export async function clearUploadTaskHistory() {
  const response = await fetch(`${API_BASE_URL}/api/upload/tasks/clear`, {
    method: 'POST'
  })

  if (!response.ok) {
    throw new Error(`HTTP ${response.status}: ${response.statusText}`)
  }

  return response.json()
}
