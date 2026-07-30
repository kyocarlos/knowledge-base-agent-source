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
  --primary: #143a66;
  --primary-light: #215ea8;
  --primary-dark: #0b2440;
  --accent: #1f8db8;
  --accent-light: #69c7e5;
  --bg-page: #eef3f8;
  --bg-card: #ffffff;
  --bg-surface: #f8fbfe;
  --text-primary: #15263d;
  --text-secondary: #5f6f82;
  --text-muted: #8694a6;
  --border: #d8e2ee;
  --border-strong: #b9c8d8;
  --success: #14835d;
  --warning: #b9770e;
  --error: #c1363a;
  --shadow-sm: 0 1px 2px rgba(15, 23, 42, 0.05);
  --shadow: 0 8px 20px -12px rgba(15, 23, 42, 0.28);
  --shadow-lg: 0 18px 44px -24px rgba(15, 23, 42, 0.42);
  --radius: 10px;
  --radius-lg: 16px;
}

body {
  font-family: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
  background:
    radial-gradient(circle at top left, rgba(31, 141, 184, 0.08), transparent 34%),
    linear-gradient(180deg, #f7fafc 0%, #eef3f8 38%, #e8eef5 100%);
  color: var(--text-primary);
  line-height: 1.6;
}

#app {
  min-height: 100vh;
  display: flex;
  flex-direction: column;
  background:
    linear-gradient(180deg, rgba(255, 255, 255, 0.62), rgba(255, 255, 255, 0.3)),
    linear-gradient(135deg, rgba(20, 58, 102, 0.04), transparent 35%, rgba(31, 141, 184, 0.05));
}

/* === Navbar === */
.navbar {
  background: linear-gradient(135deg, rgba(11, 36, 64, 0.98) 0%, rgba(20, 58, 102, 0.96) 42%, rgba(33, 94, 168, 0.94) 100%);
  backdrop-filter: blur(14px);
  padding: 0 32px;
  height: 64px;
  display: flex;
  align-items: center;
  gap: 32px;
  box-shadow: 0 8px 24px rgba(11, 36, 64, 0.22);
  position: sticky;
  top: 0;
  z-index: 100;
  border-bottom: 1px solid rgba(255, 255, 255, 0.08);
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
  color: rgba(255,255,255,0.7);
  font-size: 0.9em;
  font-weight: 500;
  transition: all 0.2s;
  position: relative;
  overflow: hidden;
}

.nav-link:hover {
  color: white;
  background: rgba(255,255,255,0.08);
}

.nav-link.router-link-active {
  color: white;
  background: linear-gradient(135deg, rgba(255,255,255,0.14), rgba(255,255,255,0.06));
  box-shadow: inset 0 1px 0 rgba(255,255,255,0.12);
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
  background: linear-gradient(135deg, rgba(255,255,255,0.12), rgba(255,255,255,0.06));
  border-radius: 20px;
  color: rgba(255,255,255,0.85);
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
  padding: 32px;
  max-width: 1200px;
  width: 100%;
  margin: 0 auto;
  background: transparent;
}

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
