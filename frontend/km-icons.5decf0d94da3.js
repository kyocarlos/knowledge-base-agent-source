/* Line icons for the sidebar: one set, one stroke weight, drawn here as inline SVG (no icon font, no extra requests).
   The pages build their navigation with JavaScript after load, so this watches the sidebar and swaps the old text symbols for icons by label. */
(function () {
  'use strict';
  const P = {
    home: '<path d="M3 11.5 12 4l9 7.5"/><path d="M5.5 10v10h13V10"/><path d="M10 20v-5.5h4V20"/>',
    wifi: '<path d="M2.5 9a14 14 0 0 1 19 0"/><path d="M5.7 12.5a9.5 9.5 0 0 1 12.6 0"/><path d="M8.9 16a5 5 0 0 1 6.2 0"/><path d="M12 19.6h.01"/>',
    signal: '<path d="M4 20v-3.5"/><path d="M9 20v-7"/><path d="M14 20V9"/><path d="M19 20V4"/>',
    network: '<rect x="3.5" y="4" width="17" height="6" rx="1.8"/><rect x="3.5" y="14" width="17" height="6" rx="1.8"/><path d="M7.5 7h.01M7.5 17h.01"/><path d="M12 10v4"/>',
    clipboard: '<rect x="5" y="4.5" width="14" height="17" rx="2"/><path d="M9 4.5h6V7H9z"/><path d="M8.5 12h7M8.5 16h4.5"/>',
    shield: '<path d="M12 3 20 6v6c0 4.8-3.3 7.9-8 9-4.7-1.1-8-4.2-8-9V6z"/><path d="m8.6 12.2 2.4 2.4 4.4-5"/>',
    search: '<circle cx="10.8" cy="10.8" r="6.8"/><path d="m20.5 20.5-4.9-4.9"/>',
    calendar: '<rect x="3.5" y="5" width="17" height="15.5" rx="2.2"/><path d="M8 3v4M16 3v4M3.5 10h17"/>',
    flask: '<path d="M9.5 3h5"/><path d="M10.5 3v6L5 19a2 2 0 0 0 1.8 3h10.4A2 2 0 0 0 19 19l-5.5-10V3"/><path d="M7.8 15h8.4"/>',
    file: '<path d="M14 3H7.5A2 2 0 0 0 5.5 5v14a2 2 0 0 0 2 2h9a2 2 0 0 0 2-2V8z"/><path d="M14 3v5h4.5"/><path d="M9 13h6M9 17h6"/>',
    dashboard: '<rect x="3.5" y="3.5" width="7.5" height="8" rx="1.6"/><rect x="13" y="3.5" width="7.5" height="5" rx="1.6"/><rect x="13" y="11" width="7.5" height="9.5" rx="1.6"/><rect x="3.5" y="14" width="7.5" height="6.5" rx="1.6"/>',
    book: '<path d="M12 6.5v13.5"/><path d="M12 6.5C10 4.7 7 4 3.5 4v14c3.5 0 6.5.7 8.5 2 2-1.3 5-2 8.5-2V4c-3.5 0-6.5.7-8.5 2.5z"/>',
    chat: '<path d="M20.5 12a8 8 0 0 1-11.7 7.1L3.8 20.2l1.2-4.4A8 8 0 1 1 20.5 12z"/><path d="M8.8 12h.01M12 12h.01M15.2 12h.01"/>',
    dot: '<circle cx="12" cy="12" r="2.4"/>',
    archive: '<rect x="3.5" y="4" width="17" height="4.5" rx="1.2"/><path d="M5 8.5V19a1.5 1.5 0 0 0 1.5 1.5h11A1.5 1.5 0 0 0 19 19V8.5"/><path d="M9.5 12.5h5"/>',
  };
  // label (or part of it) -> icon; the first match wins
  const BY_LABEL = [
    ['首頁', 'home'], ['總覽', 'dashboard'], ['文件瀏覽', 'book'], ['助理', 'chat'],
    ['WiFi', 'wifi'], ['4G/5G', 'signal'], ['CPE', 'dot'], ['Smallcell', 'dot'], ['固網', 'network'], ['CSIT', 'clipboard'],
    ['認證', 'shield'], ['Confluence', 'search'], ['設備預約', 'calendar'], ['實驗室', 'flask'], ['部門', 'file'], ['舊資料', 'archive'],
  ];
  const svg = (name) => `<svg class="km-ico" viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" focusable="false">${P[name] || P.dot}</svg>`;
  function apply() {
    document.querySelectorAll('.nav-item .nav-icon:not([data-km-ico])').forEach((slot) => {
      const label = (slot.nextElementSibling ? slot.nextElementSibling.textContent : slot.parentElement.textContent) || '';
      const hit = BY_LABEL.find(([key]) => label.includes(key));
      slot.innerHTML = svg(hit ? hit[1] : 'dot');
      slot.setAttribute('data-km-ico', '1');
    });
  }
  let queued = false;
  const schedule = () => { if (queued) return; queued = true; requestAnimationFrame(() => { queued = false; apply(); }); };
  const start = () => { apply(); new MutationObserver(schedule).observe(document.body, { childList: true, subtree: true }); };
  if (document.body) start(); else document.addEventListener('DOMContentLoaded', start);
})();
