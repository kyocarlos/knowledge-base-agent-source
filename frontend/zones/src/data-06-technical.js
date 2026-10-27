// 技術知識專區 sample data (demo): seminar slides, design documents and debugging know-how. Documents are in data-06b-technical.js.
window.KM_ZONES.technical = {
  id: 'technical', label: '技術知識專區', assistant: '技術知識助理', short: '技術', brand: 'Technical knowledge zone', brandTitle: 'Technical Knowledge Zone',
  idLabel: '文件編號', sourceLabel: '技術文件', placeholder: '研討會、架構、除錯、量測…', example: '如何排查 Wi-Fi 與 5G 同時使用時的干擾問題？',
  package: 'TECH-2026-10', feedKicker: 'Tech Watch', feedTitle: '技術動態', timelineLabel: '學習與分享進度',
  cats: [['研討會講義', '研討會與技術講座的講義與心得'], ['設計與架構', '系統設計、架構與技術選型文件'], ['除錯與操作', '除錯流程、工具使用與經驗彙整'], ['量測與方法', '量測方法、環境設定與判讀指引']],
  topics: [['射頻量測', 5], ['干擾', 4], ['除錯', 5], ['自動化測試', 4], ['OTA', 3], ['研討會', 4], ['Wi-Fi 7', 3]],
  attention: [['info', '2 份研討會講義新增', 'Keysight World Tech Day 2026 與 Anritsu 技術研討會講義已上傳'], ['warning', '1 份除錯指南超過 6 個月未更新', '自動化測試框架使用指南建議複查']],
  qa: [
    { q: '如何排查 Wi-Fi 與 5G 同時使用時的干擾問題？', a: '建議依下列順序排查 {3}：\n\n1. 先量測 2.4 GHz 與 5 GHz 的底噪，確認是否有外部干擾\n2. 檢查 Wi-Fi 6 GHz 與 5G n77／n78 的鄰頻情形\n3. 在遮蔽室重現，確認是否為設備本身互相干擾\n4. 調整天線隔離度或頻道設定後重測\n\n量測方法與環境設定見量測方法文件 {6}。' },
    { q: 'Keysight World Tech Day 2026 有哪些值得參考的內容？', a: '本次研討會講義重點 {0}：\n\n- Wi-Fi 7 與 Wi-Fi 8 的量測挑戰\n- 5G Advanced 與 6G 研究的測試方向\n- AI 在測試自動化的應用\n\n心得與可套用到本部門的建議見講義第 2 頁 {0:1}。' },
    { q: 'OTA 量測環境要注意什麼？', a: 'OTA 量測的重點 {6}：\n\n1. 暗室需定期校驗，確認靜區品質\n2. 天線與纜線損耗需先校準\n3. 待測物擺放角度與高度需固定並記錄\n\n錯誤的擺位是常見誤差來源 {6:1}。' },
  ],
  digest: {
    sources: ['技術分享', '研討會', '內部知識庫'],
    highlights: ['Keysight World Tech Day 2026 講義已上傳', '新增 Wi-Fi 與 5G 共存干擾排查指南', 'OTA 量測方法更新到 v2.1'],
    items: [
      ['研討會', 3, 'Keysight World Tech Day 2026 講義上傳', '涵蓋 Wi-Fi 7／Wi-Fi 8 量測挑戰、5G Advanced 與 AI 測試自動化。'],
      ['技術分享', 5, 'Wi-Fi 與 5G 共存干擾排查指南發布', '提供從底噪量測到天線隔離度調整的 4 步驟排查流程。'],
      ['內部知識庫', 9, 'OTA 量測方法更新到 v2.1', '新增暗室靜區校驗週期與擺位紀錄表範本。', true],
    ],
  },
  updates: [['new_document', 3, 0], ['new_document', 5, 3], ['superseded', 9, 6], ['new_document', 12, 1]],
};
