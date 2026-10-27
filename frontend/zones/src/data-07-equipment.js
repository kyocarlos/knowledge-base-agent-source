// 設備預約知識專區 sample data (demo): instrument list, vendors, booking rules and calibration. Documents are in data-07b-equipment.js.
window.KM_ZONES.equipment = {
  id: 'equipment', label: '設備預約知識專區', assistant: '設備預約助理', short: '設備預約', brand: 'Equipment booking zone', brandTitle: 'Equipment Booking Zone',
  idLabel: '資產編號', sourceLabel: '設備文件', placeholder: '設備名稱、資產編號、廠商、校驗…', example: '如何預約 Keysight UXM，需要提前幾天？',
  package: 'EQ-2026-10', feedKicker: 'Equipment Watch', feedTitle: '設備動態', timelineLabel: '校驗進度',
  cats: [['設備資訊', '設備名稱、資產編號、規格與位置'], ['廠商資訊', '儀器廠商與維護聯絡資料'], ['預約與借用規範', '預約、借用、歸還與異常通報流程'], ['校驗與維護', '校驗報告與年度校驗排程']],
  topics: [['Wi-Fi 測試設備', 3], ['5G 測試儀', 4], ['預約規範', 3], ['校驗', 4], ['歸還檢查', 2], ['廠商維護', 3]],
  attention: [['warning', '2 台設備校驗將於 30 天內到期', 'Anritsu MT8000A 與 Candela Wi-Fi7 Testbed 需安排校驗'], ['info', '預約規範已更新到 v2.1', '新增跨部門借用需主管核准的規定']],
  qa: [
    { q: '如何預約 Keysight UXM，需要提前幾天？', a: 'Keysight UXM 的預約規範 {7}：\n\n1. 至少提前 **3 個工作天** 提出預約\n2. 單次借用上限 10 個工作天，超過需主管核准\n3. 跨部門借用需雙方主管同意\n\n設備位置與資產資訊見設備資料 {1}，歸還時需完成檢查與異常通報 {8}。' },
    { q: 'Candela Wi-Fi7 Testbed 本週的預約狀況？', a: 'Candela Wi-Fi7 Testbed（資產編號 12345678）本週預約 {0:2}：\n\n| 日期 | 時段 | 預約人 | 用途 |\n| --- | --- | --- | --- |\n| 週一 | 全天 | CSIT 測試組 | RTF7907VW-D223 測試 |\n| 週二 | 上午 | 研發部 | MLO 除錯 |\n| 週三至週四 | 可預約 | — | — |\n| 週五 | 下午 | 技術分享 | 內部展示 |\n\n預約請依規範提前申請 {7}。' },
    { q: '設備校驗到期前要怎麼處理？', a: '設備校驗的處理方式 {10}：\n\n1. 年度校驗排程於每年初公布，到期前 30 天通知\n2. 校驗期間設備暫停預約\n3. 校驗後報告需上傳，並更新設備狀態\n\nKeysight UXM 的最近一次校驗結果見校驗報告 {9}。' },
  ],
  digest: {
    sources: ['設備管理組', '預約系統', '廠商通知'],
    highlights: ['Anritsu MT8000A 與 Candela Testbed 校驗將於 30 天內到期', '預約與借用規範更新到 v2.1', 'Meshlink 測試平台新增到設備清單'],
    items: [
      ['設備管理組', 2, '預約與借用規範更新到 v2.1', '新增跨部門借用需雙方主管同意，並補充異常通報時限。'],
      ['預約系統', 4, 'Meshlink Mesh 網路測試平台完成登錄', '資產編號 20260004，放置於 8F 實驗室，已開放預約。'],
      ['廠商通知', 8, 'Anritsu 校驗服務排程通知', '建議於 11 月底前送校，以免影響年底測試排程。'],
      ['設備管理組', 13, 'Keysight UXM 校驗完成', '校驗結果合格，下次校驗日期為 2027-09。', true],
    ],
  },
  updates: [['new_document', 2, 7], ['new_document', 4, 3], ['superseded', 8, 9], ['new_document', 13, 10]],
};
