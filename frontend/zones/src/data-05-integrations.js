// Confluence / Jira / TestRail 查詢專區 sample data (demo). Documents are in data-05b-integrations.js, questions and feed in data-05c-integrations.js.
window.KM_ZONES.integrations = {
  id: 'integrations', label: 'Confluence / Jira / TestRail 查詢專區', assistant: '整合查詢助理', short: '整合查詢', brand: 'Confluence / Jira / TestRail zone', brandTitle: 'Confluence / Jira / TestRail Zone',
  idLabel: '編號', sourceLabel: '整合來源資料', placeholder: '議題編號、機種、頁面標題、測試計畫…', example: 'RTF7907VW-D223 目前有哪些未解決的 Jira 議題？',
  package: 'INT-2026-10', feedKicker: 'Integration Watch', feedTitle: '整合動態', timelineLabel: '議題處理進度',
  cats: [['Confluence 頁面', '需求、設計、流程與週報頁面'], ['Jira 議題', '缺陷、任務與變更議題'], ['TestRail 計畫', '測試計畫與案例集'], ['TestRail 執行結果', '各輪測試執行結果']],
  topics: [['MLO', 4], ['韌體 2.3.1', 4], ['回歸測試', 4], ['Weekly Report', 3], ['缺陷', 4], ['發布流程', 2]],
  attention: [['warning', '2 個 Jira 議題仍為開啟狀態', 'MLO 切換時間與高溫頻率誤差兩個議題尚未結案'], ['info', 'TestRail 有 1 輪執行結果更新', 'RTF7907VW-D223 第 3 輪執行結果已同步']],
};
