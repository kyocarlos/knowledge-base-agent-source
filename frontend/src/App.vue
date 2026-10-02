<template>
  <div id="app">
    <!-- 頂部導航列 -->
    <nav class="navbar">
      <div class="navbar-brand">
        <div class="brand-icon">
          <svg width="28" height="28" viewBox="0 0 28 28" fill="none">
            <rect width="28" height="28" rx="6" fill="#0ea5e9"/>
            <path d="M7 8h14M7 14h10M7 20h12" stroke="white" stroke-width="2" stroke-linecap="round"/>
            <circle cx="21" cy="20" r="3" fill="#fbbf24"/>
          </svg>
        </div>
        <div class="brand-text">
          <span class="brand-name">DA40 知識庫</span>
          <span class="brand-sub">Knowledge Base System</span>
        </div>
      </div>
      <div class="navbar-links">
        <router-link to="/" class="nav-link">
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <circle cx="11" cy="11" r="8"/><path d="m21 21-4.35-4.35"/>
          </svg>
          <span>智慧搜尋</span>
        </router-link>
        <router-link to="/upload" class="nav-link">
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="17,8 12,3 7,8"/><line x1="12" y1="3" x2="12" y2="15"/>
          </svg>
          <span>檔案上傳</span>
        </router-link>
        <router-link to="/admin" class="nav-link">
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <circle cx="12" cy="12" r="3"/><path d="M19.07 4.93a10 10 0 0 1 0 14.14M4.93 4.93a10 10 0 0 0 0 14.14"/>
          </svg>
          <span>系統管理</span>
        </router-link>
        <router-link to="/admin/chunks" class="nav-link">
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <rect x="3" y="3" width="8" height="8" rx="1.5"/>
            <rect x="13" y="3" width="8" height="8" rx="1.5"/>
            <rect x="3" y="13" width="8" height="8" rx="1.5"/>
            <rect x="13" y="13" width="8" height="8" rx="1.5"/>
          </svg>
          <span>Chunk 檢視</span>
        </router-link>
        <router-link to="/admin/report-reviews" class="nav-link">
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <path d="M9 11l3 3L22 4"/><path d="M21 12v7a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11"/>
          </svg>
          <span>報告待審</span>
        </router-link>
        <router-link to="/skills" class="nav-link">
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <path d="M12 2L2 7l10 5 10-5-10-5zM2 17l10 5 10-5M2 12l10 5 10-5"/>
          </svg>
          <span>Skill 管理</span>
        </router-link>
      </div>
      <div class="navbar-right">
        <div class="system-badge" :class="'badge-' + systemStatus">
          <span class="badge-dot"></span>
          <span>{{ statusText }}</span>
        </div>
      </div>
    </nav>

    <!-- 主內容區 -->
    <main class="main-content">
      <router-view />
    </main>
  </div>
</template>

<script setup>
import { ref, onMounted, onUnmounted } from 'vue'

const systemStatus = ref('green')  // green, yellow, red
const statusText = ref('系統正常')
let heartbeatTimer = null
let healthFailureCount = 0

const checkSystemHealth = async () => {
  try {
    const start = Date.now()
    const [statsResponse, taskResponse] = await Promise.all([
      fetch('/api/admin/stats', { signal: AbortSignal.timeout(8000) }),
      fetch('/api/upload/tasks?limit=20', { signal: AbortSignal.timeout(8000) }).catch(() => null)
    ])
    const elapsed = Date.now() - start

    if (!statsResponse.ok) {
      healthFailureCount += 1
      systemStatus.value = healthFailureCount >= 3 ? 'red' : 'yellow'
      statusText.value = healthFailureCount >= 3 ? '系統異常' : '系統忙碌'
      return
    }

    healthFailureCount = 0
    const data = await statsResponse.json()
    let hasIngestWork = false
    if (taskResponse?.ok) {
      const taskData = await taskResponse.json()
      hasIngestWork = (taskData.active || []).length > 0 || (taskData.queued || []).length > 0
    }

    // 攝入中或回應時間偏長時顯示忙碌，不直接判定異常
    if (hasIngestWork) {
      systemStatus.value = 'yellow'
      statusText.value = '系統忙碌'
    } else if (elapsed > 3000 || (data.active_workers !== undefined && data.active_workers === 0)) {
      systemStatus.value = 'yellow'
      statusText.value = '系統緩慢'
    } else {
      systemStatus.value = 'green'
      statusText.value = '系統正常'
    }
  } catch (e) {
    healthFailureCount += 1
    systemStatus.value = healthFailureCount >= 3 ? 'red' : 'yellow'
    statusText.value = healthFailureCount >= 3 ? '系統異常' : '系統忙碌'
  }
}

onMounted(() => {
  checkSystemHealth()
  heartbeatTimer = setInterval(checkSystemHealth, 30000)  // 每 30 秒檢查一次
})

onUnmounted(() => {
  if (heartbeatTimer) {
    clearInterval(heartbeatTimer)
  }
})
</script>

<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap');

* {
  margin: 0;
  padding: 0;
  box-sizing: border-box;
}

:root {
  --primary: #7fffe3;
  --primary-light: #17d9ff;
  --primary-dark: #06161d;
  --accent: #17d9ff;
  --accent-light: #7fffe3;
  --bg-page: #06161d;
  --bg-card: rgba(10, 35, 44, .84);
  --bg-surface: rgba(14, 48, 58, .92);
  --text-primary: #e7ffff;
  --text-secondary: #b9d6da;
  --text-muted: #8da8ae;
  --border: rgba(127, 255, 227, .2);
  --border-strong: rgba(127, 255, 227, .35);
  --success: #7fffe3;
  --warning: #ffd36e;
  --error: #ffaaa8;
  --shadow-sm: 0 1px 2px rgba(0, 0, 0, .12);
  --shadow: 0 16px 45px rgba(0, 0, 0, .16);
  --shadow-lg: 0 24px 70px rgba(0, 0, 0, .3);
  --radius: 12px;
  --radius-lg: 18px;
}

body {
  font-family: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
  background:
    linear-gradient(rgba(127,255,227,.035) 1px, transparent 1px),
    linear-gradient(90deg, rgba(127,255,227,.035) 1px, transparent 1px),
    radial-gradient(circle at 55% 0%, rgba(0,228,255,.16), transparent 34%),
    #06161d;
  background-size: 48px 48px, 48px 48px, auto, auto;
  color: var(--text-primary);
  line-height: 1.6;
}

#app {
  min-height: 100vh;
  display: flex;
  flex-direction: column;
  background: transparent;
}

/* === Navbar === */
.navbar {
  background: rgba(5, 25, 32, .9);
  backdrop-filter: blur(14px);
  padding: 0 32px;
  height: 64px;
  display: flex;
  align-items: center;
  gap: 32px;
  box-shadow: 0 16px 45px rgba(0, 0, 0, .16);
  position: sticky;
  top: 0;
  z-index: 100;
  border-bottom: 1px solid rgba(127, 255, 227, .2);
}

.navbar-brand {
  display: flex;
  align-items: center;
  gap: 12px;
}

.brand-icon {
  display: flex;
  align-items: center;
  justify-content: center;
}

.brand-text {
  display: flex;
  flex-direction: column;
  line-height: 1.2;
}

.brand-name {
  color: white;
  font-size: 1.05em;
  font-weight: 700;
  letter-spacing: -0.01em;
}

.brand-sub {
  color: rgba(255,255,255,0.5);
  font-size: 0.68em;
  font-weight: 400;
  text-transform: uppercase;
  letter-spacing: 0.05em;
}

.navbar-links {
  display: flex;
  gap: 4px;
  flex: 1;
}

.nav-link {
  display: flex;
  align-items: center;
  gap: 7px;
  padding: 8px 16px;
  border-radius: 8px;
  text-decoration: none;
  color: #829ba1;
  font-size: 0.9em;
  font-weight: 500;
  transition: all 0.2s;
  position: relative;
  overflow: hidden;
}

.nav-link:hover {
  color: #06161d;
  background: #f5ffff;
}

.nav-link.router-link-active {
  color: #06161d;
  background: #f5ffff;
  box-shadow: inset 0 1px 0 rgba(255,255,255,.35);
}

.nav-link svg {
  opacity: 0.8;
}

.nav-link.router-link-active svg,
.nav-link:hover svg {
  opacity: 1;
}

.navbar-right {
  margin-left: auto;
}

.system-badge {
  display: flex;
  align-items: center;
  gap: 7px;
  padding: 5px 12px;
  background: rgba(127,255,227,.08);
  border-radius: 20px;
  color: #d8ffff;
  font-size: 0.8em;
  font-weight: 500;
  border: 1px solid rgba(255,255,255,0.08);
}

.badge-dot {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  animation: pulse 2s infinite;
}

.badge-green .badge-dot { background: #10b981; box-shadow: 0 0 6px #10b981; }
.badge-yellow .badge-dot { background: #f59e0b; box-shadow: 0 0 6px #f59e0b; }
.badge-red .badge-dot { background: #ef4444; box-shadow: 0 0 6px #ef4444; }

@keyframes pulse {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.5; }
}

/* === Main Content === */
.main-content {
  flex: 1;
  padding: 28px clamp(16px, 4vw, 48px);
  max-width: 1200px;
  width: 100%;
  margin: 0 auto;
  background: transparent;
}

/* chat-v2 visual language for legacy Vue management views; component behavior is unchanged. */
.page-header,.search-card,.result-card,.task-card,.error-card,.system-card,.analysis-card{border-color:var(--border)!important;background:linear-gradient(145deg,rgba(24,78,88,.72),rgba(7,35,43,.82))!important;color:var(--text-primary)!important;box-shadow:var(--shadow)!important}
.page-header{background:linear-gradient(135deg,rgba(24,78,88,.9),rgba(7,35,43,.9))!important}.page-title,.page-desc,.section-label,.category-label,.mode-label,.analysis-title-block h3,.analysis-name,.analysis-score,.answer-content,.source-name,.stat-value{color:var(--text-primary)!important}.page-desc,.mode-detail,.analysis-title-block p,.analysis-docs,.analysis-preview,.source-preview,.text-secondary,.text-muted{color:var(--muted,#8da8ae)!important}.mode-btn,.category-section,.mode-detail,.search-input-wrapper,.analysis-row,.source-item,.stats-grid{border-color:rgba(127,255,227,.16)!important;background:rgba(0,0,0,.16)!important;color:var(--text-primary)!important}.mode-btn.active{border-color:var(--mint,#7fffe3)!important;background:rgba(127,255,227,.1)!important}.search-input-wrapper textarea,.category-select{color:#f2ffff!important;background:transparent!important}.search-input-wrapper textarea::placeholder{color:#617f87!important}.search-btn{color:#06161d!important;background:linear-gradient(90deg,#7fffe3,#17d9ff)!important}.result-header,.answer-section,.sources-section,.quality-summary-card{border-color:rgba(127,255,227,.12)!important;background:rgba(0,0,0,.12)!important}.answer-content code,.task-info code{color:#dffaff!important;background:rgba(127,255,227,.12)!important}.source-item{color:var(--text-primary)!important}

/* === Scrollbar === */
::-webkit-scrollbar {
  width: 6px;
  height: 6px;
}
::-webkit-scrollbar-track {
  background: transparent;
}
::-webkit-scrollbar-thumb {
  background: #cbd5e1;
  border-radius: 3px;
}
::-webkit-scrollbar-thumb:hover {
  background: #94a3b8;
}
</style>
