// 固網寬頻知識專區 (PON / Cable) sample data (demo). Documents are in data-10b-broadband.js.
window.KM_ZONES.broadband = {
  id: 'broadband', label: '固網寬頻知識專區', assistant: '固網寬頻助理', short: '固網寬頻', brand: 'Fixed broadband zone', brandTitle: 'Fixed Broadband Zone',
  idLabel: '文件編號', sourceLabel: '寬頻文件', placeholder: 'PON、XGS-PON、ONU、DOCSIS、Cable Modem…', example: 'XGS-PON 與 GPON 的主要差異是什麼？',
  package: 'BB-2026-10', feedKicker: 'Broadband Watch', feedTitle: '寬頻動態', timelineLabel: '技術演進進度',
  cats: [['PON 技術', 'GPON、XGS-PON 與新世代 PON 技術文件'], ['Cable 技術', 'DOCSIS 與有線電視寬頻技術文件'], ['Broadband Forum 規範', 'Broadband Forum 的技術報告與測試規範'], ['測試與驗證', 'PON 與 Cable 設備的測試結果']],
  topics: [['XGS-PON', 5], ['GPON', 4], ['DOCSIS 4.0', 3], ['OMCI', 3], ['光功率', 3], ['QoS', 3]],
  attention: [['info', 'PON／Cable 測試計畫尚未納入 DOCSIS 4.0', '預計下季補充 DOCSIS 4.0 測試案例'], ['warning', '1 份規範有新版', 'BBF TR-178 已有新版，建議比對差異']],
  qa: [
    { q: 'XGS-PON 與 GPON 的主要差異是什麼？', a: 'XGS-PON 與 GPON 的主要差異 {2}：\n\n| 項目 | GPON | XGS-PON |\n| --- | --- | --- |\n| 下行速率 | 2.5 Gbps | 10 Gbps |\n| 上行速率 | 1.25 Gbps | 10 Gbps（對稱） |\n| 共存性 | — | 可與 GPON 在同一 ODN 共存 |\n\n部署時需留意光功率預算與分光比，量測結果見測試報告 {7}。' },
    { q: 'DOCSIS 4.0 相較 DOCSIS 3.1 有哪些改進？', a: 'DOCSIS 4.0 的主要改進 {5}：\n\n1. 支援對稱多 Gbps 速率（全雙工 DOCSIS 與擴充頻譜 DOCSIS）\n2. 更高的頻譜效率與更低的延遲\n3. 與既有 DOCSIS 3.1 網路向下相容\n\n現有測試計畫尚未涵蓋，預計下季補充。' },
    { q: 'ONU 如何透過 OMCI 管理？', a: 'ONU 透過 OMCI 由 OLT 管理 {4}：\n\n1. OLT 與 ONU 建立 OMCC 通道\n2. 透過 ME（管理實體）設定 VLAN、QoS 與服務\n3. 狀態與告警由 ONU 回報給 OLT\n\n設定範例與常見錯誤見指南。' },
  ],
  digest: {
    sources: ['技術分享', '測試平台', '規範追蹤'],
    highlights: ['XGS-PON ONU 光功率與吞吐量測試報告發布', 'DOCSIS 4.0 技術比較文件更新', 'BBF TR-178 有新版需比對'],
    items: [
      ['測試平台', 2, 'XGS-PON ONU 測試報告發布', '光功率與吞吐量均符合規範，上下行速率接近 10 Gbps。'],
      ['技術分享', 6, 'DOCSIS 4.0 技術比較更新', '補充全雙工 DOCSIS 與擴充頻譜 DOCSIS 的差異與部署情境。'],
      ['規範追蹤', 10, 'BBF TR-178 新版提醒', '建議比對與舊版的差異，評估對測試計畫的影響。', true],
    ],
  },
  updates: [['new_document', 2, 7], ['new_document', 6, 5], ['superseded', 10, 1], ['new_document', 13, 8]],
};
