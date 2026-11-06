(() => {
'use strict';
// Names and texts of the knowledge zones, and the hook that sends the zone pages' /api/wifi8/* calls to the zone's own API.
window.KM_ZONES = {
 "mobile": {
  "id": "mobile",
  "label": "行動通訊知識專區",
  "assistant": "行動通訊知識助理",
  "short": "行動通訊",
  "brand": "4G/5G knowledge zone",
  "brandTitle": "4G/5G Knowledge Zone",
  "idLabel": "文件代碼",
  "sourceLabel": "規範與技術文件",
  "placeholder": "輸入文件名稱或關鍵字…",
  "example": "這個專區有哪些 5G 或 Small Cell 的文件？",
  "feedKicker": "Cellular Watch",
  "feedTitle": "行動通訊動態",
  "timelineLabel": "3GPP Release 時程"
 },
 "broadband": {
  "id": "broadband",
  "label": "固網寬頻知識專區",
  "assistant": "固網寬頻助理",
  "short": "固網寬頻",
  "brand": "Fixed broadband zone",
  "brandTitle": "Fixed Broadband Zone",
  "idLabel": "文件代碼",
  "sourceLabel": "寬頻文件",
  "placeholder": "輸入文件名稱或關鍵字…",
  "example": "XGS-PON 與 GPON 有什麼差異？",
  "feedKicker": "Broadband Watch",
  "feedTitle": "寬頻動態",
  "timelineLabel": "技術演進進度"
 },
 "cert": {
  "id": "cert",
  "label": "認證知識專區",
  "assistant": "認證知識助理",
  "short": "認證",
  "brand": "Certification zone",
  "brandTitle": "Certification Zone",
  "idLabel": "文件代碼",
  "sourceLabel": "認證文件",
  "placeholder": "輸入文件名稱或關鍵字…",
  "example": "NCC 與 CE 認證要準備什麼？",
  "feedKicker": "Certification Watch",
  "feedTitle": "認證動態",
  "timelineLabel": "認證進度"
 },
 "csit": {
  "id": "csit",
  "label": "產品驗證專區",
  "assistant": "產品驗證助理",
  "short": "產品驗證",
  "brand": "CSIT knowledge zone",
  "brandTitle": "CSIT Knowledge Zone",
  "idLabel": "文件代碼",
  "sourceLabel": "內部文件",
  "placeholder": "輸入文件名稱或關鍵字…",
  "example": "最近有哪些測試報告？換手測試的結果如何？",
  "feedKicker": "CSIT Watch",
  "feedTitle": "產品驗證動態",
  "timelineLabel": "測試進度"
 },
 "equipment": {
  "id": "equipment",
  "label": "設備儀器專區",
  "assistant": "設備儀器助理",
  "short": "設備儀器",
  "brand": "Equipment booking zone",
  "brandTitle": "Equipment Booking Zone",
  "idLabel": "文件代碼",
  "sourceLabel": "設備文件",
  "placeholder": "輸入文件名稱或關鍵字…",
  "example": "頻譜分析儀多久校驗一次？",
  "feedKicker": "Equipment Watch",
  "feedTitle": "設備儀器動態",
  "timelineLabel": "校驗進度"
 },
 "lab": {
  "id": "lab",
  "label": "實驗室管理專區",
  "assistant": "實驗室管理助理",
  "short": "實驗室管理",
  "brand": "Lab & test environment zone",
  "brandTitle": "Lab & Test Environment Zone",
  "idLabel": "文件代碼",
  "sourceLabel": "實驗室文件",
  "placeholder": "輸入文件名稱或關鍵字…",
  "example": "實驗室有哪些空間與環境規範？",
  "feedKicker": "Lab Watch",
  "feedTitle": "實驗室管理動態",
  "timelineLabel": "建置進度"
 },
 "integrations": {
  "id": "integrations",
  "label": "Confluence / Jira / TestRail 查詢專區",
  "assistant": "整合查詢助理",
  "short": "整合查詢",
  "brand": "Confluence / Jira / TestRail zone",
  "brandTitle": "Confluence / Jira / TestRail Zone",
  "idLabel": "文件代碼",
  "sourceLabel": "整合來源資料",
  "placeholder": "輸入文件名稱或關鍵字…",
  "example": "本週 Jira 與 TestRail 有哪些更新？",
  "feedKicker": "Integration Watch",
  "feedTitle": "整合動態",
  "timelineLabel": "議題處理進度"
 }
};
const zone = document.documentElement.dataset.zone;
if (zone) {
  if (!window.KM_ZONES[zone]) throw new Error('unknown zone ' + zone);
  window.KM_ZONE_CONFIG = Object.assign({ id: zone }, window.KM_ZONES[zone]);
  const realFetch = window.fetch.bind(window);
  window.fetch = (input, init) => {
    const raw = typeof input === 'string' ? input : input.url;
    const url = new URL(raw, location.origin);
    if (!url.pathname.startsWith('/api/wifi8/')) return realFetch(input, init);
    const target = '/api/zones/' + zone + '/' + url.pathname.slice('/api/wifi8/'.length) + url.search;
    return realFetch(typeof input === 'string' ? target : new Request(target, input), init);
  };
}
})();
