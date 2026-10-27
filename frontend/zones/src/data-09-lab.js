// 實驗室與測試環境知識專區 sample data (demo): lab planning, lab build-out and test environment briefings. Documents are in data-09b-lab.js.
window.KM_ZONES.lab = {
  id: 'lab', label: '實驗室與測試環境知識專區', assistant: '實驗室知識助理', short: '實驗室', brand: 'Lab & test environment zone', brandTitle: 'Lab & Test Environment Zone',
  idLabel: '文件編號', sourceLabel: '實驗室文件', placeholder: '實驗室名稱、遮蔽室、暗室、環境簡報…', example: '8F 5G 實驗室有哪些設備與測試環境？',
  package: 'LAB-2026-10', feedKicker: 'Lab Watch', feedTitle: '實驗室動態', timelineLabel: '建置進度',
  cats: [['實驗室規劃', '實驗室介紹、海報與整體架構圖'], ['實驗室建置', '各實驗室的空間、設備配置與建置紀錄'], ['測試環境', '測試環境介紹簡報與使用說明']],
  topics: [['8F 5G 實驗室', 4], ['Wi-Fi 遮蔽室', 3], ['OTA 暗室', 3], ['架構圖', 3], ['環境簡報', 3], ['新進訓練', 2]],
  attention: [['info', '實驗室架構圖更新到 2026 版', '新增 5F Small Cell 實驗室與 OTA 暗室的位置'], ['warning', '1 份環境簡報超過 6 個月未更新', 'Wi-Fi 遮蔽室簡報建議複查設備清單']],
  qa: [
    { q: '8F 5G 實驗室有哪些設備與測試環境？', a: '8F 5G 實驗室的配置 {3}：\n\n- 5G NR 測試儀與協定測試站\n- 射頻遮蔽箱與屏蔽室\n- 專用網路與核心網模擬環境\n\n測試環境的使用方式與限制見環境簡報 {7}，整體位置見實驗室架構圖 {2}。' },
    { q: '新進同仁要怎麼快速熟悉實驗室？', a: '建議依序閱讀：\n\n1. **實驗室介紹**：了解各實驗室定位與負責範圍 {0}\n2. **實驗室架構圖**：確認位置、網路與電源配置 {2}\n3. **各環境簡報**：了解遮蔽室與暗室的使用規範 {6}\n\n實際操作設備前需完成內部訓練並登記。' },
    { q: 'OTA 暗室使用時要注意什麼？', a: 'OTA 暗室使用重點 {8}：\n\n1. 進入前需預約並確認靜區校驗狀態\n2. 待測物擺位需固定並記錄\n3. 暗室內禁止放置不必要的金屬物品\n\n詳細擺位與量測方法見簡報內容。' },
  ],
  digest: {
    sources: ['實驗室管理組', '設備管理組', '專案管理組'],
    highlights: ['實驗室架構圖更新到 2026 版', 'OTA 暗室環境簡報更新', '5F Small Cell 實驗室完成建置紀錄'],
    items: [
      ['實驗室管理組', 3, '實驗室架構圖更新到 2026 版', '新增 5F Small Cell 實驗室與 OTA 暗室的位置、網路與電源配置。'],
      ['設備管理組', 6, 'OTA 暗室環境簡報更新', '補充靜區校驗週期與擺位紀錄表的使用方式。'],
      ['專案管理組', 10, '5F Small Cell 實驗室建置完成', '完成機櫃、PoE++ 交換器與同步設備的安裝與驗收。', true],
    ],
  },
  updates: [['new_document', 3, 2], ['new_document', 6, 8], ['superseded', 10, 6], ['new_document', 13, 5]],
};
