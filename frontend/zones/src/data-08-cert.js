// 認證與法規知識專區 sample data (demo): Wi-Fi / Bluetooth / GCF / PTCRB certification per product. Documents are in data-08b-cert.js.
window.KM_ZONES.cert = {
  id: 'cert', label: '認證與法規知識專區', assistant: '認證與法規助理', short: '認證與法規', brand: 'Certification zone', brandTitle: 'Certification Zone',
  idLabel: '文件編號', sourceLabel: '認證文件', placeholder: '機種、認證項目、Wi-Fi、GCF、PTCRB…', example: 'RTF7907VW-D223 需要做哪些外部認證，目前進度？',
  package: 'CERT-2026-10', feedKicker: 'Certification Watch', feedTitle: '認證動態', timelineLabel: '認證進度',
  cats: [['Wi-Fi 認證', 'Wi-Fi Alliance 認證項目與送測資料'], ['藍牙認證', 'Bluetooth SIG 認證與列名資料'], ['蜂巢式認證', 'GCF 與 PTCRB 認證資料'], ['法規與送測流程', '各地區法規與認證送測流程']],
  topics: [['Wi-Fi 7 認證', 4], ['GCF', 3], ['PTCRB', 3], ['藍牙', 3], ['送測流程', 3], ['法規', 3]],
  attention: [['warning', '1 個機種的認證即將到期', 'RTF5510CP-A104 的 PTCRB 認證將於 60 天內到期'], ['info', 'RTF7907VW-D223 已進入送測準備', '預計 2026-11-03 送測，申請單簽核中']],
  qa: [
    { q: 'RTF7907VW-D223 需要做哪些外部認證，目前進度？', a: 'RTF7907VW-D223 需要的外部認證與進度如下：\n\n| 認證 | 狀態 | 預計時程 |\n| --- | --- | --- |\n| Wi-Fi Alliance（Wi-Fi 7） | 送測準備中 | 2026-11-03 送測 |\n| Bluetooth SIG | 資料準備中 | 與 Wi-Fi 同步送測 |\n| 當地射頻法規 | 已完成預測試 | 待正式報告 |\n\n詳細項目與前置條件見認證計畫 {0}，送測流程見指南 {7}。' },
    { q: 'GCF 與 PTCRB 認證有什麼差別？', a: 'GCF 與 PTCRB 都是行動終端的認證，差別在適用市場與組織 {4}：\n\n- **GCF**：以全球市場為主，多用於歐洲與亞洲業者\n- **PTCRB**：以北美業者為主\n\n送測前需確認目標業者要求，必要時兩者都需要取得 {5}。' },
    { q: '認證送測前要準備哪些文件？', a: '送測前至少要準備 {7}：\n\n1. 完整的功能與效能測試報告\n2. 產品規格與韌體版本資訊\n3. 送測申請單與樣品清單\n4. 認證實驗室的預約確認\n\n缺少任一項都可能延誤送測時程。' },
  ],
  digest: {
    sources: ['認證實驗室', '法規公告', '專案管理組'],
    highlights: ['RTF7907VW-D223 送測日期確認為 2026-11-03', 'RTF5510CP-A104 PTCRB 認證將於 60 天內到期', '認證送測流程指南更新到 v2.0'],
    items: [
      ['專案管理組', 3, 'RTF7907VW-D223 送測日期確認', '預計 2026-11-03 送測，樣品 6 台、韌體 1.0.8，申請單簽核中。'],
      ['認證實驗室', 7, 'RTF5510CP-A104 PTCRB 認證到期提醒', '認證將於 60 天內到期，需評估是否延展或隨新韌體重新驗證。'],
      ['法規公告', 11, '認證送測流程指南更新到 v2.0', '新增送測前檢查表與預計時程範例。', true],
    ],
  },
  updates: [['new_document', 3, 0], ['new_document', 7, 5], ['superseded', 11, 7], ['new_document', 14, 2]],
};
