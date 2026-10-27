// Smallcell知識專區 sample data (demo): small cell deployment, OAM and O-RAN interoperability. Documents are in data-04b-smallcell.js.
window.KM_ZONES.smallcell = {
  id: 'smallcell', label: 'Smallcell知識專區', assistant: 'Smallcell 知識助理', short: 'Smallcell', brand: 'Smallcell knowledge zone', brandTitle: 'Smallcell Knowledge Zone',
  idLabel: '文件編號', sourceLabel: ' Smallcell 文件', placeholder: '部署、OAM、O-RAN、同步、干擾…', example: 'SC3200-IN 的室內部署與同步設定？',
  package: 'SC-2026-10', feedKicker: 'Smallcell Watch', feedTitle: 'Smallcell 動態', timelineLabel: '專案時程',
  cats: [['產品與規格', 'Small Cell 機種規格與系統架構'], ['部署與規劃', '企業室內涵蓋規劃、安裝與同步設定'], ['OAM 與互通', 'OAM 管理、O-RAN 前傳與互通測試'], ['測試與驗證', '射頻一致性、負載與現場驗證結果']],
  topics: [['n78', 5], ['O-RAN 7.2x', 4], ['PTP 同步', 3], ['PoE++', 3], ['室內涵蓋', 4], ['NETCONF', 3], ['干擾協調', 2]],
  attention: [['warning', '1 項互通測試等待合作廠商回覆', 'O-DU 互通案例中的 M-Plane 組態項目尚未確認'], ['info', 'SC3200-IN 現場驗證已排程', '預計下月於企業客戶場域進行 5 天驗證']],
  qa: [
    { q: 'SC3200-IN 的室內部署與同步設定？', a: 'SC3200-IN 的部署重點 {1}：\n\n1. 以 PoE++ 供電，單台涵蓋半徑依隔間材質而異\n2. 同步需使用 PTP（IEEE 1588v2），時間誤差須在規範內\n3. 鄰近站台需做 PCI 與頻率規劃以降低干擾\n\n同步設定細節見指南的同步章節 {1:1}。' },
    { q: 'SC3200-IN 的射頻一致性結果？', a: 'SC3200-IN 在 n78 的射頻一致性 24 項中 **23 項通過、1 項待複測** {5}：\n\n| 項目 | 最差值 | 結果 |\n| --- | --- | --- |\n| ACLR | -47.2 dBc | 通過 |\n| EVM | 3.1% | 通過 |\n| 高溫頻率誤差 | 待複測 | 待確認 |' },
    { q: 'O-RAN 7.2x 前傳互通測試狀況如何？', a: '目前互通測試共 32 個案例，**28 項通過、4 項待確認** {4}，待確認項目集中在 M-Plane 組態與 PTP 同步切換。細部案例清單見測試報告。' },
  ],
  digest: {
    sources: ['專案管理組', 'CSIT 測試組', '合作廠商'],
    highlights: ['SC3200-IN 射頻一致性報告完成，1 項待複測', 'O-RAN 7.2x 互通測試通過 28 項', '企業場域現場驗證排程確認'],
    items: [
      ['CSIT 測試組', 3, 'SC3200-IN 射頻一致性報告 v1.0 發布', '24 項射頻項目 23 項通過，高溫頻率誤差待複測。'],
      ['合作廠商', 6, 'O-DU 廠商回覆互通測試問題', '提供 M-Plane 組態範本，預計本週內重測 4 項待確認案例。'],
      ['專案管理組', 9, '企業客戶場域現場驗證排程確認', '預計 5 天，涵蓋涵蓋範圍、漫遊與負載測試。', true],
    ],
  },
  updates: [['new_document', 3, 5], ['new_document', 6, 4], ['superseded', 8, 2], ['new_document', 11, 7]],
};
