<template>
  <div class="chat-page">
    <!-- 頁面標題區 -->
    <div class="page-header">
      <div class="header-content">
        <h1 class="page-title">💬 AI 聊天</h1>
        <p class="page-desc">透過系統助手與 AI 對話</p>
      </div>
      <div class="connection-status">
        <span :class="['status-dot', wsConnected ? 'online' : 'offline']"></span>
        <span class="status-text">{{ wsConnected ? '已連線' : '未連線' }}</span>
        <span class="tailscale-hint">{{ gatewayUrl }}</span>
      </div>
      <div v-if="queuePosition !== null" class="queue-banner">
        排隊中：前方 {{ queueAheadCount() }} 人
        <span v-if="queueEstimatedWaitSeconds !== null" class="queue-banner-hint">
          ，預估 {{ formatQueueWait(queueEstimatedWaitSeconds) }}
        </span>
      </div>
      <div v-if="waitStage" class="stage-banner">
        {{ getWaitStageLabel(waitStage) }}
      </div>
    </div>

    <!-- 聊天區域 -->
    <div class="chat-container">
      <!-- 訊息列表 -->
      <div class="messages-area" ref="messagesArea">
        <div v-if="messages.length === 0" class="empty-state">
          <div class="empty-icon">💬</div>
          <p>開始一段新對話吧！</p>
          <p class="empty-hint">輸入訊息後，AI 會即時回覆</p>
        </div>
        
        <div v-for="(msg, index) in messages" :key="index" :class="['message', msg.role]">
          <div class="message-avatar">
            {{ msg.role === 'user' ? '👤' : '🤖' }}
          </div>
          <div class="message-content">
            <div v-if="msg.sourceLabel" class="message-source-badge">{{ msg.sourceLabel }}</div>
            <div v-if="msg.sourceHint" class="message-source-hint">{{ msg.sourceHint }}</div>
            <div class="message-bubble">{{ msg.content }}</div>
            <div v-if="msg.latencyText" class="message-latency">{{ msg.latencyText }}</div>
            <div class="message-time">{{ formatTime(msg.timestamp) }}</div>
          </div>
        </div>
        
        <div v-if="isLoading" class="message bot">
          <div class="message-avatar">🤖</div>
          <div class="message-content">
            <div class="message-bubble loading">
              <span class="loading-dot">.</span>
              <span class="loading-dot">.</span>
              <span class="loading-dot">.</span>
            </div>
          </div>
        </div>
      </div>

      <!-- 輸入區域 -->
      <div class="input-area">
        <div class="input-wrapper">
          <input
            v-model="inputMessage"
            type="text"
            class="message-input"
            placeholder="輸入訊息..."
            :disabled="!wsConnected || isLoading"
            @keyup.enter="sendMessage"
          />
          <button
            class="send-btn"
            :disabled="!inputMessage.trim() || !wsConnected || isLoading"
            @click="sendMessage"
          >
            <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
              <line x1="22" y1="2" x2="11" y2="13"></line>
              <polygon points="22 2 15 22 11 13 2 9 22 2"></polygon>
            </svg>
          </button>
        </div>
        <div class="input-hint">
          使用同源代理: <code>{{ gatewayUrl }}</code>
        </div>
      </div>
    </div>
  </div>
</template>

<script>
import { getOpenClawChatConfig, searchApi, getTaskStatus } from '../services/api'
import {
  isCompareLikeQuery as sharedIsCompareLikeQuery,
  shouldPreferWifiCompare as sharedShouldPreferWifiCompare,
} from '../../lib/compare-rules.js'

export default {
  name: 'ChatView',
  data() {
    return {
      inputMessage: '',
      messages: [],
      isLoading: false,
      queuePosition: null,
      queueEstimatedWaitSeconds: null,
      waitStage: '',
      waitStageStartedAt: null,
      waitTimings: null,
      chatStartedAt: null,
      pendingAssistantMeta: null,
      pendingKbResult: null,
      pendingDeterministicKbFallback: null,
      pendingAgentBotIndex: null,
      wsConnected: false,
      ws: null,
      sessionKey: '',
      sessionBaseKey: '',
      browserSessionId: '',
      gatewayUrl: '/ws',
      gatewayWsUrl: '',
      authToken: ''
    }
  },
  async mounted() {
    await this.loadRuntimeConfig()
    this.connectWebSocket()
    this.loadHistory()
  },
  beforeUnmount() {
    if (this.ws) {
      this.ws.close()
    }
  },
  methods: {
    async loadRuntimeConfig() {
      try {
        const config = await getOpenClawChatConfig()
        this.gatewayUrl = config.browserWsUrl || '/ws'
        this.gatewayWsUrl = config.gatewayWsUrl || config.browserWsUrl || this.resolveGatewayWsUrl()
        this.sessionBaseKey = config.sessionKey || this.sessionBaseKey || 'fallback'
        this.browserSessionId = this.getOrCreateBrowserSessionId()
        this.sessionKey = this.buildBrowserSessionKey(this.sessionBaseKey)
        this.authToken = config.authToken || this.authToken
      } catch (error) {
        console.error('載入聊天室設定失敗:', error)
        this.gatewayUrl = '/ws'
        this.gatewayWsUrl = this.resolveGatewayWsUrl()
        this.browserSessionId = this.getOrCreateBrowserSessionId()
        this.sessionKey = this.buildBrowserSessionKey(this.sessionBaseKey || 'fallback')
      }
    },

    getOrCreateBrowserSessionId() {
      const storageKey = 'openclaw.chat.browserSessionId'
      try {
        const existing = localStorage.getItem(storageKey)
        if (existing) return existing

        const generated = window.crypto && window.crypto.randomUUID
          ? window.crypto.randomUUID()
          : `browser-${Date.now()}-${Math.random().toString(16).slice(2)}`
        localStorage.setItem(storageKey, generated)
        return generated
      } catch (error) {
        return `browser-${Date.now()}-${Math.random().toString(16).slice(2)}`
      }
    },

    buildBrowserSessionKey(baseSessionKey) {
      const base = (baseSessionKey || '').trim()
      const browserId = this.browserSessionId || this.getOrCreateBrowserSessionId()
      return `${base}__browser__${browserId}`
    },

    resolveGatewayWsUrl() {
      const params = new URLSearchParams(window.location.search)
      const override = import.meta.env.VITE_OPENCLAW_WS_URL || params.get('ws')
      if (override) return this.normalizeWsUrl(override)

      const scheme = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
      return `${scheme}//${window.location.host}/ws`
    },

    normalizeWsUrl(url) {
      if (url.startsWith('ws://') || url.startsWith('wss://')) return url
      if (url.startsWith('/')) {
        const scheme = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
        return `${scheme}//${window.location.host}${url}`
      }
      return url
    },

    extractEventSessionKey(msg) {
      if (!msg || typeof msg !== 'object') return ''
      const payload = msg.payload && typeof msg.payload === 'object' ? msg.payload : {}
      const message = payload.message && typeof payload.message === 'object' ? payload.message : {}
      const meta = message.meta && typeof message.meta === 'object' ? message.meta : {}
      return (
        msg.sessionKey ||
        msg.session_key ||
        payload.sessionKey ||
        payload.session_key ||
        message.sessionKey ||
        message.session_key ||
        meta.sessionKey ||
        meta.session_key ||
        ''
      )
    },

    extractAgentEventText(msg) {
      if (!msg || typeof msg !== 'object') return ''
      const payload = msg.payload && typeof msg.payload === 'object' ? msg.payload : {}
      const data = payload.data && typeof payload.data === 'object' ? payload.data : {}
      return String(data.delta || data.text || '').trim()
    },

    canonicalizeChatSessionKey(value) {
      const text = this.normalizeText(value)
      if (!text) return ''
      if (text.startsWith('agent:')) {
        const parts = text.split(':')
        if (parts.length >= 3) {
          return parts.slice(2).join(':').trim()
        }
      }
      return text
    },

    shouldRenderChatEvent(msg) {
      if (!this.sessionKey) return true
      const eventSessionKey = this.canonicalizeChatSessionKey(this.extractEventSessionKey(msg))
      const currentSessionKey = this.canonicalizeChatSessionKey(this.sessionKey)
      return Boolean(eventSessionKey && eventSessionKey === currentSessionKey)
    },

    replaceMessageAtIndex(index, content) {
      if (!Number.isFinite(index) || index < 0 || index >= this.messages.length) return false
      this.messages.splice(index, 1, {
        ...this.messages[index],
        content,
      })
      return true
    },

    isIncompleteKnowledgeAnswer(text) {
      const value = String(text || '').trim().toLowerCase()
      if (!value) return true
      const hints = [
        '目前知識庫中沒有',
        '知識庫中沒有',
        '查無資料',
        '尚未含第 4 章',
        '尚未找到',
        '還沒有找到',
        '僅包含測試環境配置',
        '僅包含測試設定',
        '僅檢索到一份',
        '沒有關於',
        '未取得任何',
        '資料不足',
        '片段不足',
        '數值表格不足',
        '吞吐量數值表格不足',
        '目前只能確認',
        '無法從提供的結果回答',
        '只找到第 2 章',
        'only section 2',
        'section 2',
        '建議用 `deep`',
        '建議用 deep',
        '建議用 hybrid',
        '找不到 throughput 數值',
        '沒有找到 throughput',
      ]
      return hints.some(hint => value.includes(hint.toLowerCase()))
    },

    isCompareLikeQuery(text) {
      return sharedIsCompareLikeQuery(text)
    },

    shouldPreferWifiCompare(text) {
      return sharedShouldPreferWifiCompare(text, this.isWifiSpecificQuery)
    },

    maybeApplyDeterministicKbFallback() {
      const pending = this.pendingDeterministicKbFallback
      if (!pending || pending.applied) return
      if (!this.pendingKbResult || !Array.isArray(this.pendingKbResult.sources) || this.pendingKbResult.sources.length === 0) return

      const excerpt = this.buildDeterministicKbExcerpt(this.pendingKbResult)
      if (!excerpt) return

      const nextContent = pending.sourceHint
        ? `${pending.baseContent}\n\n${excerpt}\n\n${pending.sourceHint}`
        : `${pending.baseContent}\n\n${excerpt}`
      if (this.replaceMessageAtIndex(pending.messageIndex, nextContent)) {
        pending.applied = true
        this.pendingDeterministicKbFallback = null
        console.log('[ChatView] Applied deterministic KB fallback after KB sources arrived.')
      }
    },

    summarizeContextText(text, limit = 260) {
      const value = String(text || '').trim()
      if (!value) return ''
      return value.length > limit ? `${value.slice(0, limit)}...` : value
    },

    buildDeterministicKbExcerpt(result) {
      if (!result || !Array.isArray(result.sources)) return ''
      const sources = result.sources
      if (sources.length === 0) return ''
      const reportMode = sources.some((source) => this.isReportLikeSource(source))
      let output = '【知識庫原始文件摘錄】\n\n'
      sources.slice(0, reportMode ? 4 : 3).forEach((source, index) => {
        const sourceName = this.getSourceDocName(source) || '未知原始文件'
        const sectionLabel = reportMode ? this.detectReportSectionLabel(source) : ''
        const chunkIndex = Number.isFinite(Number(source?.chunk_index)) ? `chunk ${Number(source.chunk_index)}` : ''
        output += `${index + 1}. 原始文件：${sourceName}${sectionLabel ? `｜${sectionLabel}` : ''}${chunkIndex ? `｜${chunkIndex}` : ''}\n`
        const snippet = this.summarizeContextText(this.getSourceRawText(source), reportMode ? 900 : 260)
        if (snippet) output += `   摘錄：${snippet}\n`
        output += '\n'
      })
      return output.trim()
    },

    connectWebSocket() {
      const wsUrl = this.gatewayWsUrl || this.resolveGatewayWsUrl()
      
      try {
        console.log('Connecting to WebSocket:', wsUrl)
        this.ws = new WebSocket(wsUrl)
        
        this.ws.onopen = () => {
          console.log('WebSocket 連線成功')
          this.wsConnected = true
          
          // 發送 auth
          this.ws.send(JSON.stringify({
            type: 'auth',
            token: this.authToken
          }))
        }
        
        this.ws.onmessage = (event) => {
          this.handleMessage(event.data)
        }
        
        this.ws.onerror = (error) => {
          console.error('WebSocket 錯誤:', error)
          this.waitStage = ''
          this.waitStageStartedAt = null
          this.waitTimings = null
          this.chatStartedAt = null
          this.clearQueueState()
          this.wsConnected = false
        }
        
        this.ws.onclose = () => {
          console.log('WebSocket 連線關閉')
          this.waitStage = ''
          this.waitStageStartedAt = null
          this.waitTimings = null
          this.chatStartedAt = null
          this.clearQueueState()
          this.wsConnected = false
          
          // 自動重連
          setTimeout(() => {
            if (!this.wsConnected) {
              this.connectWebSocket()
            }
          }, 5000)
        }
      } catch (e) {
        console.error('WebSocket 連線失敗:', e)
        this.wsConnected = false
      }
    },
    
    handleMessage(data) {
      try {
        const msg = JSON.parse(data)

        if (msg && msg.type === 'event' && (msg.event === 'chat' || msg.event === 'agent') && !this.shouldRenderChatEvent(msg)) {
          console.warn('忽略其他 session 的 chat event:', this.extractEventSessionKey(msg))
          return
        }
        
        // 處理 chat.history 回應
        if (msg.type === 'chat.history' && msg.messages) {
          this.messages = msg.messages.map(m => ({
            role: m.role === 'assistant' ? 'bot' : m.role,
            content: m.content,
            timestamp: m.timestamp || new Date().toISOString()
          }))
        }

        if (msg.type === 'event' && msg.event === 'chat' && msg.payload && msg.payload.state === 'start') {
          this.setWaitStage('generating')
        }

        if (msg.type === 'event' && msg.event === 'chat.queue') {
          if (!this.waitStage) {
            this.setWaitStage('queue')
          }
          this.setQueueState(msg.payload)
        }

        if (msg.type === 'event' && msg.event === 'agent') {
          const agentPayload = msg.payload || {}
          if (agentPayload.stream === 'lifecycle' && agentPayload.data && agentPayload.data.phase === 'start') {
            this.setWaitStage('generating')
            this.isLoading = true
            this.updateInputState()
          } else if (agentPayload.stream === 'assistant') {
            const assistantText = this.extractAgentEventText(msg)
            if (assistantText) {
              const messageMeta = {
                sourceLabel: this.pendingAssistantMeta?.sourceLabel || '',
                sourceHint: this.pendingAssistantMeta?.sourceHint || '',
                latencyText: '',
              }
              const message = {
                role: 'bot',
                content: assistantText,
                sourceLabel: messageMeta.sourceLabel,
                sourceHint: messageMeta.sourceHint,
                latencyText: messageMeta.latencyText,
                timestamp: new Date().toISOString(),
              }
              if (this.pendingAgentBotIndex === null) {
                this.pendingAgentBotIndex = this.messages.push(message) - 1
              } else {
                this.messages[this.pendingAgentBotIndex] = {
                  ...this.messages[this.pendingAgentBotIndex],
                  ...message,
                }
              }
              this.scrollToBottom()
            }
          } else if (agentPayload.stream === 'lifecycle' && agentPayload.data && agentPayload.data.phase === 'end') {
            const summary = this.finalizeWaitTimings()
            if (this.pendingAgentBotIndex !== null && this.messages[this.pendingAgentBotIndex]) {
              this.messages[this.pendingAgentBotIndex] = {
                ...this.messages[this.pendingAgentBotIndex],
                latencyText: this.buildLatencyText(summary),
                timestamp: new Date().toISOString(),
              }
            }
            this.pendingAssistantMeta = null
            this.pendingAgentBotIndex = null
            this.pendingKbResult = null
            this.clearQueueState()
            this.isLoading = false
            this.updateInputState()
          }
        }
        
        // 處理 chat.send 回應
        if (msg.type === 'chat.send' && msg.content) {
          let content = msg.content
          const isReportLikeQuery = /\b(?:scu|sce)\d+\b/i.test(this.lastQuery || '')
          const hasKbSources = this.pendingKbResult && Array.isArray(this.pendingKbResult.sources) && this.pendingKbResult.sources.length > 0
          if (isReportLikeQuery && this.isIncompleteKnowledgeAnswer(content) && hasKbSources) {
            const excerpt = this.buildDeterministicKbExcerpt(this.pendingKbResult)
            if (excerpt) {
              content = content ? `${content}\n\n${excerpt}` : excerpt
            }
          } else if (isReportLikeQuery && this.isIncompleteKnowledgeAnswer(content)) {
            this.pendingDeterministicKbFallback = {
              messageIndex: this.messages.length,
              baseContent: content,
              sourceHint: this.pendingAssistantMeta?.sourceHint || '',
              applied: false,
            }
          }

          const latencySummary = this.finalizeWaitTimings()
          this.messages.push({
            role: 'bot',
            content,
            sourceLabel: this.pendingAssistantMeta?.sourceLabel || '',
            sourceHint: this.pendingAssistantMeta?.sourceHint || '',
            latencyText: this.buildLatencyText(latencySummary),
            timestamp: new Date().toISOString()
          })
          this.pendingAssistantMeta = null
          this.maybeApplyDeterministicKbFallback()
          this.pendingKbResult = null
          this.clearQueueState()
          this.isLoading = false
          this.scrollToBottom()
        }

        if (msg.type === 'res' && msg.id && msg.id.startsWith('chat-')) {
          if (msg.ok && msg.payload && (msg.payload.status === 'queued' || msg.payload.status === 'waiting')) {
            if (!this.waitStage) {
              this.setWaitStage('queue')
            }
            this.setQueueState(msg.payload)
          } else if (!msg.ok) {
            this.finalizeWaitTimings()
            this.clearQueueState()
            this.isLoading = false
          } else if (msg.content) {
            let content = msg.content
            const isReportLikeQuery = /\b(?:scu|sce)\d+\b/i.test(this.lastQuery || '')
            const hasKbSources = this.pendingKbResult && Array.isArray(this.pendingKbResult.sources) && this.pendingKbResult.sources.length > 0
            if (isReportLikeQuery && this.isIncompleteKnowledgeAnswer(content) && hasKbSources) {
              const excerpt = this.buildDeterministicKbExcerpt(this.pendingKbResult)
              if (excerpt) {
                content = content ? `${content}\n\n${excerpt}` : excerpt
              }
            } else if (isReportLikeQuery && this.isIncompleteKnowledgeAnswer(content)) {
              this.pendingDeterministicKbFallback = {
                messageIndex: this.messages.length,
                baseContent: content,
                sourceHint: this.pendingAssistantMeta?.sourceHint || '',
                applied: false,
              }
            }

            const latencySummary = this.finalizeWaitTimings()
            this.messages.push({
              role: 'bot',
              content,
              sourceLabel: this.pendingAssistantMeta?.sourceLabel || '',
              sourceHint: this.pendingAssistantMeta?.sourceHint || '',
              latencyText: this.buildLatencyText(latencySummary),
              timestamp: new Date().toISOString()
            })
            this.pendingAssistantMeta = null
            this.maybeApplyDeterministicKbFallback()
            this.pendingKbResult = null
            this.clearQueueState()
            this.isLoading = false
            this.scrollToBottom()
          }
        }
        
        // 處理錯誤
        if (msg.error) {
          console.error('聊天錯誤:', msg.error)
          this.pendingAssistantMeta = null
          this.pendingKbResult = null
          this.pendingDeterministicKbFallback = null
          this.pendingAgentBotIndex = null
          this.finalizeWaitTimings()
          this.clearQueueState()
          this.isLoading = false
        }
      } catch (e) {
        console.error('解析訊息失敗:', e)
      }
    },
    
    async sendMessage() {
      if (!this.inputMessage.trim() || this.isLoading || !this.wsConnected) return
      
      const userMessage = this.inputMessage.trim()
      this.inputMessage = ''
      
      this.messages.push({
        role: 'user',
        content: userMessage,
        timestamp: new Date().toISOString()
      })
      
      this.isLoading = true
      this.clearQueueState()
      this.resetWaitTimings()
      this.pendingAssistantMeta = null
      this.pendingDeterministicKbFallback = null
      this.pendingAgentBotIndex = null
      this.chatStartedAt = performance.now()
      this.scrollToBottom()

      if (this.isNeo4jMetaQuestion(userMessage)) {
        this.pendingKbResult = null
        const botMessageIndex = this.messages.push({
          role: 'bot',
          content: '正在查詢 Neo4j 實際連線與資料狀態...',
          sourceLabel: '',
          sourceHint: '',
          latencyText: '',
          timestamp: new Date().toISOString()
        }) - 1

        void this.fetchNeo4jMetaAnswer()
          .then((info) => {
            this.messages[botMessageIndex] = {
              ...this.messages[botMessageIndex],
              content: this.buildNeo4jMetaAnswer(info),
              timestamp: new Date().toISOString()
            }
            this.finalizeWaitTimings()
            this.scrollToBottom()
          })
          .catch((error) => {
            console.error('[Neo4j] Meta query failed:', error)
            this.messages[botMessageIndex] = {
              ...this.messages[botMessageIndex],
              content: `抱歉，無法取得 Neo4j 即時狀態：${error?.message || error}`,
              timestamp: new Date().toISOString()
            }
            this.finalizeWaitTimings()
            this.scrollToBottom()
          })
          .finally(() => {
            this.isLoading = false
            this.clearQueueState()
          })

        return
      }

      if (this.isCompareLikeQuery(userMessage)) {
        try {
          if (this.shouldPreferWifiCompare(userMessage)) {
            const wifiPrepared = await this.prepareWifiSpecificSummary(userMessage)
            const wifiResult = wifiPrepared?.result || null
            this.pendingKbResult = wifiResult

            if (wifiResult && Array.isArray(wifiResult.sources) && wifiResult.sources.length > 0) {
              const sourceHint = this.buildSourceReferenceHint(wifiResult.sources)
              this.pendingAssistantMeta = {
                sourceLabel: 'KB 參考',
                sourceHint,
              }
              this.messages.push({
                role: 'bot',
                content: String(wifiResult.answer || '').trim() || this.formatKnowledgeBaseContext(wifiResult),
                sourceLabel: 'KB 參考',
                sourceHint,
                latencyText: this.buildLatencyText(this.finalizeWaitTimings()),
                timestamp: new Date().toISOString()
              })
              this.pendingAssistantMeta = null
              this.pendingKbResult = null
              this.pendingDeterministicKbFallback = null
              this.pendingAgentBotIndex = null
              this.clearQueueState()
              this.isLoading = false
              this.scrollToBottom()
              return
            }

            const wifiFallbackText = Array.isArray(this.pendingKbResult?.sources) && this.pendingKbResult.sources.length > 0
              ? this.formatKnowledgeBaseContext({
                  answer: '',
                  sources: this.pendingKbResult.sources,
                  citation_distribution: this.pendingKbResult.citation_distribution || null,
                })
              : '目前尚未取得 WiFi 相關資料，請稍後再試。'
            this.messages.push({
              role: 'bot',
              content: wifiFallbackText || '目前尚未取得 WiFi 相關資料，請稍後再試。',
              sourceLabel: 'KB 參考',
              sourceHint: this.buildSourceReferenceHint(this.pendingKbResult?.sources || []),
              latencyText: this.buildLatencyText(this.finalizeWaitTimings()),
              timestamp: new Date().toISOString()
            })
            this.pendingAssistantMeta = null
            this.pendingKbResult = null
            this.pendingDeterministicKbFallback = null
            this.pendingAgentBotIndex = null
            this.clearQueueState()
            this.isLoading = false
            this.scrollToBottom()
            return
          }

          const prepared = await this.prepareReportGraphContext(userMessage)
          const kbResult = prepared?.result || null
          this.pendingKbResult = kbResult

          if (kbResult && Array.isArray(kbResult.sources) && kbResult.sources.length > 0) {
            const sourceHint = this.buildSourceReferenceHint(kbResult.sources)
            this.pendingAssistantMeta = {
              sourceLabel: 'KB 參考',
              sourceHint,
            }
            this.messages.push({
              role: 'bot',
              content: kbResult.answer,
              sourceLabel: 'KB 參考',
              sourceHint,
              latencyText: this.buildLatencyText(this.finalizeWaitTimings()),
              timestamp: new Date().toISOString()
            })
            this.pendingAssistantMeta = null
            this.pendingKbResult = null
            this.pendingDeterministicKbFallback = null
            this.clearQueueState()
            this.isLoading = false
            this.scrollToBottom()
            return
          }
        } catch (error) {
          console.error('[KB] Compare report graph handling failed:', error)
        }
      }

      const reportLikeQuery = this.isReportLikeSource({ source: userMessage }) || /\b(?:scu|sce)\d+\b/i.test(userMessage)
      let preparedKb = { context: '', result: null }

      if (this.isWifiSpecificQuery(userMessage)) {
        try {
          const wifiPrepared = await this.prepareWifiSpecificSummary(userMessage)
          const wifiResult = wifiPrepared?.result || null
          this.pendingKbResult = wifiResult

          if (wifiResult && Array.isArray(wifiResult.sources) && wifiResult.sources.length > 0) {
            this.pendingAssistantMeta = {
              sourceLabel: 'KB 參考',
              sourceHint: this.buildSourceReferenceHint(wifiResult.sources),
            }
          }
          this.maybeApplyDeterministicKbFallback()

          if (wifiResult && this.shouldDirectRenderWifiSummary(userMessage, wifiResult)) {
            const displayText = String(wifiResult.answer || '').trim() || this.formatKnowledgeBaseContext(wifiResult)
            const sourceHint = this.buildSourceReferenceHint(wifiResult.sources || [])
            const latencySummary = this.finalizeWaitTimings()
            this.messages.push({
              role: 'bot',
              content: displayText,
              sourceLabel: 'KB 參考',
              sourceHint,
              latencyText: this.buildLatencyText(latencySummary),
              timestamp: new Date().toISOString()
            })
            this.pendingAssistantMeta = null
            this.pendingKbResult = null
            this.pendingDeterministicKbFallback = null
            this.clearQueueState()
            this.isLoading = false
            this.scrollToBottom()
            return
          }
        } catch (error) {
          console.error('[KB] WiFi-specific summary failed:', error)
        }

        const wifiFallbackText = Array.isArray(this.pendingKbResult?.sources) && this.pendingKbResult.sources.length > 0
          ? this.formatKnowledgeBaseContext({
              answer: this.pendingKbResult ? String(this.pendingKbResult.answer || '') : '',
              sources: this.pendingKbResult.sources,
              citation_distribution: this.pendingKbResult.citation_distribution || null,
            })
          : '目前尚未取得 WiFi 相關資料，請稍後再試。'
        const latencySummary = this.finalizeWaitTimings()
        this.messages.push({
          role: 'bot',
          content: wifiFallbackText || '目前尚未取得 WiFi 相關資料，請稍後再試。',
          sourceLabel: 'KB 參考',
          sourceHint: this.buildSourceReferenceHint(this.pendingKbResult?.sources || []),
          latencyText: this.buildLatencyText(latencySummary),
          timestamp: new Date().toISOString()
        })
        this.pendingAssistantMeta = null
        this.pendingKbResult = null
        this.pendingDeterministicKbFallback = null
        this.clearQueueState()
        this.isLoading = false
        this.scrollToBottom()
        return
      }

      if (reportLikeQuery) {
        try {
          const preparedSummary = await this.prepareGeneralHandoverSummary(userMessage)
          const summaryResult = preparedSummary?.result || null

          if (summaryResult) {
            this.pendingKbResult = summaryResult

            if (Array.isArray(summaryResult.sources) && summaryResult.sources.length > 0) {
              this.pendingAssistantMeta = {
                sourceLabel: 'KB 參考',
                sourceHint: this.buildSourceReferenceHint(summaryResult.sources),
              }
            }
            this.maybeApplyDeterministicKbFallback()

            if (summaryResult.answer) {
              const sourceHint = this.buildSourceReferenceHint(summaryResult.sources || [])
              const latencySummary = this.finalizeWaitTimings()
              this.messages.push({
                role: 'bot',
                content: summaryResult.answer,
                sourceLabel: 'KB 參考',
                sourceHint,
                latencyText: this.buildLatencyText(latencySummary),
                timestamp: new Date().toISOString()
              })
              this.pendingAssistantMeta = null
              this.pendingKbResult = null
              this.pendingDeterministicKbFallback = null
              this.pendingAgentBotIndex = null
              this.clearQueueState()
              this.isLoading = false
              this.scrollToBottom()
              return
            }
          }
        } catch (error) {
          console.error('[KB] General report summary failed:', error)
        }

        try {
          preparedKb = await this.prepareKnowledgeBaseContext(userMessage)
          const kbResult = preparedKb?.result || null
          this.pendingKbResult = kbResult

          if (kbResult && Array.isArray(kbResult.sources) && kbResult.sources.length > 0) {
            this.pendingAssistantMeta = {
              sourceLabel: 'KB 參考',
              sourceHint: this.buildSourceReferenceHint(kbResult.sources),
            }
          }
          this.maybeApplyDeterministicKbFallback()

          if (kbResult && kbResult.mode === 'report_graph' && String(kbResult.answer || '').trim()) {
            const sourceHint = this.buildSourceReferenceHint(kbResult.sources || [])
            const latencySummary = this.finalizeWaitTimings()
            this.messages.push({
              role: 'bot',
              content: kbResult.answer,
              sourceLabel: 'KB 參考',
              sourceHint,
              latencyText: this.buildLatencyText(latencySummary),
              timestamp: new Date().toISOString()
            })
            this.pendingAssistantMeta = null
            this.pendingKbResult = null
            this.pendingDeterministicKbFallback = null
            this.pendingAgentBotIndex = null
            this.clearQueueState()
            this.isLoading = false
            this.scrollToBottom()
            return
          }
          if (kbResult && this.shouldDirectRenderHandoverSummary(userMessage, kbResult)) {
            const sourceHint = this.buildSourceReferenceHint(kbResult.sources || [])
            const latencySummary = this.finalizeWaitTimings()
            this.messages.push({
              role: 'bot',
              content: kbResult.answer,
              sourceLabel: 'KB 參考',
              sourceHint,
              latencyText: this.buildLatencyText(latencySummary),
              timestamp: new Date().toISOString()
            })
            this.pendingAssistantMeta = null
            this.pendingKbResult = null
            this.pendingDeterministicKbFallback = null
            this.clearQueueState()
            this.isLoading = false
            this.scrollToBottom()
            return
          }
          } catch (error) {
            console.error('[KB] Prepare context failed:', error)
          }
      } else {
        void this.prepareKnowledgeBaseContext(userMessage)
          .then((payload) => {
            const kbResult = payload?.result || null
            this.pendingKbResult = kbResult

            if (kbResult && Array.isArray(kbResult.sources) && kbResult.sources.length > 0) {
              this.pendingAssistantMeta = {
                sourceLabel: 'KB 參考',
                sourceHint: this.buildSourceReferenceHint(kbResult.sources),
              }
            }
            this.maybeApplyDeterministicKbFallback()
          })
          .catch((error) => {
            console.error('[KB] Prepare context failed:', error)
          })
      }

      const kbContext = preparedKb && preparedKb.context ? `\n\n${preparedKb.context}` : ''
      const outboundMessage = reportLikeQuery
        ? `【使用者問題】\n${userMessage}\n\n【回答要求】\n這是報告或 case 型問題，請優先根據下方知識庫原始文件作答；若有表格，請逐 case 列出原始數據，不要只回章節摘要或只說資料不足。${kbContext}`
        : `【使用者問題】\n${userMessage}\n\n【回答要求】\n請先直接回答，不要等待知識庫補資料而卡住；若你手上已有可用的知識庫來源，請在回覆末尾附上來源。若後續還會有知識庫補充，前端會另外整理引用資訊。`
      const idempotencyKey = `msg-${Date.now()}-${Math.random().toString(16).slice(2)}`

      // 透過 WebSocket 發送
      if (this.ws && this.ws.readyState === WebSocket.OPEN) {
        this.ws.send(JSON.stringify({
          type: 'chat.send',
          sessionKey: this.sessionKey,
          message: outboundMessage,
          idempotencyKey,
        }))
      } else {
        this.finalizeWaitTimings()
        this.isLoading = false
        this.pendingAssistantMeta = null
        this.pendingDeterministicKbFallback = null
        this.messages.push({
          role: 'bot',
          content: 'WebSocket 未連線，請稍後再試。',
          timestamp: new Date().toISOString()
        })
        this.clearQueueState()
        this.scrollToBottom()
      }
    },
    
    loadHistory() {
      if (this.ws && this.ws.readyState === WebSocket.OPEN) {
        this.ws.send(JSON.stringify({
          type: 'chat.history',
          sessionKey: this.sessionKey,
          limit: 50
        }))
      }
    },
    
    scrollToBottom() {
      setTimeout(() => {
        if (this.$refs.messagesArea) {
          this.$refs.messagesArea.scrollTop = this.$refs.messagesArea.scrollHeight
        }
      }, 100)
    },
    
    formatTime(timestamp) {
      const date = new Date(timestamp)
      return date.toLocaleTimeString('zh-TW', { hour: '2-digit', minute: '2-digit' })
    },

    getSourceRawText(source) {
      return String(source?.content || source?.text || source?.snippet || source?.summary || '').trim()
    },

    getPathBaseName(value) {
      const text = String(value || '').trim()
      if (!text) return ''
      const segments = text.replace(/\\/g, '/').split('/').filter(Boolean)
      return segments.length > 0 ? segments[segments.length - 1] : ''
    },

    getSourceDocName(source) {
      return String(
        source?.citation_source_name ||
        this.getPathBaseName(source?.citation_source_path || source?.source_path || '') ||
        source?.source || source?.doc_name || source?.name || source?.docName || source?.title || ''
      ).trim()
    },

    isNeo4jMetaQuestion(question) {
      const text = String(question || '').trim().toLowerCase()
      if (!text || !text.includes('neo4j')) return false
      return [
        /連線|實例|bolt|browser|版本|哪一個|哪個|連到/i,
        /neo4j.*(有任何的資料|有沒有資料|有資料|沒有資料|資料嗎|內有.*資料)/i,
        /(目前|現在).*neo4j.*(資料|節點|關係)/i,
        /neo4j.*(節點|關係|count|數量)/i,
      ].some((pattern) => pattern.test(text))
    },

    countMapTotal(map) {
      return Object.values(map || {}).reduce((sum, value) => sum + (Number(value) || 0), 0)
    },

    buildNeo4jMetaAnswer(info) {
      const uri = String(info?.uri || 'bolt://neo4j:7687').trim()
      const user = String(info?.user || 'neo4j').trim()
      const database = String(info?.database || 'neo4j').trim()
      const nodes = info?.nodes && typeof info.nodes === 'object' ? info.nodes : {}
      const relationships = info?.relationships && typeof info.relationships === 'object' ? info.relationships : {}
      const totalNodes = this.countMapTotal(nodes)
      const totalRelationships = this.countMapTotal(relationships)
      const connected = String(info?.status || '') === 'ok'

      const nodeRows = Object.keys(nodes).length > 0
        ? Object.entries(nodes).map(([label, count]) => `| ${String(label).replace(/\|/g, '\\|')} | ${Number(count) || 0} |`).join('\n')
        : '| (無) | 0 |'
      const relRows = Object.keys(relationships).length > 0
        ? Object.entries(relationships).map(([type, count]) => `| ${String(type).replace(/\|/g, '\\|')} | ${Number(count) || 0} |`).join('\n')
        : '| (無) | 0 |'

      return [
        '根據目前 KB runtime 的實際查詢結果，Neo4j 連線與資料狀態如下：',
        '',
        '**Neo4j 連線詳細資訊：**',
        '',
        '| 項目 | 值 |',
        '|------|------|',
        '| 連線方式 | Bolt Protocol |',
        `| 連線位址 | ${uri} |`,
        `| 使用者 | ${user} |`,
        `| 資料庫 | ${database} |`,
        `| 狀態 | ${connected ? '已連線' : '未連線'} |`,
        '| 來源 | Docker 內 KB 服務（kb-neo4j） |',
        '',
        '**圖譜統計：**',
        '',
        '| 類型 | 數量 |',
        '|------|------|',
        nodeRows,
        '',
        '| 關係 | 數量 |',
        '|------|------|',
        relRows,
        '',
        `總計 ${totalNodes} 個節點、${totalRelationships} 條關係。`,
        '',
        '這個回答是依目前 `/admin/graph-stats` 的即時回傳組成，不是記憶推測。',
      ].join('\n')
    },

    async fetchNeo4jMetaAnswer() {
      const response = await fetch('/admin/graph-stats')
      if (!response.ok) {
        throw new Error(`HTTP ${response.status}`)
      }
      return response.json()
    },

    isReportLikeSource(source) {
      const haystack = `${this.getSourceDocName(source)}\n${this.getSourceRawText(source)}`.toLowerCase()
      return (
        haystack.includes('sit-tr-sc') ||
        haystack.includes('ota throughput test report') ||
        haystack.includes('performance test') ||
        haystack.includes('test result summary') ||
        haystack.includes('throughput') ||
        haystack.includes('bler') ||
        haystack.includes('rtt') ||
        haystack.includes('latency')
      )
    },

    isHandoverReportSource(source) {
      const haystack = `${this.getSourceDocName(source)}\n${this.getSourceRawText(source)}`.toLowerCase()
      return (
        haystack.includes('handover') &&
        (
          haystack.includes('nr-handover') ||
          haystack.includes('handover test report') ||
          haystack.includes('ng/xn handover test report') ||
          haystack.includes('xn handover') ||
          haystack.includes('ng handover') ||
          haystack.includes('inter handover') ||
          haystack.includes('intra handover')
        )
      )
    },

    isHandoverGeneralQuery(text) {
      const q = this.normalizeText(text).toLowerCase()
      if (!q.includes('handover')) return false
      return ![
        'performance test',
        'throughput',
        'latency',
        'bler',
        'rtt',
        'case',
        'test case',
      ].some((hint) => q.includes(hint))
    },

    shouldDirectRenderHandoverSummary(query, kbResult) {
      const queryText = this.normalizeText(query).toLowerCase()
      if (!queryText) return false
      if ([
        'performance test',
        'throughput',
        'latency',
        'bler',
        'rtt',
        'case',
        'test case',
      ].some((hint) => queryText.includes(hint))) {
        return false
      }

      const sources = Array.isArray(kbResult?.sources) ? kbResult.sources : []
      if (sources.length === 0 || !String(kbResult?.answer || '').trim()) return false
      return sources.every((source) => this.isHandoverReportSource(source))
    },

    isWifiSpecificQuery(text) {
      const queryText = this.normalizeText(text).toLowerCase()
      if (!queryText) return false
      if (/(?:scu|sce)\d+/.test(queryText)) return false
      return [
        'tp-link',
        'tp link',
        'archer',
        'be805',
        'mesh',
        'ssid',
        'router',
        'access point',
        'ap',
        '2.4ghz',
        '5ghz',
        '6ghz',
        'wifi',
        'wi-fi',
        'wifi6',
        'wifi7',
        'wireless',
        'unii',
      ].some((hint) => queryText.includes(hint))
    },

    isWifiSpecificSource(source) {
      const haystack = `${this.getSourceDocName(source)}\n${this.getSourceRawText(source)}`.toLowerCase()
      return (
        haystack.includes('/wifi/') ||
        haystack.includes('type2_wifi') ||
        haystack.includes('tp-link') ||
        haystack.includes('archer') ||
        haystack.includes('be805')
      )
    },

    shouldDirectRenderWifiSummary(query, kbResult) {
      if (!this.isWifiSpecificQuery(query)) return false
      const sources = Array.isArray(kbResult?.sources) ? kbResult.sources : []
      if (sources.length === 0) return false
      return sources.some((source) => this.isWifiSpecificSource(source))
    },

    detectReportSectionLabel(source) {
      const text = this.getSourceRawText(source).toLowerCase()
      if (!text) return ''
      if (text.includes('performance test')) return 'Performance Test'
      if (text.includes('test result summary')) return 'Test Result Summary'
      if (text.includes('reference')) return 'Reference'
      if (text.includes('test environment')) return 'Test Environment'
      if (text.includes('test commands')) return 'Test Commands'
      if (text.includes('preface')) return 'Preface'
      if (text.includes('introduction')) return 'Introduction'
      if (text.includes('screenshot')) return 'Screenshot'
      return ''
    },

    scoreReportSource(source, index = 0) {
      const name = this.getSourceDocName(source).toLowerCase()
      const text = this.getSourceRawText(source).toLowerCase()
      let score = 0

      if (name.includes('sit-tr-sc')) score += 80
      if (name.includes('throughput')) score += 30
      if (text.includes('performance test')) score += 120
      if (text.includes('test result summary')) score += 110
      if (text.includes('reference')) score += 80
      if (text.includes('throughput')) score += 90
      if (text.includes('tcp')) score += 70
      if (text.includes('udp')) score += 60
      if (text.includes('bler')) score += 80
      if (text.includes('rtt')) score += 80
      if (text.includes('latency')) score += 80
      if (text.includes('bandwidth')) score += 30
      if (text.includes('time slot')) score += 30
      if (text.includes('|')) score += 10
      if (/\b\d{2,4}\b/.test(text)) score += 10

      const chunkIndex = Number(source?.chunk_index)
      if (Number.isFinite(chunkIndex)) {
        if (chunkIndex === 7 || chunkIndex === 8) score += 120
        else if (chunkIndex === 5 || chunkIndex === 6) score += 30
        else if (chunkIndex === 4) score += 20
      }

      return score - index * 0.001
    },

    selectKnowledgeBaseSources(result) {
      const sources = Array.isArray(result?.sources)
        ? result.sources.map((source, index) => ({ ...source, __index: index }))
        : []
      if (sources.length === 0) {
        return { sources: [], reportMode: false }
      }

      const reportMode = sources.some((source) => this.isReportLikeSource(source))
      if (!reportMode) {
        return { sources: sources.slice(0, 5), reportMode: false }
      }

      const ranked = [...sources].sort((a, b) => {
        const scoreDiff = this.scoreReportSource(b, b.__index) - this.scoreReportSource(a, a.__index)
        if (Math.abs(scoreDiff) > 1e-6) return scoreDiff
        return a.__index - b.__index
      })

      return {
        sources: ranked.slice(0, 6),
        reportMode: true,
      }
    },

    formatKnowledgeBaseContext(result) {
      if (!result) return ''

      const selected = this.selectKnowledgeBaseSources(result)
      const sources = selected.sources
      if (sources.length === 0 && !result.answer) return ''

      const summarizeContextText = (text, limit = 180) => {
        const value = typeof text === 'string' ? text.trim() : ''
        if (!value) return ''
        return value.length > limit ? `${value.slice(0, limit)}...` : value
      }

      let context = '【知識庫原始文件參考】\n\n'
      if (selected.reportMode) {
        context += '文件類型：Report（測試報告）\n'
        context += '優先內容：請優先閱讀性能測試、結果摘要與參考章節中的數值與表格。\n'
        context += '回答要求：若來源中有 TCP/UDP throughput、RTT、BLER、Latency 等表格，請直接列出原始數值，不要只回章節大綱或文件摘要。\n\n'
      }

      if (sources.length > 0) {
        context += '相關原始文件：\n'
        sources.slice(0, 6).forEach((source) => {
          const sourceName = this.getSourceDocName(source) || '未知原始文件'
          const sectionLabel = selected.reportMode ? this.detectReportSectionLabel(source) : ''
          const chunkIndex = Number.isFinite(Number(source?.chunk_index)) ? `｜chunk ${source.chunk_index}` : ''
          context += `* ${sourceName}${sectionLabel ? `｜${sectionLabel}` : ''}${chunkIndex}\n`
          const snippet = summarizeContextText(this.getSourceRawText(source), selected.reportMode ? 2600 : 180)
          if (snippet) {
            context += selected.reportMode ? `  原文：${snippet}\n` : `  摘要：${snippet}\n`
          }
        })
        context += '\n'
      }

      if (selected.reportMode) {
        context += '補充說明：請把表格中的數字、單位、平均值、峰值與測試條件盡量原樣保留；若同一文件含多個 Test Case，請優先列出與使用者問題最相關的測試案例。\n\n'
      }

      context += '內容摘要：\n'
      context += result.answer
        ? result.answer
        : '本次搜尋未產生摘要，但已取得知識庫原始文件內容，請優先根據來源內容回答；若是測試報告，請直接輸出數值表格或條列重點，不要只寫章節大綱。'
      return context
    },

    getSourcePipelineLabel(source) {
      const mode = String(source?.mode || source?.type || '').toLowerCase()
      if (mode === 'vector' || mode === 'cleaned' || mode === 'doc' || mode === 'file') return 'Qdrant 文件片段'
      if (mode === 'graph') return 'Neo4j 圖譜關聯'
      return 'KB 匯整來源'
    },

    buildSourceReferenceHint(sources) {
      const items = Array.isArray(sources) ? sources : []
      if (items.length === 0) return '已整合知識庫來源'

      const unique = [...new Map(items.map((source) => {
        const name = source?.source || source?.doc_name || source?.name || '未知來源'
        return [`${this.getSourcePipelineLabel(source)}|${name}`, source]
      })).values()]

      const lines = unique.slice(0, 3).map((source) => {
        const name = source?.source || source?.doc_name || source?.name || '未知來源'
        return `- ${this.getSourcePipelineLabel(source)}：${name}`
      })

      if (unique.length > 3) {
        lines.push(`- 另有 ${unique.length - 3} 筆來源`)
      }

      return ['已整合知識庫來源', ...lines].join('\n')
    },

    async waitForSearchResult(taskId, timeoutMs = 15000) {
      if (taskId === 'cached') {
        return { status: 'completed', task_id: 'cached' }
      }
      const maxAttempts = Math.max(1, Math.ceil(timeoutMs / 1000))
      let attempts = 0

      while (attempts < maxAttempts) {
        try {
          const status = await getTaskStatus(taskId)

          if (status.status === 'completed') {
            return status
          }

          if (status.status === 'failed') {
            return null
          }

          await new Promise((resolve) => setTimeout(resolve, 1000))
          attempts++
        } catch (error) {
          await new Promise((resolve) => setTimeout(resolve, 2000))
          attempts += 2
        }
      }

      return null
    },

    async prepareKnowledgeBaseContext(query) {
      try {
        const searchData = await searchApi(query, 'vector', { top_k: 5, sources_only: true })

        if (!searchData.task_id) {
          return { context: '', result: null }
        }

        const result = await this.waitForSearchResult(searchData.task_id, 360000)
        if (result && (result.answer || (Array.isArray(result.sources) && result.sources.length > 0))) {
          const context = this.formatKnowledgeBaseContext(result)
          if (context) {
            console.log('[KB] Context prepared:', context.slice(0, 100) + '...')
          }
          return { context, result }
        }
      } catch (error) {
        console.error('[KB] Search failed:', error)
      }

      return { context: '', result: null }
    },

    async prepareGeneralHandoverSummary(query) {
      try {
        const searchData = await searchApi(query, 'basic', { top_k: 6 })

        if (!searchData.task_id) {
          return { result: null }
        }

        const result = await this.waitForSearchResult(searchData.task_id, 240000)
        if (result && String(result.answer || '').trim()) {
          return { result }
        }
      } catch (error) {
        console.error('[KB] General handover summary search failed:', error)
      }

      return { result: null }
    },

    async prepareWifiSpecificSummary(query) {
      try {
        const searchData = await searchApi(query, 'auto', { top_k: 6, sources_only: true })

        if (!searchData.task_id) {
          return { result: null }
        }

        const result = await this.waitForSearchResult(searchData.task_id, 240000)
        if (result && Array.isArray(result.sources) && result.sources.length > 0) {
          return { result }
        }
      } catch (error) {
        console.error('[KB] WiFi-specific summary search failed:', error)
      }

      return { result: null }
    },

    async prepareReportGraphContext(query) {
      try {
        const searchData = await searchApi(query, 'auto', { top_k: 12, sources_only: true })

        if (!searchData.task_id) {
          return { result: null }
        }

        const result = await this.waitForSearchResult(searchData.task_id, 360000)
        if (result && result.mode === 'report_graph' && String(result.answer || '').trim()) {
          return { result }
        }
      } catch (error) {
        console.error('[KB] Report graph search failed:', error)
      }

      return { result: null }
    },

    queueAheadCount() {
      if (this.queuePosition === null) return 0
      const parsed = Number(this.queuePosition)
      if (!Number.isFinite(parsed)) return 0
      return Math.max(0, parsed - 1)
    },

    formatQueueWait(seconds) {
      const parsed = Number(seconds)
      if (!Number.isFinite(parsed) || parsed <= 0) {
        return '即將處理'
      }
      if (parsed < 60) {
        return `${Math.max(1, Math.round(parsed))} 秒`
      }
      const minutes = Math.ceil(parsed / 60)
      return `${minutes} 分鐘`
    },

    setQueueState(payload) {
      const data = payload && typeof payload === 'object' ? payload : {}
      const position = Number(data.queuePosition ?? data.queue_position)
      const waitSeconds = Number(data.estimatedWaitSeconds ?? data.estimated_wait_seconds)
      this.queuePosition = Number.isFinite(position) ? position : null
      this.queueEstimatedWaitSeconds = Number.isFinite(waitSeconds) ? waitSeconds : null
    },

    clearQueueState() {
      this.queuePosition = null
      this.queueEstimatedWaitSeconds = null
    },

    resetWaitTimings() {
      this.waitStage = ''
      this.waitStageStartedAt = null
      this.waitTimings = {
        queueWaitMs: null,
        generationMs: null,
        firstAssistantMs: null,
        totalMs: null,
      }
      this.chatStartedAt = null
    },

    getWaitStageLabel(stage) {
      switch (stage) {
        case 'kb-search':
          return 'KB 查詢中'
        case 'queue':
          return '排隊中'
        case 'generating':
          return '生成回覆中'
        default:
          return ''
      }
    },

    recordWaitStage() {
      if (!this.waitStage || this.waitStageStartedAt === null || !this.waitTimings) return
      const elapsed = Math.max(0, performance.now() - this.waitStageStartedAt)
      if (this.waitStage === 'queue') {
        this.waitTimings.queueWaitMs = elapsed
      } else if (this.waitStage === 'generating') {
        this.waitTimings.generationMs = elapsed
      }
    },

    snapshotWaitTimings() {
      this.recordWaitStage()
      if (this.chatStartedAt !== null && this.waitTimings) {
        this.waitTimings.totalMs = Math.max(0, performance.now() - this.chatStartedAt)
        return { ...this.waitTimings }
      }
      return null
    },

    formatLatencyMs(ms) {
      if (!Number.isFinite(ms) || ms < 0) return ''
      if (ms < 1000) return `${Math.round(ms)}ms`
      return `${(ms / 1000).toFixed(ms < 10000 ? 1 : 0)}s`
    },

    buildLatencyText(summary) {
      if (!summary) return ''
      const pieces = []
      if (Number.isFinite(summary.totalMs)) {
        pieces.push(`回覆耗時 ${this.formatLatencyMs(summary.totalMs)}`)
      }
      if (Number.isFinite(summary.firstAssistantMs)) {
        pieces.push(`首字 ${this.formatLatencyMs(summary.firstAssistantMs)}`)
      }
      return pieces.join('，')
    },

    setWaitStage(stage) {
      if (this.waitStage === stage) return
      this.recordWaitStage()
      this.waitStage = stage
      this.waitStageStartedAt = stage ? performance.now() : null
    },

    finalizeWaitTimings() {
      const summary = this.snapshotWaitTimings()
      if (summary) {
        console.log('[ChatView] wait timing summary:', {
          queueWaitMs: Math.round(summary.queueWaitMs || 0),
          generationMs: Math.round(summary.generationMs || 0),
          firstAssistantMs: Math.round(summary.firstAssistantMs || 0),
          totalMs: Math.round(summary.totalMs || 0),
        })
      }
      this.waitStage = ''
      this.waitStageStartedAt = null
      this.waitTimings = null
      this.chatStartedAt = null
      return summary
    }
  }
}
</script>

<style scoped>
.chat-page {
  min-height: 100vh;
  padding: 20px;
  background:
    radial-gradient(circle at top left, rgba(31, 141, 184, 0.08), transparent 30%),
    linear-gradient(180deg, #f7fafc 0%, #eef3f8 42%, #e8eef5 100%);
}

.page-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 16px;
  margin-bottom: 20px;
  padding: 18px 20px;
  border-radius: 18px;
  background: linear-gradient(135deg, rgba(11, 36, 64, 0.98), rgba(20, 58, 102, 0.92) 46%, rgba(31, 141, 184, 0.9));
  box-shadow: 0 16px 40px -26px rgba(15, 23, 42, 0.5);
  position: relative;
  overflow: hidden;
}

.page-header::after {
  content: '';
  position: absolute;
  inset: 0;
  background: linear-gradient(90deg, transparent, rgba(255,255,255,0.08), transparent);
  pointer-events: none;
}

.header-content {
  color: white;
}

.page-title {
  font-size: 28px;
  font-weight: 700;
  margin: 0 0 5px 0;
  letter-spacing: -0.02em;
}

.page-desc {
  margin: 0;
  opacity: 0.82;
}

.connection-status {
  display: flex;
  align-items: center;
  gap: 8px;
  background: rgba(255,255,255,0.12);
  padding: 8px 16px;
  border-radius: 20px;
  color: white;
  border: 1px solid rgba(255,255,255,0.1);
  backdrop-filter: blur(10px);
  position: relative;
  z-index: 1;
}

.status-dot {
  width: 10px;
  height: 10px;
  border-radius: 50%;
}

.status-dot.online {
  background: #4ade80;
  animation: pulse 2s infinite;
}

.status-dot.offline {
  background: #f87171;
}

@keyframes pulse {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.5; }
}

.tailscale-hint {
  font-size: 12px;
  opacity: 0.8;
  margin-left: 8px;
}

.queue-banner {
  margin-top: 10px;
  padding: 8px 12px;
  border-radius: 999px;
  background: rgba(250, 204, 21, 0.12);
  border: 1px solid rgba(250, 204, 21, 0.28);
  color: #7c5d00;
  font-size: 13px;
  display: inline-flex;
  align-items: center;
  gap: 4px;
}

.queue-banner-hint {
  opacity: 0.82;
}

.stage-banner {
  margin-top: 8px;
  padding: 8px 12px;
  border-radius: 999px;
  background: rgba(59, 130, 246, 0.12);
  border: 1px solid rgba(59, 130, 246, 0.25);
  color: #1d4ed8;
  font-size: 13px;
  display: inline-flex;
  align-items: center;
  gap: 4px;
}

.chat-container {
  background: linear-gradient(180deg, rgba(255,255,255,0.98), rgba(248, 251, 254, 0.98));
  border-radius: 18px;
  box-shadow: 0 18px 48px -28px rgba(15, 23, 42, 0.42);
  overflow: hidden;
  height: calc(100vh - 140px);
  display: flex;
  flex-direction: column;
  border: 1px solid rgba(184, 200, 216, 0.85);
}

.messages-area {
  flex: 1;
  overflow-y: auto;
  padding: 20px;
  display: flex;
  flex-direction: column;
  gap: 16px;
  background:
    linear-gradient(180deg, rgba(248, 251, 254, 0.95), rgba(243, 247, 251, 0.95));
}

.empty-state {
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  color: #6b7280;
}

.empty-icon {
  font-size: 48px;
  margin-bottom: 16px;
}

.empty-hint {
  font-size: 14px;
  color: #9ca3af;
}

.message {
  display: flex;
  gap: 12px;
  max-width: 80%;
}

.message.user {
  flex-direction: row-reverse;
  margin-left: auto;
}

.message-avatar {
  font-size: 24px;
  width: 40px;
  height: 40px;
  display: flex;
  align-items: center;
  justify-content: center;
  background: linear-gradient(135deg, rgba(20, 58, 102, 0.1), rgba(31, 141, 184, 0.12));
  color: var(--primary);
  border: 1px solid rgba(184, 200, 216, 0.75);
  border-radius: 50%;
  flex-shrink: 0;
}

.message.bot .message-avatar {
  background: linear-gradient(135deg, var(--primary), var(--primary-light));
  color: white;
  border-color: transparent;
}

.message-content {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.message.user .message-content {
  align-items: flex-end;
}

.message-bubble {
  padding: 12px 16px;
  border-radius: 16px;
  line-height: 1.5;
  white-space: pre-wrap;
  word-break: break-word;
  border: 1px solid rgba(184, 200, 216, 0.8);
  box-shadow: 0 8px 18px -14px rgba(15, 23, 42, 0.4);
}

.message.user .message-bubble {
  background: linear-gradient(135deg, var(--primary), var(--primary-light));
  color: white;
  border-bottom-right-radius: 4px;
  border-color: transparent;
}

.message.bot .message-bubble {
  background: linear-gradient(180deg, #ffffff, #f8fbfe);
  color: #1f2937;
  border-bottom-left-radius: 4px;
}

.message-source-badge {
  align-self: flex-start;
  display: inline-flex;
  align-items: center;
  padding: 4px 10px;
  border-radius: 999px;
  font-size: 12px;
  font-weight: 700;
  letter-spacing: 0.02em;
  background: rgba(20, 58, 102, 0.12);
  color: #143a66;
  border: 1px solid rgba(20, 58, 102, 0.16);
}

.message-source-hint {
  align-self: flex-start;
  font-size: 12px;
  line-height: 1.4;
  color: #64748b;
  white-space: pre-wrap;
}

.message-latency {
  align-self: flex-start;
  font-size: 11px;
  line-height: 1.4;
  color: #64748b;
}

.message-time {
  font-size: 11px;
  color: #9ca3af;
}

.loading-dots {
  display: flex;
  gap: 4px;
}

.loading-dot {
  animation: bounce 1.4s infinite;
}

.loading-dot:nth-child(2) {
  animation-delay: 0.2s;
}

.loading-dot:nth-child(3) {
  animation-delay: 0.4s;
}

@keyframes bounce {
  0%, 60%, 100% { transform: translateY(0); }
  30% { transform: translateY(-4px); }
}

.input-area {
  padding: 20px;
  background: linear-gradient(180deg, rgba(247, 250, 252, 0.98), rgba(241, 246, 252, 0.98));
  border-top: 1px solid rgba(184, 200, 216, 0.8);
}

.input-wrapper {
  display: flex;
  gap: 12px;
  align-items: center;
}

.message-input {
  flex: 1;
  padding: 12px 16px;
  border: 1px solid rgba(184, 200, 216, 0.95);
  background: white;
  border-radius: 24px;
  font-size: 16px;
  outline: none;
  transition: border-color 0.2s, box-shadow 0.2s;
}

.message-input:focus {
  border-color: rgba(31, 141, 184, 0.8);
  box-shadow: 0 0 0 4px rgba(31, 141, 184, 0.08);
}

.send-btn {
  width: 48px;
  height: 48px;
  border: none;
  background: linear-gradient(135deg, var(--primary), var(--primary-light) 55%, var(--accent));
  color: white;
  border-radius: 50%;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  transition: transform 0.2s, box-shadow 0.2s;
  box-shadow: 0 10px 24px -14px rgba(20, 58, 102, 0.6);
}

.send-btn:hover:not(:disabled) {
  transform: translateY(-1px);
}

.send-btn:disabled {
  background: #d1d5db;
  cursor: not-allowed;
  box-shadow: none;
}

.input-hint {
  margin-top: 8px;
  font-size: 12px;
  color: #6b7280;
  text-align: center;
}

.input-hint code {
  background: #e5e7eb;
  padding: 2px 6px;
  border-radius: 4px;
  font-family: monospace;
}
</style>
