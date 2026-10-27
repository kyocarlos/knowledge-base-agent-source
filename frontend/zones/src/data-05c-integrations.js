// Confluence / Jira / TestRail 查詢專區 sample questions and feed (demo).
Object.assign(window.KM_ZONES.integrations, {
  qa: [
    { q: 'RTF7907VW-D223 目前有哪些未解決的 Jira 議題？', a: 'RTF7907VW-D223 目前有 **1 個開啟中的議題**：\n\n- **KM-1287 MLO 切換時間超出需求**：優先級 High，指派給研發部，狀態為處理中；MLO 切換時間量測為 87 ms，需求為 50 ms 以內 {3}。\n\n相關測試結果見 TestRail 第 3 輪，4 項失敗中有 2 項與此議題相關 {8}。' },
    { q: 'RTF7907VW-D223 最新一輪 TestRail 執行結果？', a: 'RTF7907VW-D223 第 3 輪共執行 126 個案例 {8}：\n\n| 狀態 | 案例數 |\n| --- | --- |\n| 通過 | 119 |\n| 失敗 | 4 |\n| 阻擋 | 3 |\n\n失敗案例集中在 MLO 切換與 DFS 重新偵測，與 Jira 議題 KM-1287 相關 {3:1}。' },
    { q: 'CSIT 測試組本週週報的重點是什麼？', a: 'CSIT 測試組 2026-W42 週報重點 {2}：\n\n1. 完成 RTF7907VW-D223 測試報告 v1.2\n2. RTF5510CP-A104 韌體 2.3.1 回歸測試完成\n3. 下週預計進行 SC3200-IN 高溫頻率誤差複測' },
  ],
  digest: {
    sources: ['Confluence', 'Jira', 'TestRail'],
    highlights: ['Jira KM-1301 已結案，韌體 2.3.1 回歸測試通過', 'TestRail 新增 RTF7907VW-D223 第 3 輪執行結果', 'Confluence 新增 5G CPE 韌體發布流程頁面'],
    items: [
      ['Jira', 2, 'KM-1301 待機後無法重新註冊：已結案', '韌體 2.3.1 修正，回歸測試 18 項全部通過。'],
      ['TestRail', 3, 'RTF7907VW-D223 第 3 輪執行結果同步', '126 項中通過 119、失敗 4、阻擋 3。'],
      ['Confluence', 6, '5G CPE 韌體發布流程頁面更新', '新增業者驗證通過後才可對外發布的檢查項目。'],
      ['Jira', 10, 'KM-1315 SC3200-IN 高溫頻率誤差偏移建立', '指派給研發部，等待溫度箱複測資料。', true],
    ],
  },
  updates: [['new_document', 2, 9], ['new_document', 3, 8], ['superseded', 6, 1], ['new_document', 10, 5]],
});
