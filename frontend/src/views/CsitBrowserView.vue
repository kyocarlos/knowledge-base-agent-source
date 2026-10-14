<template>
  <section class="csit-page">
    <header class="page-header">
      <div><p class="eyebrow">CSIT STAGE · READ ONLY</p><h1>CSIT 測試資料瀏覽</h1><p>依序瀏覽 Module、Project/Record、Case、Task 與附件。此頁不提供新增、修改或刪除操作。</p></div>
      <button type="button" @click="loadModules" :disabled="loading.modules">重新整理</button>
    </header>
    <div v-if="error" class="notice error">{{ error }}</div>
    <div class="browser-grid">
      <article v-for="column in columns" :key="column.key" class="panel">
        <div class="panel-title"><span>{{ column.title }}</span><span class="count">{{ column.items.length }}</span></div>
        <button v-for="item in column.items" :key="item.id || item.moduleCode || item.code" class="list-item" :class="{ selected: column.selected(item) }" type="button" @click="column.select(item)">
          <strong>{{ column.label(item) }}</strong><small>{{ column.meta(item) }}</small>
        </button>
        <p v-if="column.loading()" class="empty">讀取中…</p><p v-else-if="column.selectedValue() && !column.items.length" class="empty">沒有資料</p>
      </article>
    </div>
    <article v-if="selectedTaskId" class="panel files-panel">
      <div class="panel-title"><span>5. Task files / Test reports</span><span class="count">{{ files.length }}</span></div>
      <div v-if="loading.files" class="empty">讀取中…</div>
      <div v-for="file in files" :key="file.id || file.fileId" class="file-row">
        <div><strong>{{ file.name || file.fileName || file.originalFileName || '未命名檔案' }}</strong><small>{{ file.id || file.fileId }}</small></div>
        <a class="download-link" :href="downloadUrl(file)" target="_blank" rel="noreferrer">下載</a>
      </div>
      <p v-if="!loading.files && !files.length" class="empty">此 Task 沒有檔案</p>
    </article>
  </section>
</template>

<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
const modules = ref([]), records = ref([]), cases = ref([]), tasks = ref([]), files = ref([])
const selectedModule = ref(''), selectedRecordId = ref(''), selectedCaseId = ref(''), selectedTaskId = ref('')
const error = ref(''), loading = reactive({ modules: false, records: false, cases: false, tasks: false, files: false })
const items = payload => Array.isArray(payload) ? payload : (payload?.items || payload?.data || [])
const key = item => item.moduleCode || item.code || item.id || ''
const name = item => item.moduleName || item.name || item.title || key(item)
async function getJson(path) { const response = await fetch(path, { headers: { Accept: 'application/json' } }); if (!response.ok) throw new Error('HTTP ' + response.status); return response.json() }
function clearBelow(level) { if (level <= 1) { records.value=[]; selectedRecordId.value='' }; if (level <= 2) { cases.value=[]; selectedCaseId.value='' }; if (level <= 3) { tasks.value=[]; selectedTaskId.value='' }; if (level <= 4) files.value=[] }
async function loadModules() { loading.modules=true; error.value=''; try { modules.value=items(await getJson('/api/csit/modules/enabled')) } catch (e) { error.value='CSIT 模組讀取失敗：' + e.message } finally { loading.modules=false } }
async function selectModule(item) { selectedModule.value=key(item); clearBelow(1); loading.records=true; error.value=''; try { records.value=items(await getJson('/api/csit/modules/' + encodeURIComponent(selectedModule.value) + '/records?page=1&page_size=50')) } catch (e) { error.value='Record 讀取失敗：' + e.message } finally { loading.records=false } }
async function selectRecord(item) { selectedRecordId.value=item.id; clearBelow(2); loading.cases=true; error.value=''; try { cases.value=items(await getJson('/api/csit/records/' + encodeURIComponent(item.id) + '/cases?page=1&page_size=50')) } catch (e) { error.value='Case 讀取失敗：' + e.message } finally { loading.cases=false } }
async function selectCase(item) { selectedCaseId.value=item.id; clearBelow(3); loading.tasks=true; error.value=''; try { tasks.value=items(await getJson('/api/csit/cases/' + encodeURIComponent(item.id) + '/tasks?page=1&page_size=50')) } catch (e) { error.value='Task 讀取失敗：' + e.message } finally { loading.tasks=false } }
async function selectTask(item) { selectedTaskId.value=item.id; files.value=[]; loading.files=true; error.value=''; try { files.value=items(await getJson('/api/csit/tasks/' + encodeURIComponent(item.id) + '/files')) } catch (e) { error.value='檔案讀取失敗：' + e.message } finally { loading.files=false } }
const columns = computed(() => [
  { key:'module', title:'1. Module', items:modules.value, selected:v=>selectedModule.value===key(v), selectedValue:()=>selectedModule.value, loading:()=>loading.modules, select:selectModule, label:name, meta:key },
  { key:'record', title:'2. Project / Record', items:records.value, selected:v=>selectedRecordId.value===v.id, selectedValue:()=>selectedModule.value, loading:()=>loading.records, select:selectRecord, label:v=>v.name||v.recordNo||v.id, meta:v=>v.recordNo||v.id },
  { key:'case', title:'3. Case', items:cases.value, selected:v=>selectedCaseId.value===v.id, selectedValue:()=>selectedRecordId.value, loading:()=>loading.cases, select:selectCase, label:v=>v.name||v.caseNo||v.id, meta:v=>v.caseNo||v.id },
  { key:'task', title:'4. Task', items:tasks.value, selected:v=>selectedTaskId.value===v.id, selectedValue:()=>selectedCaseId.value, loading:()=>loading.tasks, select:selectTask, label:v=>v.name||v.taskNo||v.id, meta:v=>v.taskNo||v.status||v.id }
])
function downloadUrl(file) { return '/api/csit/files/' + encodeURIComponent(file.id || file.fileId) + '/download' }
onMounted(loadModules)
</script>

<style scoped>
.csit-page{max-width:1440px;margin:0 auto;padding:34px 38px 56px;color:#172a42}.page-header{display:flex;justify-content:space-between;gap:24px;align-items:flex-start;margin-bottom:24px}.eyebrow{margin:0 0 8px;color:#0b8091;font-size:12px;font-weight:700;letter-spacing:.12em}h1{margin:0 0 8px;font-size:30px}.page-header p:not(.eyebrow){margin:0;color:#607289}.page-header button{border:1px solid #b7cad8;background:#fff;border-radius:8px;padding:10px 16px;color:#194b6d;cursor:pointer}.notice{margin:12px 0;padding:12px 14px;border-radius:8px;background:#eef7fb;color:#24516d}.notice.error{background:#fff2f0;color:#a13832}.browser-grid{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:14px}.panel{background:#fff;border:1px solid #d8e2ea;border-radius:12px;box-shadow:0 8px 22px #18304e0f;padding:16px;min-height:270px}.panel-title{display:flex;justify-content:space-between;align-items:center;font-weight:750;color:#183a5d;margin-bottom:12px}.count{min-width:24px;padding:3px 7px;border-radius:99px;background:#e9f3f7;color:#177184;text-align:center;font-size:12px}.list-item{display:block;width:100%;text-align:left;border:1px solid transparent;background:#f6f9fb;border-radius:8px;padding:10px;margin:7px 0;color:#203a54;cursor:pointer}.list-item:hover,.list-item.selected{border-color:#3b9cb1;background:#e9f7f7}.list-item strong,.list-item small,.file-row strong,.file-row small{display:block;overflow-wrap:anywhere}.list-item small,.file-row small{color:#718297;margin-top:4px;font-size:11px}.empty{color:#8190a0;font-size:13px;margin:18px 4px}.files-panel{margin-top:16px;min-height:0}.file-row{display:flex;justify-content:space-between;align-items:center;gap:18px;border-top:1px solid #e4ebef;padding:12px 4px}.download-link{color:#08778b;font-weight:700;text-decoration:none;white-space:nowrap}@media(max-width:980px){.browser-grid{grid-template-columns:repeat(2,minmax(0,1fr))}}@media(max-width:620px){.csit-page{padding:24px 16px 40px}.page-header{display:block}.page-header button{margin-top:16px}.browser-grid{grid-template-columns:1fr}}
</style>
