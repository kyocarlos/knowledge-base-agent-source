// CPE知識專區 sample data (demo): customer premises equipment (4G/5G routers and gateways). Documents are in data-03b-cpe.js.
window.KM_ZONES.cpe = {
  id: 'cpe', label: 'CPE知識專區', assistant: 'CPE 知識助理', short: 'CPE', brand: 'CPE knowledge zone', brandTitle: 'CPE Knowledge Zone',
  idLabel: '文件編號', sourceLabel: ' CPE 文件', placeholder: '機種、韌體版本、SIM、天線…', example: 'RTF5510CP-A104 的 5G 吞吐量與韌體版本差異？',
  package: 'CPE-2026-10', feedKicker: 'CPE Watch', feedTitle: 'CPE 動態', timelineLabel: '機種開發進度',
  cats: [['機種規格', 'CPE 機種規格、天線與硬體資訊'], ['韌體與測試', '韌體版本、回歸測試與相容性結果'], ['部署與設定', '安裝、設定與除錯指南'], ['業者規範', '電信業者 CPE 規範與驗證需求']],
  topics: [['5G SA', 7], ['FOTA', 4], ['外接天線', 4], ['eSIM', 3], ['VoNR', 3], ['PoE', 2], ['業者驗證', 4]],
  attention: [['warning', '1 個機種的韌體尚未通過業者驗證', 'RTF5510CP-A104 韌體 2.3.1 等待業者實驗室回覆'], ['info', '2 份設定指南有新版', '室內安裝與外接天線指南已更新']],
  qa: [
    { q: 'RTF5510CP-A104 的 5G 吞吐量與韌體版本差異？', a: 'RTF5510CP-A104 韌體 2.3.1 的回歸測試共 88 項，**84 項通過、4 項待確認** {2}。\n\n| 項目 | 案例數 | 通過 | 備註 |\n| --- | --- | --- | --- |\n| 註冊與重新註冊 | 18 | 18 | 已修正 |\n| FOTA 升級 | 30 | 30 | 成功率 100% |\n| VoNR 通話 | 16 | 15 | MOS 平均 4.1 |\n| 業者 APN | 24 | 21 | 3 項待確認 |\n\n版本差異：2.3.0 引入 VoNR，但待機後有重新註冊問題，2.3.1 已修正 {3:1}。' },
    { q: '5G CPE 訊號很弱時該怎麼處理？', a: '建議依序處理 {5}：\n\n1. 避免放在金屬櫃內與牆角，改放窗邊或高處\n2. 用 RSRP 與 SINR 判讀訊號品質\n3. 訊號弱於 -110 dBm 時改用外接天線\n\n外接天線要注意饋線線損，n78 頻段建議優先使用低損耗饋線 {6:1}。' },
    { q: '業者 A 的 CPE 送測有什麼要求？', a: '業者 A 的室內型 CPE 要求 {8}：\n\n- 需通過業者實驗室的網路相容性測試\n- 韌體升級須支援 FOTA\n- 送測週期約 4 至 6 週\n\n另外必須支援 VoNR 與 eSIM，詳細頻段與測試項目見規範摘要。' },
  ],
  digest: {
    sources: ['技術支援組', 'CSIT 測試組', '業者窗口'],
    highlights: ['RTF5510CP-A104 韌體 2.3.1 回歸測試完成', '外接天線與線損指南更新', '業者 B 固定無線接取驗證計畫已發布'],
    items: [
      ['CSIT 測試組', 2, 'RTF5510CP-A104 韌體 2.3.1 回歸測試結果', '88 項中 84 項通過，4 項待確認，主要與業者 APN 設定有關。'],
      ['技術支援組', 5, '外接天線安裝與線損計算指南更新', '新增 n78 與 n79 的線損範例，補充低損耗饋線建議。'],
      ['業者窗口', 8, '業者 B 公布固定無線接取 CPE 驗證計畫', '外場測試至少 14 天，吞吐量需達承諾速率的 90%。'],
    ],
  },
  updates: [['new_document', 2, 2], ['new_document', 5, 6], ['superseded', 6, 3], ['new_document', 8, 9]],
};
