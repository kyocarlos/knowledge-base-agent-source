# WiFi 知識專區工作區部署記錄（2026-10-16）

## 範圍與結果

- 僅修改 KM DEV `:3030` 的 TEST 與 DA40；未修改 Production。
- `chat-v2.html` 的可見版面、CSS、WebSocket 與其他知識專區行為保持不變；原 WiFi 入口改為同頁導向 `/wifi8/#/overview`。
- `/wifi8/` 提供總覽、文件與版本關係、段落、BM25＋向量 RRF 混合搜尋、AI Agent、匯入工作與進度。其他六頁只顯示「功能待移植」，無假資料或可誤觸動作。
- 視覺沿用現行 `chat-v2.html` 的 `#06161d` 網格背景、薄荷綠／青色強調、深色半透明卡片、Inter 字體與側邊導覽。

## Source 與 runtime

- branch: `codex/cross-search-source-credentials-20261015`
- 主功能 commit: `b67c223`
- 部署保留 backport 修正: `98a01fc`
- stale hash render 修正: `2eee1ef`
- TEST image: `km-chat-v2-secure:418610dc-llm-ba82d79-wifi8-c01693c-workspace-b67c223`
  - image ID: `sha256:43efcaa708f1019f8c8e781c402b5b5dc48e87b18434c65711918118c4ec7cda`
  - container ID: `526376085ccd9b2cb98d5a5abacf583cd80b3e881c85a22f1ebab53c9ad3bea1c`
- DA40 image: `km-da40-web:ddl-free-fd8dd34-llm-ba82d79-wifi8-c01693c-workspace-b67c223`
  - image ID: `sha256:01b62b8adfdb2392b35e673bf368ee11327fb67a34026c4a0f9a7590d3fb71cf`
  - container ID: `f1095565d755e7d84ab12322ea434ac803b72bad4f24aa02d55cfe2557b6efb9`
- 兩個後端 runtime `wifi8_routes.py` SHA-256：`c2ba0c5fc0676cde2d2a69d5c6189f1c3f820b4d131123e3ff08c7fbff20dc79`。
- Nginx 靜態 runtime SHA-256：
  - `chat-v2.html`: `b6d55076792c7cce5592bbeae53ff2f9a01a738f0ada5d6776dd0e1d7cebeb2a`
  - `wifi8/index.html`: `1fb39f385d0b0a9ff73262a656f16292770cc47f00244efb2064c75041de7ff4`
  - CSS: `7e49d7b7ba704dd6141a3d34997415802f8a0ed89a9772ef38bbf2b17e0e049e`
  - JS: `696f24f8d05c458a23766c19673e41c8533e196bb4282b4b01a4c2b258682ef5`

## 驗證

- `pytest`: WiFi import/search/agent/routes 共 `24 passed`。
- `node --check` 通過新版 hash JS；`git diff --check` 通過。
- TEST Webwright 最終驗收全綠：原 chat-v2、WiFi 同頁入口、主題、`503 / 368 / 135 / 31,395`、ELR 文件篩選、metadata／chunks／versions、NPCA 混合搜尋、Agent 回答與 5 筆引用、jobs、待移植頁、其他知識專區回歸，以及 390／760／1024／1440 px 無水平溢位；console error 與 failed request 均為 0。證據：`/home/da40_ai_gb10/.km-control/wifi8-deploy-20261016/webwright/workspace-test-final/`。
- DA40 job `wifi8-import-20261016T062515Z-282e90db` 已完成並切換 `current.json`：503 documents、368 current、94,528 segments、31,395/31,395 chunks ready、active job none。DA40 獨立 Webwright 已通過新 SPA 總覽與 ELR Agent；證據：`/home/da40_ai_gb10/.km-control/wifi8-deploy-20261016/webwright-agent/run5-da40-spa/`。
- TEST 與 DA40 web、原 ingest/search workers 與 Nginx 均維持 running；Compose runtime copy 與 Git overlay 相符。

## 備份與回復

- 備份位於 `/home/da40_ai_gb10/.km-control/wifi8-deploy-20261016/evidence/`，含部署前 `chat-v2.html`、`wifi8-import.html`、TEST／DA40 image overlay 與容器資訊。
- 靜態回復：用 `chat-v2.html.pre-ui-b67c223` 與 `wifi8-import.html.pre-ui-b67c223` 原子替回 Nginx 掛載目錄，並移除或保留不再被引用的 `/wifi8/` 目錄。
- 後端回復：將 TEST `kb-web.chat-runtime.override.yml` 與 DA40 `km-da40.llm-primary.override.yml` 的 web image 分別改回 `*-wifi8-c01693c`，只重建各自 `web` 服務。不需要切換 worker、Qdrant、Neo4j 或 WiFi data volume。
