<template>
  <div class="skill-management">
    <div class="page-header">
      <h1>🔧 Skill 管理頁面</h1>
      <p class="subtitle">管理與檢視所有可用的 Skills 狀態</p>
    </div>

    <!-- 系統 Stats -->
    <div class="stats-bar">
      <div class="stat-item">
        <span class="stat-value">{{ knowledgeSkills.length }}</span>
        <span class="stat-label">知識庫</span>
      </div>
      <div class="stat-item">
        <span class="stat-value">{{ securitySkills.length }}</span>
        <span class="stat-label">安全</span>
      </div>
      <div class="stat-item">
        <span class="stat-value">{{ systemSkills.length }}</span>
        <span class="stat-label">系統</span>
      </div>
      <div class="stat-item">
        <span class="stat-value">{{ workspaceSkills.length }}</span>
        <span class="stat-label">自訂</span>
      </div>
      <div class="stat-item refresh-btn" @click="loadSkills">
        <span>🔄</span>
        <span class="stat-label">重新整理</span>
      </div>
    </div>

    <!-- 篩選器 -->
    <div class="filter-bar">
      <button 
        :class="{ active: filter === 'all' }" 
        @click="filter = 'all'"
      >全部 ({{ totalSkills }})</button>
      <button 
        :class="{ active: filter === 'knowledge' }" 
        @click="filter = 'knowledge'"
      >🧠 知識庫 ({{ knowledgeSkills.length }})</button>
      <button 
        :class="{ active: filter === 'security' }" 
        @click="filter = 'security'"
      >🔒 安全 ({{ securitySkills.length }})</button>
      <button 
        :class="{ active: filter === 'system' }" 
        @click="filter = 'system'"
      >🖥️ 系統 ({{ systemSkills.length }})</button>
      <button 
        :class="{ active: filter === 'workspace' }" 
        @click="filter = 'workspace'"
      >📦 自訂 ({{ workspaceSkills.length }})</button>
    </div>

    <!-- Skills 列表 -->
    <div class="skills-list">
      
      <!-- 知識庫 Skills -->
      <div v-if="filter === 'all' || filter === 'knowledge'" class="skill-section">
        <h2>🧠 知識庫 Skills</h2>
        <p class="section-desc">與知識庫系統相關的 Skills，用於文件攝入、查詢、萃取等</p>
        <div class="skills-grid">
          <div 
            v-for="skill in knowledgeSkills" 
            :key="skill.name"
            class="skill-card knowledge"
            @click="openSkillEditor(skill)"
          >
            <div class="skill-header">
              <span class="skill-icon">🧠</span>
              <span class="skill-name">{{ skill.name }}</span>
            </div>
            <div class="skill-description">{{ skill.description }}</div>
            <div class="skill-path">{{ skill.path }}</div>
            <div class="skill-meta">
              <span v-if="skill.files" class="meta-tag">📁 {{ skill.files }} 個檔案</span>
              <span v-if="skill.hasReferences" class="meta-tag">📚 含參考資料</span>
            </div>
            <div class="skill-status">
              <span class="status-dot active"></span>
              <span>可編輯</span>
            </div>
          </div>
        </div>
        <div v-if="knowledgeSkills.length === 0" class="empty-state">
          <span>尚無知識庫相關 Skills</span>
        </div>
      </div>

      <!-- 安全 Skills -->
      <div v-if="filter === 'all' || filter === 'security'" class="skill-section">
        <h2>🔒 安全 Skills</h2>
        <p class="section-desc">與系統安全、監控、診斷相關的 Skills</p>
        <div class="skills-grid">
          <div 
            v-for="skill in securitySkills" 
            :key="skill.name"
            class="skill-card security"
            :class="{ 'readonly': skill.type === 'system' }"
            @click="openSkillEditor(skill)"
          >
            <div class="skill-header">
              <span class="skill-icon">🔒</span>
              <span class="skill-name">{{ skill.name }}</span>
            </div>
            <div class="skill-description">{{ skill.description }}</div>
            <div class="skill-path">{{ skill.path }}</div>
            <div class="skill-meta">
              <span v-if="skill.files" class="meta-tag">📁 {{ skill.files }} 個檔案</span>
              <span v-if="skill.hasReferences" class="meta-tag">📚 含參考資料</span>
            </div>
            <div class="skill-status">
              <span v-if="skill.type === 'system'" class="status-dot inactive"></span>
              <span v-else class="status-dot active"></span>
              <span>{{ skill.type === 'system' ? '唯讀' : '可編輯' }}</span>
            </div>
          </div>
        </div>
        <div v-if="securitySkills.length === 0" class="empty-state">
          <span>尚無安全相關 Skills</span>
        </div>
      </div>

      <!-- 系統 Skills -->
      <div v-if="filter === 'all' || filter === 'system'" class="skill-section">
        <h2>🖥️ 系統 Skills</h2>
        <p class="section-desc">OpenClaw 內建的系統 Skills</p>
        <div class="skills-grid">
          <div 
            v-for="skill in systemSkills" 
            :key="skill.name"
            class="skill-card system"
            @click="openSkillEditor(skill)"
          >
            <div class="skill-header">
              <span class="skill-icon">⚙️</span>
              <span class="skill-name">{{ skill.name }}</span>
            </div>
            <div class="skill-description">{{ skill.description }}</div>
            <div class="skill-path">{{ skill.path }}</div>
            <div class="skill-status">
              <span class="status-dot inactive"></span>
              <span>唯讀</span>
            </div>
          </div>
        </div>
      </div>

      <!-- 自訂 Skills -->
      <div v-if="filter === 'all' || filter === 'workspace'" class="skill-section">
        <h2>📦 自訂 Skills (Workspace)</h2>
        <p class="section-desc">位於 workspace/skills 目錄下的自訂 Skills</p>
        <div class="skills-grid">
          <div 
            v-for="skill in workspaceSkills" 
            :key="skill.name"
            class="skill-card workspace"
            @click="openSkillEditor(skill)"
          >
            <div class="skill-header">
              <span class="skill-icon">📦</span>
              <span class="skill-name">{{ skill.name }}</span>
            </div>
            <div class="skill-description">{{ skill.description }}</div>
            <div class="skill-path">{{ skill.path }}</div>
            <div class="skill-meta">
              <span v-if="skill.files" class="meta-tag">📁 {{ skill.files }} 個檔案</span>
              <span v-if="skill.hasReferences" class="meta-tag">📚 含參考資料</span>
            </div>
            <div class="skill-status">
              <span class="status-dot active"></span>
              <span>可編輯</span>
            </div>
          </div>
        </div>
        <div v-if="workspaceSkills.length === 0" class="empty-state">
          <span>尚無自訂 Skills</span>
        </div>
      </div>
    </div>

    <!-- Skill 編輯 Modal -->
    <div v-if="showModal" class="modal-overlay" @click.self="closeModal">
      <div class="modal-content">
        <div class="modal-header">
          <h2>📝 編輯 Skill: {{ editingSkill?.name }}</h2>
          <button class="close-btn" @click="closeModal">✕</button>
        </div>
        
        <!-- 檔案選擇器 -->
        <div class="file-tabs">
          <button 
            v-for="file in skillFiles" 
            :key="file.name"
            :class="{ active: selectedFile === file.name }"
            @click="selectFile(file.name)"
          >
            {{ file.name }}
          </button>
        </div>

        <!-- Monaco Editor 容器 -->
        <div class="editor-container" ref="editorContainer"></div>

        <!-- Modal 操作 -->
        <div class="modal-actions">
          <span class="file-info">檔案: {{ selectedFile }} | {{ editingSkill?.type === 'system' ? '唯讀' : '可編輯' }}</span>
          <div class="action-buttons">
            <button class="btn-cancel" @click="closeModal">取消</button>
            <button 
              v-if="editingSkill?.type !== 'system'" 
              class="btn-save" 
              @click="saveFile"
              :disabled="saving"
            >
              {{ saving ? '儲存中...' : '儲存' }}
            </button>
          </div>
        </div>
      </div>
    </div>

    <!-- API 資訊 -->
    <div class="api-info">
      <h2>🔌 Skill API 端點</h2>
      <table class="api-table">
        <thead>
          <tr>
            <th>端點</th>
            <th>方法</th>
            <th>說明</th>
          </tr>
        </thead>
        <tbody>
          <tr>
            <td><code>/api/skills</code></td>
            <td>GET</td>
            <td>取得所有 Skills 列表</td>
          </tr>
          <tr>
            <td><code>/api/skills/:name/files</code></td>
            <td>GET</td>
            <td>列出 Skill 的所有檔案</td>
          </tr>
          <tr>
            <td><code>/api/skills/:name/files/:filename</code></td>
            <td>GET</td>
            <td>讀取特定檔案內容</td>
          </tr>
          <tr>
            <td><code>/api/skills/:name/files/:filename</code></td>
            <td>PUT</td>
            <td>寫入檔案內容（僅 Workspace）</td>
          </tr>
        </tbody>
      </table>
    </div>
  </div>
</template>

<script>
import { ref, computed, onMounted, nextTick } from 'vue'
import loader from '@monaco-editor/loader'

export default {
  name: 'SkillManagementView',
  setup() {
    const systemSkills = ref([])
    const workspaceSkills = ref([])
    const filter = ref('all')
    const loading = ref(false)

    // Modal 狀態
    const showModal = ref(false)
    const editingSkill = ref(null)
    const skillFiles = ref([])
    const selectedFile = ref('')
    const editorContainer = ref(null)
    let monacoEditor = null
    const saving = ref(false)

    // 知識庫相關 Skills
    const knowledgeSkillNames = ['kb-ingest', 'kb-query', 'kb-extraction-mode', 'confluence', 'session-logs']
    
    // 安全相關 Skills  
    const securitySkillNames = ['healthcheck', 'node-connect', 'skill-creator', 'tmux', 'taskflow', 'taskflow-inbox-triage']

    const knowledgeSkills = computed(() => 
      workspaceSkills.value.filter(s => knowledgeSkillNames.includes(s.name))
    )

    const securitySkills = computed(() => 
      workspaceSkills.value.filter(s => securitySkillNames.includes(s.name)) ||
      systemSkills.value.filter(s => securitySkillNames.includes(s.name))
    )

    const totalSkills = computed(() => 
      systemSkills.value.length + workspaceSkills.value.length
    )

    const loadSkills = async () => {
      loading.value = true
      try {
        const response = await fetch('/api/skills')
        const data = await response.json()
        systemSkills.value = data.system || []
        workspaceSkills.value = data.workspace || []
      } catch (error) {
        console.error('載入 Skills 失敗:', error)
        systemSkills.value = []
        workspaceSkills.value = []
      }
      loading.value = false
    }

    const openSkillEditor = async (skill) => {
      editingSkill.value = skill
      showModal.value = true
      
      try {
        // 取得檔案列表
        const response = await fetch(`/api/skills/${skill.name}/files`)
        const data = await response.json()
        skillFiles.value = data.files || []
        
        if (skillFiles.value.length > 0) {
          await selectFile(skillFiles.value[0].name)
        }
      } catch (error) {
        console.error('取得檔案列表失敗:', error)
        skillFiles.value = []
      }
    }

    const selectFile = async (filename) => {
      selectedFile.value = filename
      
      try {
        const response = await fetch(`/api/skills/${editingSkill.value.name}/files/${filename}`)
        const data = await response.json()
        
        await nextTick()
        
        if (monacoEditor) {
          monacoEditor.dispose()
          monacoEditor = null
        }
        
        // 初始化 Monaco Editor
        loader.init().then((monaco) => {
          if (!editorContainer.value) return
          
          const isReadonly = editingSkill.value?.type === 'system'
          
          monacoEditor = monaco.editor.create(editorContainer.value, {
            value: data.content || '',
            language: filename.endsWith('.md') ? 'markdown' : 'plaintext',
            theme: 'vs-dark',
            readOnly: isReadonly,
            automaticLayout: true,
            minimap: { enabled: false },
            fontSize: 14,
            lineNumbers: 'on',
            scrollBeyondLastLine: false,
            wordWrap: 'on',
            padding: { top: 10 }
          })
        })
      } catch (error) {
        console.error('讀取檔案失敗:', error)
      }
    }

    const saveFile = async () => {
      if (!editingSkill.value || !selectedFile.value || saving.value) return
      if (editingSkill.value.type === 'system') return

      saving.value = true
      
      try {
        const content = monacoEditor?.getValue() || ''
        
        const response = await fetch(`/api/skills/${editingSkill.value.name}/files/${selectedFile.value}`, {
          method: 'PUT',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ content })
        })
        
        if (response.ok) {
          alert('檔案已儲存！')
        } else {
          const error = await response.json()
          alert(`儲存失敗: ${error.detail}`)
        }
      } catch (error) {
        console.error('儲存檔案失敗:', error)
        alert('儲存時發生錯誤')
      }
      
      saving.value = false
    }

    const closeModal = () => {
      showModal.value = false
      editingSkill.value = null
      selectedFile.value = ''
      skillFiles.value = []
      
      if (monacoEditor) {
        monacoEditor.dispose()
        monacoEditor = null
      }
    }

    onMounted(() => {
      loadSkills()
    })

    return {
      systemSkills,
      workspaceSkills,
      knowledgeSkills,
      securitySkills,
      filter,
      loading,
      totalSkills,
      loadSkills,
      openSkillEditor,
      showModal,
      editingSkill,
      skillFiles,
      selectedFile,
      editorContainer,
      selectFile,
      saveFile,
      closeModal,
      saving
    }
  }
}
</script>

<style scoped>
.skill-management {
  padding: 24px;
  max-width: 1400px;
  margin: 0 auto;
}

.page-header {
  margin-bottom: 24px;
}

.page-header h1 {
  font-size: 28px;
  color: #1e3a5f;
  margin-bottom: 8px;
}

.subtitle {
  color: #666;
  font-size: 14px;
}

/* Stats Bar */
.stats-bar {
  display: flex;
  gap: 16px;
  margin-bottom: 24px;
  padding: 16px;
  background: #f8fafc;
  border-radius: 12px;
}

.stat-item {
  display: flex;
  flex-direction: column;
  align-items: center;
  min-width: 80px;
}

.stat-value {
  font-size: 24px;
  font-weight: 700;
  color: #1e3a5f;
}

.stat-label {
  font-size: 12px;
  color: #666;
}

.refresh-btn {
  cursor: pointer;
  padding: 8px 16px;
  border-radius: 8px;
  transition: background 0.2s;
}

.refresh-btn:hover {
  background: #e2e8f0;
}

/* Filter Bar */
.filter-bar {
  display: flex;
  gap: 8px;
  margin-bottom: 24px;
  flex-wrap: wrap;
}

.filter-bar button {
  padding: 8px 16px;
  border: 1px solid #e2e8f0;
  background: white;
  border-radius: 8px;
  cursor: pointer;
  transition: all 0.2s;
}

.filter-bar button.active {
  background: #1e3a5f;
  color: white;
  border-color: #1e3a5f;
}

/* Section Description */
.section-desc {
  color: #666;
  font-size: 13px;
  margin-bottom: 16px;
}

/* Skills List */
.skill-section {
  margin-bottom: 32px;
}

.skill-section h2 {
  font-size: 18px;
  color: #1e3a5f;
  margin-bottom: 8px;
}

.skills-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(300px, 1fr));
  gap: 16px;
}

.skill-card {
  background: white;
  border: 1px solid #e2e8f0;
  border-radius: 12px;
  padding: 16px;
  transition: box-shadow 0.2s, cursor 0.2s;
  cursor: pointer;
}

.skill-card:hover {
  box-shadow: 0 4px 12px rgba(0,0,0,0.1);
}

.skill-card.readonly {
  cursor: default;
  opacity: 0.8;
}

/* Knowledge Base Skill Card */
.skill-card.knowledge {
  border-left: 4px solid #3b82f6;
}

/* Security Skill Card */
.skill-card.security {
  border-left: 4px solid #22c55e;
}

/* System Skill Card */
.skill-card.system {
  border-left: 4px solid #666;
}

/* Workspace Skill Card */
.skill-card.workspace {
  border-left: 4px solid #f59e0b;
}

.skill-header {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 8px;
}

.skill-icon {
  font-size: 20px;
}

.skill-name {
  font-weight: 600;
  color: #1e3a5f;
}

.skill-description {
  font-size: 13px;
  color: #666;
  margin-bottom: 8px;
  min-height: 40px;
}

.skill-path {
  font-size: 11px;
  color: #999;
  font-family: monospace;
  background: #f8fafc;
  padding: 4px 8px;
  border-radius: 4px;
  margin-bottom: 8px;
  word-break: break-all;
}

.skill-meta {
  display: flex;
  gap: 8px;
  margin-bottom: 8px;
}

.meta-tag {
  font-size: 11px;
  background: #e2e8f0;
  padding: 2px 8px;
  border-radius: 4px;
  color: #666;
}

.skill-status {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 12px;
  color: #22c55e;
}

.status-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: #22c55e;
}

.status-dot.inactive {
  background: #999;
}

/* Empty State */
.empty-state {
  padding: 32px;
  text-align: center;
  color: #999;
  background: #f8fafc;
  border-radius: 8px;
}

/* Modal */
.modal-overlay {
  position: fixed;
  top: 0;
  left: 0;
  right: 0;
  bottom: 0;
  background: rgba(0,0,0,0.5);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 1000;
}

.modal-content {
  background: white;
  border-radius: 12px;
  width: 90%;
  max-width: 1000px;
  height: 80vh;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

.modal-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 16px 20px;
  border-bottom: 1px solid #e2e8f0;
  background: #f8fafc;
}

.modal-header h2 {
  font-size: 18px;
  color: #1e3a5f;
  margin: 0;
}

.close-btn {
  background: none;
  border: none;
  font-size: 24px;
  cursor: pointer;
  color: #666;
  padding: 4px 8px;
}

.close-btn:hover {
  color: #1e3a5f;
}

/* File Tabs */
.file-tabs {
  display: flex;
  gap: 4px;
  padding: 8px 20px;
  background: #f1f5f9;
  overflow-x: auto;
}

.file-tabs button {
  padding: 6px 12px;
  border: 1px solid #e2e8f0;
  background: white;
  border-radius: 6px;
  cursor: pointer;
  white-space: nowrap;
  font-size: 13px;
}

.file-tabs button.active {
  background: #1e3a5f;
  color: white;
  border-color: #1e3a5f;
}

/* Editor Container */
.editor-container {
  flex: 1;
  min-height: 400px;
}

/* Modal Actions */
.modal-actions {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 12px 20px;
  border-top: 1px solid #e2e8f0;
  background: #f8fafc;
}

.file-info {
  font-size: 13px;
  color: #666;
}

.action-buttons {
  display: flex;
  gap: 8px;
}

.btn-cancel, .btn-save {
  padding: 8px 16px;
  border-radius: 6px;
  cursor: pointer;
  font-size: 14px;
  font-weight: 500;
}

.btn-cancel {
  background: white;
  border: 1px solid #e2e8f0;
  color: #666;
}

.btn-cancel:hover {
  background: #f1f5f9;
}

.btn-save {
  background: #22c55e;
  border: none;
  color: white;
}

.btn-save:hover {
  background: #16a34a;
}

.btn-save:disabled {
  background: #ccc;
  cursor: not-allowed;
}

/* API Info */
.api-info {
  margin-top: 32px;
  padding: 20px;
  background: #f8fafc;
  border-radius: 12px;
}

.api-info h2 {
  font-size: 16px;
  color: #1e3a5f;
  margin-bottom: 16px;
}

.api-table {
  width: 100%;
  border-collapse: collapse;
}

.api-table th,
.api-table td {
  padding: 12px;
  text-align: left;
  border-bottom: 1px solid #e2e8f0;
}

.api-table th {
  background: #e2e8f0;
  font-weight: 600;
  color: #1e3a5f;
}

.api-table code {
  background: #e2e8f0;
  padding: 2px 8px;
  border-radius: 4px;
  font-size: 13px;
}
</style>
