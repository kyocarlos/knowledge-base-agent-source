# 知識群島首頁設計（封存）

2026-10-30 起首頁改回卡片盒方向；知識群島是更之後才考慮的設計，這裡保留當時的完整版本。

內容
- `zones-src/hub-15-islands.js`：島嶼地圖（等角六角島、各專區圖書館、點島顯示摘要、知識島主「帶你去那座島」）
- `zones-src/hub-16-people.js`：島上走動的動物、專區徽章（8 級）、動物解鎖、徽章牆（示範資料，無後端）
- `zones-src/hub-1-data.js`、`hub-2-view.js`、`hub-template.html`、`hub.css`：首頁用到的資料、畫面、版型、樣式
- `islands.html`：離線原型
- `keeper/`：知識島主（只帶路、不回答專區內容）的後端路由與專區目錄

伺服器上的線上版本備份：`~/.km-control/backups/kb-island-home-20261030/`，執行其中的 `RESTORE.sh` 即可重新套用島嶼首頁。
