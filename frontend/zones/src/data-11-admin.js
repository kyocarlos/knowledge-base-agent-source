// 部門與公司文管專區 sample data (demo): department records (time / weekly reports) and company policies. Documents are in data-11b-admin.js.
window.KM_ZONES.admin = {
  id: 'admin', label: '部門與公司文管專區', assistant: '文管知識助理', short: '文管', brand: 'Department & company records zone', brandTitle: 'Department & Company Records Zone',
  idLabel: '文件編號', sourceLabel: '文管文件', placeholder: '週報、工時、請款流程、組織架構…', example: '採購請款的流程與需要準備的文件？',
  package: 'ADM-2026-10', feedKicker: 'Records Watch', feedTitle: '文管動態', timelineLabel: '文件更新進度',
  cats: [['部門文管', 'Time Report、Weekly Report 與內部雜項文件'], ['公司官方文件', '人事行政、採購請款與組織架構相關文件']],
  topics: [['週報', 4], ['工時填報', 3], ['請款流程', 3], ['採購', 3], ['請假規定', 2], ['組織架構', 2]],
  attention: [['info', '2026 Q4 工時填報規定已更新', 'Time Report 填報截止日調整為每週五 17:00'], ['warning', '公司官方文件含敏感內容', '人事與請款類文件僅授權人員可檢視，請確認帳號權限']],
  qa: [
    { q: '採購請款的流程與需要準備的文件？', a: '採購請款流程 {5}：\n\n1. 填寫請款單並附上採購單與驗收單\n2. 部門主管簽核\n3. 送交行政部審核與付款\n\n金額超過一定額度需加簽部門之上主管，請依最新規定辦理 {5:1}。' },
    { q: 'Time Report 什麼時候要填？', a: 'Time Report 每週五 17:00 前需完成填報 {0}。專案工時需對應到專案代碼，休假與出差請依規定填寫，逾期補填需主管同意 {0:1}。' },
    { q: '本週 Weekly Report 的格式要求？', a: 'Weekly Report 需包含 {1}：\n\n1. 本週完成事項\n2. 風險與議題\n3. 下週預計事項\n\n各組週報於每週一中午前提交，由部門彙整後送交主管。' },
  ],
  digest: {
    sources: ['行政部', '部門公告', '人資部'],
    highlights: ['Time Report 填報截止日調整為每週五 17:00', '採購請款流程更新到 v3.0', '組織架構圖更新到 2026 Q4'],
    items: [
      ['部門公告', 2, 'Time Report 填報規定更新', '填報截止日調整為每週五 17:00，逾期需主管同意補填。'],
      ['行政部', 6, '採購請款流程更新到 v3.0', '新增電子簽核流程與額度分級規定。'],
      ['人資部', 12, '組織架構圖更新到 2026 Q4', '新增設備管理組與實驗室管理組的隸屬關係。', true],
    ],
  },
  updates: [['new_document', 2, 0], ['superseded', 6, 5], ['new_document', 9, 1], ['new_document', 12, 7]],
};
